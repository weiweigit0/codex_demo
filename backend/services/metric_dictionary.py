METRIC_DICTIONARY = {
    "revenue": {
        "name": "营业收入",
        "plain": "公司卖产品或服务收到的总业务规模。",
        "how_to_read": "收入增长说明业务规模扩大，但要结合利润和现金流判断质量。",
    },
    "net_profit": {
        "name": "净利润",
        "plain": "扣除成本、费用、税费后最终留下的钱。",
        "how_to_read": "净利润增长好，但如果现金流跟不上，利润质量可能需要观察。",
    },
    "gross_margin": {
        "name": "毛利率",
        "plain": "卖出产品后扣除直接成本，还能留下多少钱。",
        "how_to_read": "毛利率上升通常说明定价权增强或成本压力下降。",
    },
    "net_margin": {
        "name": "净利率",
        "plain": "每 100 元收入最终能留下多少净利润。",
        "how_to_read": "净利率越高，最终赚钱效率通常越强。",
    },
    "operating_cashflow": {
        "name": "经营现金流",
        "plain": "公司日常经营真正流入或流出的现金。",
        "how_to_read": "它比利润更能判断公司有没有真正收到钱。",
    },
    "debt_ratio": {
        "name": "资产负债率",
        "plain": "公司资产中有多少是靠负债支撑的。",
        "how_to_read": "过高可能意味着偿债压力，但也要看行业属性。",
    },
    "receivables": {
        "name": "应收账款",
        "plain": "已经卖出但还没收回来的钱。",
        "how_to_read": "增速明显高于收入时，需要关注回款压力。",
    },
    "inventory": {
        "name": "存货",
        "plain": "还没卖出去的商品、原材料或在产品。",
        "how_to_read": "增速明显高于收入时，可能存在库存压力。",
    },
    "roe": {
        "name": "ROE",
        "plain": "股东投入的钱产生净利润的效率。",
        "how_to_read": "ROE 高通常代表资本效率好，但要排除高负债推高的情况。",
    },
    "rd_expense": {
        "name": "研发费用",
        "plain": "公司用于技术、产品、工艺研发的钱。",
        "how_to_read": "研发增加可能是长期投入，也可能短期压低利润。",
    },
}


def list_metrics():
    return METRIC_DICTIONARY


def explain_metric(metric_key: str):
    return METRIC_DICTIONARY.get(
        metric_key,
        {
            "name": metric_key,
            "plain": "该指标暂未收录解释。",
            "how_to_read": "建议结合行业、历史趋势和现金流一起判断。",
        },
    )
