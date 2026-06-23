# 数据平台运行说明

## 职责与边界

`backend/data_platform/` 是 SEC、巨潮资讯、Wikipedia、百度百科和模型结果的唯一持久化入口。

- 财报掘金通过 `ReportService -> DataService` 读取公司、财务数据和报告元数据。
- 公司画像通过 `CompanyProfileOrchestrator -> DataService` 读取披露原文、解析文本、百科快照和画像缓存。
- 外部 Client 只在 `DataService` 内部被调用；业务服务不应再直接 import SEC、巨潮或百科 Client。

## 本地数据位置

| 内容 | 位置 | 说明 |
| --- | --- | --- |
| 数据元数据、版本、任务 | `backend/storage/app.db` | SQLite 表：`data_companies`、`source_documents`、`data_snapshots`、`refresh_jobs` |
| SEC HTML / 巨潮 PDF 原始文件 | `backend/storage/assets/documents/` | 以文档 ID 哈希命名，已被 Git 忽略 |
| 解析文本、财务数据、百科与画像缓存 | SQLite `data_snapshots` | 带资源类型、版本和失效时间 |

## 缓存与更新策略

- 公司与披露文件索引：命中本地优先；索引有效期为 1 天。
- 财务数据：首次请求抓取并持久化；同报告期重复请求直接读取数据库。
- 原始披露文件与解析文本：首次下载后永久保留，只有手动刷新才重新下载并写入新内容哈希。
- 百科：45 天有效期，过期或手动刷新时更新；顺序为 Wikipedia、百度百科。
- 公司画像：缓存键为公司、文件内容版本、百科内容、Agent 版本；有效期 30 天。新年报、百科变化、提示词/Agent 版本变化都会形成新键。
- 模型失败不会覆盖已生成的画像缓存。

## 管理 API

### 查看资源状态

`GET /api/data/status?ticker=AAPL&market=US`

返回财务数据、披露文件、百科的 `ready`、`stale` 或 `missing` 状态和更新时间。

### 手动刷新单家公司

`POST /api/data/refresh`

```json
{
  "ticker": "000001",
  "market": "CN",
  "resource_type": "documents"
}
```

支持 `financial_dataset`、`documents`、`encyclopedia` 和 `company_profile`。接口立即返回任务 ID；通过 `GET /api/data/jobs/{job_id}` 轮询进度。

### 预热头部公司

`POST /api/data/prewarm`

```json
{
  "market": "ALL",
  "resources": ["financial_dataset", "documents"],
  "limit": 20
}
```

预热采用受控的头部公司清单，不会在单次请求中抓取全市场全部文件。

## 可选季度调度

在 `.env` 设置：

```text
DATA_SCHEDULED_REFRESH=true
```

服务启动后会每 6 小时检查一次；距离上次预热满 90 天时，为头部 20 家公司创建财务数据与披露文件刷新任务。默认关闭，避免本地开发环境启动即触发外网访问。
