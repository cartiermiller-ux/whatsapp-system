# 排障手册

记录本项目中真实踩过、且不容易一眼看出的坑。每条都包含**判定方法**和**处理办法**。

排查工具箱：

```powershell
python tests/wa_net_diag.py     # WhatsApp 连通性诊断（DNS / 逐 IP / 本机代理）
python tests/real_send_test.py  # 发送逻辑是否符合预期，不联网
```

---

## 1. 二维码一直不出现（最常见）

### 现象

- 终端出现 `Server running on 5000 port`（Node 服务起来了）
- 但**永远不出现二维码**，也不报错，进程看起来像"卡死"
- 项目目录里没有 `qr.png`（或长时间不更新）

### 先确认脚本和事件名（这些其实都是对的）

wasock 0.5.2 的 `node/server.js` 里写得很明确：

```js
// 有二维码时
send(socket, { type: "event", event: "login", qr });     // 事件名就是 login，二维码在顶层 qr
// 连接状态变化时
send(socket, { type: "event", event: "connection", status: "open" | "close", ... });
```

所以 `bot.on("login", on_login)` + `data["qr"]` 是正确写法，**不要怀疑事件名**。

另外 `WhatsAppSocket.start()` 内部确实会 `input()` 阻塞主线程，但回调是丢进
`ThreadPoolExecutor` 执行的（见 `nodejs.py`），**不会挡住出码**。真正卡住的是网络。

### 真正的原因：DNS 污染导致 TCP 握手停在 SYN_SENT

被污染的 DNS 会把 `web.whatsapp.com` 解析到一个**不属于 Meta 的 IP**（例如 Akamai 网段），
这个 IP 的 443 端口被黑洞，SYN 发出去永远收不到 SYN-ACK。
Node 端既不报错也不出码，表现就是静默卡住。

判定方法（看 Node 进程的 socket 状态）：

```powershell
# 先找到 wasock 的 node 进程
Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Select-Object ProcessId,CommandLine
# 看它的连接状态
Get-NetTCPConnection -OwningProcess <pid> | Where-Object { $_.RemotePort -eq 443 } |
  Select-Object State,RemoteAddress,RemotePort
```

真实案例中抓到的对比：

| 状态 | 对端 IP | 结论 |
|---|---|---|
| `SynSent` | `64.13.192.74` | Akamai 网段，**不是** WhatsApp 的 IP，被污染的答案，握手永远完不成 |
| `Established` | `157.240.11.53` | 真实 Meta IP，0.01s 就连上了 |

同一个域名在不同时刻 / 不同解析路径下会拿到不同答案，所以表现为"有时候能出码，有时候卡死"。
Baileys 内部会重连，**往往等几分钟后某次重连拿到好 IP 就突然出码了**。

### 处理办法

按推荐顺序：

1. **让域名固定走代理**（推荐）：代理客户端切到 **TUN / 全局模式**，或改成按域名分流
   （`geosite:whatsapp`）。注意：**系统代理（WinINET）对 Node 无效**，Baileys 是裸 TCP 直连，
   所以"只开系统代理"的情况下 WhatsApp 流量根本没走代理
2. **配 hosts** 指向真实 IP（需要管理员权限，IP 可能变化）：
   ```text
   # C:\Windows\System32\drivers\etc\hosts
   157.240.11.53  web.whatsapp.com
   ```
3. **重跑脚本**：DNS 答案是轮换的，重启就可能拿到好 IP
4. 确认代理端口确实可用：`python tools/check_network.py --scan` 会检测 `127.0.0.1:10808` 等
   常见端口的 SOCKS5 / HTTP CONNECT 是否真的能建立到 `web.whatsapp.com:443` 的隧道
5. **让 Node 自己走代理（本项目已支持，最省事）**：不用改 hosts、不用开 TUN 全局，
   直接把代理地址给 Node 服务：

   ```powershell
   $env:WA_PROXY_URL = "http://127.0.0.1:7890"        # Clash 混合端口
   $env:WA_PROXY_URL = "socks5://127.0.0.1:10808"     # v2rayN / Nekoray 的 SOCKS5
   python -m uvicorn main:app --port 8000
   ```

   **更推荐写进项目根目录的 `.env`**，不用改环境变量、也不用重启后端：

   ```ini
   WA_PROXY_URL=socks5://127.0.0.1:10808
   WA_VERSION_TIMEOUT_MS=5000
   ```

   `whatsapp_session.py` 和 `deploy/wasock/server.js` 都会在**运行时**读这个文件
   （环境变量优先于 `.env`），所以改完直接点「启动会话」就生效。

   `deploy/wasock/server.js` 用它给 Baileys 的 WebSocket 和媒体下载都挂上代理
   （`agent` / `fetchAgent`）。HTTP 代理开箱可用；SOCKS5 需要额外装包，
   注意要装到 wasock 能找到的位置，例如：

   ```powershell
   cd "$(python -c "import wasock,pathlib;print(pathlib.Path(wasock.__file__).parent/'node')")"
   npm install socks-proxy-agent --registry=https://registry.npmmirror.com
   ```

   配好后在面板「账号管理 → 扫码登录 WhatsApp」就能出码。
   状态里出现 `connected` 就说明号已经上线了。

   启动前先体检，一条命令看清链路：

   ```powershell
   python tools/check_network.py --proxy socks5://127.0.0.1:10808 --scan
   ```

   看到 `[OK] HTTP/1.1 101` 就说明 TLS + WebSocket 握手都通了，扫码和发消息都没问题。

### 另一个隐性卡点：Baileys 版本号请求会永久挂起（已修复）

即使代理配好了，旧版 `server.js` 仍可能卡住 —— 它在 `start` 分支里：

```javascript
const { version } = await fetchLatestBaileysVersion();   // 请求 raw.githubusercontent.com
```

这个请求打的是 GitHub，国内网络下同样会被黑洞：**连接既不成功也不报错，Promise 永不 resolve**。
而 `start` 是 `await` 完才回包，于是前端看到的就是「二维码一直转圈」，且永远不会超时。

实测数据（本机）：

| 场景 | 耗时 |
|---|---|
| 原始 `fetchLatestBaileysVersion()` | **20 秒仍无响应（挂死）** |
| 修复后 `start` 回包（跳过联网） | 0.04s |
| 修复后 `start` 回包（联网失败走回退） | 0.54s |

`deploy/wasock/server.js` 的修复方式：

- 给 `fetchLatestBaileysVersion` 传 `timeout` + 代理 `httpsAgent`，外面再套一层
  `Promise.race` 硬超时（双保险，axios 的 timeout 兜不住的场景也能脱身）
- 超时/失败就回退到 Baileys **内置版本号**（`lib/Defaults/baileys-version.json`），照常出码
- 版本号**只解析一次并缓存**，断线重连不会反复去网上拉

可用的环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `WA_PROXY_URL` | 空 | `http://…` 或 `socks5://…`，空则直连 |
| `WA_VERSION_TIMEOUT_MS` | `5000` | 取版本号的超时；**设为 `0` 则完全不联网**，直接用内置版本 |
| `WA_BAILEYS_VERSION` | 空 | 手动指定 `2.3000.1043857760` 这样的版本号，跳过联网 |
| `WA_PORT` | `5000` | Node 服务端口，后端会跟着 `WASOCK_PORT` 自动设置 |

对应的回归测试：`python tests/wasock_wiring_test.py`（11 项断言，会真的拉起 node 进程验证
`setup` / `start` 一定回包）。

### 用推荐脚本

仓库里的 `connect_whatsapp.py` 已经做了针对性处理：

- **终端直接打印二维码**（不必追着每 20 秒刷新一次的 `qr.png` 扫）
- 启动前**预检** `web.whatsapp.com:443`，把解析到的 IP 和连接耗时打出来
- 监听 `connection` 事件，连不上立刻打印 `statusCode` / `reason`，不再静默
- 120 秒没出码就给出明确原因和可操作建议
- 不使用 `bot.start()`（它的 `input()` 会挡住主线程）

---

## 1.1 在面板里扫码登录

面板已经内置扫码入口（**账号管理 → 扫码登录 WhatsApp**），不需要再开终端脚本：

- `POST /api/v1/whatsapp/start` 会自动拉起 wasock 的 Node 服务（找不到 server.js 时
  用 `WASOCK_SERVER_JS` 指定路径），随后页面每 3 秒轮询 `/whatsapp/status` 拿二维码
- 二维码由后端请 Node 端渲染成 PNG，再转成 data URL 下发，前端不需要引入二维码库
- 扫码成功后点「登记到账号池」，该号会写进 `number_pool` / `account_pool`，
  之后就能在群发任务里选择

如果会话停在「连接已断开」并显示 `statusCode=408`，说明本机到 WhatsApp 的
WebSocket 握手超时 —— 属于第 1 节的 DNS/网络问题，按那里的办法处理，不是面板的 bug。

## 2. 端口 5000 是单例，别同时跑两份

wasock 的 Node 服务**固定监听 127.0.0.1:5000**，而 `NodeJS` 的连接逻辑只是"重试连接 5000"，
**不校验这个服务是不是自己拉起来的**（见 `nodejs.py` 的 `connectToServer`）。

后果：启动第二个 `WhatsAppSocket` 时，它会静默连上第一个进程的 Node 服务，
在同一个 Baileys 会话上再叠一个连接，两个会话互相干扰，甚至互相顶下线。

因此：

- 同一时间只跑**一个** `connect_whatsapp.py`，不要开两份
- 后端**不创建会话**，它只往 5000 端口发 `sendMessage` 指令（见下一节），
  所以后端和数据登录脚本不会互相抢端口

### 后端报 "wasock Node 服务未运行"

这是真实发送最常见的失败原因。后端发送前会先探一次 `127.0.0.1:5000`：

```text
[real_mass_send] 任务 #12 未执行：wasock Node 服务未运行（127.0.0.1:5000），
                 请先运行 python connect_whatsapp.py 并保持它在线
```

原因：Node 服务是 `connect_whatsapp.py` 启动的**子进程**，脚本一退出它就跟着退出。
所以真实发送期间必须让 `connect_whatsapp.py` 一直开着（它最后会进入常驻循环，按 Ctrl+C 才退出）。

快速确认：

```powershell
# 端口在不在
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 5000 }
# 后端视角的探测结果
python -c "import main; print('node running =', main.wasock_is_running())"
```

### 后端如何与 Node 服务通信

不 import wasock，直接走 TCP + 换行分隔 JSON（协议见 `wasock/node/server.js`）：

```python
{"action": "sendMessage", "chat": "8613800138000@s.whatsapp.net", "msg": "文本"}
# 响应 {"type": "response", "success": true, "message": ""}
```

实现见 `main.py` 的 `wasock_request()` / `send_via_wasock()`：按行读取，能容忍响应被拆包，
并会跳过 `type=event` 的事件行（二维码轮换等事件只会推给发起 `start` 的那个连接，
本连接正常只收到自己的响应，跳过只是防御性处理）。

地址和端口可用环境变量覆盖：`WASOCK_HOST`、`WASOCK_PORT`。

---

## 3. 登录态判定：`registered` 为 false 也算已登录

扫码成功后的 `whatsapp_auth/creds.json` 长这样：

```json
{ "registered": false, "me": { "id": "8613xxxxxxx:1@s.whatsapp.net", "name": "..." } }
```

**`registered` 在部分版本/流程里会一直是 false**，真正代表配对成功的是 `me.id`。
只看 `registered` 会把已登录判成未登录，导致真实发送全部被拒。

`main.py` 的 `is_wasock_logged_in()` 已按"`registered` 或 `me.id` 任一成立"判定，
并额外对齐 wasock 自带 `isauthvalid.js` 的规则（目录内文件数 > 1 且 `creds.json` 能解析）。

另外注意：**扫码完成前 `whatsapp_auth` 目录内容很少甚至为空是正常的**，
`creds.json` 要配对后才会写入，不能拿它判断"连不上"。

```powershell
# 快速判断登录态
python -c "import main; print(main.is_wasock_logged_in())"
```

---

## 4. 打开真实发送后任务立刻 failed，日志写"新设备冷却中"

这是**发送策略拦截，不是 bug**。`real_mass_send` 在发送前会调用 `can_send()` 校验：

- 新设备冷却：`new_device_cooldown_hours`（默认 24 小时）
- 健康度低于 60 拒绝
- 单账号当日发送量达到 `daily_send_limit`（默认 50）拒绝

而账号池里的账号往往是刚注册的，`created_at` 在 24 小时内 → 必然被冷却拦下。

处理：**系统设置 → 发送策略 → 新设备冷却（小时）改成 0**，保存后立即生效（参数是真的会读取的）。

---

## 5. 后端启动失败 / 多进程同时启动

`create_all()` 只建新表，**不会给已存在的表补字段**，因此新增字段走 `ensure_columns()` 做轻量迁移
（`ALTER TABLE ... ADD COLUMN`）。

多个进程同时启动时可能同时执行同一条 `ALTER TABLE`，其中一个会拿到
`duplicate column name`。`ensure_columns()` 已做容错：捕获异常后重新检查字段是否存在，
存在就当作正常跳过，其他异常也只记录日志、**不阻断服务启动**。

如果后端起不来，先单独验证导入：

```powershell
python -c "import main; print('ok')"
```

---

## 6. 前端页面能打开，但所有接口报错

Vite（5173）还活着、后端（8000）已经挂了 —— 页面能渲染，但每个请求都会失败。

```powershell
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 8000,5173 }
python -m uvicorn main:app --reload
```

---

## 7. 改完密码后所有请求都 401

设计如此：修改密码会**吊销该用户全部 token**（`revoke_user_tokens`），需要用新密码重新登录。
管理员在用户管理里重置密码同理。

---

## 8. 充值订单创建失败，提示"尚未配置收款地址"

这是有意的引导，不是 bug。先在 **系统设置 → 计费与充值** 填写 `recharge_address`，
保存后返回余额页刷新即可下单。

---

## 9. 群发消息发到了错误的会话

检查任务的 `target_type`。`resource_group.id` 与 `number_pool.id` **各自从 1 开始**，
两者会大量重号：

- `target_type = "group"` → `target_ids` 按资源群 ID 解析
- `target_type = "contact"` → 按号码池 ID 解析，取不到再当手填手机号

早期版本没有这个字段、只按 ID 猜，会把联系人任务发到群里。现在 `target_type` 已落库且必填
（不传默认 `group`，老数据也是 `group`）。
