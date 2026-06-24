# 数据与模型约束

## 数据读取原则

所有业务域都必须通过 `DataService` 读取基础数据：

1. 优先读取本地 SQLite 快照、原始资产和标准化知识。
2. 缓存缺失、过期或用户发起刷新时，才访问 SEC、巨潮、Wikipedia 或百度百科。
3. 外部内容进入业务 Agent 前，必须转为统一的公司、文档、页面、证据块或事实结构。
4. 模型派生结果以输入指纹缓存；相同公司、披露版本、上下文与提示词版本不得重复调用模型。

详细表结构与刷新策略参见 `docs/data_platform.md`。

## 数据质量与证据

- A 股 PDF 可能存在扫描件、表格列错位和单位识别错误；不通过质量校验的财务事实不能作为 Agent 的确定性依据。
- 美股财务事实来自 SEC XBRL，披露文本来自 10-K/20-F/招股书 HTML。
- Agent 的财务与公司结论必须引用已存在的 `evidence_block_ids` 或明确标注“当前证据不足以确认”。
- Wikipedia、百度百科只能补充披露未覆盖的基础背景，不得覆盖、冲突或替代正式披露事实。

## DeepSeek 接入

模型客户端为 `backend/company_profile/llm_client.py`，由下列环境变量控制：

```text
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_CHAT_COMPLETIONS_URL=https://api.deepseek.com/chat/completions
LLM_TRANSPORT=requests
```

- `LLM_TRANSPORT=curl` 仅用于企业代理导致 `requests` 无法连接的场景。
- 不要把 API Key 写入日志、测试夹具、文档或 Git 提交。
- 输出面向用户时必须为简体中文；英文 SEC 原文仅作为模型理解材料。
- 模型 JSON 必须经过本地 schema、证据引用和语言校验，不接受未验证的自由文本作为事实。
- 美股公司缓存必须具备数字格式的 SEC CIK。缓存缺失时，`DataService` 会回源 SEC 自动补齐；修复记录保存到 `company_identity_repairs`，可用 `scripts/repair_company_identities.py` 批量治理。

## 各 Agent 的职责

| Agent | 代码 | 输入 | 输出约束 |
| --- | --- | --- | --- |
| 财报分析 | `financial_agent/agent.py` | 已验证财务事实、披露证据块 | 先抽取事实，再生成趋势，再评估风险；禁止投资建议 |
| 公司画像 | `company_profile/agent.py` | 三年年报、可得招股书、百科补充 | 分阶段抽取、综合、非财务风险事实与等级分离 |
| 3 分钟总结 | `three_minute_summary/agent.py` | 财报产物、画像事实、证据块 | 面向普通人的通俗表述，评分不是投资评级 |
| 视频脚本 | `three_minute_summary/video_agent.py` | 已完成总结 | 仅生成口播与分镜，不直接生产视频 |
