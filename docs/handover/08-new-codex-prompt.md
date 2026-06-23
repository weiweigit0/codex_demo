# 新 Codex 账号接手提示词

将以下内容作为新 Codex 账号进入本仓库后的第一条项目指令，再根据需要补充具体任务：

```text
你正在维护“财报掘金”项目，仓库根目录已包含 docs/handover/ 交接包。

请先按顺序阅读：
1. docs/handover/README.md
2. docs/handover/00-project-overview.md
3. docs/handover/01-architecture.md
4. docs/handover/02-module-map.md
5. docs/handover/03-data-and-model.md
6. docs/handover/06-known-issues.md
7. docs/handover/07-product-constraints.md

工作原则：
- 先阅读当前代码和相关测试，再提出或实施修改；不根据旧聊天记录猜测实现。
- 主页、财报 Agent、公司画像、3 分钟总结、查询中心、媒体生产相互解耦；共享数据只能通过 backend/data_platform/ 的 DataService 与标准化知识结构。
- 不在业务模块中直接访问 SEC、巨潮、Wikipedia、百度百科；由数据平台缓存优先、缺失刷新。
- 所有模型面向用户的输出必须是简体中文，财务事实必须有已验证事实或 evidence_block_ids 支撑；证据不足时明确说明，不得编造，也不得给投资建议。
- 不读取、不输出、不提交 .env、生产密钥、用户数据或 backend/storage 中的真实缓存。
- 保留用户已有的未提交改动，不使用 destructive git 命令。
- 修改后运行相关测试、compileall 和页面冒烟测试；跨模块改动至少验证 000001、AAPL、BIDU。

现在先给出：
1. 你对当前架构与数据流的简明理解；
2. 发现的未提交改动及其可能归属；
3. 本地启动和测试是否成功；
4. 在不修改代码的前提下，等待我的下一个具体需求。
```

## 推荐的新账号首轮学习任务

1. 按 `04-local-development.md` 启动应用并检查 `/api/health`。
2. 阅读 `backend/main.py`、`backend/services/container.py`、`backend/data_platform/service.py`。
3. 逐一阅读 `financial_agent`、`company_profile`、`three_minute_summary` 的 `router.py`、`orchestrator.py` 与 `agent.py`。
4. 运行交接包中的测试命令，记录失败但不要为“全绿”而绕过质量校验。
5. 完成三公司冒烟测试后，再接手新功能或修复需求。

