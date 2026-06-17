from __future__ import annotations

import re
from collections import Counter
from typing import List

from backend.services.compliance_service import ComplianceService
from backend.services.metric_dictionary import explain_metric, METRIC_DICTIONARY


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "公司",
    "财报",
    "怎么样",
    "如何",
    "是否",
}


def answer_question(question: str, analysis: dict) -> dict:
    chunks = analysis.get("rag_chunks", [])
    hits = _retrieve(question, chunks)
    answer = _compose_answer(question, analysis, hits)
    compliance = ComplianceService().review_text(answer)
    return {
        "answer": compliance["text"],
        "citations": hits,
        "compliance": compliance,
        "disclaimer": analysis.get("disclaimer", compliance["disclaimer"]),
    }


def _retrieve(question: str, chunks: List[dict]) -> List[dict]:
    question_tokens = _tokens(question)
    scored = []
    for chunk in chunks:
        content = f"{chunk.get('title', '')} {chunk.get('content', '')}"
        score = _score(question_tokens, _tokens(content))
        if score:
            scored.append({**chunk, "score": score})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:3] or chunks[:1]


def _score(query_tokens: List[str], doc_tokens: List[str]) -> int:
    doc_counter = Counter(doc_tokens)
    return sum(doc_counter[token] for token in query_tokens)


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", text.lower())
    return [word for word in words if word not in STOPWORDS]


def _compose_answer(question: str, analysis: dict, hits: List[dict]) -> str:
    q = question.lower()
    metrics = analysis.get("metrics", {})
    risks = analysis.get("risks", [])
    company = analysis.get("company", {})
    latest_period = analysis.get("latest_period", "")

    if re.search(r"现金流|cash", q):
        cashflow = metrics.get("operating_cashflow", {})
        return (
            f"先说结论：{company.get('name', '这家公司')}在{latest_period}的经营现金流为"
            f"{cashflow.get('display', '待补充')}。如果经营现金流持续为正，通常说明利润含金量更高；"
            "如果连续低于净利润，则需要继续追问回款、库存和资本开支。"
        )

    for metric_key, meta in METRIC_DICTIONARY.items():
        if meta["name"] in question or metric_key.lower() in q:
            metric = metrics.get(metric_key, {})
            explanation = explain_metric(metric_key)
            return (
                f"先说结论：{explanation['name']}的意思是：{explanation['plain']}"
                f"当前识别值为{metric.get('display', '待补充')}。"
                f"怎么看：{explanation['how_to_read']}"
            )

    if re.search(r"风险|雷|问题", q):
        active = [risk for risk in risks if risk.get("level") != "green"]
        if not active:
            return "先说结论：当前结构化数据里没有识别到突出的红色风险，但仍需要结合完整 10-K/10-Q 文本和行业数据判断。"
        details = " ".join([f"{risk['name']}：{risk['reason']}" for risk in active])
        names = "、".join([risk["name"] for risk in active])
        return f"先说结论：需要重点看 {names}。{details}"

    if re.search(r"收入|增长|revenue", q):
        revenue = metrics.get("revenue", {})
        yoy = revenue.get("yoy")
        yoy_text = "同比待补充" if yoy is None else f"同比{'增长' if yoy >= 0 else '下降'}{abs(yoy)}%"
        return f"先说结论：{latest_period}收入为{revenue.get('display', '待补充')}，{yoy_text}。收入要和净利润、毛利率、现金流一起看。"

    if re.search(r"利润|盈利|毛利率|margin", q):
        profit = metrics.get("net_profit", {})
        gross_margin = metrics.get("gross_margin", {})
        net_margin = metrics.get("net_margin", {})
        return (
            f"先说结论：净利润为{profit.get('display', '待补充')}，毛利率为"
            f"{gross_margin.get('display', '待补充')}，净利率为{net_margin.get('display', '待补充')}。"
            "毛利率看产品和成本压力，净利率看最终赚钱效率。"
        )

    if re.search(r"对比|多年|季度|趋势|trend", q):
        rows = analysis.get("comparison", {}).get("rows", [])
        text = "；".join(
            [
                f"{row['period']}收入{row['revenue']}、净利润{row['net_profit']}、现金流{row['operating_cashflow']}"
                for row in rows
            ]
        )
        return f"先说结论：多期对比可以看到这些变化：{text}。建议重点观察收入增速、利润增速和现金流是否同向。"

    context = " ".join([hit.get("content", "") for hit in hits])
    return f"先说结论：{analysis.get('summary', '当前信息不足以形成完整判断')} 相关依据：{context}"
