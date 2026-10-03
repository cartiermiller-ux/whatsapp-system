# -*- coding: utf-8 -*-
"""在控制台里管理 WhatsApp 会话：启动 Node 服务、接收二维码、跟踪登录状态。

之前扫码只能在终端跑 connect_whatsapp.py，本模块把同一套能力搬进后端：
后端持有那条发过 start 的连接（wasock 只会把 login/connection 事件推给它），
把二维码转成 data URL 供网页直接显示。

与 connect_whatsapp.py 的关系：**同一时间只能有一个会话**（Node 服务固定占用
127.0.0.1:5000），所以面板扫码期间要先关掉那个终端脚本，否则两边会互相顶。
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
AUTH_NAME = os.environ.get("WASOCK_AUTH_NAME", "whatsapp_auth")
LOGGER_LEVEL = os.environ.get("WASOCK_LOGGER_LEVEL", "warn")
CONNECT_TIMEOUT = 8.0
START_TIMEOUT = 40.0        # startBaileys 要拉版本、建 socket，给宽一点
QR_TIMEOUT = 20.0


def find_server_js() -> Optional[str]:
    """定位 wasock 的 node/server.js。

    用 find_spec 只找位置、不导入模块，避免后端重新依赖 wasock 这个 Python 包。
    也可以用 WASOCK_SERVER_JS 环境变量直接指定。
    """
    explicit = os.environ.get("WASOCK_SERVER_JS")
    if explicit and Path(explicit).is_file():
        return explicit
    try:
        spec = importlib.util.find_spec("wasock")
    except (ImportError, ValueError):
        return None
    if not spec or not spec.origin:
        return None
    candidate = Path(spec.origin).parent / "node" / "server.js"
    return str(candidate) if candidate.is_file() else None


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
    auth_name: str = AUTH_NAME
    events: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.__dict__)
        data["qr_age_seconds"] = (
            round(time.time() - self.qr_updated_at, 1) if self.qr_updated_at else None
        )
        data.pop("qr", None)      # 原始串不给接口，页面只需要图片
        return data


def read_paired_phone(auth_name: str = "") -> str:
    """从登录态里解析出已配对的号码。

    Baileys 里代表配对成功的是 creds.json 的 me.id（形如
    "8613800000000:12@s.whatsapp.net"），registered 在部分流程里会一直是 false，
    不能只看它。解析不出来就返回空串。
    """
    creds = Path(auth_name or AUTH_NAME) / "creds.json"
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
    """全局唯一的 WhatsApp 会话。线程安全，供 FastAPI 接口调用。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = SessionState()
        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        self._running = False

    # ---------------------------------------------------------------- 对外
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            # 只刷新"服务在不在"，不要动 status：
            # 之前这里会把 error 抹成 idle，失败原因就被藏起来了
            self._state.node_running = is_node_running()
            return self._state.to_dict()

    def start(self) -> Dict[str, Any]:
        """启动会话。Node 服务没起就拉起，然后 setup + start 并开始收二维码。"""
        with self._lock:
            if self._state.status in ("starting", "waiting_qr", "connected") and self._sock:
                return self._state.to_dict()
            self._state.status = "starting"
            self._state.last_error = ""
            self._state.events = []
        try:
            self._ensure_node()
            self._open_and_start()
        except Exception as exc:                       # noqa: BLE001 - 统一转成状态
            with self._lock:
                self._state.status = "error"
                self._state.last_error = f"{type(exc).__name__}: {exc}"
            self._teardown(keep_error=True)
        return self.snapshot()

    def stop(self) -> Dict[str, Any]:
        """断开当前会话（不删除登录态）。"""
        self._teardown()
        with self._lock:
            self._state = SessionState(node_running=is_node_running())
        return self._state.to_dict()

    # ---------------------------------------------------------------- 内部
    def _ensure_node(self) -> None:
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
        self._process = subprocess.Popen(["node", server_js], creationflags=creation)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if is_node_running():
                with self._lock:
                    self._state.node_owned = True
                return
            time.sleep(0.3)
        raise SessionError("wasock Node 服务启动超时（端口 5000 未被监听）")

    def _open_and_start(self) -> None:
        sock = socket.create_connection((WASOCK_HOST, WASOCK_PORT), CONNECT_TIMEOUT)
        sock.settimeout(START_TIMEOUT)
        try:
            # setup 告诉 Node 端用哪个登录态目录
            setup = {"action": "setup", "loggerLevel": LOGGER_LEVEL, "authName": AUTH_NAME,
                     "browserInfo": ["ubuntu", "Chrome", "14.4.1"], "syncFullHistory": False}
            sock.sendall(json.dumps(setup).encode() + b"\n")
            buffer = b""
            line, buffer = _read_line(sock, buffer)
            if not json.loads(line).get("success"):
                raise SessionError("setup 被拒绝")

            sock.sendall(json.dumps({"action": "start"}).encode() + b"\n")
            line, buffer = _read_line(sock, buffer)
            if not json.loads(line).get("success"):
                raise SessionError("start 被拒绝")
        except Exception:
            sock.close()
            raise

        sock.settimeout(None)
        with self._lock:
            self._sock = sock
            self._running = True
            self._state.status = "waiting_qr"
        self._reader = threading.Thread(target=self._read_events, daemon=True)
        self._reader.start()

    def _read_events(self) -> None:
        buffer = b""
        sock = self._sock
        try:
            while self._running and sock:
                line, buffer = _read_line(sock, buffer)
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                self._handle_event(message)
        except Exception as exc:                        # noqa: BLE001
            if self._running:
                with self._lock:
                    self._state.status = "closed"
                    self._state.last_error = f"事件通道断开：{exc}"
        finally:
            with self._lock:
                if self._state.status not in ("connected",):
                    if self._state.status != "closed":
                        self._state.status = "idle"

    def _handle_event(self, message: Dict[str, Any]) -> None:
        if message.get("type") != "event":
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
            else:
                code = message.get("statusCode")
                reason = message.get("reason") or ""
                detail = f"连接关闭（statusCode={code}）{reason}".strip()
                if code == 408 or "timed out" in reason.lower():
                    detail += ("；本机到 web.whatsapp.com 的 WebSocket 握手超时，"
                               "通常是网络/DNS 问题，排查方法见 docs/TROUBLESHOOTING.md")
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
                sock.close()
            except OSError:
                pass


_session: Optional[WhatsAppSession] = None
_session_lock = threading.Lock()


def get_session() -> WhatsAppSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = WhatsAppSession()
        return _session
