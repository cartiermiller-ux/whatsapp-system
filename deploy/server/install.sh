#!/usr/bin/env bash
# ============================================================
#  WhatsApp 超链群发系统 —— 服务器端一键部署
#  适配：宝塔面板 / Alibaba Cloud Linux / CentOS / Ubuntu
#
#  用法（在项目根目录执行）：
#      bash deploy/server/install.sh
#
#  做的事：
#      1. 找一个 >= 3.11 的 Python，建 venv 装依赖
#      2. 注册 systemd 服务 whatsapp-api（监听 127.0.0.1:8000）
#      3. 写 nginx 站点配置（静态文件 + /api 反代），reload
#      4. 健康检查
#
#  幂等：重复执行只更新，不会重复建库、不会丢数据。
# ============================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_NAME="whatsapp-api"
NGINX_CONF_NAME="whatsapp.conf"
API_PORT="${API_PORT:-8000}"

# 宝塔环境优先用宝塔的 nginx，否则用系统的
if [ -d /www/server/nginx ]; then
    NGINX_BIN="/www/server/nginx/sbin/nginx"
    VHOST_DIR="/www/server/panel/vhost/nginx"
    LOG_DIR="/www/wwwlogs"
else
    NGINX_BIN="$(command -v nginx || true)"
    VHOST_DIR="/etc/nginx/conf.d"
    LOG_DIR="/var/log/nginx"
fi

RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'; BLUE='\033[36m'; NC='\033[0m'
info()  { echo "${BLUE}[信息]${NC} $*"; }
ok()    { echo "${GREEN}[完成]${NC} $*"; }
warn()  { echo "${YELLOW}[注意]${NC} $*"; }
fail()  { echo "${RED}[失败]${NC} $*" >&2; exit 1; }

echo "============================================================"
echo " WhatsApp 超链群发系统 —— 服务器部署"
echo " 安装目录: $APP_DIR"
echo "============================================================"

[ "$(id -u)" -eq 0 ] || fail "请用 root 执行（sudo bash deploy/server/install.sh）"
[ -f "$APP_DIR/main.py" ] || fail "没找到 main.py，请在项目根目录执行"

# ------------------------------------------------------------
# 1. 找 Python >= 3.11
# ------------------------------------------------------------
info "查找 Python 3.11+ ..."
PYTHON_BIN=""
for cand in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        v="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0.0)"
        major="${v%%.*}"; minor="${v##*.}"
        if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON_BIN="$(command -v "$cand")"
            info "  使用 $PYTHON_BIN (Python $v)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    warn "系统里没有 Python 3.11+，尝试自动安装..."
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y python3.11 python3.11-devel || true
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3.11 python3.11-devel || true
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y python3.11 python3.11-venv || true
    fi
    for cand in python3.13 python3.12 python3.11; do
        if command -v "$cand" >/dev/null 2>&1; then PYTHON_BIN="$(command -v "$cand")"; break; fi
    done
fi
[ -n "$PYTHON_BIN" ] || fail "装不上 Python 3.11+。请在宝塔面板「软件商店」装 Python 项目管理器，或手动装好再重跑"

# ------------------------------------------------------------
# 2. 虚拟环境 + 依赖
# ------------------------------------------------------------
info "准备虚拟环境 ..."
mkdir -p "$APP_DIR/logs" "$APP_DIR/data"
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$APP_DIR/venv" || fail "创建 venv 失败（可能缺 python3-venv）"
fi
VENV_PY="$APP_DIR/venv/bin/python"

info "安装依赖（首次会比较慢）..."
"$VENV_PY" -m pip install --upgrade pip -q
"$VENV_PY" -m pip install -r "$APP_DIR/requirements.txt" -q
ok "依赖就绪：$("$VENV_PY" -c 'import fastapi, sqlalchemy, pydantic, uvicorn; print("fastapi", fastapi.__version__, "| sqlalchemy", sqlalchemy.__version__)')"

# ------------------------------------------------------------
# 3. 环境变量文件（首次生成，之后不覆盖）
# ------------------------------------------------------------
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    info "生成 $ENV_FILE ..."
    cat > "$ENV_FILE" <<'ENVEOF'
# WhatsApp 超链群发系统 —— 运行时环境变量
# 改完执行： systemctl restart whatsapp-api

# 真实发送总开关。账号养好之前务必保持 false
USE_REAL_SEND=false

# 数据库（留空则用项目目录下的 whatsapp.db）
# WHATSAPP_DATABASE_URL=sqlite:////www/wwwroot/whatsapp-system/whatsapp.db

# ---------- WhatsApp 出口代理（国内服务器必配）----------
# 不配的话扫码会一直转圈：直连 web.whatsapp.com 会被黑洞
# WA_PROXY_URL=socks5://127.0.0.1:10808
# WA_PROXY_URL=http://127.0.0.1:7890

# 取 Baileys 版本号的超时，0 = 完全不联网
WA_VERSION_TIMEOUT_MS=5000

# ---------- 第三方对接（不配则走 mock）----------
PROXY_PROVIDER=mock
SMS_PROVIDER=mock
MESSAGE_PROVIDER=wasock
ACCOUNT_PROVIDER=mock
ENVEOF
    ok "已生成 .env"
else
    info ".env 已存在，保留不动"
fi

# ------------------------------------------------------------
# 4. systemd 服务
# ------------------------------------------------------------
info "注册 systemd 服务 $SERVICE_NAME ..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=WhatsApp Bulk Marketing Console (FastAPI)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$ENV_FILE
ExecStart=$VENV_PY -m uvicorn main:app --host 127.0.0.1 --port $API_PORT
Restart=always
RestartSec=3
StandardOutput=append:$APP_DIR/logs/api.log
StandardError=append:$APP_DIR/logs/api.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
systemctl restart "$SERVICE_NAME"
sleep 3

if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "后端已启动（127.0.0.1:$API_PORT）"
else
    warn "后端没起来，最后 30 行日志："
    tail -n 30 "$APP_DIR/logs/api.log" 2>/dev/null || journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
    fail "请按上面的日志排查"
fi

# ------------------------------------------------------------
# 5. nginx 站点
# ------------------------------------------------------------
DIST_DIR="$APP_DIR/frontend/dist"
if [ ! -f "$DIST_DIR/index.html" ]; then
    warn "没找到前端构建产物 $DIST_DIR/index.html"
    warn "请先在本机执行： cd frontend && npm run build"
    warn "然后把 frontend/dist 整个目录上传到服务器同位置"
fi

if [ -n "$NGINX_BIN" ] && [ -x "$NGINX_BIN" ]; then
    info "写入 nginx 配置 ..."
    mkdir -p "$VHOST_DIR"
    cat > "$VHOST_DIR/$NGINX_CONF_NAME" <<EOF
# WhatsApp 超链群发系统
# 由 deploy/server/install.sh 生成，请勿手改（重跑会覆盖）

server {
    listen 80 default_server;
    server_name _;

    root $DIST_DIR;
    index index.html;

    access_log $LOG_DIR/whatsapp.access.log;
    error_log  $LOG_DIR/whatsapp.error.log;

    client_max_body_size 50m;

    # ---------- 后端接口 ----------
    location /api/ {
        proxy_pass http://127.0.0.1:$API_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # 接口文档
    location ~ ^/(docs|redoc|openapi\.json) {
        proxy_pass http://127.0.0.1:$API_PORT;
        proxy_set_header Host $host;
    }

    # ---------- 前端单页应用 ----------
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 静态资源缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|svg|woff2?|ttf|ico)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }
}
EOF

    if "$NGINX_BIN" -t 2>&1 | grep -q 'successful'; then
        "$NGINX_BIN" -s reload
        ok "nginx 已重载"
    else
        warn "nginx 配置校验没通过："
        "$NGINX_BIN" -t 2>&1 || true
        warn "配置已写入 $VHOST_DIR/$NGINX_CONF_NAME，修好后执行： $NGINX_BIN -s reload"
    fi
else
    warn "找不到 nginx，跳过站点配置。后端仍在 127.0.0.1:$API_PORT 运行"
fi

# ------------------------------------------------------------
# 6. 健康检查
# ------------------------------------------------------------
info "健康检查 ..."
sleep 1
if command -v curl >/dev/null 2>&1; then
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/api/v1/auth/login" -X POST -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}' || echo 000)"
    if [ "$code" = "200" ]; then
        ok "后端接口正常（登录接口返回 200）"
    else
        warn "登录接口返回 $code，请查 $APP_DIR/logs/api.log"
    fi
fi

IP="$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo '<服务器IP>')"
echo
echo "============================================================"
echo " 部署完成"
echo "============================================================"
echo " 后端服务 : systemctl status $SERVICE_NAME"
echo " 后端日志 : tail -f $APP_DIR/logs/api.log"
echo " 重启后端 : systemctl restart $SERVICE_NAME"
echo " 接口文档 : http://$IP/docs"
echo " 管理后台 : http://$IP/login"
echo " 默认账号 : admin / admin123   （请尽快改密码）"
echo
echo " 如果浏览器打不开，先在服务器上自测："
echo "   curl -I http://127.0.0.1/"
echo "   curl -s http://127.0.0.1:$API_PORT/api/v1/auth/login -X POST -H 'Content-Type: application/json' -d '{\"username\":\"admin\",\"password\":\"admin123\"}'"
echo " 还不行就检查阿里云安全组有没有放行 80 端口"
echo "============================================================"
