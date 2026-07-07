# 公网部署说明

## 推荐架构

GitHub 仓库保存源码并运行 CI；GitHub Actions 构建 Docker 镜像并发布到 `ghcr.io`；支持容器和持久磁盘的平台运行该镜像。

GitHub Pages 只能托管静态 HTML、CSS 和 JavaScript，不能运行本项目的 Python API。若使用 Pages，必须另外部署后端，并在构建时设置 `VITE_API_BASE_URL`。

## 上线前必需配置

1. 从 `.env.example` 复制 `.env`，生成高强度 `ADMIN_TOKEN`。
2. 如需公共 AI 功能，通过部署平台的 Secret 设置 `AI_PROVIDER`、`AI_MODEL`、`AI_API_KEY`。`AI_PROVIDER` 支持 `deepseek`、`gemini` 和 `openai`；OpenAI 走服务端 Responses API。
3. 为 `/data` 挂载持久磁盘，否则重新部署会丢失项目数据。
4. 使用平台提供的 HTTPS 和自定义域名。
5. 将 `AI_RATE_LIMIT_PER_MINUTE` 设置为可承担的值，并配置模型账户的消费上限。

真实密钥、`.env`、`data/projects.json`、`data/auth.json` 和 `data/ai-settings.json` 均不得提交到 GitHub。

## 本机容器验证

```bash
cp .env.example .env
# 编辑 .env 后运行
docker compose up --build
```

访问 <http://127.0.0.1:4173>，健康检查为 `/api/health`。

## 发布到个人 GitHub 仓库

```bash
git init
git add .
git commit -m "Initial public release"
git branch -M main
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

创建 `v1.0.0` 等标签后，`publish-container.yml` 会把镜像发布到 GitHub Container Registry。GitHub 官方文档说明 GHCR 镜像可由 Actions 使用仓库自带的 `GITHUB_TOKEN` 发布。

## 当前公共访问边界

- 公网容器已支持基础邮箱密码注册登录，密码使用 PBKDF2 哈希保存，登录后项目列表按用户隔离。
- 未登录访客仍按匿名浏览器 ID 隔离，适合试用，不适合保存正式工程数据。
- 当前账号系统是轻量实现；正式大规模开放前建议升级到 PostgreSQL/SQLite 迁移、GitHub OAuth 或邮箱验证、审计日志、备份恢复和持久化限流。
- AI 配置写入和清除在公网模式下需要 `ADMIN_TOKEN`，普通访客只能使用管理员预先配置的模型。
- AI 请求有进程内分钟限流；如开放给多人使用，需要增加按用户额度和成本统计。

## 登录与会话

服务端提供 `/api/auth/register`、`/api/auth/login`、`/api/auth/logout` 和 `/api/auth/me`。登录成功后写入 `HttpOnly` Session Cookie，默认 30 天有效。

生产环境建议：

```bash
SESSION_TTL_SECONDS=2592000
APP_SECURE_COOKIES=1
```

如果前端和 API 分域部署，请设置 `CORS_ALLOWED_ORIGINS=https://你的前端域名`，并确保反向代理保留 Cookie 与 `X-Forwarded-Proto=https`。

## Codex 智能体接入

Codex 与普通模型 API 的权限不同：它可以读取工程目录并调用工具，因此默认关闭，`/api/codex/run` 始终要求管理员权限。

本机已安装 Codex CLI 时可直接启用：

```powershell
$env:ENABLE_CODEX_AGENT='1'
$env:CODEX_MODEL='gpt-5.4'
$env:CODEX_ALLOW_WRITE='0'
python serve.py
```

也可以安装官方 Python SDK：

```powershell
python -m pip install -r requirements-codex.txt
```

服务端优先使用 Python SDK，没有 SDK 时回退到 `codex exec --ephemeral`。默认沙箱为 `read_only`；只有在隔离环境中评估后才可设置 `CODEX_ALLOW_WRITE=1`。不要在匿名公共站点开放 Codex 写入权限。

设置页的“检查网络”会调用管理员专用 `/api/diagnostics/connectivity`，检查当前模型服务和 `api.openai.com` 的 DNS/443 可达性。如果 DNS 能解析但 443 不通，应先检查公司防火墙、透明代理、VPN 或运营商 DNS；不要通过关闭 TLS 校验绕过问题。
