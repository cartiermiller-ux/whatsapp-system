# WhatsApp 超链群发系统

面向 WhatsApp 批量运营的一体化控制台，覆盖 **号码池 → 注册 → 账号养护 → 资源群 → 群发 / 拉群 → 广告文案 → 余额计费 → 系统设置** 的完整链路。

前后端分离：后端 FastAPI + SQLAlchemy，前端 Vue 3 + TypeScript + Element Plus。真实发送通过 [wasock](https://pypi.org/project/wasock/)（封装 Baileys）接入，**默认关闭**，开箱即跑模拟发送。

> ⚠️ **合规提示**：本系统用于**自有账号**的运营管理。请遵守 WhatsApp 服务条款与当地法律法规，不要用于骚扰或垃圾信息群发。

---

## 目录

- [功能模块](#功能模块)
- [实现状态](#实现状态哪些是真的哪些是模拟的)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [默认账号](#默认账号)
- [系统设置项](#系统设置项)
- [真实发送接入](#真实发送接入use_real_send)
- [数据模型](#数据模型)
- [接口文档](#接口文档)
- [测试](#测试)
- [常见问题](#常见问题)
- [安全须知](#安全须知)

---

## 功能模块

| 模块 | 路由 | 能力 |
|---|---|---|
| 数据看板 | \`/dashboard\` | 发送 / 送达 / 阅读汇总，账号健康度分布 |
| 号码池管理 | \`/numbers\` | 批量导入（粘贴或上传 txt/csv）、来源类型、信任分、批量删除、CSV 导出 |
| 注册管理 | \`/register\` | 批量注册、注册状态、失败归因 |
| 账号管理 | \`/accounts\` | 账号列表与详情、健康度、暂停 / 恢复 |
| 资源群管理 | \`/groups\` | 群列表、可发言 / 可邀请 / 审批模式、营销分 |
| 群发任务 | \`/mass-send\` | 创建任务、目标选择（资源群 / 联系人）、进度跟踪 |
| 拉群任务 | \`/pull-group\` | 创建拉群任务、任务列表与详情 |
| 广告消息管理 | \`/ads\` | 多语言文案 CRUD（变量自动提取 + 预览）、超链（短链 / 伪装域名 / 追踪参数）、效果统计 |
| 余额与计费 | \`/billing\` | 余额概览、USDT 充值订单、消费流水、国家计费规则 |
| 个人中心 | \`/profile\` | 账号信息、编辑资料、修改密码、操作日志 |
| 系统设置 | \`/settings\` | 全局参数（按 schema 动态渲染）、用户管理 |

---

## 实现状态（哪些是真的，哪些是模拟的）

阅读代码前先看这张表，避免误判。

| 能力 | 状态 | 说明 |
|---|---|---|
| 号码池 / 账号 / 资源群 CRUD | ✅ 真实 | 落库、分页、筛选齐全 |
| 广告文案 / 超链 / 效果统计 | ✅ 真实 | 短链 \`GET /s/{code}\` 可跳转并累计点击 |
| 余额流水 / 充值订单 / 计费规则 | ✅ 真实（到账为人工确认） | 余额 = 全部流水之和 |
| 用户体系 / 登录 / 改密 / 操作日志 | ✅ 真实 | pbkdf2 加盐散列，改密后旧 token 全部失效 |
| 系统设置读写 | ✅ 真实 | 保存后立即影响发送策略与充值下单 |
| 群发发送 | ⚙️ 默认模拟 | \`USE_REAL_SEND=False\` 走 \`simulate_mass_send\`；置 True 走 \`real_mass_send\`（已实现并测试） |
| 批量注册 | 🧪 模拟 | \`simulate_register\`，成功率随机，未接真实注册协议 |
| 拉群任务 | 🧪 仅建单 | 只写入 \`invite_task\`，暂无执行器 |
| 群链接获取 | 🧪 占位 | \`POST /groups/fetch-links\` 返回"待 wasock 接入" |
| 充值到账 | 🧪 人工确认 | \`POST /balance/recharge/{id}/confirm\`，等链上回调接入 |
| 计费规则 | 🧪 内置常量 | \`BILLING_RULES\`，后续可迁到表里后台维护 |

---

## 技术栈

**后端**：Python 3.11+（开发环境 3.14）、FastAPI、SQLAlchemy 2.x、Pydantic 2、SQLite、Uvicorn
**前端**：Vue 3、TypeScript、Element Plus、Vite、Pinia、Vue Router、ECharts、axios、dayjs
**真实发送（可选）**：wasock 0.5.2（Node.js ≥ 18 + Baileys）

---

## 目录结构

\`\`\`text
whatsapp-system/
├── main.py                  # 后端全部代码：模型、初始化、53 个接口
├── connect_whatsapp.py      # 扫码登录脚本：终端直接打印二维码 + 落盘 qr.png
├── requirements.txt         # 后端依赖（wasock 可选）
├── whatsapp_auth/           # ⚠️ WhatsApp 登录态，已在 .gitignore 中，勿提交
├── whatsapp.db              # SQLite 数据库，首次启动自动建表 + 种子数据
├── docs/
│   ├── API.md               # 接口文档
│   └── TROUBLESHOOTING.md   # 排障手册（二维码不出、DNS 污染等）
├── tests/
│   ├── real_send_test.py    # 发送逻辑自测（49 项断言，不联网）
│   ├── p2_api_test.py       # 接口回归（109 项断言）
│   ├── mass_send_http_test.py
│   └── wa_net_diag.py       # WhatsApp 连通性诊断
└── frontend/
    ├── src/
    │   ├── api/             # axios 封装 + 各模块 API 客户端
    │   ├── types/api.ts     # 与后端一致的 TS 类型
    │   ├── views/           # 11 个页面
    │   ├── layouts/ stores/ router/ utils/
    └── vite.config.ts       # /api 代理到后端 8000
\`\`\`

---

## 快速开始

### 1. 后端

\`\`\`powershell
cd whatsapp-system
pip install -r requirements.txt
python -m uvicorn main:app --reload
\`\`\`

- 服务地址：<http://127.0.0.1:8000>
- 交互式文档：<http://127.0.0.1:8000/docs>
- 首次启动会自动建表、写入默认参数、创建内置管理员

数据库默认落在 \`./whatsapp.db\`，可用环境变量切换：

\`\`\`powershell
$env:WHATSAPP_DATABASE_URL='sqlite:///./tests/.tmp/api_test.db'
\`\`\`

### 2. 前端

\`\`\`powershell
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173
\`\`\`

Vite 已把 \`/api\` 代理到 \`http://127.0.0.1:8000\`（见 \`vite.config.ts\`），无需额外配置 CORS。

生产构建：

\`\`\`powershell
npm run build      # vue-tsc 类型检查 + vite build，产物在 frontend/dist
\`\`\`

---

## 默认账号

| 用户名 | 密码 | 角色 |
|---|---|---|
| \`admin\` | \`admin123\` | 超级管理员 |

> 为兼容早期"任意用户名可登录"的行为，保留了**首次登录自动开户**（\`AUTO_PROVISION_USERS\`）。
> 接入正式权限体系时把它改成 \`False\`，并修改内置管理员密码。

---

## 系统设置项

设置存在 \`setting\` 表，字段定义集中在 \`main.py\` 的 \`SETTING_DEFS\`，前端按 \`GET /settings/schema\` 动态渲染。

| key | 类型 | 默认 | 作用 |
|---|---|---|---|
| \`send_interval_min\` | int | 5 | 真实发送时两条消息的最小间隔（秒） |
| \`send_interval_max\` | int | 30 | 最大间隔（秒），实际取区间内随机值 |
| \`new_device_cooldown_hours\` | int | 24 | 新设备冷却，冷却期内不发送（\`can_send\` 会读） |
| \`daily_send_limit\` | int | 50 | 单账号每日发送上限（\`can_send\` 会读） |
| \`currency\` | str | USDT | 结算币种 |
| \`min_recharge_amount\` | float | 10 | 单笔最低充值 |
| \`recharge_chain\` | str | TRC20 | 充值链 |
| \`recharge_address\` | str | 空 | 收款地址；**为空时无法创建充值订单** |
| \`recharge_expire_minutes\` | int | 30 | 充值订单有效期 |
| \`short_link_domain\` | str | go.wa-link.com | 超链默认域名 |

---

## 真实发送接入（USE_REAL_SEND）

代码已完整实现，**默认关闭**：

\`\`\`python
# main.py
USE_REAL_SEND = False     # False -> simulate_mass_send（模拟发送）
                          # True  -> real_mass_send（wasock 真实发送）
\`\`\`

\`dispatch_mass_send()\` 是唯一分流入口，创建群发任务时挂到 FastAPI 的 BackgroundTasks 上。

### 打开真实发送的步骤

1. 安装 wasock 与 Node.js，取消 \`requirements.txt\` 里 \`wasock==0.5.2\` 的注释并安装
2. 扫码登录：\`python connect_whatsapp.py\`（终端会直接打印二维码，同时写入 \`qr.png\`）
3. 确认登录态：\`whatsapp_auth/creds.json\` 中 \`me.id\` 有值
4. 把系统设置里的 **新设备冷却** 调整为 0（否则账号在冷却期内会被拒发）
5. 把 \`USE_REAL_SEND\` 改成 \`True\`，重启后端

### 发送前会做三道前置校验

任一不通过都会把任务置为 \`failed\` 并把原因打到服务端日志，不会静默空跑：

1. wasock 是否可导入
2. \`whatsapp_auth\` 登录态是否有效（判定逻辑对齐 wasock 自带 \`isauthvalid.js\`）
3. 账号是否满足 \`can_send()\` 发送策略（冷却 / 健康度 / 每日上限）

### 已知限制

- wasock 的 Node 服务**固定占用 127.0.0.1:5000，一个进程只能有一个会话**，因此暂不支持多账号并发发送，\`account_ids\` 只取首个账号做策略校验与日志归属
- 同一时间只能跑一个 \`WhatsAppSocket\`：后端在真实发送时与手动运行的 \`connect_whatsapp.py\` 会抢端口，二者不要同时开

---

## 数据模型

共 13 张表，首次启动由 \`Base.metadata.create_all\` 自动创建；新增字段通过 \`ensure_columns()\` 做轻量迁移（\`create_all\` 不会给已有表补字段）。

| 分组 | 表 | 说明 |
|---|---|---|
| 号码与账号 | \`number_pool\` | 号码池：来源、号段、信任分、状态 |
| | \`account_pool\` | 账号：设备指纹、IP、养护阶段、健康度 |
| 资源 | \`resource_group\` | 资源群：群 JID、可发言/可邀请、营销分 |
| 任务 | \`mass_send_task\` | 群发任务：\`target_type\` + \`target_ids\`、发送/送达/阅读计数 |
| | \`invite_task\` | 拉群任务 |
| | \`task_log\` | 任务执行日志（按账号统计当日发送量） |
| 广告 | \`ad_message\` | 多语言文案、变量、效果计数 |
| | \`ad_link\` | 超链：短码、伪装域名、追踪参数、点击量 |
| 计费 | \`balance_transaction\` | 余额流水账本，**余额 = sum(amount)** |
| | \`recharge_order\` | 充值订单：订单号、链、地址、有效期、状态 |
| 用户 | \`sys_user\` | 用户：pbkdf2 散列、角色、租户、登录统计 |
| | \`operation_log\` | 操作日志：时间 / 操作 / 对象 / 结果 / 详情 |
| 配置 | \`setting\` | 全局参数键值对 |

> \`mass_send_task.target_type\` 用于区分目标语义：\`group\`（\`resource_group.id\`）或 \`contact\`（\`number_pool.id\` 或手机号）。
> 两张表主键都从 1 开始，**只按 ID 猜会把消息发到错误的会话**，因此必须带上类型。

---

## 接口文档

- 完整接口清单：[\`docs/API.md\`](docs/API.md)（53 个接口）
- 运行时交互文档：<http://127.0.0.1:8000/docs>

统一响应结构：

\`\`\`json
{ "code": 0, "data": { }, "message": "可选" }
\`\`\`

出错时返回对应 HTTP 状态码，并统一包装成 \`{ "code": <status>, "message": "<原因>" }\`，
前端 axios 拦截器会自动解包 \`data\` 并弹出 \`message\`。

---

## 测试

\`\`\`powershell
python tests/real_send_test.py        # 49 项：发送逻辑，不联网
python tests/p2_api_test.py           # 109 项：接口回归（需 8099 服务，见 tests/README.md）
python tests/mass_send_http_test.py   # 9 项：群发 HTTP 链路
python tests/wa_net_diag.py           # WhatsApp 连通性诊断
\`\`\`

详见 [\`tests/README.md\`](tests/README.md)。

---

## 常见问题

**Q：二维码一直不出现？**
先跑 \`python tests/wa_net_diag.py\`。最常见原因是 DNS 污染导致 \`web.whatsapp.com\` 解析到被黑洞的 IP，
TCP 握手停在 \`SYN_SENT\`，Node 端既不报错也不出码。处理办法见 [\`docs/TROUBLESHOOTING.md\`](docs/TROUBLESHOOTING.md)。

**Q：打开开关后群发任务立刻 failed，日志写"新设备冷却中"？**
账号 \`created_at\` 在冷却期内。把系统设置的 **新设备冷却（小时）** 改成 0 即可。

**Q：充值订单创建失败，提示未配置收款地址？**
这是有意的引导：先在 **系统设置 → 计费与充值** 填写 \`recharge_address\`。

**Q：改完密码后所有请求 401？**
改密会吊销该用户全部 token（这是设计如此），用新密码重新登录即可。

**Q：前端页面能打开但所有接口报错？**
后端没起来。确认 8000 端口在监听：\`python -m uvicorn main:app --reload\`。

更多排障见 [\`docs/TROUBLESHOOTING.md\`](docs/TROUBLESHOOTING.md)。

---

## 安全须知

以下文件**已在 \`.gitignore\` 中，任何时候都不要提交**：

| 文件 | 泄露后果 |
|---|---|
| \`whatsapp_auth/\` | 含 \`creds.json\`、pre-key、session 文件，等同于完整的 WhatsApp 账号凭据，可被直接接管 |
| \`qr.png\` | 登录二维码，扫了就能登上你的号 |
| \`whatsapp.db\` | 号码、账号、手机号、密码散列等运营数据 |
| \`.cowork-temp/\` | 排查过程的临时文件、备份、解包产物 |

其他建议：

- 首次部署后立即修改内置管理员密码
- 生产环境把 \`AUTO_PROVISION_USERS\` 置为 \`False\`
- 生产环境建议换 PostgreSQL，并把 \`balance_transaction.amount\` 的浮点转换改为 Decimal 直存
- 当前登录态存在进程内存（\`TOKEN_STORE\`），多副本部署需改为 Redis 等共享存储
