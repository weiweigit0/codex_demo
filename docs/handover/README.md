# 财报掘金交接包

本目录用于将项目交接给新的开发者或 Codex 账号。它以当前仓库为唯一事实来源，不依赖历史聊天记录。

## 30 分钟接手顺序

1. 阅读 [项目概览](00-project-overview.md) 了解产品、用户路径和模块边界。
2. 阅读 [架构与数据流](01-architecture.md) 和 [模块地图](02-module-map.md)，建立代码导航。
3. 按 [本地开发](04-local-development.md) 配置环境并启动应用。
4. 使用 [验收清单](06-known-issues.md) 的冒烟测试验证本地服务。
5. 把 [新 Codex 接手提示词](08-new-codex-prompt.md) 作为新账号的首条项目指令，再开始开发。

## 文档目录

| 文档 | 用途 |
| --- | --- |
| `00-project-overview.md` | 产品背景、用户路径和业务约束 |
| `01-architecture.md` | 全系统组件图、关键时序与解耦规则 |
| `02-module-map.md` | 页面、API、编排器和数据表的代码入口 |
| `03-data-and-model.md` | 统一知识层、外部数据源、DeepSeek 和缓存约束 |
| `04-local-development.md` | 新账号本地启动、配置、测试与排障命令 |
| `05-deployment-runbook.md` | 单机正式演示环境的部署、升级、备份与回滚 |
| `06-known-issues.md` | 已知问题、风险和每次改动后的验收清单 |
| `07-product-constraints.md` | 不应被破坏的产品与架构边界 |
| `08-new-codex-prompt.md` | 交给新 Codex 账号的学习与协作提示词 |

## 安全交接原则

- 不提交或复制 `.env`、`.env.production`、`.env.media.production`、私钥、数据库、缓存或原始披露文件。
- 新账号自行生成 GitHub Token、部署 SSH Key、DeepSeek Key、视频签名密钥与媒体管理员 Token。
- 所有真实密钥仅写入本机或服务器环境变量；仓库只保留 `.env*.example`。
- 旧账号应撤销曾暴露、过期或不再使用的令牌。

