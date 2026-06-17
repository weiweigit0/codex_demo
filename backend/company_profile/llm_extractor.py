from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

import requests


class LLMProfileExtractor:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        self.endpoint = os.getenv("OPENAI_CHAT_COMPLETIONS_URL", "https://api.openai.com/v1/chat/completions")

    def extract(self, company: dict, document: dict, parsed: dict) -> Optional[dict]:
        if not self.api_key:
            return None

        snippets = _build_snippets(parsed.get("blocks", []))
        if not snippets:
            return None

        prompt = _prompt(company, document, snippets)
        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": "你是严谨的上市公司公开文件信息抽取助手。只基于用户给出的原文片段输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=45,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            payload = _json_from_text(content)
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None
        return _normalize_payload(payload)


def _build_snippets(blocks: List[dict]) -> List[dict]:
    groups = [
        ("business", ["主营业务", "主要业务", "业务模式", "产品", "服务", "销售模式"]),
        ("ownership", ["控股股东", "实际控制人", "股权结构", "股东"]),
        ("people", ["董事", "监事", "高级管理人员", "核心技术人员", "简历", "履历"]),
        ("chain", ["供应商", "客户", "采购", "销售", "上游", "下游"]),
        ("capital", ["募集资金", "发行", "分红", "回购", "股权激励", "增持", "减持"]),
        ("risk", ["风险因素", "风险", "诉讼", "处罚", "合规"]),
    ]
    selected = []
    seen = set()
    for group, keywords in groups:
        hits = [block for block in blocks if any(keyword in block.get("text", "") for keyword in keywords)]
        for block in hits[:3]:
            block_id = block.get("id")
            if block_id in seen:
                continue
            seen.add(block_id)
            selected.append(
                {
                    "group": group,
                    "page": block.get("page"),
                    "section_title": block.get("section_title"),
                    "text": _trim(block.get("text", ""), 1200),
                }
            )
    return selected[:16]


def _prompt(company: dict, document: dict, snippets: List[dict]) -> str:
    schema = {
        "business_summary": "一句话说明公司业务，不分析财务指标",
        "industry": "行业名称，未知则空字符串",
        "controlling_shareholder": "控股股东，未知则空字符串",
        "actual_controller": "实际控制人，未知则空字符串",
        "key_people": [
            {
                "name": "姓名",
                "role": "职务",
                "background": "基于原文的履历摘要",
                "importance_reason": "为什么是关键人物",
                "tags": ["创始人/实控人/核心技术/管理层等"],
            }
        ],
        "industry_chain": {
            "upstream": ["上游要素"],
            "downstream": ["下游客户/场景"],
            "major_customers": ["主要客户，未知则空数组"],
            "major_suppliers": ["主要供应商，未知则空数组"],
        },
        "capital_actions": {
            "summary": "发行、募资、分红、回购、股权激励等资本动作摘要",
        },
        "non_financial_risks": [
            {"risk_name": "风险名称", "risk_type": "风险类型", "severity": "high/medium/low", "plain_explanation": "普通人解释"}
        ],
    }
    return (
        f"公司：{company.get('name')}（{company.get('ticker')}）\n"
        f"来源文件：{document.get('title') or document.get('period')}\n"
        "任务：从公开披露文件片段中抽取公司画像。尤其注意关键人物和人物履历，不要用模板猜测。\n"
        "边界：不要做收入、利润、现金流、估值等财务分析；不知道就填空字符串或空数组；不得编造。\n"
        "输出：只返回 JSON，不要 Markdown。JSON 字段结构如下：\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "原文片段：\n"
        f"{json.dumps(snippets, ensure_ascii=False)}"
    )


def _json_from_text(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        return json.loads(match.group(0)) if match else None


def _normalize_payload(payload: dict) -> dict:
    payload["key_people"] = _list_of_dicts(payload.get("key_people"))
    payload["non_financial_risks"] = _list_of_dicts(payload.get("non_financial_risks"))
    chain = payload.get("industry_chain")
    payload["industry_chain"] = chain if isinstance(chain, dict) else {}
    capital = payload.get("capital_actions")
    payload["capital_actions"] = capital if isinstance(capital, dict) else {}
    return payload


def _list_of_dicts(value) -> List[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."
