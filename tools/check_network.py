# -*- coding: utf-8 -*-
"""WhatsApp 网络连通性体检 —— 一条命令判断「到底能不能连上 WhatsApp」。

用法（在项目根目录执行）：
    python tools/check_network.py
    python tools/check_network.py --proxy socks5://127.0.0.1:10808
    python tools/check_network.py --proxy http://127.0.0.1:7890
    python tools/check_network.py --proxy 1.2.3.4:8080:user:pass
    python tools/check_network.py --scan

它会依次检查：
    1. web.whatsapp.com 的 DNS 是否被污染（连续解析 8 次看是否稳定）
    2. 直连 443 能不能通
    3. 如果给了代理：代理隧道能不能建起来
    4. 走代理真正做完 TLS 握手 + 发 WebSocket Upgrade，看有没有 HTTP 101
       —— 这一步过了，扫码/发消息就一定能用

只用标准库 + 项目自带的 providers.proxy_provider。
"""
from __future__ import annotations

import argparse
import base64
import os
import socket
import ssl
import struct
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

HOST = "web.whatsapp.com"
PORT = 443
WS_PATH = "/ws/chat"

OK = "[OK]"
BAD = "[!!]"
WARN = "[??]"


def line(text=""):
    print(text, flush=True)


def resolve_host(rounds=8):
    seen = {}
    for _ in range(rounds):
        try:
            ips = sorted({info[4][0] for info in socket.getaddrinfo(HOST, PORT, proto=socket.IPPROTO_TCP)})
        except Exception as exc:
            ips = ["ERR:" + type(exc).__name__]
        key = ",".join(ips)
        seen[key] = seen.get(key, 0) + 1
    return seen


def tcp_probe(ip, port=PORT, timeout=4.0):
    started = time.time()
    try:
        socket.create_connection((ip, port), timeout).close()
        return True, time.time() - started
    except Exception:
        return False, time.time() - started


def scan_local_ports(ports):
    found = []
    for port in ports:
        try:
            sock = socket.create_connection(("127.0.0.1", port), 0.25)
        except Exception:
            continue
        found.append(port)
        sock.close()
    return found


def open_tunnel(proxy, timeout=8.0):
    """建立到 target 的隧道，返回一个可继续做 TLS 的 socket。"""
    from providers.proxy_provider import _http_connect, _socks5_connect

    target = (HOST, PORT)
    sock = socket.create_connection((proxy.host, proxy.port), timeout)
    sock.settimeout(timeout)
    if (proxy.protocol or "http").startswith("socks"):
        _socks5_connect(sock, target, proxy)
    else:
        _http_connect(sock, target, proxy)
    return sock


def ws_upgrade_through(sock, timeout=12.0):
    """在已建立的隧道上做 TLS + WebSocket Upgrade，返回服务端第一行响应。"""
    ctx = ssl.create_default_context()
    tls = ctx.wrap_socket(sock, server_hostname=HOST)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {WS_PATH} HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Origin: https://{HOST}\r\n"
        "\r\n"
    )
    tls.settimeout(timeout)
    tls.sendall(request.encode())
    data = tls.recv(4096)
    tls.close()
    first = data.decode("latin-1", "replace").split("\r\n")[0].strip()
    return first, data


def direct_ws_upgrade(timeout=10.0):
    """不走代理，直接对解析出的 IP 做 TLS + Upgrade。"""
    sock = socket.create_connection((HOST, PORT), timeout)
    return ws_upgrade_through(sock, timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description="WhatsApp 连通性体检")
    parser.add_argument("--proxy", default=os.environ.get("WA_PROXY_URL", ""),
                        help="代理地址，支持 http://host:port / socks5://user:pass@host:port / host:port:user:pass")
    parser.add_argument("--scan", action="store_true", help="顺带扫描本机常用代理端口")
    parser.add_argument("--skip-direct", action="store_true", help="跳过直连测试")
    args = parser.parse_args(argv)

    line("=" * 64)
    line("WhatsApp 连通性体检")
    line("=" * 64)

    # ---------- 1. DNS ----------
    line("\n[1/4] 解析 " + HOST)
    seen = resolve_host()
    for key, count in seen.items():
        line(f"      {count} 次 -> {key}")
    poisoned = False
    clean_ips = []
    for key in seen:
        for ip in key.split(","):
            if ip.startswith("ERR"):
                continue
            clean_ips.append(ip)
    if len(seen) > 1:
        poisoned = True
        line(f"      {BAD} 解析结果不稳定，典型的 DNS 污染特征")
    else:
        line(f"      {OK} 解析稳定")
    known_bad = ("64.13.192.74", "199.59.149.230", "31.13.64.51", "8.7.198.45")
    hit = [ip for ip in clean_ips if ip in known_bad]
    if hit:
        poisoned = True
        line(f"      {BAD} 命中已知被污染 IP：{', '.join(hit)}")

    # ---------- 2. 直连 ----------
    if not args.skip_direct:
        line("\n[2/4] 直连 443（不走代理）")
        any_ok = False
        for ip in clean_ips[:6]:
            ok, cost = tcp_probe(ip)
            line(f"      {'OK  ' if ok else 'FAIL'} {ip:<18} {cost:5.2f}s")
            any_ok = any_ok or ok
        if any_ok:
            line(f"      {OK} 至少有一个 IP 能建立 TCP 连接")
        else:
            line(f"      {BAD} 所有 IP 都不通 —— 直连方案不可行，必须走代理")
        if any_ok:
            try:
                first, _ = direct_ws_upgrade()
                line(f"      WebSocket 握手响应: {first or '(空)'}")
            except Exception as exc:
                line(f"      WebSocket 握手失败: {type(exc).__name__}: {exc}")
    else:
        line("\n[2/4] 直连测试已跳过")

    # ---------- 3. 代理隧道 ----------
    proxy = None
    raw_proxy = (args.proxy or "").strip()
    if not raw_proxy:
        line("\n[3/4] 代理隧道")
        line(f"      {WARN} 未提供 --proxy，也没有 WA_PROXY_URL 环境变量")
        line("      用法: python tools/check_network.py --proxy socks5://127.0.0.1:10808")
    else:
        from providers.proxy_provider import parse_proxy_line

        proxy = parse_proxy_line(raw_proxy)
        line("\n[3/4] 代理隧道")
        if proxy is None:
            line(f"      {BAD} 代理地址无法解析: {raw_proxy}")
        else:
            line(f"      目标代理 {proxy.display()}")
            try:
                sock = open_tunnel(proxy)
            except Exception as exc:
                line(f"      {BAD} 隧道建立失败: {type(exc).__name__}: {exc}")
                line("      常见原因：代理客户端没启动 / 端口写错 / 账号密码不对 / 代理本身连不上 WhatsApp")
                sock = None
            if sock is not None:
                line(f"      {OK} 隧道建立成功（代理可以访问 " + HOST + "）")

                # ---------- 4. TLS + Upgrade ----------
                line("\n[4/4] 走代理完成 TLS + WebSocket 握手")
                try:
                    first, _ = ws_upgrade_through(sock)
                except Exception as exc:
                    try:
                        sock.close()
                    except Exception:
                        pass
                    line(f"      {BAD} 握手失败: {type(exc).__name__}: {exc}")
                    first = ""
                if first:
                    if "101" in first:
                        line(f"      {OK} {first}")
                        line("\n结论：网络完全没问题，可以扫码登录、可以发消息。")
                        line(f"      启动后端前设置：$env:WA_PROXY_URL=\"{raw_proxy}\"")
                        return 0
                    line(f"      {WARN} 收到响应：{first}")
                    line("      能收到 HTTP 响应就说明链路是通的（101 才是标准的升级成功）")

    # ---------- 扫描 ----------
    if args.scan:
        line("\n[附] 本机常用代理端口扫描")
        ports = [1080, 1081, 10808, 10809, 7890, 7891, 7897, 7898, 8080, 8118, 8889, 2080, 20171, 33210]
        found = scan_local_ports(ports)
        if found:
            line(f"      发现监听：{', '.join(str(p) for p in found)}")
            line("      逐个试：--proxy socks5://127.0.0.1:<端口> 或 --proxy http://127.0.0.1:<端口>")
        else:
            line("      没有任何常用代理端口在监听 —— 代理客户端没启动")

    # ---------- 结论 ----------
    line("\n" + "=" * 64)
    if proxy is None:
        line("结论：还没提供可用的代理。")
    line("下一步：")
    if poisoned:
        line("  · 本机 DNS 已被污染，直连 WhatsApp 不可能成功")
    line("  · 启动你的代理客户端（Clash / v2rayN / Nekoray 等），确认能打开网页版 WhatsApp")
    line("  · 用 python tools/check_network.py --proxy <你的代理地址> --scan 复测")
    line("  · 看到 [OK] HTTP/1.1 101 之后，再启动后端并设置 WA_PROXY_URL")
    line("=" * 64)
    return 1


if __name__ == "__main__":
    sys.exit(main())
