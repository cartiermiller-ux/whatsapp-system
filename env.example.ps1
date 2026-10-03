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

# ---------- 群发真实发送总开关 ----------
$env:USE_REAL_SEND = "false"
