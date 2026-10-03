# 测试脚本

所有脚本都用标准库 + `requests`，不需要 pytest。**请在仓库根目录执行**（脚本会 `import main`）。

```powershell
pip install requests
```

## 1. 发送逻辑自测（不需要联网、不需要起服务）

```powershell
python tests/real_send_test.py
```

脚本会起一个**假的 wasock Node 服务**（复刻 `node/server.js` 的"换行分隔 JSON"协议），
让 `wasock_request` / `send_via_wasock` / `real_mass_send` 走**真实 TCP** 完整跑一遍。覆盖：

- **传输层**：正常发送、请求格式、中文/emoji 不乱码、响应被拆包、响应前穿插事件行、
  返回非 JSON、服务直接断开、服务返回 `success=false`、未监听时的报错
- **业务层**：目标解析（含 `resource_group.id` 与 `number_pool.id` 冲突的场景）、文案变量渲染、
  失败重试、计数与 TaskLog、五条前置校验分支、`USE_REAL_SEND` 分流、发送间隔取值、登录态判定

共 **61 项断言**。临时库写在 `tests/.tmp/`，不会碰 `whatsapp.db`，也不连真实 WhatsApp。

## 2. 第三方对接自测（不需要联网、不需要密钥）

```powershell
python tests/integrations_test.py
```

覆盖：代理/号码/验证码解析、**真实代理连通性探测**（起本地假 CONNECT 代理，验证
`Proxy-Authorization` 与失败路径）、代理池同步/导入/分配/释放/连续失败自动停用、
接码取号-查询-等待-取消全流程、账号采购下单-同步-删除、注册时自动写 `proxy_ip`、
发消息通道切换。共 **56 项断言**。

## 3. 扫码登录会话自测（不需要联网）

```powershell
python tests/whatsapp_session_test.py
```

用一个假 Node 服务复刻 `wasock/node/server.js` 的协议，覆盖 setup/start 握手、
二维码事件转 data URL、连接状态流转、408 断开时的可操作提示、setup 被拒绝、
以及登录态解析（`creds.json` 的 `me.id`）。共 **22 项断言**，不连真实 WhatsApp。

## 4. 接口回归（P2 模块，109 项断言）

先起一个隔离的后端，再跑脚本：

```powershell
# 终端 A
$env:WHATSAPP_DATABASE_URL='sqlite:///./tests/.tmp/api_test.db'
python -m uvicorn main:app --host 127.0.0.1 --port 8099

# 终端 B
python tests/p2_api_test.py
```

覆盖鉴权、广告文案/超链 CRUD、短链跳转计点击、余额与充值到账、个人中心与改密、
用户管理权限、系统参数校验等。

## 5. 群发任务 HTTP 链路（9 项断言）

复用上面 8099 的服务：

```powershell
python tests/mass_send_http_test.py
```

验证开关关闭时任务确实由 `simulate_mass_send` 跑完，且 `target_type` 正确落库与返回。

## 6. WhatsApp 网络诊断（排查连不上 / 不出二维码）

```powershell
python tests/wa_net_diag.py
```

会连续解析 `web.whatsapp.com`、逐个 IP 测 443 连通性，并检测本机代理端口
（常见的 10808/10809）。判定依据见 `docs/TROUBLESHOOTING.md`。
