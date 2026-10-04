# -*- coding: utf-8 -*-
"""在控制台里管理 WhatsApp 会话：启动 Node 服务、接收二维码、跟踪登录状态。

每个账号有独立事件订阅与状态，所有账号共用一个多会话 Node 服务。
旧 connect_whatsapp.py 的单会话服务需要升级；后台会检查多会话能力，避免接入时顶掉账号。
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

WASOCK_HOST = os.environ.get("WASOCK_HOST", "127.0.0.1")
WASOCK_PORT = int(os.environ.get("WASOCK_PORT", "5000"))
PROJECT_DIR = Path(__file__).resolve().parent      # 一律以项目目录为锚点
DEFAULT_AUTH_NAME = os.environ.get("WASOCK_AUTH_NAME", "whatsapp_auth")
AUTH_NAME = DEFAULT_AUTH_NAME          # 兼容旧引用
LOGGER_LEVEL = os.environ.get("WASOCK_LOGGER_LEVEL", "warn")
CONNECT_TIMEOUT = 8.0
START_TIMEOUT = 40.0        # startBaileys 要拉版本、建 socket，给宽一点
QR_TIMEOUT = 20.0


PROJECT_SERVER_JS = PROJECT_DIR / "deploy" / "wasock" / "server.js"
ENV_FILE = PROJECT_DIR / ".env"


def _read_env_file() -> Dict[str, str]:
    """读项目目录下的 .env。

    每次调用都重新读盘，所以改完 .env 不用重启后端 —— 下一次启动会话就生效。
    格式就是最普通的 KEY=VALUE，支持 # 注释、export 前缀和两侧引号。
    """
    data: Dict[str, str] = {}
    try:
        text = ENV_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            data[key] = value
    return data


def setting(name: str, default: str = "") -> str:
    """取配置：进程环境变量优先，其次项目目录下的 .env。"""
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    return _read_env_file().get(name, default)


def proxy_url() -> str:
    """出口代理地址，形如 socks5://127.0.0.1:10808 或 http://127.0.0.1:7890。"""
    import sys
    app = sys.modules.get('main')
    if app and hasattr(app, 'ProxyPool') and hasattr(app, 'SessionLocal'):
        with app.SessionLocal() as db:
            row = db.query(app.ProxyPool).filter_by(is_default=True).first()
            if row:
                if row.provider == 'mock' or row.status == 'disabled':
                    raise SessionError('默认出口代理不可用，请到资源对接 → 代理池更换默认出口')
                return row.address
    return setting("WA_PROXY_URL", "").strip()


def _wasock_package_dir() -> Optional[Path]:
    """wasock 包所在目录。用 find_spec 只找位置、不导入模块。"""
    try:
        spec = importlib.util.find_spec("wasock")
    except (ImportError, ValueError):
        return None
    if not spec or not spec.origin:
        return None
    return Path(spec.origin).parent


def find_server_js() -> Optional[str]:
    """定位 server.js。

    优先用项目里 deploy/wasock/server.js —— 它比 wasock 自带的多一个代理支持
    （国内服务器连不上 WhatsApp，必须走代理）。
    其次才是 wasock 自带的，也可以用 WASOCK_SERVER_JS 直接指定。
    """
    if PROJECT_SERVER_JS.is_file():
        return str(PROJECT_SERVER_JS)
    explicit = os.environ.get("WASOCK_SERVER_JS")
    if explicit and Path(explicit).is_file():
        return explicit
    package = _wasock_package_dir()
    if not package:
        return None
    candidate = package / "node" / "server.js"
    return str(candidate) if candidate.is_file() else None


def find_node_modules() -> str:
    """wasock 自带的 node_modules —— 项目里的 server.js 靠 NODE_PATH 找到 baileys。"""
    package = _wasock_package_dir()
    if not package:
        return ""
    modules = package / "node" / "node_modules"
    return str(modules) if modules.is_dir() else ""


class SessionError(Exception):
    pass


@dataclass
class SessionState:
    status: str = "idle"          # idle / starting / waiting_qr / connected / closed / error
    qr: str = ""
    qr_image: str = ""            # data:image/png;base64,...
    qr_seq: int = 0
    qr_updated_at: Optional[float] = None
    connected_at: Optional[str] = None
    last_error: str = ""
    node_running: bool = False
    node_owned: bool = False      # Node 服务是否由后端拉起
    auth_name: str = ""
    events: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.__dict__)
        data["qr_age_seconds"] = (
            round(time.time() - self.qr_updated_at, 1) if self.qr_updated_at else None
        )
        data.pop("qr", None)      # 原始串不给接口，页面只需要图片
        return data


def auth_path(auth_name: str) -> Path:
    """把登录态目录名解析成绝对路径。

    传绝对路径原样返回；传名字则挂到项目目录下，因此不受启动时 cwd 影响。
    """
    path = Path(auth_name)
    return path if path.is_absolute() else PROJECT_DIR / path


def next_auth_name(base: str = "") -> str:
    """给「关联新账号」挑一个尚未使用的登录态目录名。

    已配对的目录里不会再出二维码，所以必须用一个全新的目录才能扫新号。
    """
    base = base or DEFAULT_AUTH_NAME
    existing = {path.name for path in PROJECT_DIR.glob(f"{base}*") if path.is_dir()}
    index = 1
    while True:
        candidate = base if index == 1 else f"{base}_{index}"
        if candidate not in existing:
            return candidate
        index += 1


def list_auth_dirs(base: str = "") -> list:
    """列出本机已有的登录态目录及其配对号码，供界面展示与切换。"""
    base = base or DEFAULT_AUTH_NAME
    result = []
    for path in sorted(PROJECT_DIR.glob(f"{base}*")):
        if not path.is_dir():
            continue
        phone = read_paired_phone(str(path))
        result.append({
            "auth_name": path.name,
            "paired_phone": phone,
            "paired": bool(phone),
            "files": len([f for f in path.iterdir() if f.is_file()]),
        })
    return result


def remove_auth_dir(auth_name: str) -> bool:
    """解绑：删掉登录态目录（不可恢复）。"""
    import shutil
    path = auth_path(auth_name)
    if not path.is_dir() or path.name in ("", ".", ".."):
        return False
    # 安全起见只允许删项目目录下的东西
    if PROJECT_DIR not in path.resolve().parents:
        raise ValueError(f"拒绝删除项目目录之外的路径：{path}")
    shutil.rmtree(path, ignore_errors=True)
    return True


def read_paired_phone(auth_name: str = "") -> str:
    """从登录态里解析出已配对的号码。

    Baileys 里代表配对成功的是 creds.json 的 me.id（形如
    "8613800000000:12@s.whatsapp.net"），registered 在部分流程里会一直是 false，
    不能只看它。解析不出来就返回空串。
    """
    creds = auth_path(auth_name or AUTH_NAME) / "creds.json"
    if not creds.is_file():
        return ""
    try:
        data = json.loads(creds.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    me = data.get("me") or {}
    head = str(me.get("id") or "").split("@", 1)[0].split(":", 1)[0]
    return "".join(ch for ch in head if ch.isdigit())


def is_node_running(host: str = WASOCK_HOST, port: int = WASOCK_PORT,
                    timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def _read_line(sock: socket.socket, buffer: bytes) -> tuple:
    while b"\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("wasock 服务关闭了连接")
        buffer += chunk
    line, buffer = buffer.split(b"\n", 1)
    return line.decode("utf-8", "ignore").strip(), buffer


class WhatsAppSession:
    """一个账号的 WhatsApp 会话；Node 服务由所有账号共享。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._multi_session = False
        self._require_multi = False
        self._state = SessionState()
        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._proxy_url = ''  # Resolve the selected exit at connection time, not module import.

    # ---------------------------------------------------------------- 对外
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            # 只刷新"服务在不在"，不要动 status：
            # 之前这里会把 error 抹成 idle，失败原因就被藏起来了
            self._state.node_running = is_node_running()
            data = self._state.to_dict()
            from urllib.parse import urlsplit
            parsed = urlsplit(self._proxy_url)
            data["proxy_url"] = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}" if parsed.hostname else ""
            data["server_js"] = "project" if PROJECT_SERVER_JS.is_file() else "wasock"
            return data

    def start(self, auth_name: str = "", proxy_override: Optional[str] = None) -> Dict[str, Any]:
        with self._lifecycle_lock:
            return self._start(auth_name, proxy_override)

    def _start(self, auth_name: str = "", proxy_override: Optional[str] = None) -> Dict[str, Any]:
        """启动会话。Node 服务没起就拉起，然后 setup + start 并开始收二维码。

        auth_name 指定登录态目录：传一个**全新的目录**就会出二维码（关联新账号），
        传已配对的目录则直接以该账号上线。不传则沿用上次的目录。
        """
        target = auth_name or self._state.auth_name or DEFAULT_AUTH_NAME
        desired_proxy = proxy_url() if proxy_override is None else proxy_override
        with self._lock:
            same_dir = (self._state.auth_name == target and self._proxy_url == desired_proxy)
            self._proxy_url = desired_proxy
            if (same_dir and self._state.status in ("starting", "waiting_qr", "connected")
                    and self._sock):
                return self._state.to_dict()
            if self._sock:
                # Disconnect only this event subscriber; other account sessions stay online.
                self._teardown()
            self._state.auth_name = target
            self._state.status = "starting"
            self._state.last_error = ""
            self._state.events = []
            self._state.qr = ""
            self._state.qr_image = ""
            self._state.connected_at = None
        try:
            with _node_start_lock:
                self._ensure_node()
            self._open_and_start(target)
        except Exception as exc:                       # noqa: BLE001 - 统一转成状态
            with self._lock:
                self._state.status = "error"
                self._state.last_error = f"{type(exc).__name__}: {exc}"
            self._teardown(keep_error=True)
        return self.snapshot()

    def stop(self) -> Dict[str, Any]:
        with self._lifecycle_lock:
            return self._stop()

    def detach(self) -> None:
        """Close the API event subscription without stopping the account at Node."""
        with self._lifecycle_lock:
            self._teardown()

    def _stop(self) -> Dict[str, Any]:
        """断开当前会话（不删除登录态）。"""
        previous = self._state.auth_name
        if self._multi_session and previous:
            with socket.create_connection((WASOCK_HOST, WASOCK_PORT), START_TIMEOUT) as control:
                control.settimeout(START_TIMEOUT)
                control.sendall(json.dumps({"action": "stop", "authName": str(auth_path(previous))}).encode()+b"\n")
                line, _ = _read_line(control, b"")
                reply = json.loads(line)
                if not reply.get('success'):
                    raise SessionError(reply.get('message') or '停止账号会话失败')
        self._teardown()
        with self._lock:
            self._state = SessionState(node_running=is_node_running(), auth_name=previous)
        return self._state.to_dict()

    # ---------------------------------------------------------------- 内部
    def _ensure_node(self) -> None:
        if setting('WASOCK_EXTERNAL', 'false').lower() == 'true':
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if is_node_running():
                    with self._lock:
                        self._state.node_owned = False
                    return
                time.sleep(0.3)
            raise SessionError('WhatsApp 会话服务未启动，请联系管理员检查会话服务')
        if is_node_running():
            with self._lock:
                self._state.node_owned = False
            return
        server_js = find_server_js()
        if not server_js:
            raise SessionError(
                "找不到 wasock 的 node/server.js。请先安装 wasock（pip install wasock==0.5.2），"
                "或用环境变量 WASOCK_SERVER_JS 指定路径"
            )
        creation = 0
        if os.name == "nt":
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        env = dict(os.environ)
        modules = find_node_modules()
        if modules:
            # 项目里的 server.js 在 deploy/wasock 下，靠 NODE_PATH 才能 require 到 baileys
            env["NODE_PATH"] = modules
        # server.js 默认监听 5000，这里跟随 WASOCK_PORT，避免改了端口后两边对不上
        env["WA_PORT"] = str(WASOCK_PORT)

        # 代理和其他 Node 侧配置：环境变量优先，其次项目目录下的 .env
        proxy = proxy_url()
        if proxy:
            env["WA_PROXY_URL"] = proxy
        for key in ("WA_VERSION_TIMEOUT_MS", "WA_BAILEYS_VERSION"):
            value = setting(key, "")
            if value:
                env[key] = value

        if proxy:
            print("[wasock] 已启用代理", flush=True)
        else:
            print("[wasock] 未配置 WA_PROXY_URL，将直连 WhatsApp（国内网络会失败）", flush=True)
        self._process = subprocess.Popen(["node", server_js], creationflags=creation, env=env)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if is_node_running():
                with self._lock:
                    self._state.node_owned = True
                return
            time.sleep(0.3)
        raise SessionError(f"wasock Node 服务启动超时（端口 {WASOCK_PORT} 未被监听）")

    def _open_and_start(self, auth_name: str) -> None:
        sock = socket.create_connection((WASOCK_HOST, WASOCK_PORT), CONNECT_TIMEOUT)
        sock.settimeout(START_TIMEOUT)
        try:
            # setup 告诉 Node 端用哪个登录态目录
            # 传绝对路径：server.js 内部按 Node 进程的 cwd 解析，相对路径会跑偏
            setup = {"action": "setup", "loggerLevel": LOGGER_LEVEL,
                     "authName": str(auth_path(auth_name)),
                     "browserInfo": ["ubuntu", "Chrome", "14.4.1"], "syncFullHistory": False, "proxyUrl": self._proxy_url}
            sock.sendall(json.dumps(setup).encode() + b"\n")
            buffer = b""
            line, buffer = _read_line(sock, buffer)
            setup_reply = json.loads(line)
            if not setup_reply.get("success"):
                raise SessionError("setup 被拒绝")
            self._multi_session = setup_reply.get("multi_session", False)
            if self._require_multi and not self._multi_session:
                raise SessionError('Node 服务不支持多账号会话，请重启升级后的 deploy/wasock/server.js')

            sock.sendall(json.dumps({"action": "start"}).encode() + b"\n")
            pending_events = []
            while True:
                line, buffer = _read_line(sock, buffer)
                start_reply = json.loads(line)
                if start_reply.get('type') == 'event':
                    pending_events.append(start_reply)
                    continue
                if not start_reply.get('success'):
                    raise SessionError(start_reply.get('message') or 'start 被拒绝')
                break
        except Exception:
            sock.close()
            raise

        sock.settimeout(None)
        with self._lock:
            self._sock = sock
            self._running = True
            self._state.status = 'connected' if start_reply.get('status') == 'connected' else 'waiting_qr'
        if start_reply.get('qr'):
            pending_events.append({'type':'event','event':'login','qr':start_reply['qr']})
        for event in pending_events:
            self._handle_event(event)
        self._reader = threading.Thread(target=self._read_events, args=(sock, buffer), daemon=True)
        self._reader.start()

    def _read_events(self, sock=None, buffer=b"") -> None:
        sock = sock or self._sock
        try:
            while self._running and sock is self._sock:
                line, buffer = _read_line(sock, buffer)
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if sock is self._sock:
                    self._handle_event(message)
        except Exception as exc:                        # noqa: BLE001
            if self._running and sock is self._sock:
                with self._lock:
                    self._state.status = "closed"
                    self._state.last_error = f"事件通道断开：{exc}"
        finally:
            if sock is self._sock and not self._running:
                with self._lock:
                    if self._state.status not in ('error', 'closed'):
                        self._state.status = 'idle'

    def _handle_event(self, message: Dict[str, Any]) -> None:
        if message.get("type") != "event":
            return
        if message.get('authName') and Path(message['authName']).resolve() != auth_path(self._state.auth_name).resolve():
            return
        event = message.get("event")
        with self._lock:
            self._state.events.append({"event": event, "at": datetime.now().isoformat()})
            self._state.events = self._state.events[-20:]

        if event == "login" and message.get("qr"):
            qr = message["qr"]
            image = self._qr_to_data_url(qr)
            with self._lock:
                self._state.qr = qr
                self._state.qr_seq += 1
                self._state.qr_updated_at = time.time()
                self._state.status = "waiting_qr"
                if image:
                    self._state.qr_image = image
        elif event == "connection":
            status = message.get("status")
            if status == "open":
                with self._lock:
                    self._state.status = "connected"
                    self._state.connected_at = datetime.now().isoformat()
                    self._state.qr = ""
                    self._state.qr_image = ""
                    self._state.last_error = ""
            elif status == 'stopped':
                with self._lock:
                    self._state.status = 'idle'
                    self._state.qr = self._state.qr_image = ''
            else:
                code = message.get("statusCode")
                reason = message.get("reason") or ""
                detail = f"连接关闭（statusCode={code}）{reason}".strip()
                if code == 408 or "timed out" in reason.lower():
                    detail = ("服务器连接 WhatsApp 超时（408），暂时无法生成二维码或恢复登录。"
                              "请检查出口网络，或在资源对接 → 代理池配置默认出口，"
                              "然后停止此会话并重新连接。无需解绑已有账号。")
                with self._lock:
                    self._state.status = "closed"
                    self._state.last_error = detail

    def _qr_to_data_url(self, qr: str) -> str:
        """让 Node 端把二维码渲染成 PNG，再读成 data URL。

        用独立连接发起：事件只会推给发过 start 的那条连接，所以这里能干净地只收响应。
        """
        try:
            with socket.create_connection((WASOCK_HOST, WASOCK_PORT), QR_TIMEOUT) as sock:
                sock.settimeout(QR_TIMEOUT)
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "qr.png"
                    payload = {"action": "qrcodeGenerate", "type": "img", "qr": qr,
                               "fileName": str(path), "fileWidth": 520}
                    sock.sendall(json.dumps(payload).encode() + b"\n")
                    buffer = b""
                    while True:
                        line, buffer = _read_line(sock, buffer)
                        if not line:
                            continue
                        data = json.loads(line)
                        if "success" in data or data.get("type") == "response":
                            if not data.get("success"):
                                return ""
                            break
                    if not path.is_file():
                        return ""
                    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                    return f"data:image/png;base64,{encoded}"
        except Exception:                               # noqa: BLE001 - 渲染失败不影响主流程
            return ""

    def _teardown(self, keep_error: bool = False) -> None:
        with self._lock:
            self._running = False
            sock, self._sock = self._sock, None
            if not keep_error:
                self._state.status = "idle"
                self._state.qr = ""
                self._state.qr_image = ""
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
            except OSError:
                pass


_session: Optional[WhatsAppSession] = None  # legacy standalone callers
_session_lock = threading.Lock()
_node_start_lock = threading.Lock()
_sessions: Dict[str, WhatsAppSession] = {}


def get_session(auth_name: Optional[str] = None) -> WhatsAppSession:
    global _session
    with _session_lock:
        if auth_name is None:
            if _session is None:
                _session = WhatsAppSession()
            return _session
        key = str(auth_path(auth_name).resolve())
        if key not in _sessions:
            session = WhatsAppSession()
            session._require_multi = True
            session._state.auth_name = auth_name
            _sessions[key] = session
        return _sessions[key]


def session_snapshots() -> Dict[str, Dict[str, Any]]:
    with _session_lock:
        sessions = list(_sessions.items())
    return {name: session.snapshot() for name, session in sessions}


def detach_sessions() -> None:
    with _session_lock:
        sessions = list(_sessions.values())
    for session in sessions:
        session.detach()
