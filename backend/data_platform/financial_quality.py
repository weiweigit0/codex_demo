from __future__ import annotations

import hashlib
from typing import Tuple


CORE_METRICS = {"revenue", "net_profit", "assets", "liabilities", "equity", "operating_cashflow"}


def assess_record(record: dict, market: str) -> Tuple[str, list[str]]:
    """Return a conservative quality status for a parsed financial record."""
    if market == "US":
        return "validated", []
    metrics = record.get("metrics", {})
    values = {key: _number(value.get("value")) for key, value in metrics.items()}
    reasons = []
    assets, liabilities, equity = values.get("assets"), values.get("liabilities"), values.get("equity")
    if assets and liabilities is not None and equity is not None:
        difference = abs(assets - liabilities - equity) / max(abs(assets), 1)
        if difference > 0.12:
            reasons.append("资产、负债与权益不满足合理的会计恒等式")
    positive = [abs(value) for key, value in values.items() if key in CORE_METRICS and value not in (None, 0)]
    if len(positive) >= 3 and max(positive) / max(min(positive), 1) > 10 ** 8:
        reasons.append("核心指标数量级差异异常，可能存在 PDF 列错位或单位识别错误")
    if assets and values.get("revenue") and abs(assets) / max(abs(values["revenue"]), 1) > 10 ** 7:
        reasons.append("资产与收入数量级异常，可能存在单位识别错误")
    return ("needs_review", reasons) if reasons else ("validated", [])


def fact_id(company_id: str, document_id: str, metric_key: str) -> str:
    raw = "%s|%s|%s" % (company_id, document_id, metric_key)
    return "ff_%s" % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _number(value):
    return value if isinstance(value, (int, float)) else None
