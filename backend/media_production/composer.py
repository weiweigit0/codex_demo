from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from backend.media_production.providers import ProviderError


class FfmpegComposer:
    def __init__(self):
        self.ffmpeg = os.getenv("MEDIA_FFMPEG_BIN", "ffmpeg")
        self.ffprobe = os.getenv("MEDIA_FFPROBE_BIN", "ffprobe")
        self.burn_subtitles = os.getenv("MEDIA_BURN_SUBTITLES", "true").lower() in {"1", "true", "yes"}

    def configured(self) -> bool:
        return bool(shutil.which(self.ffmpeg) and shutil.which(self.ffprobe))

    def compose(self, clips: list[Path], audios: list[Path], subtitle_path: Path, output_path: Path, profile: str) -> Path:
        if not self.configured():
            raise ProviderError("未找到 ffmpeg/ffprobe。请在独立媒体 Worker 镜像中安装 FFmpeg。")
        if not clips or not audios:
            raise ProviderError("FFmpeg 合成缺少视频片段或音频。")
        workspace = output_path.parent
        workspace.mkdir(parents=True, exist_ok=True)
        scale = "720:1280" if profile == "vertical_720p" else "1280:720"
        normalized_clips = []
        for index, clip in enumerate(clips, start=1):
            target = workspace / ("normalized_%02d.mp4" % index)
            self._run([self.ffmpeg, "-y", "-i", str(clip), "-an", "-vf", "scale=%s:force_original_aspect_ratio=increase,crop=%s" % (scale, scale), "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)])
            normalized_clips.append(target)
        video_list = workspace / "videos.txt"
        audio_list = workspace / "audios.txt"
        video_list.write_text("".join("file '%s'\n" % _concat_path(path) for path in normalized_clips), encoding="utf-8")
        audio_list.write_text("".join("file '%s'\n" % _concat_path(path) for path in audios), encoding="utf-8")
        video_track = workspace / "video_track.mp4"
        audio_track = workspace / "audio_track.m4a"
        self._run([self.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(video_list), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video_track)])
        self._run([self.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(audio_list), "-c:a", "aac", "-ar", "48000", "-ac", "2", str(audio_track)])
        command = [self.ffmpeg, "-y", "-stream_loop", "-1", "-i", str(video_track), "-i", str(audio_track)]
        if self.burn_subtitles and subtitle_path.exists():
            command.extend(["-vf", "subtitles=%s" % _filter_path(subtitle_path)])
        command.extend(["-c:v", "libx264", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output_path)])
        self._run(command)
        if not output_path.is_file() or output_path.stat().st_size < 1024:
            raise ProviderError("FFmpeg 未生成有效 MP4。")
        return output_path

    def _run(self, command: list[str]) -> None:
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=int(os.getenv("MEDIA_FFMPEG_TIMEOUT_SECONDS", "900")))
        except OSError as exc:
            raise ProviderError("无法执行 FFmpeg：%s" % exc) from exc
        if result.returncode != 0:
            raise ProviderError("FFmpeg 合成失败：%s" % (result.stderr or result.stdout)[-700:])


def _concat_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
