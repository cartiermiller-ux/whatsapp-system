# -*- coding: utf-8 -*-
"""连接 WhatsApp，输出登录二维码（终端直接打印 + 落盘 qr.png）。

import os
os.environ["HTTP_PROXY"] = "http://127.0.0.1:10808"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:10808"
os.environ["ALL_PROXY"] = "socks5://127.0.0.1:10808"

from wasock import WhatsAppSocket, QRCode, Browser
# ... 下面保持不变

与 wasock 0.5.2 的 node/server.js 核对过的事实：
  * 有二维码时 Node 端发出的事件是 {"type":"event","event":"login","qr":"<字符串>"}
    —— 事件名就是 login，二维码字符串在顶层 qr 字段，所以 data["qr"] 是正确写法。
  * 连接状态变化时发出 {"type":"event","event":"connection","status":"open|close",...}
  * 二维码约 20 秒轮换一次，login 事件会反复触发；本脚本每次都同时刷新终端二维码和 qr.png。
  * WhatsAppSocket.start() 内部会 input() 阻塞主线程，但回调跑在独立线程里，并不影响出码；
    这里不用 start()，改成显式等待 + 超时提示，避免"卡住但没有任何输出"。

注意：Node 服务固定占用 127.0.0.1:5000，同一时间只能跑一个实例。
      重复启动时第二个进程会连上第一个进程的 Node 服务，导致两个 Baileys 会话互相干扰。
"""
import socket
import sys
import threading
import time

from wasock import Browser, QRCode, WhatsAppSocket

AUTH_NAME = "whatsapp_auth"
QR_FILE = "qr.png"
LOGGER_LEVEL = "warn"      # 想看得更细可改成 "debug"
WA_HOST = "web.whatsapp.com"
QR_WAIT_SECONDS = 120      # 等待出码
SCAN_WAIT_SECONDS = 300    # 等待扫码完成


def preflight(host=WA_HOST, port=443, attempts=3, timeout=5.0):
    """提前探一次链路。

    DNS 被污染时会解析到被黑洞的 IP，TCP 握手会一直停在 SYN_SENT：
    Node 端既不报错也不出码，看起来就是"卡住了"。这里提前把结果打出来。
    """
    print(f"[预检] 连接 {host}:{port} ...", flush=True)
    for attempt in range(1, attempts + 1):
        try:
            ips = sorted({info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)})
        except OSError as exc:
            print(f"  [{attempt}/{attempts}] DNS 解析失败：{exc}", flush=True)
            continue
        for ip in ips:
            start = time.time()
            try:
                with socket.create_connection((ip, port), timeout):
                    print(f"  [{attempt}/{attempts}] {ip}:{port} 可连通（{time.time() - start:.2f}s）", flush=True)
                    return True
            except OSError as exc:
                print(f"  [{attempt}/{attempts}] {ip}:{port} 连不上：{type(exc).__name__}"
                      f"（{time.time() - start:.1f}s）", flush=True)
        time.sleep(1)
    print("  预检未通过，仍会继续启动（wasock 内部会自己重连）。", flush=True)
    return False


qr_ready = threading.Event()
connected = threading.Event()
qr_count = 0


def on_login(data):
    global qr_count
    qr_data = data.get("qr")
    if not qr_data:
        print("[login] 事件里没有 qr 字段：", data, flush=True)
        return
    qr_count += 1
    try:
        QRCode(qr_data, bot.nodeJS, small=True, type="terminal").render()
        QRCode(qr_data, bot.nodeJS, small=True, type="img", imgWidth=500).render(QR_FILE)
    except Exception as exc:                       # 生成失败也要说清楚，不能静默
        print("[login] 生成二维码失败：", repr(exc), flush=True)
    else:
        print(f"[login] 第 {qr_count} 个二维码已输出（终端 + {QR_FILE}）", flush=True)
        if qr_count == 1:
            print("       手机 WhatsApp → 设置 → 已关联的设备 → 关联新设备，扫描上方二维码", flush=True)
    qr_ready.set()


def on_connection(data):
    if data.get("status") == "open":
        print("[connection] 已登录，WhatsApp 连接建立成功", flush=True)
        connected.set()
    else:
        print(f"[connection] 连接关闭：status={data.get('status')} "
              f"statusCode={data.get('statusCode')} reason={data.get('reason')}", flush=True)


preflight()

bot = WhatsAppSocket(authName=AUTH_NAME, loggerLevel=LOGGER_LEVEL, browserInfo=Browser.ubuntu("Chrome"))
bot.on("login", on_login)
bot.on("connection", on_connection)

print("[启动] 正在连接 WhatsApp ...", flush=True)
bot.nodeJS.send({"action": "start"})

if not qr_ready.wait(timeout=QR_WAIT_SECONDS):
    print(f"\n[失败] {QR_WAIT_SECONDS} 秒内没有收到二维码。", flush=True)
    print("        最常见原因：本机到 web.whatsapp.com 的连接被阻断 —— DNS 解析到被污染的 IP 后，", flush=True)
    print("        TCP 握手停在 SYN_SENT，Node 端不报错、也不出码。", flush=True)
    print("        处理：让域名固定走代理（代理客户端开 TUN / 按域名 geosite:whatsapp 分流），", flush=True)
    print("        或给 web.whatsapp.com 配一条 hosts 指向真实 IP，然后重跑本脚本。", flush=True)
    bot.end()
    sys.exit(1)

if connected.wait(timeout=SCAN_WAIT_SECONDS):
    print("[完成] 登录成功，进程保持运行中，按 Ctrl+C 退出。", flush=True)
else:
    print(f"[提示] {SCAN_WAIT_SECONDS} 秒内没有完成扫码，二维码仍在轮换，可继续扫描。", flush=True)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[退出] 正在关闭 ...", flush=True)
finally:
    bot.end()
