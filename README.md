# 施工进度计划 AI

基于 React + TypeScript + Vite 的通用工程计划应用。当前版本已经从房建单一模板升级为支持多工程类型和自定义模板的计划工作台。

## 已实现

- 项目描述本地解析，以及 DeepSeek / Gemini AI 解析
- 44 项房建标准工序模板
- 道路、桥梁、市政管网、工业安装、自定义工程模板包
- 自定义空间层级，例如楼栋/楼层、标段/区段、桥梁/墩台、片区/管段、装置区/系统
- 自定义工序模板新增、复制、编辑、删除和浏览器持久化，可配置项目类型、空间展开、前置工序、计量单位、资源及材料节点
- FS / SS / FF / SF 关系和 Lag 数据结构
- CPM 正排与逆排、总时差、关键路径实时重算
- 前置任务、关系类型和 Lag 编辑，循环依赖与锁定节点可达性校验
- 按有效工作日计算专业班组/设备峰值、容量和超载天数
- 资源容量可编辑并随项目保存，支持自动错峰、后续链顺延和撤销
- 按项目规模、楼层节拍和工程范围生成计划
- “工序计划”按楼栋和楼层展开主体、二次结构、机电及装修流水任务；“总控计划”保持阶段级颗粒度
- 横道图、AON 网络图、WBS、工序、工序库、计划审查、关键节点、汇报版
- 任务日期、状态、进度和实际日期编辑
- 任务空间、工作面、工程量、资源投入和材料节点，以及自检完成、资料闭合等现场状态
- 横道图日 / 周 / 月尺度切换、任务条拖动和右端工期调整
- 施工日历：周末规则、春节停工、梅雨季敏感工序提示
- 后续依赖任务自动顺延、撤销和重做
- 工作台 AI 助手：关键线路、赶工建议、计划检查、会议摘要和自然语言调整
- 新建计划多 Agent 流水线：条件解析、模板匹配、候选工序确认、依赖试排、置信度与风险预审
- AI 候选模板可选择后写入带版本的自定义模板库；模型 JSON 支持代码块、提取和尾逗号自动修复
- 新建页必填校验、日期校验、空间完整性检查和实时任务/关键线路/风险摘要
- 多版本计划基准、横道图基准条与偏差对比
- 项目 JSON 完整备份/恢复
- A4 横向打印及浏览器“另存为 PDF”版式
- 项目与任务本地保存
- 本机服务端项目库：多项目保存、打开、删除及刷新恢复
- `/api/projects` 同源 CRUD API，默认写入 SQLite 数据库 `data/app.db`
- `/api/templates` 用户级自定义工序模板库，按登录账号或访客 ID 隔离保存到后端
- Excel 五表工作簿导出（项目概览、WBS、资源负荷、风险审查、计划基准）
- CSV 导出
- DeepSeek / Gemini 服务端代理，API Key 脱敏读取且不再进入浏览器模型请求
- OpenAI Responses API 服务端代理，可与 DeepSeek、Gemini 在设置页切换
- 可选 Codex 本机智能体桥接：管理员专用、默认只读沙箱，支持官方 Python SDK或 `codex exec` 回退
- 管理员运营概览：统计 SQLite 存储、注册用户、项目、模板、活跃会话和集成状态
- 邮箱密码注册登录、服务端 Session Cookie、登录用户项目隔离和匿名访客兜底模式
- 登录用户可自助导出账号数据，也可删除账号、项目、模板和会话
- `ADMIN_EMAILS` 登录管理员角色和 `PROJECT_LIMIT_PER_OWNER` 每用户项目数量限制
- `AI_DAILY_LIMIT_PER_OWNER` 每用户每日 AI 调用额度，运营概览统计今日成功/失败调用
- AI 管理令牌和分钟级调用限流
- Docker 多阶段构建、GitHub Actions CI 与 GHCR 镜像发布

## 构建

```powershell
node node_modules/typescript/bin/tsc -b --force
node node_modules/vite/bin/vite.js build .
```

## 本机运行与备份

```powershell
.\scripts\start-local.ps1 -Build
```

默认访问 <http://127.0.0.1:4173/>，数据保存到 `data/app.db`。需要临时给别人访问时，保持本机服务运行，再开一个 PowerShell：

```powershell
.\scripts\start-tunnel.ps1
```

备份和恢复 SQLite 数据库：

```powershell
.\scripts\backup-db.ps1
.\scripts\restore-db.ps1 -BackupFile .\backups\app-YYYYMMDD-HHMMSS.db -Force
```

## 测试

```powershell
node --experimental-strip-types --test tests/schedule.test.ts tests/excel.test.ts
python -m unittest tests.test_server -v
```

测试覆盖 FS / SS / FF / SF、逆排总时差、循环依赖、施工日历、资源容量与自动错峰、六类项目模板生成、自定义空间模板展开、Excel 二进制写入后重新读取、项目 CRUD、登录注册与用户项目隔离，以及 AI 配置脱敏和未配置代理拒绝。

生产文件输出到 `dist/`。本机服务脚本 `serve.py` 会优先发布 `dist/`，并提供项目、登录、模板和 AI 设置 API。默认数据库是 SQLite：`data/app.db`；如果历史目录中存在 `data/projects.json`、`data/auth.json`、`data/templates.json` 或 `data/ai-settings.json`，首次启动会尽量导入 SQLite。

访问地址：<http://127.0.0.1:4173/>

## 公网部署

完整部署步骤、环境变量、持久磁盘及 GitHub 发布流程见 [DEPLOYMENT.md](DEPLOYMENT.md)。GitHub Pages 只能发布静态前端；要保留登录、项目库、模板库和 AI 代理，必须同时运行后端。免费好落地的试用方案是：GitHub 保存代码，你的电脑运行 `python serve.py`，SQLite 存在本机 `data/app.db`，需要临时公网访问时再用 Cloudflare Tunnel 暴露本机端口。

## 安全提示

AI API Key 保存在本机配置文件或部署平台 Secret 中；浏览器只读取脱敏后的末四位，并通过同源 `/api/ai/chat` 调用模型。项目、账号、会话、用户级自定义工序模板和 AI 设置默认保存在 `data/app.db`。公网部署必须设置 `ADMIN_TOKEN`、HTTPS、持久磁盘或稳定数据卷，以及模型消费上限。当前已支持基础邮箱密码登录，但仍建议在正式保存机密工程数据前继续补充审计日志、备份恢复、邮箱验证和企业级权限。
