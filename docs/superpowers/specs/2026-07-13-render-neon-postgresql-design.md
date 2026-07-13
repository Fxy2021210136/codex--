# Render 与 Neon PostgreSQL 公网部署设计

## 目标

在不改变现有前端功能和本机使用方式的前提下，让同一套应用可以部署到 Render Free，并将账号、会话、项目、自定义工序模板和 AI 配置持久保存到 Neon Free PostgreSQL。

验收结果：

- 本机未配置 PostgreSQL 时仍使用 `data/app.db`。
- 配置 PostgreSQL `DATABASE_URL` 后，服务自动建表并使用 PostgreSQL。
- Render 重启、休眠唤醒或重新部署后，账号和项目数据仍然存在。
- `/api/health` 和管理员上线检查能显示数据库类型及连接状态。
- SQLite 与 PostgreSQL 的核心账号、项目和模板流程都经过自动测试。

## 非目标

本阶段不实现邮箱验证码、找回密码、真实短信、GitHub OAuth、微服务拆分、ORM、数据库管理后台，也不自动迁移本机 `app.db` 中的历史数据。需要迁移正式历史项目时，先使用现有项目 JSON 逐个导出和导入；账号、Session 和 AI 密钥不迁移。

## 架构

```text
GitHub main
    ↓ Render 自动构建 Dockerfile
React 静态文件 + Python HTTP 服务（同一容器）
    ↓ DATABASE_URL=postgresql://...
Neon PostgreSQL

本机 ScheduleAI.exe / start-local.ps1
    ↓ 未配置 PostgreSQL DATABASE_URL
SQLite data/app.db
```

保留现有单体结构。`serve.py` 继续承载静态文件和 API，不拆分前后端服务。数据库层只增加 PostgreSQL 连接适配，不引入 ORM。

## 数据库选择与连接

数据库选择遵循一个规则：

- `DATABASE_URL` 以 `postgresql://` 或 `postgres://` 开头时使用 PostgreSQL。
- 其他情况继续使用当前 SQLite 文件路径。

PostgreSQL 使用 `psycopg`，这是唯一新增的 Python 运行依赖。连接串完全来自部署环境变量，不写入仓库、前端或日志。

现有存储类继续使用同一组 `execute`、`fetchone`、`fetchall` 和事务调用。轻量连接适配层负责：

- 将现有 `?` 参数占位符转换为 PostgreSQL 的 `%s`。
- 将 PostgreSQL 查询结果保持为字典式行，兼容现有 `row["name"]` 访问。
- 统一事务提交、回滚和关闭行为。
- 继续使用现有进程内锁，避免在当前单实例部署中引入连接池和并发写入复杂度。

`ON CONFLICT ... excluded`、部分唯一索引和大部分现有字段定义可直接用于 PostgreSQL。SQLite 专属的 `PRAGMA`、`AUTOINCREMENT` 和表字段检查使用独立的 PostgreSQL 建表与迁移语句替代。

## 建表与迁移

启动时按当前数据库类型执行幂等建表：

- SQLite 保留现有建表和旧字段迁移逻辑。
- PostgreSQL 使用 `CREATE TABLE IF NOT EXISTS`、`CREATE INDEX IF NOT EXISTS` 和 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。
- `ai_usage.id` 在 PostgreSQL 中使用 identity 自增列。
- 手机号唯一约束继续使用 `WHERE phone <> ''` 的部分唯一索引。

JSON 文件到 SQLite 的旧版自动迁移只在 SQLite 模式运行。公网 PostgreSQL 从空数据库开始，避免容器中的临时文件被误认为迁移源。

## 请求数据流

1. 浏览器调用现有同源 `/api/*`。
2. Python 服务从 Session Cookie 确定用户或访客 owner。
3. 现有 Store 类通过统一数据库连接执行查询。
4. PostgreSQL 事务成功后提交；失败时回滚并返回现有 JSON 错误格式。
5. Render 容器不保存业务数据，因此重新部署不会影响 Neon 中的数据。

前端 API、项目 JSON 结构、模板结构和登录交互均不改变。

## 错误处理与安全

- PostgreSQL 驱动缺失但配置了 PostgreSQL URL：启动立即失败，并给出安装运行依赖的明确错误。
- 数据库连接或建表失败：启动失败，不降级到临时 SQLite，防止公网数据写入错误位置。
- `/api/health` 只暴露数据库类型和是否可连接，不暴露主机、用户名、密码或完整连接串。
- 管理员上线检查将 PostgreSQL 可连接列为公网必需项。
- Neon 连接串通过 Render Secret 环境变量保存。
- 保持现有密码哈希、HttpOnly Cookie、用户数据隔离、配额和管理员权限边界。

## Render 部署

仓库新增 Render Blueprint，复用当前 Dockerfile：

- 服务类型：Docker Web Service。
- 套餐：Free。
- 健康检查：`/api/health`。
- 自动部署分支：`main`。
- `APP_HOST=0.0.0.0`、`APP_SECURE_COOKIES=1`；前端公开模式继续使用 Dockerfile 现有的构建默认值。
- `DATABASE_URL`、`ADMIN_TOKEN`、`ADMIN_DEFAULT_PASSWORD` 和 `ADMIN_EMAILS` 由用户在 Render 控制台填写，不提供默认秘密值。

Docker 运行阶段安装 PostgreSQL 驱动；本机未配置 PostgreSQL 时不要求运行 Neon。

## 测试

保留当前 24 项 TypeScript 测试和 24 项 SQLite 后端测试。新增最小 PostgreSQL 集成测试，覆盖：

- 幂等建表。
- 注册、登录和 Session 查询。
- 项目保存、读取、更新与用户隔离。
- 自定义模板保存与读取。
- 服务重新创建数据库连接后数据仍存在。

GitHub Actions 启动临时 PostgreSQL service，安装 Python 运行依赖并运行该集成测试。生产构建和 Docker 构建继续作为提交门禁。

## 用户需要完成的操作

代码合并后，用户只需要：

1. 使用 GitHub 账号注册 Neon，创建免费 PostgreSQL 项目并复制带 `sslmode=require` 的连接串。
2. 使用 GitHub 账号登录 Render，从 `Fxy2021210136/codex--` 创建 Blueprint 或 Web Service。
3. 在 Render 填写 `DATABASE_URL`、`ADMIN_TOKEN`、`ADMIN_DEFAULT_PASSWORD` 和 `ADMIN_EMAILS`。
4. 首次部署后打开 `/api/health`，再以管理员身份运行上线健康检查。
5. 注册一个测试账号、保存项目，触发一次重新部署后确认数据仍然存在。

## 完成标准

- 本机 SQLite 启动、测试和 EXE 启动方式不受影响。
- GitHub Actions 的 SQLite、PostgreSQL、TypeScript、构建和 Docker 检查全部通过。
- Render 获得固定 HTTPS 地址。
- 测试账号跨 Render 重启后仍可登录并读取已保存项目和模板。
- 仓库和日志中不出现数据库密码或连接串。
