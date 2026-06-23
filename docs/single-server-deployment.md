# 单机正式演示版部署

## 架构

一台长期运行的 Linux 云服务器承载 `app` 与 `caddy` 两个容器。域名的 A 记录指向该服务器的固定 EIP；Caddy 持有 HTTPS 证书并反向代理到 FastAPI。升级时域名不变，只替换 `app` 容器。

当前演示版使用一个持久化 Docker volume 保存 SQLite、JSON 任务缓存和原始文档资产，因此必须保持单个 `app` 副本。不要在该版本中横向扩容 `app`。

## 首次部署

1. 准备 Ubuntu 22.04+ 云服务器、固定 EIP、开放 TCP `80/443` 的安全组。
2. 为域名创建 A 记录并指向该 EIP。
3. 安装 Docker Engine 和 Docker Compose Plugin，克隆仓库。
4. 创建生产密钥文件：`cp .env.production.example .env.production`，填写域名和真实 DeepSeek Key。不要提交此文件。
5. 启动：`docker compose -f compose.production.yaml up -d --build`。
6. 检查：`docker compose -f compose.production.yaml ps`，并访问 `https://<APP_DOMAIN>/api/health`。

## 升级而不换地址

1. 在服务器执行 `git pull`。
2. 在 GitHub Actions 或服务器上的源码目录先执行 `python3 -m unittest tests.test_financial_agent tests.test_three_minute_summary`。
3. 执行 `docker compose -f compose.production.yaml up -d --build app`。
4. 访问 `/api/health` 和核心页面验收。Caddy、域名、EIP 与数据卷均不变。

## 备份与恢复

每日执行：`bash scripts/backup_storage.sh /srv/financial-mining-backups`，并把备份同步到对象存储。恢复时停止 `app`，将压缩包解压回 Docker volume 对应的 storage 目录后重新启动。

## 运行边界

- 本版本是单机正式演示版，不是多副本高可用集群。
- 需要长期稳定和零停机升级时，应迁移到 PostgreSQL、Redis 队列、对象存储和多副本应用服务。
- 如部署在中国大陆，完成域名、服务器和云厂商选型后，请确认备案与相关合规要求。
# 音视频生产服务补充部署

音视频生产服务使用独立的 `financial_mining_media` 卷、独立 `.env.media.production` 和独立管理员凭证。它不会读取财报系统的 SQLite/JSON 数据或 DeepSeek 密钥。

1. 使用 `python3 scripts/generate_video_brief_keys.py` 生成密钥对。
2. 将私钥与 `VIDEO_BRIEF_SUBJECT_SALT` 写入应用 `.env.production`，并设置 `MEDIA_PRODUCTION_URL=https://<domain>/media`。
3. 将公钥、`MEDIA_ADMIN_TOKEN` 与 `MEDIA_ALLOWED_ORIGINS` 写入 `.env.media.production`。
4. 执行 `docker compose -f compose.production.yaml up -d --build app media caddy`。

默认 `MEDIA_RENDER_MODE=demo` 不会调用外部 TTS/即梦模型，只产生可审核的字幕和生产清单。真实媒体 Provider 必须在独立服务中配置后才可启用。

真实生产模式设置 `MEDIA_RENDER_MODE=production` 后，`media_worker` 才会调用火山 TTS、即梦异步视频任务和容器内 FFmpeg。`Dockerfile.media` 独立安装 FFmpeg 与中文字体，原财报应用镜像不携带任何媒体 Provider 凭证。生产前必须先在火山控制台核验 TTS 音色、即梦 `req_key`、额度与并发配额。
