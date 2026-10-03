# -*- coding: utf-8 -*-
"""代理稳定性体检：跑 N 次，统计成功率与耗时。

群发场景下「能不能连上」比「连得多快」更重要 ——
一次掉线就可能让整批任务中断，所以成功率是核心指标。

    python tools/check_proxy_stability.py
    python tools/check_proxy_stability.py --proxy socks5://127.0.0.1:10808 --rounds 20
    python tools/check_proxy_stability.py --targets web.whatsapp.com,www.google.com
"""
from __future__ import annotations

import argparse
import os
import socket
import ssl
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

DEFAULT_TARGETS = ["web.whatsapp.com", "www.google.com"]


def default_proxy() -> str:
    env = os.environ.get("WA_PROXY_URL", "").strip()
    if env:
        return env
    env_file = PROJECT_DIR / ".env"
    try:
        for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("WA_PROXY_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def grade(rate: float) -> str:
    if rate >= 0.95:
        return "优秀 —— 可以放心跑群发"
    if rate >= 0.8:
        return "还行 —— 偶有掉线，群发时留意日志"
    if rate >= 0.5:
        return "偏差 —— 大概一半会失败，建议换节点"
    return "很差 —— 基本不能用，换节点"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="代理稳定性体检")
    ap.add_argument("--proxy", default=default_proxy(), help="代理地址，默认取 WA_PROXY_URL 或 .env")
    ap.add_argument("--rounds", type=int, default=10, help="每个目标测几次（默认 10）")
    ap.add_argument("--timeout", type=float, default=20.0, help="单次超时秒数（默认 20）")
    ap.add_argument("--targets", default=",".join(DEFAULT_TARGETS), help="目标域名，逗号分隔")
    args = ap.parse_args(argv)

    if not args.proxy:
        print("没有代理地址。用 --proxy 指定，或先在 .env 里写 WA_PROXY_URL")
        return 2

    from providers.proxy_provider import parse_proxy_line, _socks5_connect

    proxy = parse_proxy_line(args.proxy)
    if proxy is None:
        print(f"代理地址无法解析：{args.proxy}")
        return 2

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    print("=" * 60)
    print(" 代理稳定性体检")
    print("=" * 60)
    print(f" 代理   : {proxy.display()}")
    print(f" 轮次   : 每目标 {args.rounds} 次，单次超时 {args.timeout:.0f}s")
    print()

    overall_ok = 0
    overall_total = 0
    for host in targets:
        print(f"--- {host} ---")
        ok = 0
        costs = []
        for i in range(args.rounds):
            t0 = time.time()
            try:
                sock = socket.create_connection((proxy.host, proxy.port), 10)
                sock.settimeout(args.timeout)
                if (proxy.protocol or "http").startswith("socks"):
                    _socks5_connect(sock, (host, 443), proxy)
                else:
                    from providers.proxy_provider import _http_connect
                    _http_connect(sock, (host, 443), proxy)
                ctx = ssl.create_default_context()
                tls = ctx.wrap_socket(sock, server_hostname=host)
                tls.close()
                ok += 1
                cost = time.time() - t0
                costs.append(cost)
                print(f"  #{i+1:<2} OK    {cost:6.2f}s")
            except Exception as exc:
                print(f"  #{i+1:<2} 失败  {time.time()-t0:6.2f}s  {type(exc).__name__}")
            time.sleep(0.5)

        rate = ok / args.rounds
        avg = sum(costs) / len(costs) if costs else 0.0
        print(f"  成功 {ok}/{args.rounds}  ({rate:.0%})   成功时平均 {avg:.2f}s")
        print()
        overall_ok += ok
        overall_total += args.rounds

    total_rate = overall_ok / overall_total if overall_total else 0.0
    print("=" * 60)
    print(f" 总成功率：{overall_ok}/{overall_total}  ({total_rate:.0%})")
    print(f" 评价：{grade(total_rate)}")
    print("=" * 60)
    if total_rate < 0.8:
        print()
        print(" 免费 Cloudflare 节点普遍是这个水平：能用，但会随机超时。")
        print(" 群发任务对稳定性要求高，建议换付费节点或机场订阅。")
    return 0 if total_rate >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
