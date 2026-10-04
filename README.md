# WhatsApp 超链群发系统

面向 WhatsApp 批量运营的一体化控制台，覆盖 **号码池 → 注册 → 账号养护 → 资源群 → 群发 / 拉群 → 广告文案 → 余额计费 → 系统设置** 的完整链路。

前后端分离：后端 FastAPI + SQLAlchemy，前端 Vue 3 + TypeScript + Element Plus。真实发送通过 [wasock](https://pypi.org/project/wasock/)（封装 Baileys）的 Node 服务接入，**默认关闭**，开箱即跑模拟发送。

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
| 数据看板 | `/dashboard` | 发送 / 送达 / 阅读汇总，账号健康度分布 |
| 号码池管理 | `/numbers` | 批量导入（粘贴或上传 txt/csv）、来源类型、信任分、批量删除、CSV 导出 |
| 注册管理 | `/register` | 批量注册、注册状态、失败归因 |
| 账号管理 | `/accounts` | 账号列表与详情、健康度、暂停 / 恢复 |
| 资源群管理 | `/groups` | 群列表、可发言 / 可邀请 / 审批模式、营销分 |
| 群发任务 | `/mass-send` | 创建任务、目标选择（资源群 / 联系人）、进度跟踪 |
| 拉群任务 | `/pull-group` | 创建拉群任务、任务列表与详情 |
| 广告消息管理 | `/ads` | 多语言文案 CRUD（变量自动提取 + 预览）、超链（短链 / 伪装域名 / 追踪参数）、效果统计 |
| 余额与计费 | `/billing` | 余额概览、USDT 充值订单、消费流水、国家计费规则 |
| 个人中心 | `/profile` | 账号信息、编辑资料、修改密码、操作日志 |
| 系统设置 | `/settings` | 全局参数（按 schema 动态渲染）、用户管理 |
| 资源对接 | `/integrations` | 代理池、接码订单、采购订单、供应商状态 |

---

## 实现状态（哪些是真的，哪些是模拟的）

阅读代码前先看这张表，避免误判。

| 能力 | 状态 | 说明 |
|---|---|---|
| 号码池 / 账号 / 资源群 CRUD | ✅ 真实 | 落库、分页、筛选齐全 |
| 广告文案 / 超链 / 效果统计 | ✅ 真实 | 短链 `GET /s/{code}` 可跳转并累计点击 |
| 余额流水 / 充值订单 / 计费规则 | ✅ 真实（到账为人工确认） | 余额 = 全部流水之和 |
| 用户体系 / 登录 / 改密 / 操作日志 | ✅ 真实 | pbkdf2 加盐散列，改密后旧 token 全部失效 |
| 系统设置读写 | ✅ 真实 | 保存后立即影响发送策略与充值下单 |
| 群发发送 | ⚙️ 默认模拟 | 环境变量 `USE_REAL_SEND` 控制：关闭走 `simulate_mass_send`，打开走 `real_mass_send`（已实现并测试） |
| 批量注册 | 🧪 模拟 | `simulate_register`，成功率随机，未接真实注册协议 |
| 拉群任务 | 🧪 仅建单 | 只写入 `invite_task`，暂无执行器 |
| 群链接获取 | 🧪 占位 | `POST /groups/fetch-links` 返回"待 wasock 接入" |
| 充值到账 | 🧪 人工确认 | `POST /balance/recharge/{id}/confirm`，等链上回调接入 |
| 计费规则 | 🧪 内置常量 | `BILLING_RULES`，后续可迁到表里后台维护 |
| 代理 IP / 接码 / 账号采购 | 🔌 已接入，待填密钥 | 统一 Provider 层，**没配密钥自动用 mock**；详见 [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) |

---

## 技术栈

**后端**：Python 3.11+（开发环境 3.14）、FastAPI、SQLAlchemy 2.x、Pydantic 2、SQLite、Uvicorn
**前端**：Vue 3、TypeScript、Element Plus、Vite、Pinia、Vue Router、ECharts、axios、dayjs
**真实发送（可选）**：wasock 0.5.2 的 Node 服务（Node.js ≥ 18 + Baileys），仅 `connect_whatsapp.py` 需要安装

---

## 目录结构

```text
whatsapp-system/
├── main.py                  # 后端全部代码：模型、初始化、53 个接口
├── connect_whatsapp.py      # 扫码登录脚本（终端版）：打印二维码 + 落盘 qr.png
├── whatsapp_session.py      # 扫码登录（面板版）：多账号会话管理、二维码渲染
├── providers/               # 第三方对接层：代理 IP / 接码 / 发消息 / 账号采购
│   ├── base.py              # HTTP 客户端、错误归一、状态对象
│   ├── sms_provider.py      # 接码：mock / virtualsms / smsactivate
│   ├── proxy_provider.py    # 代理：mock / byteful(Ping Proxies) / static
│   ├── message_provider.py  # 发消息：wasock / wsapi / mock
│   └── account_provider.py  # 账号采购：mock / http
├── deploy/
│   ├── server/install.sh    # 服务器端一键部署（venv + systemd + nginx）
│   ├── package.py           # 打部署包：python deploy/package.py --build
│   └── wasock/              # 改良版 wasock Node 服务
│       ├── server.js        #   代理支持 + 版本号超时兜底
│       └── assets/          #   isauthvalid.js / resolvebrowser.js
├── tools/
│   ├── check_network.py     # WhatsApp 连通性体检：DNS / 直连 / 代理隧道 / TLS+WS 握手
│   └── wait_proxy.py        # 守着等代理出现，通到 WhatsApp 就报出来
├── env.example.ps1          # 所有对接相关环境变量示例
├── requirements.txt         # 后端依赖（wasock 仅登录脚本需要，后端不需要）
├── whatsapp_auth/           # ⚠️ WhatsApp 登录态，已在 .gitignore 中，勿提交
├── whatsapp.db              # SQLite 数据库，首次启动自动建表 + 种子数据
├── docs/
│   ├── API.md               # 接口文档
│   ├── DEPLOY.md            # 服务器部署指南（宝塔 / 阿里云）
│   ├── INTEGRATIONS.md      # 第三方对接说明（代理/接码/发消息/采购）
│   └── TROUBLESHOOTING.md   # 排障手册（二维码不出、DNS 污染等）
├── tests/
│   ├── real_send_test.py    # 发送逻辑自测（61 项断言，不联网）
│   ├── integrations_test.py # 第三方对接自测（56 项断言，不联网）
│   ├── p2_api_test.py       # 接口回归（109 项断言）
│   ├── mass_send_http_test.py
│   ├── whatsapp_session_test.py
│   ├── wasock_wiring_test.py # 真拉起 node 进程，验证 setup/start 一定回包
│   └── wa_net_diag.py       # WhatsApp 连通性诊断（旧版，建议用 tools/check_network.py）
└── frontend/
    ├── src/
    │   ├── api/             # axios 封装 + 各模块 API 客户端
    │   ├── types/api.ts     # 与后端一致的 TS 类型
    │   ├── views/           # 11 个页面
    │   ├── layouts/ stores/ router/ utils/
    └── vite.config.ts       # /api 代理到后端 8000
```

---

## 快速开始

### 1. 后端

```powershell
cd whatsapp-system
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

- 服务地址：<http://127.0.0.1:8000>
- 交互式文档：<http://127.0.0.1:8000/docs>
- 首次启动会自动建表、写入默认参数、创建内置管理员

数据库默认落在 `./whatsapp.db`，可用环境变量切换：

```powershell
$env:WHATSAPP_DATABASE_URL='sqlite:///./tests/.tmp/api_test.db'
```

### 2. 前端

```powershell
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173
```

Vite 已把 `/api` 代理到 `http://127.0.0.1:8000`（见 `vite.config.ts`），无需额外配置 CORS。

生产构建：

```powershell
npm run build      # vue-tsc 类型检查 + vite build，产物在 frontend/dist
```

---

## 默认账号

| 用户名 | 密码 | 角色 |
|---|---|---|
| `admin` | `admin123` | 超级管理员 |

> 默认关闭首次登录自动开户（`AUTO_PROVISION_USERS=false`），用户必须由管理员创建。
> 旧版 `mock-token-用户名` 已禁用；仅接受服务器签发的随机会话 token。首次部署后应修改内置管理员密码。

---

## 系统设置项

设置存在 `setting` 表，字段定义集中在 `main.py` 的 `SETTING_DEFS`，前端按 `GET /settings/schema` 动态渲染。

| key | 类型 | 默认 | 作用 |
|---|---|---|---|
| `send_interval_min` | int | 5 | 真实发送时两条消息的最小间隔（秒） |
| `send_interval_max` | int | 30 | 最大间隔（秒），实际取区间内随机值 |
| `new_device_cooldown_hours` | int | 24 | 新设备冷却，冷却期内不发送（`can_send` 会读） |
| `daily_send_limit` | int | 50 | 单账号每日发送上限（`can_send` 会读） |
| `currency` | str | USDT | 结算币种 |
| `min_recharge_amount` | float | 10 | 单笔最低充值 |
| `recharge_chain` | str | TRC20 | 充值链 |
| `recharge_address` | str | 空 | 收款地址；**为空时无法创建充值订单** |
| `recharge_expire_minutes` | int | 30 | 充值订单有效期 |
| `short_link_domain` | str | go.wa-link.com | 超链默认域名 |

---

## 真实发送接入（USE_REAL_SEND）

**默认关闭**，开箱即跑模拟发送。开关由环境变量控制：

```powershell
$env:USE_REAL_SEND="true"        # 只认 true（大小写不敏感），其它值一律当作关闭
python -m uvicorn main:app --reload
```

```python
# main.py
USE_REAL_SEND = os.environ.get("USE_REAL_SEND", "false").strip().lower() == "true"
```

`dispatch_mass_send()` 是唯一分流入口，创建群发任务时挂到 FastAPI 的 BackgroundTasks 上。

### 分工：谁负责登录，谁负责发送

```text
connect_whatsapp.py ──启动──> wasock Node 服务 (127.0.0.1:5000) <──发指令── 后端 main.py
      负责扫码、保持在线            换行分隔 JSON 协议               只发 sendMessage
```

后端**不 import wasock**，而是直接向 5000 端口发 JSON 行指令：

```python
{"action": "sendMessage", "chat": "8613800138000@s.whatsapp.net", "msg": "文本"}
# 响应 {"type": "response", "success": true, "message": ""}
```

好处：后端不会去拉起第二个 Node 进程抢 5000 端口，也不依赖 wasock 这个 Python 包。

### 扫码登录（面板内，支持多账号）

不用再开终端跑脚本，直接在面板里操作：**账号管理 → 扫码登录 WhatsApp**

弹窗里有两个入口，别搞混 —— 这也是最容易误解的地方：

| 按钮 | 用哪个登录态 | 会不会出二维码 |
|---|---|---|
| **关联新账号（扫码）** | 每次都用**全新**的空目录（`whatsapp_auth_2`、`_3`…） | **会**，扫完就多一个号 |
| **使用已登录账号** | 已有账号在用的目录（默认 `whatsapp_auth`） | **不会**（已配对，直接上线） |

> 之所以要分两条路：wasock 的登录态是按目录存放的，目录一旦配对过就不会再出二维码。
> 所以「想加新号」必须用全新目录，否则点开只会显示「已登录」。

```text
点「关联新账号」 → 后端挑一个全新的登录态目录并启动会话
                → 页面每 3 秒轮询，显示二维码与状态
                → 手机扫码 → 状态变「已登录」
                → 点「登记到账号池」→ 该号写入号码池/账号池，并记住它用的是哪个目录
```

弹窗底部还会列出**其它已关联的账号**，可以一键「使用」切换，或「解绑」删掉登录态。

| 接口 | 说明 |
|---|---|
| `GET /api/v1/whatsapp/status` | 会话状态 + 二维码（data URL）+ 当前会话对应的账号 |
| `GET /api/v1/whatsapp/sessions` | 本机已有的登录态目录及各自对应的账号 |
| `POST /api/v1/whatsapp/start` | `{mode: "new" 或 "current"}` 启动会话 |
| `POST /api/v1/whatsapp/switch` | `{account_id}` 切换到某个账号的会话 |
| `POST /api/v1/whatsapp/stop` | 断开会话（不删登录态） |
| `POST /api/v1/whatsapp/register-account` | 登记到号码池/账号池并绑定登录态目录 |
| `POST /api/v1/whatsapp/unlink` | `{auth_name}` 解绑并删除登录态目录 |

实现见 `whatsapp_session.py`：后端持有那条发过 `start` 的连接（wasock 只会把
login/connection 事件推给它），收到二维码后让 Node 端渲染成 PNG 再转 data URL。

> ⚠️ Node 服务固定占用 `127.0.0.1:5000`，**同一时间只能有一个会话** ——
> 所以多账号是「切换」而不是「并存」，群发时用的是当前会话那个号。
> 面板扫码期间不要在终端再跑 `connect_whatsapp.py`，否则两边会互相顶；
> 接口检测到端口被占用时会直接提示，不会硬抢。

**连不上 WhatsApp 时**：会话会停在「连接已断开」并给出 `statusCode=408` 与排查链接。
这通常是本机到 `web.whatsapp.com` 的网络问题（DNS 污染），不是代码问题，
处理方法见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

### 打开真实发送的步骤

1. 安装 Node.js 与 wasock（**只有 `connect_whatsapp.py` 需要它**）：`pip install wasock==0.5.2`
2. 扫码登录并**保持它一直运行**：`python connect_whatsapp.py`
3. 确认登录态：`whatsapp_auth/creds.json` 里 `me.id` 有值
4. 把系统设置里的 **新设备冷却（小时）** 调整为 0，否则账号在冷却期内会被拒发
5. 另开一个终端，带环境变量启动后端：
   ```powershell
   $env:USE_REAL_SEND="true"; python -m uvicorn main:app --reload
   ```

> 环境变量在**进程启动时**读取，改完必须重启后端；`--reload` 只监听文件变化，不会重新读环境变量。

### 发送前会做三道前置校验

任一不通过都会把任务置为 `failed` 并把原因打到服务端日志，不会静默空跑：

1. wasock Node 服务是否在监听（`127.0.0.1:5000`）
2. `whatsapp_auth` 登录态是否有效（判定逻辑对齐 wasock 自带 `isauthvalid.js`）
3. 账号是否满足 `can_send()` 发送策略（冷却 / 健康度 / 每日上限）

### 已知限制

- **`connect_whatsapp.py` 必须一直开着**：它退出时 Node 服务也随之退出，后端就发不出消息
  （任务会明确失败并提示 `wasock Node 服务未运行`）
- Node 服务**固定占用 127.0.0.1:5000，全局只有一个会话**，因此暂不支持多账号并发发送，
  `account_ids` 只取首个账号做策略校验与日志归属
- 地址与端口可用环境变量覆盖：`WASOCK_HOST`、`WASOCK_PORT`

---

## 资源对接

四类外部资源都收敛到统一 Provider 层（`providers/`），**没配密钥时自动退化为 mock**，
所以开箱即可跑通，拿到密钥后只改环境变量：

| 资源 | 供应商 | 已核对接口 | 配置 |
|---|---|---|---|
| 代理 IP | Byteful / Ping Proxies | ✅ 官方文档 | `PROXY_PROVIDER=byteful` + 公私钥 |
| 接码平台 | VirtualSMS / sms-activate 系（SMSTwins 等） | ✅ 官方文档 | `SMS_PROVIDER=virtualsms` + key |
| 发消息 | wasock（现用）/ WSAPI | wasock 协议已核对 | `MESSAGE_PROVIDER=wasock` |
| 账号采购 | 账号星球 | ⚠️ 无公开文档，用通用适配器 | `ACCOUNT_PROVIDER=http` + 路径 |

注册时会给号码自动分配代理（写进 `number_pool.proxy_ip`），接码平台可一键取号并等待验证码。

完整说明（含接口字段、环境变量、状态机）：**[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)**，
变量示例见 `env.example.ps1`（可直接 dot-source）。

---

## 数据模型

共 16 张表，首次启动由 `Base.metadata.create_all` 自动创建；新增字段通过 `ensure_columns()` 做轻量迁移（`create_all` 不会给已有表补字段）。

| 分组 | 表 | 说明 |
|---|---|---|
| 号码与账号 | `number_pool` | 号码池：来源、号段、信任分、状态 |
| | `account_pool` | 账号：设备指纹、IP、养护阶段、健康度 |
| 资源 | `resource_group` | 资源群：群 JID、可发言/可邀请、营销分 |
| 任务 | `mass_send_task` | 群发任务：`target_type` + `target_ids`、发送/送达/阅读计数 |
| | `invite_task` | 拉群任务 |
| | `task_log` | 任务执行日志（按账号统计当日发送量） |
| 广告 | `ad_message` | 多语言文案、变量、效果计数 |
| | `ad_link` | 超链：短码、伪装域名、追踪参数、点击量 |
| 计费 | `balance_transaction` | 余额流水账本，**余额 = sum(amount)** |
| | `recharge_order` | 充值订单：订单号、链、地址、有效期、状态 |
| 用户 | `sys_user` | 用户：pbkdf2 散列、角色、租户、登录统计 |
| | `operation_log` | 操作日志：时间 / 操作 / 对象 / 结果 / 详情 |
| 配置 | `setting` | 全局参数键值对 |
| 对接 | `proxy_pool` | 代理池：地址、状态机（free/in_use/disabled）、成功率 |
| | `sms_order` | 接码订单：远端单号、号码、验证码、状态 |
| | `purchase_order` | 账号采购订单：商品、数量、金额、交付账号 |

> `mass_send_task.target_type` 用于区分目标语义：`group`（`resource_group.id`）或 `contact`（`number_pool.id` 或手机号）。
> 两张表主键都从 1 开始，**只按 ID 猜会把消息发到错误的会话**，因此必须带上类型。

---

## 接口文档

- 完整接口清单：[`docs/API.md`](docs/API.md)（53 个接口）
- 运行时交互文档：<http://127.0.0.1:8000/docs>

统一响应结构：

```json
{ "code": 0, "data": { }, "message": "可选" }
```

出错时返回对应 HTTP 状态码，并统一包装成 `{ "code": <status>, "message": "<原因>" }`，
前端 axios 拦截器会自动解包 `data` 并弹出 `message`。

---

## 测试

```powershell
python tests/real_send_test.py        # 61 项：发送逻辑与传输层，不联网
python tests/integrations_test.py     # 56 项：代理/接码/采购对接，不联网
python tests/p2_api_test.py           # 109 项：接口回归（需 8099 服务，见 tests/README.md）
python tests/mass_send_http_test.py   # 9 项：群发 HTTP 链路
python tests/whatsapp_session_test.py # 35 项：登录态与会话管理
python tests/wasock_wiring_test.py    # 11 项：真拉起 node，验证握手与 start 回包
```

网络不通时，先用体检脚本把链路一次看清：

```powershell
python tools/check_network.py --scan                                  # 直连诊断 + 扫本机代理端口
python tools/check_network.py --proxy socks5://127.0.0.1:10808        # 走代理做完整握手
```

看到 `[OK] HTTP/1.1 101` 就说明 WhatsApp 链路完全可用。

详见 [`tests/README.md`](tests/README.md)。

---

## 常见问题

**Q：二维码一直不出现？**
先跑 `python tools/check_network.py --scan`。国内网络下有两处会卡住：

1. DNS 污染让 `web.whatsapp.com` 解析到被黑洞的 IP，TCP 握手停在 `SYN_SENT`；
2. Baileys 取版本号时请求 GitHub，同样被黑洞，**Promise 永不 resolve**，`start` 就一直不回包。

解决办法是给 Node 一个代理：`$env:WA_PROXY_URL = "socks5://127.0.0.1:10808"`（第 2 点已在
`deploy/wasock/server.js` 里做了超时 + 内置版本兜底）。详见
[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)。

**Q：打开开关后群发任务立刻 failed，日志写"新设备冷却中"？**
账号 `created_at` 在冷却期内。把系统设置的 **新设备冷却（小时）** 改成 0 即可。

**Q：充值订单创建失败，提示未配置收款地址？**
这是有意的引导：先在 **系统设置 → 计费与充值** 填写 `recharge_address`。

**Q：改完密码后所有请求 401？**
改密会吊销该用户全部 token（这是设计如此），用新密码重新登录即可。

**Q：前端页面能打开但所有接口报错？**
后端没起来。确认 8000 端口在监听：`python -m uvicorn main:app --reload`。

更多排障见 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)。

---

## 安全须知

以下文件**已在 `.gitignore` 中，任何时候都不要提交**：

| 文件 | 泄露后果 |
|---|---|
| `whatsapp_auth/` | 含 `creds.json`、pre-key、session 文件，等同于完整的 WhatsApp 账号凭据，可被直接接管 |
| `qr.png` | 登录二维码，扫了就能登上你的号 |
| `whatsapp.db` | 号码、账号、手机号、密码散列等运营数据 |
| `.cowork-temp/` | 排查过程的临时文件、备份、解包产物 |

其他建议：

- 首次部署后立即修改内置管理员密码
- 生产环境保持 `AUTO_PROVISION_USERS=false`，并通过 `ALLOWED_ORIGINS` 配置明确的跨域白名单
- 生产环境建议换 PostgreSQL，并把 `balance_transaction.amount` 的浮点转换改为 Decimal 直存
- 当前登录态存在进程内存（`TOKEN_STORE`），多副本部署需改为 Redis 等共享存储
