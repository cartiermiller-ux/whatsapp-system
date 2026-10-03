# 第三方资源对接

覆盖四类外部资源：**代理 IP（P0）**、**接码平台（P0）**、**发消息通道（P1）**、**账号采购（P2）**。

## 统一设计

\`\`\`text
providers/
├── base.py               HTTP 客户端（超时/重试/错误归一）、ProviderStatus、号码与代理解析
├── sms_provider.py       接码：mock / virtualsms / smsactivate
├── proxy_provider.py     代理：mock / byteful(Ping Proxies) / static
├── message_provider.py   发消息：wasock（默认）/ wsapi / mock
└── account_provider.py   账号采购：mock / http（通用适配器）
\`\`\`

三条共同规则：

1. **没配密钥就自动退化为 mock**——整套系统在没有第三方账号的情况下依然能跑通、能测试。
2. **只依赖标准库**（\`urllib\`），后端不引入 \`requests\` 等额外依赖。
3. **密钥只从环境变量读**，不出现在代码和仓库里；接口返回一律打码（\`mask_secret\`）。

所有状态都能在 **资源对接** 页面（\`/integrations\`）或 \`GET /api/v1/providers/status\` 看到。

---

## 一、代理 IP（P0）—— Byteful / Ping Proxies

### 已核对的接口

来源：<https://documentation.byteful.com>（Byteful 与 Ping Proxies 是同一套产品线）

| 项目 | 值 |
|---|---|
| 基础地址 | \`https://api.byteful.com/1.0/\` |
| 认证 | 请求头 **同时**需要 \`X-API-Public-Key\` 与 \`X-API-Private-Key\` |
| 账号信息 | \`GET /public/customer/retrieve\` |
| 代理列表 | \`GET /public/user/proxy/search\`（支持 proxy_id / service_id 等筛选） |
| 单个代理 | \`GET /public/user/proxy/retrieve/{proxy_id}\` |
| 代理字段 | \`http_formatted\` / \`socks5_formatted\`，格式为 \`host:port:username:password\` |

### 配置

\`\`\`powershell
$env:PROXY_PROVIDER   = "byteful"          # mock（默认）/ byteful / static
$env:BYTEFUL_PUBLIC_KEY  = "你的公钥"
$env:BYTEFUL_PRIVATE_KEY = "你的私钥"
\`\`\`

如果没有 API、只有一批现成代理，用 \`static\`：

\`\`\`powershell
$env:PROXY_PROVIDER = "static"
$env:PROXY_LIST = "1.2.3.4:8080:user:pass;socks5://user:pass@5.6.7.8:1080"
# 或放一个 proxies.txt，每行一个
\`\`\`

### 注册时自动分配

\`number_pool\` 增加了 \`proxy_ip\` 字段（存**完整代理地址** \`http://user:pass@host:port\`，
不是裸 IP——配置浏览器/客户端时直接可用）。

流程：

\`\`\`text
simulate_register()
   └─ allocate_proxy(db, number, country=number.region)
        ├─ 从 proxy_pool 取一条 status='free' 的代理（优先同国家）
        ├─ 池子空了 -> 自动 sync_proxy_pool() 从供应商拉一次
        ├─ 标记 in_use、绑定号码、used_count+1
        └─ 把 address 写进 number.proxy_ip
\`\`\`

- 池子里没有可用代理时**默认继续注册**（只记日志）。要改成硬性要求：
  \`\`\`powershell
  $env:PROXY_REQUIRED = "true"    # 没有代理就把号码置为 failed
  \`\`\`
- 号码弃用后记得释放：\`POST /api/v1/proxies/{id}/release\`（或代码里调 \`release_proxy(db, number_id)\`）

> ⚠️ 默认的 \`PROXY_PROVIDER=mock\` 会生成一批 \`10.0.x.x\` 的**占位代理**用于打通流程，
> 它们**不能真正上网**。配好真实供应商后（或手工导入自己的代理）才会分配可用代理。
> 想先不让任何代理进池子，把 \`PROXY_REQUIRED\` 保持 false 并在注册前不触发同步即可。

### 代理状态机

\`free\` →（分配）→ \`in_use\` →（释放）→ \`free\`
连续 **3 次**探测失败 → \`disabled\`（不再被分配）

### 连通性探测是真的建隧道

\`POST /api/v1/proxies/{id}/test\` 不是"端口通就算好"：HTTP 代理走完整 \`CONNECT\`握手（带
\`Proxy-Authorization\`），SOCKS5 走完整握手 + 认证 + \`CONNECT\`，默认目标是
\`web.whatsapp.com:443\`——这正是发消息要用的链路。

---

## 二、接码平台（P0）—— VirtualSMS / SMSTwins

### 已核对的接口

来源：<https://virtualsms.io/docs>（官方文档，2026-10 核对）

| 项目 | 值 |
|---|---|
| 基础地址 | \`https://virtualsms.io\` |
| 认证 | 请求头 \`x-api-key: vsms_...\` |
| 取号 | \`POST /api/v1/customer/purchase\` body \`{"service":"wa","country":"ID"}\` |
| 查码 | \`GET /api/v1/customer/order/{orderId}\`（官方建议 3-5 秒轮询一次） |
| 取消 | \`POST /api/v1/customer/cancel/{orderId}\`（购买后 120 秒冷却期才能取消/换号） |
| 余额 | \`GET /api/v1/customer/balance\` |

查码返回的关键字段：

\`\`\`json
{
  "success": true, "order_id": "...", "phone_number": "+447911123456",
  "status": "waiting | completed | cancelled | expired",
  "sms_received": false, "expires_at": "2026-03-14T16:00:00+08:00",
  "messages": [{ "sender": "WhatsApp", "content": "...", "received_at": "..." }]
}
\`\`\`

未收到短信时 \`messages\` 是空数组；订单 20 分钟无人使用会自动过期并退款。

### 配置

\`\`\`powershell
$env:SMS_PROVIDER          = "virtualsms"       # mock（默认）/ virtualsms / smsactivate
$env:VIRTUALSMS_API_KEY    = "vsms_xxx"
$env:SMS_SERVICE           = "wa"               # 默认服务代码
$env:SMS_COUNTRY           = "ID"               # 默认国家
\`\`\`

### SMSTwins 等 sms-activate 系平台

VirtualSMS 同时提供 **sms-activate 兼容协议**，很多平台（SMSTwins / DaisySMS 等）同款。
本项目的 \`SmsActivateProvider\` 实现了这套协议，因此直接可用：

\`\`\`powershell
$env:SMS_PROVIDER          = "smsactivate"
$env:SMS_ACTIVATE_API_KEY  = "你的key"
$env:SMS_ACTIVATE_BASE_URL = "https://你的平台/stubs/handler_api.php"
\`\`\`

协议（纯文本响应，出错时 HTTP 仍是 200）：

\`\`\`text
action=getNumber&service=wa&country=0   -> ACCESS_NUMBER:<id>:<phone>
action=getStatus&id=<id>                -> STATUS_WAIT_CODE | STATUS_OK:<code> | STATUS_CANCEL
action=setStatus&status=8&id=<id>       -> 取消并退款
action=getBalance                       -> ACCESS_BALANCE:<n>
\`\`\`

### 代码用法

业务侧只依赖两个方法，不感知厂商：

\`\`\`python
from providers import get_sms_provider

sms = get_sms_provider()
order = sms.request_number(service="wa", country="ID")   # 取号
print(order.phone, order.order_id)

result = sms.wait_for_code(order.order_id, timeout=180, interval=5)
if result.ok:
    print("验证码:", result.code)        # WhatsApp 的 "123-456" 会被拼成 123456
else:
    print("失败:", result.detail)
\`\`\`

验证码提取支持 WhatsApp 的 \`123-456\` 格式和普通 4-8 位数字。

### 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | \`/api/v1/sms/orders\` | 订单分页 |
| POST | \`/api/v1/sms/orders\` | 取号，并把号码写进 \`number_pool\` |
| POST | \`/api/v1/sms/orders/{id}/poll\` | 查询一次验证码 |
| POST | \`/api/v1/sms/orders/{id}/wait\` | 阻塞等待（默认 180 秒，上限 600） |
| POST | \`/api/v1/sms/orders/{id}/cancel\` | 取消（仅 waiting 可取消） |

---

## 三、发消息通道（P1）

发消息已经收敛成 **一个出口** \`send_message()\`（main.py），换厂商只改这一层：

\`\`\`powershell
$env:MESSAGE_PROVIDER = "wasock"    # wasock（默认）/ wsapi / mock
\`\`\`

### wasock（默认）

后端不 import wasock，直接往它的 Node 服务发 JSON 行指令：

\`\`\`text
connect_whatsapp.py ──启动──> wasock Node 服务 (127.0.0.1:5000) <──发指令── 后端
\`\`\`

协议：\`{"action":"sendMessage","chat":"<jid>","msg":"<文本>"}\` → \`{"type":"response","success":true}\`

### wsapi（任何 HTTP 发消息接口）

URL 与字段名全部可配置，不写死任何厂商：

\`\`\`powershell
$env:MESSAGE_PROVIDER   = "wsapi"
$env:WSAPI_URL          = "https://api.example.com/v1/message/send"
$env:WSAPI_TOKEN        = "你的token"
$env:WSAPI_AUTH_HEADER  = "Authorization"     # 自定义鉴权头名
$env:WSAPI_AUTH_PREFIX  = "Bearer "           # 自定义前缀
$env:WSAPI_CHAT_FIELD   = "chat"              # 收件人字段名
$env:WSAPI_TEXT_FIELD   = "message"           # 正文字段名
$env:WSAPI_SUCCESS_FIELD= "success"           # 成功标志字段
\`\`\`

### mock

\`MESSAGE_PROVIDER=mock\` 时不真正发送，直接返回成功，用于本地联调。

---

## 四、账号采购（P2）—— 账号星球

**现状说明**：账号星球的开放 API 目前**没有公开文档**，所以这里不臆造接口，
而是提供一个**通用 HTTP 适配器**：拿到对方的接口文档后，用环境变量填路径和字段名即可，不用改代码。

\`\`\`powershell
$env:ACCOUNT_PROVIDER          = "http"            # mock（默认）/ http
$env:ACCOUNT_API_BASE          = "https://对方的域名"
$env:ACCOUNT_API_TOKEN         = "你的token"
$env:ACCOUNT_API_AUTH_HEADER   = "Authorization"
$env:ACCOUNT_API_AUTH_PREFIX   = "Bearer "
$env:ACCOUNT_API_PRODUCTS_PATH = "/products"       # 商品列表路径
$env:ACCOUNT_API_ORDER_PATH    = "/orders"         # 下单路径
$env:ACCOUNT_API_QUERY_PATH    = "/orders/{order_no}"   # 查单路径
\`\`\`

适配器假定返回体里有 \`data\`（或 \`items\`/\`list\`）数组，元素含
\`id/product_id\`、\`name\`、\`price\`、\`stock\` 等字段；下单返回 \`order_no/order_id\`、
\`status\`、\`accounts\`。若对方协议差异较大，照 \`AccountProvider\` 再写一个类即可。

### 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | \`/api/v1/purchase/products\` | 商品列表 |
| GET | \`/api/v1/purchase/orders\` | 采购订单分页 |
| POST | \`/api/v1/purchase/orders\` | 下单 \`{product_id, quantity, remark}\`（管理员） |
| POST | \`/api/v1/purchase/orders/{id}/sync\` | 查询供应商最新状态，交付后回填账号 |
| DELETE | \`/api/v1/purchase/orders/{id}\` | 删除订单（管理员） |

---

## 环境变量速查

| 变量 | 默认 | 作用 |
|---|---|---|
| \`PROXY_PROVIDER\` | mock | 代理来源：mock / byteful / static |
| \`BYTEFUL_PUBLIC_KEY\` / \`BYTEFUL_PRIVATE_KEY\` | 空 | Byteful/Ping Proxies 公私钥 |
| \`PROXY_LIST\` / \`PROXY_LIST_FILE\` | 空 / proxies.txt | static 模式的代理来源 |
| \`PROXY_REQUIRED\` | false | 没有可用代理时是否中断注册 |
| \`SMS_PROVIDER\` | mock | 接码来源：mock / virtualsms / smsactivate |
| \`VIRTUALSMS_API_KEY\` | 空 | VirtualSMS 密钥 |
| \`SMS_ACTIVATE_API_KEY\` / \`SMS_ACTIVATE_BASE_URL\` | 空 | sms-activate 兼容平台 |
| \`SMS_SERVICE\` / \`SMS_COUNTRY\` | wa / ID | 默认服务与国家 |
| \`MESSAGE_PROVIDER\` | wasock | 发消息通道：wasock / wsapi / mock |
| \`WSAPI_*\` | 空 | wsapi 通道的 URL、token、字段名 |
| \`WASOCK_HOST\` / \`WASOCK_PORT\` | 127.0.0.1 / 5000 | wasock Node 服务地址 |
| \`ACCOUNT_PROVIDER\` | mock | 账号采购：mock / http |
| \`ACCOUNT_API_*\` | 空 | 供应商接口地址、token、路径 |
| \`USE_REAL_SEND\` | false | 群发是否走真实发送 |

参考 \`env.example.ps1\`（可直接 dot-source）。

---

## 安全

- **密钥只走环境变量**，不要写进代码或提交到仓库
- 接口返回的密钥一律打码（只露头尾 4 位）
- 代理密码要展示给运营使用时才返回完整地址；日志里用 \`display()\` 打码
- \`.gitignore\` 已排除 \`proxies.txt\`（如果放在仓库根目录，自行确认不要提交）

---

## 测试

\`\`\`powershell
python tests/integrations_test.py     # 56 项：解析函数、真实代理探测、全部新接口
\`\`\`

测试全部使用 mock 实现，**不联网、不需要任何密钥**。其中代理探测部分会起一个本地假
CONNECT 代理，验证真的完成了握手（含 \`Proxy-Authorization\`）与失败路径。
