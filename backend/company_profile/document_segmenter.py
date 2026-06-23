from __future__ import annotations

import re
from typing import Dict, List


SECTION_GROUPS = {
    "basic_info": ["公司简介", "公司基本情况", "发行人基本情况", "基本信息", "business overview", "company information"],
    "business": ["主营业务", "主要业务", "业务模式", "产品", "服务", "销售模式", "item 1. business", "business", "products", "services"],
    "ownership": ["控股股东", "实际控制人", "股权结构", "股东情况", "principal shareholders", "beneficial ownership"],
    "people": ["董事", "监事", "高级管理人员", "核心技术人员", "简历", "履历", "directors", "executive officers", "management"],
    "chain": ["供应商", "客户", "采购", "销售", "上游", "下游", "customers", "suppliers", "supply chain"],
    "capital": ["募集资金", "发行", "分红", "回购", "股权激励", "增持", "减持", "dividends", "repurchase", "share-based compensation"],
    "risk": ["风险因素", "风险", "诉讼", "处罚", "合规", "item 1a. risk factors", "risk factors", "legal proceedings"],
}


class DocumentSegmenter:
    def parse(self, text: str) -> dict:
        pages = [page.strip() for page in text.split("\n\n") if page.strip()]
        if len(pages) <= 1:
            pages = [part.strip() for part in re.split(r"\n(?=\d{1,3}\s*$)", text) if part.strip()]
        blocks = []
        for idx, page_text in enumerate(pages[:160], start=1):
            clean = re.sub(r"\s+", " ", page_text).strip()
            if not clean:
                continue
            blocks.append(
                {
                    "id": "txt_%03d" % idx,
                    "page": idx,
                    "section_title": self.guess_section(clean),
                    "groups": self.classify(clean),
                    "text": clean,
                }
            )
        if not blocks:
            blocks = [{"id": "txt_001", "page": 1, "section_title": "全文", "groups": ["full_text"], "text": _trim(text, 2000)}]
        return {"blocks": blocks, "text": "\n".join(block["text"] for block in blocks), "parse_quality": "MEDIUM"}

    def context_pack(self, parsed: dict, max_blocks_per_group: int = 4, max_chars: int = 1400) -> Dict[str, List[dict]]:
        packs: Dict[str, List[dict]] = {key: [] for key in SECTION_GROUPS}
        for group in SECTION_GROUPS:
            for block in parsed.get("blocks", []):
                if group in block.get("groups", []):
                    packs[group].append(
                        {
                            "block_id": block["id"],
                            "page": block["page"],
                            "section_title": block.get("section_title"),
                            "text": _trim(block["text"], max_chars),
                        }
                    )
                if len(packs[group]) >= max_blocks_per_group:
                    break
        return {key: value for key, value in packs.items() if value}

    def guess_section(self, text: str) -> str:
        comparable = text.lower()
        for group, keywords in SECTION_GROUPS.items():
            for keyword in keywords:
                if keyword.lower() in comparable:
                    return keyword
        return "披露文件正文"

    def classify(self, text: str) -> List[str]:
        comparable = text.lower()
        groups = []
        for group, keywords in SECTION_GROUPS.items():
            if any(keyword.lower() in comparable for keyword in keywords):
                groups.append(group)
        return groups or ["body"]


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."
