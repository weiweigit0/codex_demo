# 模块地图

## 主应用入口

| 范围 | 主要代码 | 说明 |
| --- | --- | --- |
| 应用装配 | `backend/main.py` | 路由注册、静态资源挂载、领域编排器初始化 |
| 依赖容器 | `backend/services/container.py` | 初始化 `DataService`、认证与兼容服务 |
| 环境读取 | `backend/config.py` | 加载根目录 `.env`，不覆盖进程环境变量 |
| 基础存储 | `backend/repositories/sqlite_store.py`、`json_store.py` | 用户会话、历史兼容 JSON 存储 |
| 前端静态页 | `app/` | 多页面应用，无独立前端构建步骤 |

## 业务域与路由

| 域 | API 前缀 | 编排入口 | 页面 |
| --- | --- | --- | --- |
| 认证 | `/api/auth` | `backend/api/auth.py` | `login.html`、`register.html`、`auth.js` |
| 公司与报告兼容接口 | `/api/companies`、`/api/reports` | `backend/api/companies.py`、`reports.py` | `home.js`、`app.js` |
| 财报 Agent | `/api/financial-agent` | `backend/financial_agent/orchestrator.py` | `index.html`、`app.js` |
| 公司画像 | `/api/company-profile` | `backend/company_profile/orchestrator.py` | `profile.html`、`profile.js` |
| 3 分钟总结 | `/api/three-minute-summary` | `backend/three_minute_summary/orchestrator.py` | `summary.html`、`summary.js` |
| 视频脚本 | `/api/three-minute-summary/...` | `video_orchestrator.py`、`video_brief.py` | `summary-video.html`、`summary-video.js` |
| 查询中心 | `/api/support` | `backend/support/router.py` | `support.html`、`support.js` |
| 数据管理 | `/api/data` | `backend/data_platform/router.py` | 供后台、排障和预热调用 |

## 统一知识整理层

| 组件 | 代码 | 职责 |
| --- | --- | --- |
| 服务门面 | `backend/data_platform/service.py` | 缓存优先读取、缺失时拉取、文档物化、手动刷新 |
| 元数据仓库 | `backend/data_platform/repository.py` | 公司、数据快照、文档、刷新任务 |
| 知识仓库 | `backend/data_platform/knowledge_repository.py` | 标准文档、页面、证据块、财务事实、模型运行、Agent 产物 |
| 文档处理 | `backend/data_platform/document_processor.py` | 将原文处理为标准页面与证据块 |
| 财务质量 | `backend/data_platform/financial_quality.py` | 指标验证、质量状态与事实 ID |
| 更新调度 | `backend/data_platform/scheduler.py` | 可选的季度预热与刷新 |

## 独立媒体生产系统

| 组件 | 代码 | 职责 |
| --- | --- | --- |
| 媒体 API | `backend/media_production/main.py`、`router.py` | 导入签名简报、创建任务、管理员审批、查询任务 |
| 签名安全 | `security.py` | Ed25519 签名验证，防止伪造生产请求 |
| 任务编排 | `orchestrator.py`、`repository.py` | 独立 SQLite/文件存储与状态机 |
| 生产 Worker | `worker.py` | 审批后执行 Provider 与合成 |
| 外部 Provider | `providers.py` | TTS 与即梦适配，演示模式不调用外部服务 |
| 合成 | `composer.py` | 使用 FFmpeg 合成音视频与字幕 |
| 前端 | `media_app/` | 普通用户请求页与管理员审批页 |

