# -*- coding: utf-8 -*-
"""whatsapp_session 自测：用假 Node 服务复刻 server.js 的协议，不连真实 WhatsApp。

覆盖 setup/start 握手、二维码事件转图片、连接状态流转、错误提示、登录态解析。
"""
import base64
import json
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

# 1x1 透明 PNG，用来冒充 Node 端渲染出的二维码文件
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

PASSED, FAILED = [], []


def check(name, cond, extra=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  | {extra}"))


class _ClientGone(Exception):
    """客户端已断开，停止推送事件。"""


class FakeNode(threading.Thread):
    """复刻 wasock/node/server.js 的关键行为。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.host, self.port = self.sock.getsockname()
        self.sock.listen(8)
        self.received = []
        self.mode = "qr"            # qr / connected / close408 / badsetup
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        buffer = b""
        with conn:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    self.received.append(msg)
                    action = msg.get("action")
                    if action == "setup":
                        ok = self.mode != "badsetup"
                        conn.sendall(json.dumps({"type": "response", "success": ok,
                                                 "message": "" if ok else "bad"}).encode() + b"\n")
                    elif action == "start":
                        conn.sendall(b'{"type":"response","success":true,"message":""}\n')
                        threading.Thread(target=self._emit_events, args=(conn,),
                                         daemon=True).start()
                    elif action == "qrcodeGenerate":
                        Path(msg["fileName"]).write_bytes(TINY_PNG)
                        conn.sendall(b'{"type":"response","success":true,"message":""}\n')

    def _emit_events(self, conn):
        """客户端随时可能断开，写失败属正常，吞掉即可。"""
        def emit(payload):
            try:
                conn.sendall(json.dumps(payload).encode() + b"\n")
            except OSError:
                raise _ClientGone

        try:
            time.sleep(0.2)
            if self.mode == "qr":
                for seq in range(1, 3):
                    emit({"type": "event", "event": "login", "qr": f"FAKEQR-{seq}"})
                    time.sleep(0.4)
            if self.mode == "connected":
                emit({"type": "event", "event": "login", "qr": "FAKEQR-9"})
                time.sleep(0.2)
                emit({"type": "event", "event": "connection", "status": "open"})
            if self.mode == "close408":
                emit({"type": "event", "event": "connection", "status": "close",
                      "statusCode": 408,
                      "reason": "WebSocket Error (Opening handshake has timed out)"})
        except _ClientGone:
            pass

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


server = FakeNode()
server.start()
os.environ["WASOCK_HOST"] = "127.0.0.1"
os.environ["WASOCK_PORT"] = str(server.port)
os.environ["WASOCK_AUTH_NAME"] = "tests/.tmp/wa_session_auth"
sys.path.insert(0, os.getcwd())

import whatsapp_session as ws  # noqa: E402

print("===== 1. 基础工具 =====")
check("能找到 server.js", bool(ws.find_server_js()), ws.find_server_js())
check("端口在监听时返回 True", ws.is_node_running() is True)
check("端口没人监听时返回 False",
      ws.is_node_running(port=59998) is False)

print()
print("===== 2. 登录态解析 =====")
AUTH = Path("tests/.tmp/wa_session_auth")
shutil.rmtree(AUTH, ignore_errors=True)
AUTH.mkdir(parents=True)
check("没有 creds.json 时返回空", ws.read_paired_phone(str(AUTH)) == "")
(AUTH / "creds.json").write_text(json.dumps({"me": {"id": "8613800000000:12@s.whatsapp.net"}}),
                                 encoding="utf-8")
check("能从 me.id 解析出号码", ws.read_paired_phone(str(AUTH)) == "8613800000000",
      ws.read_paired_phone(str(AUTH)))
(AUTH / "creds.json").write_text(json.dumps({"registered": False}), encoding="utf-8")
check("只看 registered 会误判，这里返回空是预期的", ws.read_paired_phone(str(AUTH)) == "")
(AUTH / "creds.json").write_text("{ not json", encoding="utf-8")
check("creds.json 损坏时返回空", ws.read_paired_phone(str(AUTH)) == "")

print()
print("===== 2.5 多账号：登录态目录管理 =====")
# 在一个干净的子目录里验证，避免动到真实登录态
import tempfile  # noqa: E402

workdir = Path(tempfile.mkdtemp(prefix="wa_dirs_"))
os.chdir(workdir)
try:
    check("目录都不存在时，下一个可用目录就是默认名", ws.next_auth_name("wa") == "wa")
    (workdir / "wa").mkdir()
    check("默认名被占用后顺延到 _2", ws.next_auth_name("wa") == "wa_2")
    (workdir / "wa_2").mkdir()
    check("继续顺延到 _3", ws.next_auth_name("wa") == "wa_3")
    (workdir / "wa_2" / "creds.json").write_text(
        json.dumps({"me": {"id": "8613900000000:1@s.whatsapp.net"}}), encoding="utf-8")
    dirs = {d["auth_name"]: d for d in ws.list_auth_dirs("wa")}
    check("list_auth_dirs 能列出全部目录", set(dirs) == {"wa", "wa_2"}, list(dirs))
    check("能识别出哪个目录已配对", dirs["wa_2"]["paired"] is True and dirs["wa"]["paired"] is False,
          dirs)
    check("已配对目录能解析出号码", dirs["wa_2"]["paired_phone"] == "8613900000000", dirs["wa_2"])
    check("解绑会删除目录", ws.remove_auth_dir("wa") is True and not (workdir / "wa").exists())
    check("解绑不存在的目录返回 False", ws.remove_auth_dir("not-there") is False)
finally:
    os.chdir(Path(__file__).resolve().parent.parent)
    shutil.rmtree(workdir, ignore_errors=True)

print()
print("===== 3. 会话流程（假 Node 服务）=====")
session = ws.WhatsAppSession()
state = session.start()
check("start 后进入 waiting_qr", state["status"] in ("waiting_qr", "starting"), state["status"])
check("没有拉起多余的 Node 进程（端口已有人监听）", state["node_owned"] is False, state)

qr_image = ""
deadline = time.time() + 15
while time.time() < deadline:
    snap = session.snapshot()
    if snap["qr_image"]:
        qr_image = snap["qr_image"]
        break
    time.sleep(0.3)

check("收到 login 事件并转成 data URL", qr_image.startswith("data:image/png;base64,"),
      qr_image[:40] or session.snapshot())
if qr_image:
    raw = base64.b64decode(qr_image.split(",", 1)[1])
    check("data URL 解出来是合法 PNG", raw[:8] == b"\x89PNG\r\n\x1a\n")
check("二维码序号会累加", session.snapshot()["qr_seq"] >= 1, session.snapshot()["qr_seq"])
check("事件流有记录", any(e["event"] == "login" for e in session.snapshot()["events"]))

session.stop()
check("stop 后回到 idle", session.snapshot()["status"] == "idle", session.snapshot()["status"])
check("stop 后仍记得上次用的登录态目录", session.snapshot()["auth_name"] != "",
      session.snapshot()["auth_name"])

print()
print("===== 3.5 换目录启动（关联新账号的基础）=====")
session_a = ws.WhatsAppSession()
state_a = session_a.start("dir_a")
check("用 dir_a 启动后 auth_name 为 dir_a", state_a["auth_name"] == "dir_a", state_a["auth_name"])
state_b = session_a.start("dir_b")
check("换目录启动后 auth_name 切到 dir_b", state_b["auth_name"] == "dir_b", state_b["auth_name"])
check("换目录不会复用旧连接", session_a.snapshot()["status"] in ("waiting_qr", "starting"),
      session_a.snapshot()["status"])
session_a.stop()

print()
print("===== 4. 连接成功 =====")
server.mode = "connected"
session2 = ws.WhatsAppSession()
session2.start()
deadline = time.time() + 15
while time.time() < deadline:
    if session2.snapshot()["status"] == "connected":
        break
    time.sleep(0.3)
final = session2.snapshot()
check("收到 connection:open 后状态为 connected", final["status"] == "connected", final["status"])
check("connected 时带上时间戳", bool(final["connected_at"]), final["connected_at"])
check("connected 后清掉二维码", final["qr_image"] == "", final["qr_image"][:30])
session2.stop()

print()
print("===== 5. 408 关闭要给可操作提示 =====")
server.mode = "close408"
session3 = ws.WhatsAppSession()
session3.start()
deadline = time.time() + 15
while time.time() < deadline:
    if session3.snapshot()["status"] == "closed":
        break
    time.sleep(0.3)
final = session3.snapshot()
check("状态为 closed", final["status"] == "closed", final["status"])
check("错误信息含 408", "408" in final["last_error"], final["last_error"])
check("错误信息指向排障文档", "TROUBLESHOOTING" in final["last_error"], final["last_error"])
session3.stop()

print()
print("===== 6. setup 被拒绝 =====")
server.mode = "badsetup"
session4 = ws.WhatsAppSession()
state4 = session4.start()
check("setup 失败时状态为 error 且不被抹掉", state4["status"] == "error", state4["status"])
check("错误信息可见", bool(state4["last_error"]), state4["last_error"])

server.stop()
shutil.rmtree(AUTH.parent, ignore_errors=True)
print()
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
for name in FAILED:
    print("  - " + name)
sys.exit(1 if FAILED else 0)
