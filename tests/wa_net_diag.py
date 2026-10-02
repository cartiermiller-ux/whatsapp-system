# -*- coding: utf-8 -*-
"""1) 反复解析 web.whatsapp.com 看是否被污染  2) 测试本机代理 10808/10809 是否可用"""
import socket, struct, time

HOST = "web.whatsapp.com"

print("=== 连续 10 次解析 " + HOST + " ===")
seen = {}
for i in range(10):
    try:
        ips = sorted({info[4][0] for info in socket.getaddrinfo(HOST, 443, proto=socket.IPPROTO_TCP)})
    except Exception as exc:
        ips = ["ERR:" + str(exc)]
    key = ",".join(ips)
    seen[key] = seen.get(key, 0) + 1
    print(f"  #{i+1:<2} {key}")
print("  统计:", seen)

print("\n=== 对每个出现过的 IP 做 TCP 443 连接 (4s) ===")
all_ips = sorted({ip for key in seen for ip in key.split(",") if not ip.startswith("ERR")})
for ip in all_ips:
    t0 = time.time()
    try:
        socket.create_connection((ip, 443), 4).close()
        print(f"  {ip:<18} OK    {time.time()-t0:4.2f}s")
    except Exception as exc:
        print(f"  {ip:<18} FAIL  {time.time()-t0:4.2f}s {type(exc).__name__}")


def test_socks5(port):
    try:
        s = socket.create_connection(("127.0.0.1", port), 3)
        s.settimeout(6)
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            s.close(); return "握手失败(非 SOCKS5?)"
        host_b = HOST.encode()
        req = b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + struct.pack(">H", 443)
        s.sendall(req)
        resp = s.recv(10)
        s.close()
        if len(resp) >= 2 and resp[1] == 0:
            return "OK 隧道建立成功"
        return f"代理拒绝 rep={resp[1] if len(resp) > 1 else '?'}"
    except Exception as exc:
        return f"不可用 {type(exc).__name__}: {exc}"


def test_http_connect(port):
    try:
        s = socket.create_connection(("127.0.0.1", port), 3)
        s.settimeout(6)
        s.sendall(f"CONNECT {HOST}:443 HTTP/1.1\r\nHost: {HOST}:443\r\n\r\n".encode())
        head = s.recv(200).decode("latin-1", "replace").split("\r\n")[0]
        s.close()
        return f"{head}"
    except Exception as exc:
        return f"不可用 {type(exc).__name__}: {exc}"


print("\n=== 本机代理端口 ===")
print("  10808 SOCKS5 ->", test_socks5(10808))
print("  10809 HTTP   ->", test_http_connect(10809))
print("  10808 HTTP   ->", test_http_connect(10808))
