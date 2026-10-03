"""验证 deploy/wasock/server.js 的握手与「start 不再挂起」。

背景：原始 wasock server.js 在 start 分支里 await fetchLatestBaileysVersion()，
该方法请求 raw.githubusercontent.com。国内网络下该域名 TCP 被黑洞：连接既不成功
也不报错，Promise 永不 resolve —— 前端表现就是「二维码一直转圈」。

本测试用真实 node 进程验证：
    1. setup 能收到回包（说明依赖解析成功、NODE_PATH 正确）
    2. start 在几秒内一定回包（版本号有硬超时 + 内置回退）
    3. WA_VERSION_TIMEOUT_MS=0 时完全不联网
    4. 配了代理也不会卡住启动

只用标准库。需要本机有 node，且能找到 wasock 的 node_modules。
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SERVER_JS = PROJECT_DIR / "deploy" / "wasock" / "server.js"

PASSED = 0
FAILED = []


def check(label, ok, detail=""):
    global PASSED
    if ok:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILED.append(label)
        print(f"  [FAIL] {label} {detail}")


def find_node():
    return shutil.which("node")


def find_node_modules():
    """找一个装了 @whiskeysockets/baileys 的 node_modules。"""
    candidates = []
    env_path = os.environ.get("WASOCK_NODE_MODULES", "")
    if env_path:
        candidates.append(Path(env_path))
    try:
        import wasock  # noqa
        pkg = Path(wasock.__file__).resolve().parent
        candidates.append(pkg / "node" / "node_modules")
    except Exception:
        pass
    candidates.append(PROJECT_DIR / "node_modules")
    for c in candidates:
        if (c / "@whiskeysockets" / "baileys").is_dir():
            return c
    return None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


class Server:
    def __init__(self, extra_env=None, timeout_ms="0"):
        self.port = free_port()
        self.dir = Path(tempfile.mkdtemp(prefix="wasock_wire_"))
        env = dict(os.environ)
        env["WA_PORT"] = str(self.port)
        env["WA_VERSION_TIMEOUT_MS"] = timeout_ms
        env["NODE_PATH"] = str(find_node_modules())
        env.update(extra_env or {})
        self.proc = subprocess.Popen(
            [find_node(), str(SERVER_JS)],
            cwd=str(self.dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.sock = None

    def connect(self, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("node 进程已退出: " + (self.output() or "")[:400])
            s = socket.socket()
            s.settimeout(timeout)
            if s.connect_ex(("127.0.0.1", self.port)) == 0:
                self.sock = s
                return s
            s.close()
            time.sleep(0.15)
        raise RuntimeError("端口未就绪: " + (self.output() or "")[:400])

    def request(self, payload, timeout):
        self.sock.sendall((json.dumps(payload) + "\n").encode())
        self.sock.settimeout(timeout)
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None, time.time() - (deadline - timeout)
            if not chunk:
                return None, 0.0
            buf += chunk
            for line in buf.decode("utf-8", "replace").split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "response":
                    return obj, time.time() - (deadline - timeout)
        return None, timeout

    def output(self):
        if self.proc.stdout is None:
            return ""
        try:
            self.proc.stdout.flush()
        except Exception:
            pass
        return ""

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=8)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


def test_handshake_and_start_returns():
    print("\n[1] setup 握手 + start 必须回包（内置版本，不联网）")
    node = find_node()
    nm = find_node_modules()
    if not node or not nm:
        check("node / node_modules 可用", False, f"node={node} node_modules={nm}")
        return
    srv = Server(timeout_ms="0")
    try:
        srv.connect()
        resp, dt = srv.request({"action": "setup", "loggerLevel": "silent",
                                "authName": str(srv.dir / "auth"),
                                "syncFullHistory": False,
                                "browserInfo": ["ubuntu", "Chrome", "14.4.1"]}, timeout=15)
        check("setup 有回包", resp is not None, f"resp={resp}")
        check("setup success=true", bool(resp and resp.get("success")), f"resp={resp}")
        check("setup 回包 < 5s", resp is not None and dt < 5, f"{dt:.2f}s")

        resp2, dt2 = srv.request({"action": "start"}, timeout=25)
        check("start 有回包（原始版本会永久挂起）", resp2 is not None, "25s 内无响应")
        check("start success=true", bool(resp2 and resp2.get("success")), f"resp={resp2}")
        check("start 回包 < 10s", resp2 is not None and dt2 < 10, f"{dt2:.2f}s")
        print(f"      start 耗时 {dt2:.2f}s")
    finally:
        srv.close()


def test_online_fetch_times_out_but_returns():
    print("\n[2] 允许联网取版本时，也必须靠超时兜底回包")
    if not find_node() or not find_node_modules():
        return
    srv = Server(timeout_ms="3000")
    try:
        srv.connect()
        srv.request({"action": "setup", "loggerLevel": "silent",
                     "authName": str(srv.dir / "auth"),
                     "syncFullHistory": False,
                     "browserInfo": ["ubuntu", "Chrome", "14.4.1"]}, timeout=15)
        resp, dt = srv.request({"action": "start"}, timeout=25)
        check("联网失败后 start 仍回包", resp is not None, "25s 内无响应")
        check("回包耗时不超超时上限太多", resp is not None and dt < 12, f"{dt:.2f}s")
        print(f"      start 耗时 {dt:.2f}s（超时上限 3s）")
    finally:
        srv.close()


def test_proxy_env_does_not_block_startup():
    print("\n[3] 配了不可用代理时，服务仍能启动并回包")
    if not find_node() or not find_node_modules():
        return
    srv = Server(extra_env={"WA_PROXY_URL": "http://127.0.0.1:19998"}, timeout_ms="0")
    try:
        srv.connect()
        resp, _ = srv.request({"action": "setup", "loggerLevel": "silent",
                               "authName": str(srv.dir / "auth"),
                               "syncFullHistory": False,
                               "browserInfo": ["ubuntu", "Chrome", "14.4.1"]}, timeout=15)
        check("坏代理下 setup 仍成功", bool(resp and resp.get("success")), f"resp={resp}")
        resp2, dt2 = srv.request({"action": "start"}, timeout=25)
        check("坏代理下 start 仍回包", resp2 is not None, "25s 内无响应")
        check("坏代理下进程未崩溃", srv.proc.poll() is None, f"exit={srv.proc.poll()}")
    finally:
        srv.close()


def main():
    print("=" * 60)
    print("wasock server.js 握手 / 版本号超时回归测试")
    print("=" * 60)
    test_handshake_and_start_returns()
    test_online_fetch_times_out_but_returns()
    test_proxy_env_does_not_block_startup()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print("  失败:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
