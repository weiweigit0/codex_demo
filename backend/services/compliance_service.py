FORBIDDEN_PHRASES = [
    "建议买入",
    "建议卖出",
    "强烈买入",
    "马上买",
    "马上卖",
    "一定上涨",
    "稳赚",
    "目标价必达",
]


DISCLAIMER = "本内容仅用于财报信息理解和研究辅助，不构成任何投资建议。投资有风险，决策需谨慎。"


class ComplianceService:
    def review_text(self, text: str) -> dict:
        hits = [phrase for phrase in FORBIDDEN_PHRASES if phrase in text]
        return {
            "passed": not hits,
            "hits": hits,
            "disclaimer": DISCLAIMER,
            "text": self.sanitize(text),
        }

    def sanitize(self, text: str) -> str:
        sanitized = text
        for phrase in FORBIDDEN_PHRASES:
            sanitized = sanitized.replace(phrase, "需要谨慎研究")
        return sanitized
