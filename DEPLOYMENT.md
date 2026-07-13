# 公网部署说明

## 推荐架构

GitHub 仓库保存源码并运行 CI；Render Blueprint 直接从仓库根目录的 `Dockerfile` 构建 Web Service；Neon PostgreSQL 保存账号、项目、模板和 AI 设置等持久数据。

GitHub Pages 只能托管静态 HTML、CSS 和 JavaScript，不能运行本项目的 Python API。若使用 Pages，必须另外部署后端，并在构建时设置 `VITE_API_BASE_URL`。

## 上线前必需配置

1. 从 `.env.production.example` 核对生产环境变量。Render Blueprint 会自动生成高强度 `ADMIN_TOKEN`；其他部署方式需要自行生成。
2. 设置 `ADMIN_DEFAULT_PASSWORD`，不要在公网继续使用本地默认密码 `177099`。
3. 设置 `PHONE_CODE_DEV_MODE=0`；没有真实短信服务前，不要向公网开放验证码登录。
4. 如需公共 AI 功能，通过部署平台的 Secret 设置 `AI_PROVIDER`、`AI_MODEL`、`AI_API_KEY`。`AI_PROVIDER` 支持 `deepseek`、`gemini` 和 `openai`；OpenAI 走服务端 Responses API。
5. 设置 `ADMIN_EMAILS=你的邮箱@example.com`，该邮箱登录后也会获得管理员角色。
6. 设置 `PROJECT_LIMIT_PER_OWNER`，控制每个普通用户或访客最多保存多少个项目，默认 20。
7. 设置 `LOGIN_FAILURE_LIMIT_PER_15_MINUTES`，控制同一 IP + 邮箱 15 分钟内允许的登录失败次数，默认 6。
8. 设置 `AI_DAILY_LIMIT_PER_OWNER` 和 `AI_RATE_LIMIT_PER_MINUTE`，前者控制每日额度，后者控制突发频率。
9. 仅在本机或其他 SQLite 容器路线中，才需要为 `/data` 挂载持久磁盘或稳定 volume；Render Free 路线使用 Neon PostgreSQL，不依赖 `/data` 持久化。
10. 使用平台提供的 HTTPS 和自定义域名，并设置 `APP_SECURE_COOKIES=1`。
11. 配置模型账户的消费上限，避免 Key 被滥用后产生不可控费用。

真实密钥、`.env`、`data/app.db`、`data/*.db-*`、`data/projects.json`、`data/auth.json`、`data/templates.json` 和 `data/ai-settings.json` 均不得提交到 GitHub。

## Render Free + Neon Free

> 代码完成并推送到 GitHub 前无需操作 Neon 或 Render；以下步骤在代码就绪后一次完成即可。

Render Free 的文件系统是临时的，不能用 SQLite 保存账号和项目。本方案用 Render 运行应用、Neon 保存 PostgreSQL 数据，适合免费公开内测和试用，不作为生产稳定长期服务承诺：

1. 打开 Neon，点击 **Sign up with GitHub** 登录，再点击 **New project**；选择 **Free** 方案，填写项目名并创建项目。
2. 在 Neon 项目的 **Connect** 页面选择数据库和角色，复制 PostgreSQL 连接字符串；确认末尾包含 `sslmode=require`。该字符串是秘密，不要写入仓库。
3. 打开 Render，点击 **Get Started for Free** 并用 GitHub 登录；依次选择 **New > Blueprint**，授权并选择仓库 `Fxy2021210136/codex--`，Render 会读取仓库根目录的 `render.yaml`。
4. 在 Blueprint 创建页面填写待同步的环境变量：
   - `DATABASE_URL`：粘贴第 2 步的 Neon 连接字符串；
   - `ADMIN_DEFAULT_PASSWORD`：填写新的高强度管理员密码；
   - `ADMIN_EMAILS`：填写管理员邮箱，多个邮箱用英文逗号分隔。
5. 保持 `EMAIL_VERIFICATION_MODE=off`；`ADMIN_TOKEN` 由 Blueprint 自动生成。点击 **Apply** 部署，无需创建数据库、磁盘或其他 Render 服务。
6. 部署状态变为 **Live** 后，打开 `https://<服务名>.onrender.com/api/health`，确认返回内容中的 `database.engine` 为 `postgresql`。
7. 打开应用，注册测试账号并保存一个项目。回到 Render 服务页点击 **Manual Deploy > Deploy latest commit**；重新部署完成后登录，确认账号和项目仍然存在。

免费实例可能在闲置后休眠，首次访问需要等待启动；Render 和 Neon 的免费计划都有月度额度与平台限制，额度耗尽或平台策略变化时可能暂停服务或要求升级。具体额度以各平台当期控制台和官方说明为准。数据保存在 Neon，不受 Render 重新部署影响。

## 免费好落地方案：本机 + SQLite + 临时公网

不需要买硬件，也不需要先买云数据库。最简单的路线是：

1. GitHub 仓库只放源码。
2. 生成管理员令牌：

   ```powershell
   .\scripts\new-admin-token.ps1
   ```

3. 复制 `.env.example` 为 `.env`，填入 `ADMIN_TOKEN`、`ADMIN_EMAILS` 和本机测试用配置。
4. 你的电脑运行后端和前端静态服务：

   ```powershell
   .\scripts\start-local.ps1 -Build
   ```

5. 数据保存在本机 `data/app.db`，它就是持久磁盘文件。备份时复制这个文件即可。
6. 如果需要让别人临时访问，用 Cloudflare Tunnel 把本机端口暴露出去：

   ```powershell
   .\scripts\start-tunnel.ps1
   ```

这个本机 SQLite 方案免费、落地快，但你的电脑必须开机，临时公网地址可能变化；适合测试、演示和早期内测。需要固定公网试用地址时可改用上面的 Render + Neon 路线；生产稳定长期服务还需评估付费资源、备份和监控。

更完整的执行清单见 `PUBLIC_DEPLOYMENT_CHECKLIST.md`；生产环境变量模板见 `.env.production.example`。

## 本机 SQLite 数据备份与恢复

SQLite 数据库默认在 `data/app.db`。正式演示或给别人试用前，建议先备份：

```powershell
.\scripts\backup-db.ps1
```

恢复时先停止正在运行的 `python serve.py`，再执行：

```powershell
.\scripts\restore-db.ps1 -BackupFile .\backups\app-YYYYMMDD-HHMMSS.db -Force
```

`backups/`、`data/app.db` 和 SQLite 的 `-wal` / `-shm` 旁路文件都已加入 `.gitignore`，不要提交到 GitHub。

## 本机容器验证

```bash
cp .env.example .env
# 编辑 .env 后运行
docker compose up --build
```

访问 <http://127.0.0.1:4173>，健康检查为 `/api/health`。公网部署只有在 `ADMIN_TOKEN`、`ADMIN_DEFAULT_PASSWORD` 和 `PHONE_CODE_DEV_MODE=0` 等必需项满足后，`publicReady` 才会为 `true`。

也可以用脚本快速检查：

```powershell
.\scripts\check-public-ready.ps1 -BaseUrl http://127.0.0.1:4173
```

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
- 登录用户可在账号弹窗中导出自己的项目和模板，也可删除账号及其服务端数据；删除前建议先导出备份。
- 登录用户可修改密码；连续失败登录会被短期限制，降低暴力猜测风险。
- `ADMIN_EMAILS` 中的账号登录后是管理员；普通用户和访客会受到 `PROJECT_LIMIT_PER_OWNER` 项目数量限制。
- 自定义工序模板会通过 `/api/templates` 按用户保存；本机 SQLite 路线写入 `data/app.db`，Render + Neon 路线写入 PostgreSQL。
- 未登录访客仍按匿名浏览器 ID 隔离，适合试用，不适合保存正式工程数据。
- 当前账号系统是轻量实现；正式大规模开放前建议补充 GitHub OAuth 或邮箱验证、审计日志、备份恢复、按用户额度和持久化限流，并评估付费计算与数据库资源。本机 SQLite 路线若转为多人公网服务，再迁移到 PostgreSQL。
- AI 配置写入和清除在公网模式下需要 `ADMIN_TOKEN`，普通访客只能使用管理员预先配置的模型。
- 设置页的“上线健康检查”需要 `ADMIN_TOKEN`；会检查数据目录、数据库、管理员令牌、管理员密码、手机验证码模式、安全 Cookie、AI 配置、额度和 Codex 状态。
- 设置页的“运营概览”同样需要 `ADMIN_TOKEN`；只返回统计数据、最近用户、最近项目、最近模板和 AI 调用摘要，不返回密码、Session Token 或 API Key。
- AI 请求有分钟级限流和每日用户额度；运营概览会统计今日成功/失败调用和最近调用状态。后续若开放大规模使用，仍建议接入模型账户侧消费上限和更细的按用户成本统计。

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
