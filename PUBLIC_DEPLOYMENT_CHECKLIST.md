# 公开使用上线清单

这份清单适合当前最省钱、最好落地的路线：源码放 GitHub，应用运行在你的电脑或支持持久磁盘的容器平台，数据先用 SQLite。

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

## 方案 B：长期公开访问，容器 + 持久磁盘

适合：希望别人长期打开一个固定网址使用。

部署平台需要满足三件事：

- 能运行 Docker 镜像或 Python 服务；
- 能挂载持久磁盘到 `/data`；
- 能设置环境变量和 HTTPS 域名。

环境变量可参考 `.env.production.example`。最关键的是：

```env
ADMIN_TOKEN=强随机令牌
ADMIN_EMAILS=你的邮箱@example.com
ADMIN_DEFAULT_PASSWORD=强随机管理员密码
PHONE_CODE_DEV_MODE=0
APP_SECURE_COOKIES=1
APP_DATA_DIR=/data
DATABASE_URL=sqlite:////data/app.db
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

容器平台方案：

- 优先使用平台的磁盘快照；
- 或定期下载 `/data/app.db`；
- 备份前最好暂停写入，避免复制到不完整状态。

## 不建议现在就做的事

- 不建议把 `data/app.db` 上传到 GitHub。
- 不建议在匿名公共站点开放 Codex 写入权限。
- 不建议把 API Key 写到前端代码或仓库文件。
- 不建议没有持久磁盘就长期开放注册登录，因为重新部署会丢数据。

## 推荐上线顺序

1. 本机跑通。
2. 本机 Tunnel 给 1-3 个人试用。
3. 修正模板、权限和 AI 额度。
4. 再迁移到有持久磁盘的长期部署平台。
5. 用户和数据明显增长后，再从 SQLite 升级到 PostgreSQL。
