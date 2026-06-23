# 本地开发与快速部署

以下命令假设仓库根目录为当前目录。新账号应先克隆仓库，再配置自己的密钥。

## 1. 最小本地启动

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL> financial-mining
cd financial-mining
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，至少填写：

```text
DEEPSEEK_API_KEY=你的新密钥
```

启动主应用：

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765 --reload
```

验证：

```bash
curl --fail http://127.0.0.1:8765/api/health
open http://127.0.0.1:8765/home.html
```

若系统没有 `open` 命令，直接在浏览器访问该地址。

## 2. 本地媒体演示服务

媒体服务与主应用独立。先生成视频简报密钥对：

```bash
python scripts/generate_video_brief_keys.py
cp .env.media.production.example .env.media.production
```

将私钥、`VIDEO_BRIEF_SUBJECT_SALT` 等主应用侧变量写入 `.env`；将公钥、`MEDIA_ADMIN_TOKEN` 写入 `.env.media.production`。本地先保持：

```text
MEDIA_RENDER_MODE=demo
MEDIA_ALLOWED_ORIGINS=http://localhost:8765
```

新开一个终端启动媒体 API：

```bash
source .venv/bin/activate
bash scripts/run_media_demo.sh
```

再开一个终端启动 Worker：

```bash
source .venv/bin/activate
bash scripts/run_media_worker.sh
```

媒体演示入口默认是 `http://localhost:8766`。真实 TTS、即梦和 FFmpeg 生产模式应先通过 Docker 验证，不要在本地演示配置中填生产凭证。

## 3. 测试命令

```bash
python -m unittest \
  tests.test_financial_agent \
  tests.test_three_minute_summary \
  tests.test_video_brief \
  tests.test_media_production \
  tests.test_media_providers
```

快速语法检查：

```bash
python -m compileall -q backend
```

## 4. 三公司冒烟测试

在浏览器依次验证：

1. A 股：`000001`。
2. 美股：`AAPL`。
3. 美股：`BIDU`。

每个公司至少验证报告期加载、财报 Agent、公司画像和 3 分钟总结的任务状态能结束，且页面没有脚本报错。首次请求可能需要下载披露和调用模型；同输入后续请求应优先命中本地缓存。

## 5. 常见本地问题

- API 返回 502 或 Agent 不可用：先检查 `.env` 中的 DeepSeek 配置和网络代理，再查看模型运行记录。
- 页面轮询超时：确认 Uvicorn 进程仍在运行、端口为 `8765`，并减少一次选择的报告期数量。
- A 股无可用指标：检查巨潮访问和 PDF 数据质量；这不应改写为模型猜测。
- 端口被占用：换用另一个端口，并同步修改 `MEDIA_ALLOWED_ORIGINS` 或浏览器地址。

