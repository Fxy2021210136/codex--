# 公开使用上线清单

这份清单提供两条免费路线：长期公开访问用 Render + Neon；无需云账号的临时演示继续用本机 SQLite + Tunnel。

> 代码完成并推送到 GitHub 前无需操作 Neon 或 Render。

## 方案 A：零成本内测，本机 + SQLite + Tunnel

适合：演示、同学/同事试用、小范围收集反馈。

1. 拉取或打开仓库。
2. 生成管理员令牌：

   ```powershell
   .\scripts\new-admin-token.ps1
   ```

3. 复制 `.env.example` 为 `.env`，至少填写：

   ```env
   ADMIN_TOKEN=上一步生成的长令牌
   ADMIN_EMAILS=你的邮箱@example.com
   ADMIN_DEFAULT_PASSWORD=本机测试可保留177099
   PHONE_CODE_DEV_MODE=1
   APP_SECURE_COOKIES=0
   APP_DATA_DIR=./data
   PROJECT_LIMIT_PER_OWNER=20
   AI_DAILY_LIMIT_PER_OWNER=20
   ```

4. 启动本机服务：

   ```powershell
   .\scripts\start-local.ps1 -Build
   ```

5. 打开 <http://127.0.0.1:4173/>，用 `ADMIN_EMAILS` 中的邮箱注册/登录。
6. 进入“系统设置”，刷新“上线健康检查”和“运营概览”。
7. 如果要临时给别人访问，另开一个 PowerShell：

   ```powershell
   .\scripts\start-tunnel.ps1
   ```

8. 把 Tunnel 输出的公网地址发给试用者。

注意：你的电脑关机、断网或程序停止后，别人就不能访问；Tunnel 临时地址也可能变化。

## 方案 B：长期公开访问，Render Free + Neon Free

适合：希望别人长期打开一个固定网址使用。

1. 在 Neon 点击 **Sign up with GitHub**，登录后点击 **New project**，创建 Free 项目。
2. 打开项目的 **Connect** 页面，复制 PostgreSQL 连接字符串，并确认包含 `sslmode=require`。
3. 在 Render 用 GitHub 登录，点击 **New > Blueprint**，授权并选择 `Fxy2021210136/codex--`。
4. Render 读取 `render.yaml` 后，填写：

   ```env
   DATABASE_URL=粘贴 Neon 连接字符串
   ADMIN_EMAILS=你的邮箱@example.com
   ADMIN_DEFAULT_PASSWORD=新的高强度管理员密码
   ```

5. 确认 Blueprint 中 `PHONE_CODE_DEV_MODE=0`、`APP_SECURE_COOKIES=1`、`EMAIL_VERIFICATION_MODE=off`；`ADMIN_TOKEN` 会自动生成。
6. 点击 **Apply** 部署。不要创建 Render 磁盘，也不要把连接字符串或密码写入仓库。
7. 部署变为 **Live** 后打开 `https://<服务名>.onrender.com/api/health`，确认 `database.engine` 为 `postgresql`。
8. 注册测试账号、保存项目，再在服务页执行 **Manual Deploy > Deploy latest commit**；重新部署后确认数据仍存在。

Render Free 的文件系统是临时的，因此长期方案必须使用 Neon PostgreSQL，不能使用 SQLite。生产环境变量可参考 `.env.production.example`，关键值为：

```env
ADMIN_EMAILS=你的邮箱@example.com
ADMIN_DEFAULT_PASSWORD=强随机管理员密码
PHONE_CODE_DEV_MODE=0
APP_SECURE_COOKIES=1
APP_DATA_DIR=/data
EMAIL_VERIFICATION_MODE=off
DATABASE_URL=postgresql://user:password@host/database?sslmode=require
PROJECT_LIMIT_PER_OWNER=20
AI_DAILY_LIMIT_PER_OWNER=20
```

上线后第一件事：

1. 用管理员邮箱注册/登录。
2. 打开“系统设置”。
3. 运行“上线健康检查”。
4. 如果数据目录、数据库、管理员密码或验证码模式不是绿色，不要正式开放给别人保存项目。

## 数据备份

本机方案：

```powershell
.\scripts\backup-db.ps1
```

Render + Neon 方案：

- 在 Neon 控制台使用项目提供的备份、分支或导出能力；
- 不要尝试从 Render 的 `/data` 备份 SQLite，长期数据不应存放在那里。

## 不建议现在就做的事

- 不建议把 `data/app.db` 上传到 GitHub。
- 不建议在匿名公共站点开放 Codex 写入权限。
- 不建议把 API Key 写到前端代码或仓库文件。
- 不建议没有持久磁盘就长期开放注册登录，因为重新部署会丢数据。

## 推荐上线顺序

1. 本机跑通。
2. 本机 Tunnel 给 1-3 个人试用。
3. 修正模板、权限和 AI 额度。
4. 用 Render + Neon 建立长期公开地址。
5. 用户和数据明显增长后，再评估付费实例、备份和监控。
