# 单机正式演示部署手册

生产部署使用 Docker Compose、Caddy、持久化卷和固定域名。完整背景见 `docs/single-server-deployment.md`；本文件提供新账号的最短操作路径。

## 前置条件

- 一台 Linux 服务器，已安装 Docker Engine 与 Docker Compose Plugin。
- 域名 A 记录已指向服务器固定公网 IP，安全组开放 TCP `80`、`443`。
- 新账号拥有仓库读取权限和独立 SSH 部署密钥。
- 新账号拥有新的 DeepSeek Key；媒体生产另行准备密钥，不与主应用共用。

## 首次部署命令

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL> /opt/financial-mining
cd /opt/financial-mining
cp .env.production.example .env.production
cp .env.media.production.example .env.media.production
chmod 600 .env.production .env.media.production
```

编辑 `.env.production`：

```text
APP_DOMAIN=你的域名
APP_ALLOWED_ORIGINS=https://你的域名
DEEPSEEK_API_KEY=新的生产密钥
```

媒体演示模式下编辑 `.env.media.production`：

```text
MEDIA_BRIEF_PUBLIC_KEY=生成的视频简报公钥
MEDIA_ADMIN_TOKEN=新的管理员令牌
MEDIA_RENDER_MODE=demo
MEDIA_ALLOWED_ORIGINS=https://你的域名
```

构建并启动：

```bash
docker compose -f compose.production.yaml up -d --build
docker compose -f compose.production.yaml ps
curl --fail https://你的域名/api/health
```

## 常规升级命令

```bash
cd /opt/financial-mining
git pull --ff-only
docker compose -f compose.production.yaml build app media media_worker
docker compose -f compose.production.yaml up -d
docker compose -f compose.production.yaml ps
curl --fail https://你的域名/api/health
```

升级不会改变域名、Caddy 证书或 Docker 数据卷。不要使用 `docker compose down -v`，它会删除持久化数据卷。

## 日志、备份与回滚

```bash
docker compose -f compose.production.yaml logs --tail=150 app
docker compose -f compose.production.yaml logs --tail=150 media
docker compose -f compose.production.yaml logs --tail=150 media_worker
bash scripts/backup_storage.sh /srv/financial-mining-backups
```

代码升级失败时，回退到上一个已验证 Git 提交后重新构建 `app`；不要删除 `financial_mining_data` 与 `financial_mining_media` 卷。数据库迁移、数据恢复和多副本改造前必须先做备份。

