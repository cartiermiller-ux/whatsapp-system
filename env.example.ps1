# 第三方资源对接的环境变量示例（PowerShell）
# 用法：. .\env.example.ps1       然后在同一个会话里启动后端
# 全部为可选：不设置时，各类资源自动使用 mock 实现，系统照常可跑。

# ---------- 代理 IP（P0） ----------
# mock（默认） / byteful / static
$env:PROXY_PROVIDER = "mock"
# Byteful = Ping Proxies，两个密钥都要
# $env:BYTEFUL_PUBLIC_KEY  = ""
# $env:BYTEFUL_PRIVATE_KEY = ""
# static 模式：直接用自己手上的代理
# $env:PROXY_LIST = "1.2.3.4:8080:user:pass;socks5://user:pass@5.6.7.8:1080"
# 没有可用代理时是否中断注册（默认 false，只记日志）
$env:PROXY_REQUIRED = "false"

# ---------- 接码平台（P0） ----------
# mock（默认） / virtualsms / smsactivate
$env:SMS_PROVIDER = "mock"
# $env:VIRTUALSMS_API_KEY = "vsms_xxx"
# sms-activate 兼容平台（SMSTwins / DaisySMS 等）
# $env:SMS_ACTIVATE_API_KEY  = ""
# $env:SMS_ACTIVATE_BASE_URL = "https://你的平台/stubs/handler_api.php"
$env:SMS_SERVICE = "wa"
$env:SMS_COUNTRY = "ID"

# ---------- 发消息通道（P1） ----------
# wasock（默认） / wsapi / mock
$env:MESSAGE_PROVIDER = "wasock"
# $env:WSAPI_URL           = "https://api.example.com/v1/message/send"
# $env:WSAPI_TOKEN         = ""
# $env:WSAPI_CHAT_FIELD    = "chat"
# $env:WSAPI_TEXT_FIELD    = "message"
# $env:WSAPI_SUCCESS_FIELD = "success"

# ---------- 账号采购（P2） ----------
# mock（默认） / http
$env:ACCOUNT_PROVIDER = "mock"
# $env:ACCOUNT_API_BASE          = "https://对方的域名"
# $env:ACCOUNT_API_TOKEN         = ""
# $env:ACCOUNT_API_PRODUCTS_PATH = "/products"
# $env:ACCOUNT_API_ORDER_PATH    = "/orders"
# $env:ACCOUNT_API_QUERY_PATH    = "/orders/{order_no}"

# ---------- wasock 服务地址 ----------
$env:WASOCK_HOST = "127.0.0.1"
$env:WASOCK_PORT = "5000"

# ---------- WhatsApp 网络出口（国内必配） ----------
# 国内直连 web.whatsapp.com 会被黑洞（TCP 握手停在 SYN_SENT），必须给 Node 一个代理。
# 不配就直连，只会一直转圈出不来二维码。
# $env:WA_PROXY_URL = "http://127.0.0.1:7890"        # Clash / Mihomo 混合端口
# $env:WA_PROXY_URL = "socks5://127.0.0.1:10808"     # v2rayN / Nekoray（需 npm i -g socks-proxy-agent）
# 取 Baileys 版本号的超时；设成 0 就完全不联网，直接用内置版本
$env:WA_VERSION_TIMEOUT_MS = "5000"
# 也可以手动钉死版本号，彻底跳过联网
# $env:WA_BAILEYS_VERSION = "2.3000.1043857760"

# 配好之后先体检，看到 [OK] HTTP/1.1 101 再启动后端：
#   python tools/check_network.py --proxy $env:WA_PROXY_URL --scan

# ---------- 群发真实发送总开关 ----------
$env:USE_REAL_SEND = "false"
