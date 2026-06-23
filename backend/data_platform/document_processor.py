from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path


TABLE_TITLES = (
    "资产负债表", "利润表", "现金流量表", "所有者权益变动表",
    "balance sheet", "income statement", "cash flows",
)


class DocumentProcessor:
    """Build page and evidence-block records while preserving original assets.

    This processor intentionally does not infer financial values. It preserves page
    text and table candidates for the fact extraction/validation stage.
    """

    version = "document_processor_v1"

    def process(self, document: dict, asset_path: Path | None, fallback_text: str) -> dict:
        pages = self._pdf_pages(asset_path) if asset_path and asset_path.suffix.lower() == ".pdf" else self._text_pages(fallback_text)
        result_pages = []
        blocks = []
        for page_number, raw_text in enumerate(pages, start=1):
            text = _clean(raw_text)
            quality = "extracted" if len(text) >= 80 else "needs_review"
            result_pages.append({
                "page_number": page_number,
                "text": text,
                "parse_method": "native_pdf_text" if asset_path and asset_path.suffix.lower() == ".pdf" else "html_or_text",
                "quality_status": quality,
                "metadata": {"char_count": len(text), "processor_version": self.version},
            })
            blocks.extend(self._blocks(document, page_number, text, quality))
        if not result_pages:
            result_pages = [{"page_number": 1, "text": "", "parse_method": "empty", "quality_status": "needs_review", "metadata": {"processor_version": self.version}}]
        return {"pages": result_pages, "blocks": blocks, "processor_version": self.version}

    def _pdf_pages(self, path: Path) -> list[str]:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(BytesIO(path.read_bytes()))
            return [(page.extract_text() or "") for page in reader.pages]
        except Exception:
            return []

    def _text_pages(self, text: str) -> list[str]:
        markers = re.split(r"\s*--- PAGE \d+ ---\s*", text or "")
        pages = [item for item in markers if item.strip()]
        return pages or [text or ""]

    def _blocks(self, document: dict, page_number: int, text: str, quality: str) -> list[dict]:
        if not text:
            return []
        title = _section_title(text)
        base_id = "%s-p%03d" % (document["id"], page_number)
        blocks = []
        table = _table_candidate(text, title)
        if table:
            blocks.append({
                "block_id": base_id + "-table",
                "page_number": page_number,
                "section_title": table["name"],
                "content_type": "table",
                "text": text,
                "table": table,
                "source_quote": _quote(text),
                "quality_status": quality,
                "confidence": "medium" if quality == "extracted" else "low",
                "metadata": {"table_candidate": True, "processor_version": self.version},
            })
        for index, chunk in enumerate(_chunks(text), start=1):
            blocks.append({
                "block_id": "%s-b%03d" % (base_id, index),
                "page_number": page_number,
                "section_title": title,
                "content_type": "paragraph",
                "text": chunk,
                "source_quote": _quote(chunk),
                "quality_status": quality,
                "confidence": "high" if quality == "extracted" else "low",
                "metadata": {"processor_version": self.version},
            })
        return blocks


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text or "")).strip()


def _section_title(text: str) -> str:
    for title in TABLE_TITLES:
        if title.lower() in text.lower():
            return title
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "披露文件正文")
    return first_line[:80]


def _table_candidate(text: str, title: str) -> dict | None:
    if not any(item.lower() in text.lower() for item in TABLE_TITLES):
        return None
    unit = ""
    match = re.search(r"(?:单位[：:]?\s*)([^\n]{1,24})", text)
    if match:
        unit = match.group(1).strip()
    return {"name": title, "unit": unit, "raw_text": text, "extraction": "layout_candidate"}


def _chunks(text: str, limit: int = 1400) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks, current = [], ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 1 > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = (current + "\n" + paragraph).strip()
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


def _quote(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized[:520] + ("..." if len(normalized) > 520 else "")
