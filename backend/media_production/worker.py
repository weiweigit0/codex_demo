from __future__ import annotations

import argparse
import json
import math
import os
import time
import uuid
from pathlib import Path

from backend.config import load_env_file
from backend.data_platform.repository import utc_now
from backend.media_production.composer import FfmpegComposer
from backend.media_production.providers import JimengVideoProvider, ProviderError, VolcTtsProvider
from backend.media_production.repository import MediaRepository


class MediaProductionWorker:
    """Persistent worker that alone may consume externally billable Providers."""

    def __init__(self, storage_dir: Path):
        self.repository = MediaRepository(storage_dir)
        self.mode = os.getenv("MEDIA_RENDER_MODE", "disabled").strip().lower()
        self.tts = VolcTtsProvider()
        self.jimeng = JimengVideoProvider()
        self.composer = FfmpegComposer()

    def run_once(self) -> bool:
        request = next(iter(self.repository.queued_requests(1)), None)
        if not request:
            return False
        self.process(request["request_id"])
        return True

    def process(self, request_id: str) -> None:
        request = self.repository.claim_request(request_id)
        if not request:
            return
        try:
            if self.mode == "demo":
                self._demo_delivery(request)
            elif self.mode == "production":
                self._production_delivery(request)
            else:
                raise ProviderError("MEDIA_RENDER_MODE 必须为 demo 或 production。")
        except Exception as exc:
            self.repository.update_request(request_id, status="FAILED", status_note=str(exc)[:400])
            self._event(request_id, "FAILED", str(exc)[:400])

    def _production_delivery(self, request: dict) -> None:
        if not (self.tts.configured() and self.jimeng.configured() and self.composer.configured()):
            missing = []
            if not self.tts.configured(): missing.append("TTS")
            if not self.jimeng.configured(): missing.append("即梦")
            if not self.composer.configured(): missing.append("FFmpeg")
            raise ProviderError("真实媒体生产未就绪：%s。" % "、".join(missing))
        brief = self.repository.get_brief(request["brief_id"])
        directory = self.repository.assets_dir / request["request_id"]
        directory.mkdir(parents=True, exist_ok=True)
        audios, clips = [], []
        self.repository.update_request(request["request_id"], status="AUDIO_RENDERING", status_note="正在调用独立 TTS 生成配音与字幕。")
        for index, segment in enumerate(brief["segments"], start=1):
            path = directory / ("audio_%02d.mp3" % index)
            asset = self.tts.synthesize(segment["narration"], path, request["request_id"])
            audios.append(asset.path)
            self._asset(request["request_id"], "tts_audio", asset.path, asset.mime_type)
        subtitle_path = directory / "subtitles.vtt"
        subtitle_path.write_text(_vtt(brief["segments"]), encoding="utf-8")
        self._asset(request["request_id"], "subtitles", subtitle_path, "text/vtt")
        self.repository.update_request(request["request_id"], status="VISUAL_RENDERING", status_note="正在提交即梦视频镜头任务。")
        ratio = "9:16" if request["output_profile"] == "vertical_720p" else "16:9"
        for shot in _shots(brief["segments"]):
            path = directory / ("clip_%02d.mp4" % (len(clips) + 1))
            clip = self.jimeng.generate(shot["prompt"], shot["duration_seconds"], ratio, path)
            clips.append(clip)
            self._asset(request["request_id"], "jimeng_clip", clip, "video/mp4")
        self.repository.update_request(request["request_id"], status="COMPOSITING", status_note="正在由 FFmpeg 合成 MP4、配音与字幕。")
        final_path = directory / "financial-video.mp4"
        self.composer.compose(clips, audios, subtitle_path, final_path, request["output_profile"])
        self._asset(request["request_id"], "final_video", final_path, "video/mp4")
        render = {"mode": "production", "tts_provider": "volc", "video_provider": "jimeng", "clip_count": len(clips), "disclaimer": "视频画面由模型生成；字幕和口播仅来自已签名脚本包。"}
        self.repository.update_request(request["request_id"], status="DELIVERED", status_note="音视频成片已生成，可预览和下载。", render=render)
        self._event(request["request_id"], "DELIVERED", "真实音视频生产完成")

    def _demo_delivery(self, request: dict) -> None:
        brief = self.repository.get_brief(request["brief_id"])
        directory = self.repository.assets_dir / request["request_id"]
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {"request_id": request["request_id"], "mode": "demo", "brief_id": brief["brief_id"], "output_profile": request["output_profile"], "segments": brief["segments"], "next_step": "配置独立 TTS、即梦和 FFmpeg 后，使用 production 模式生成 MP4。"}
        manifest_path = directory / "production-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        subtitle_path = directory / "subtitles.vtt"
        subtitle_path.write_text(_vtt(brief["segments"]), encoding="utf-8")
        self._asset(request["request_id"], "production_manifest", manifest_path, "application/json")
        self._asset(request["request_id"], "subtitles", subtitle_path, "text/vtt")
        self.repository.update_request(request["request_id"], status="DEMO_DELIVERED", status_note="演示生产流程已完成。该交付包不包含真实 MP4，不会产生外部模型费用。", render={"mode": "demo", "disclaimer": "真实成片需配置已审批的 TTS、即梦与 FFmpeg Worker。"})
        self._event(request["request_id"], "DEMO_DELIVERED", "已生成演示交付包")

    def _asset(self, request_id: str, asset_type: str, path: Path, mime_type: str) -> None:
        self.repository.add_asset({"asset_id": "asset_%s" % uuid.uuid4().hex[:16], "request_id": request_id, "asset_type": asset_type, "relative_path": str(path.relative_to(self.repository.root)), "mime_type": mime_type, "created_at": utc_now()})

    def _event(self, request_id: str, action: str, note: str) -> None:
        self.repository.add_event({"event_id": "worker_%s" % uuid.uuid4().hex[:16], "request_id": request_id, "actor": "media-worker", "action": action, "note": note, "created_at": utc_now()})


def _shots(segments: list[dict]) -> list[dict]:
    result = []
    for segment in segments:
        count = max(1, int(math.ceil(segment["target_duration_seconds"] / 10.0)))
        for index in range(count):
            duration = 10 if index < count - 1 else max(5, segment["target_duration_seconds"] - 10 * (count - 1))
            visual = str(segment.get("visual_direction") or "抽象数据背景").replace("\n", " ")[:280]
            prompt = "简洁、可信赖的财经科普短视频背景画面，%s。无可读文字、无数字、无股票代码、无公司 Logo、无水印、无人物肖像、无投资建议。" % visual
            result.append({"duration_seconds": duration, "prompt": prompt, "segment_id": segment["segment_id"]})
    return result


def _vtt(segments: list[dict]) -> str:
    offset, rows = 0, ["WEBVTT", ""]
    for index, segment in enumerate(segments, start=1):
        end = offset + segment["target_duration_seconds"]
        rows.extend([str(index), "%s --> %s" % (_stamp(offset), _stamp(end)), segment["narration"], ""])
        offset = end
    return "\n".join(rows)


def _stamp(seconds: int) -> str:
    return "%02d:%02d:%02d.000" % (seconds // 3600, seconds % 3600 // 60, seconds % 60)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    load_env_file(root / ".env.media.production")
    storage = Path(os.getenv("MEDIA_PRODUCTION_STORAGE_DIR", str(root / "backend" / "media_storage")))
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = MediaProductionWorker(storage)
    if args.once:
        worker.run_once()
        return
    interval = max(1.0, float(os.getenv("MEDIA_WORKER_POLL_SECONDS", "2")))
    while True:
        if not worker.run_once():
            time.sleep(interval)


if __name__ == "__main__":
    main()
