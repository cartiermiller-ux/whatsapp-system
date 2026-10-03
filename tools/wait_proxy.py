# -*- coding: utf-8 -*-
"""等待本机出现一个「真的能连上 WhatsApp」的代理，找到就退出。

用途：网断了又不想反复手敲命令时，挂着这个脚本，等你打开代理客户端，
它自动把可用地址试出来并打印出来，直接复制进 WA_PROXY_URL 就能用。

    python tools/wait_proxy.py                # 默认最多等 15 分钟
    python tools/wait_proxy.py --timeout 3600
    python tools/wait_proxy.py --ports 10808,7890

判定标准：不只是端口在监听，而是真的能完成
    隧道 -> TLS 握手 -> WebSocket Upgrade -> HTTP 101
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

DEFAULT_PORTS = [10808, 10809, 7890, 7891, 7897, 1080, 1081, 2080, 20171, 8118, 8889, 1087, 9150]

from tools.check_network import open_tunnel, ws_upgrade_through  # noqa: E402


def port_open(port):
    try:
        sock = socket.create_connection(("127.0.0.1", port), 0.25)
    except Exception:
        return False
    sock.close()
    return True


def try_proxy(url):
    """返回 (是否完全可用, 说明文字)。"""
    from providers.proxy_provider import parse_proxy_line

    proxy = parse_proxy_line(url)
    if proxy is None:
        return False, "地址无法解析"
    try:
        sock = open_tunnel(proxy, timeout=8)
    except Exception as exc:
        return False, f"隧道失败 {type(exc).__name__}"
    try:
        first, _ = ws_upgrade_through(sock, timeout=12)
    except Exception as exc:
        try:
            sock.close()
        except Exception:
            pass
        return False, f"握手失败 {type(exc).__name__}"
    if "101" in first:
        return True, first
    return False, f"响应 {first or '(空)'}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="等待可用代理")
    parser.add_argument("--timeout", type=int, default=900, help="最长等待秒数（默认 900）")
    parser.add_argument("--interval", type=int, default=5, help="扫描间隔秒数")
    parser.add_argument("--ports", default="", help="额外扫描的端口，逗号分隔")
    args = parser.parse_args(argv)

    ports = list(DEFAULT_PORTS)
    for extra in args.ports.split(","):
        extra = extra.strip()
        if extra.isdigit() and int(extra) not in ports:
            ports.append(int(extra))

    env_proxy = (os.environ.get("WA_PROXY_URL") or "").strip()
    deadline = time.time() + args.timeout
    announced = set()
    round_no = 0

    print("=" * 64, flush=True)
    print(f"等待可用代理，最长 {args.timeout} 秒，每 {args.interval} 秒扫一次", flush=True)
    print(f"扫描端口：{', '.join(str(p) for p in ports)}", flush=True)
    if env_proxy:
        print(f"另外会持续验证环境变量里的：{env_proxy}", flush=True)
    print("=" * 64, flush=True)

    while time.time() < deadline:
        round_no += 1

        if env_proxy:
            ok, detail = try_proxy(env_proxy)
            if ok:
                print(f"\n[OK] WA_PROXY_URL 可用：{env_proxy}\n     {detail}", flush=True)
                return 0
            if env_proxy not in announced:
                announced.add(env_proxy)
                print(f"      WA_PROXY_URL={env_proxy} 暂不可用：{detail}", flush=True)

        open_ports = [p for p in ports if port_open(p)]
        for port in open_ports:
            for scheme in ("socks5", "http"):
                url = f"{scheme}://127.0.0.1:{port}"
                ok, detail = try_proxy(url)
                if ok:
                    print(f"\n[OK] 找到可用代理：{url}\n     {detail}", flush=True)
                    print(f"\n启动后端前先执行：", flush=True)
                    print(f'    $env:WA_PROXY_URL = "{url}"', flush=True)
                    return 0
                tag = f"{url}"
                if tag not in announced:
                    announced.add(tag)
                    print(f"      端口 {port} 在监听，但 {scheme} 走不通：{detail}", flush=True)
        if not open_ports and round_no % 6 == 1:
            print(f"      [{time.strftime('%H:%M:%S')}] 还没有任何代理端口在监听…", flush=True)
        elif open_ports and round_no % 6 == 1:
            print(f"      [{time.strftime('%H:%M:%S')}] 监听中：{open_ports}", flush=True)

        time.sleep(args.interval)

    print(f"\n[!!] {args.timeout} 秒内没有等到能连上 WhatsApp 的代理", flush=True)
    print("     请确认代理客户端已启动，并且能打开 https://web.whatsapp.com", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
