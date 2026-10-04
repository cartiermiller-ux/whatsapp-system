# 测试脚本

脚本使用标准库、项目依赖及 `requests` / `httpx`，不需要 pytest。**请在仓库根目录执行**（脚本会 `import main`）。

```powershell
pip install -r requirements.txt requests httpx
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

共 **62 项断言**。临时库写在 `tests/.tmp/`，不会碰 `whatsapp.db`，也不连真实 WhatsApp。

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
以及登录态解析（`creds.json` 的 `me.id`）。共 **35 项断言**，不连真实 WhatsApp。

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

## 运营接口回归

```bash
python tests/operations_test.py
```

覆盖账号展示与代理分配、任务执行/调度/暂停/恢复/取消、失败目标重试、结果不确定时人工核对、回执单调更新、完整会话 ZIP、服务配置脱敏、资源群导入导出与删除、成功目标计费、签名到账回调及防重复入账。使用自动清理的独立临时数据库与会话目录，不访问真实 WhatsApp。

WSL 下旧脚本可设置 `WHATSAPP_TEST_TMP_DIR=/tmp/whatsapp-regression`，避免 Windows 挂载目录中的 SQLite 锁问题。

## 上线安全与备份回归

```bash
python tests/security_test.py
python tests/backup_test.py
```

安全测试使用临时库，覆盖所有业务接口匿名访问、自动开户关闭、拒绝旧 mock-token、普通用户权限、代理管理员越权、CORS、登出撤销、密码修改以及敏感操作审计。备份测试验证 WAL 模式下只复制已提交数据，并检查失败时不留下半成品。

`operations_test.py` 默认使用 SQLite 临时库；可通过 `WHATSAPP_TEST_DATABASE_URL` 指定专用 PostgreSQL 测试库，库名必须以 `_test` 结尾。测试会创建并修改数据，禁止指向生产库。

## 多租户隔离与旧库升级

```bash
python tests/tenant_test.py
python tests/tenant_migration_test.py
```

两个租户分别验证读写、聚合统计、余额、扣费、回调、任务执行、会话和导出隔离；旧库升级测试从提交 bd36441 构造历史数据库，连续升级两次并比较所有原有字段。tenant_test.py 可使用 WHATSAPP_TEST_DATABASE_URL 指定专用 PostgreSQL 测试库，库名必须以 _test 结尾。

## 多账号通道隔离

```bash
node tests/multi_session_node_test.cjs
```

运行真实 server.js 指令处理逻辑，使用内存 Baileys 替身验证双账号同时上线、指令指定账号、共享账号连接复用、消息事件和回执隔离、停止一个账号不影响另一个。operations_test.py 同时覆盖两个操作者的二维码隔离和独立当前选择、跨账号并发任务及消息 ID 冲突时的回执归属。均不访问 WhatsApp。
