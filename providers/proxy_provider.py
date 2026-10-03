# -*- coding: utf-8 -*-
"""代理 IP 对接：拉取可用代理、校验连通性。

支持三种实现，由环境变量 PROXY_PROVIDER 选择，没配密钥时自动退回 mock：

    PROXY_PROVIDER = mock（默认） | byteful | static

已按官方文档核对的接口（Byteful / Ping Proxies，2026-10 核对）：

    文档：https://documentation.byteful.com
    基础地址：https://api.byteful.com/1.0/
    认证：请求头 X-API-Public-Key + X-API-Private-Key（两个都要）
    账号：GET /public/customer/retrieve
    代理：GET /public/user/proxy/search          支持 proxy_id / service_id 等筛选
          GET /public/user/proxy/retrieve/{id}
    代理对象里 http_formatted / socks5_formatted 形如：
          "15.32.0.111:6000:yzrxnxD9:6Gh9Hm1Q"   即 host:port:username:password

static 实现用于"我自己有一批代理"的场景，直接把列表放在
PROXY_LIST 环境变量或 proxies.txt 里，每行一个：
    host:port:user:pass        或        socks5://user:pass@host:port
"""
from __future__ import annotations

import os
import socket
import struct
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from .base import HttpClient, ProviderError, ProviderStatus, env, env_int, mask_secret

DEFAULT_FALLBACK_FILE = env("PROXY_LIST_FILE", "proxies.txt")


@dataclass
class ProxyInfo:
    host: str
    port: int
    username: str = ""
    password: str = ""
    protocol: str = "http"          # http / socks5
    country: str = ""
    asn: str = ""
    provider: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def auth(self) -> str:
        return f"{self.username}:{self.password}" if self.username else ""

    def url(self, protocol: str = "") -> str:
        scheme = protocol or self.protocol
        if self.username:
            return f"{scheme}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{scheme}://{self.host}:{self.port}"

    def display(self) -> str:
        """日志用：把密码打码。"""
        if self.username:
            return f"{self.protocol}://{self.username}:{mask_secret(self.password, 2)}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        data["url"] = self.url()
        return data


def parse_proxy_line(line: str, protocol: str = "http") -> Optional[ProxyInfo]:
    """解析一行代理配置。支持三种常见写法。"""
    text = (line or "").strip()
    if not text or text.startswith("#"):
        return None
    scheme = protocol
    if "://" in text:
        scheme, _, rest = text.partition("://")
        scheme = scheme.lower()
    else:
        rest = text
    auth = ""
    if "@" in rest:
        auth, _, rest = rest.rpartition("@")
    elif rest.count(":") == 3:                  # host:port:user:pass
        host, port, user, pwd = rest.split(":")
        return ProxyInfo(host=host, port=int(port), username=user, password=pwd, protocol=scheme)
    if ":" not in rest:
        return None
    host, _, port_text = rest.rpartition(":")
    try:
        port = int(port_text)
    except ValueError:
        return None
    username, password = "", ""
    if auth:
        username, _, password = auth.partition(":")
    return ProxyInfo(host=host, port=port, username=username, password=password, protocol=scheme)


def test_proxy(proxy: ProxyInfo, target: Tuple[str, int] = ("web.whatsapp.com", 443),
               timeout: float = 8.0) -> Tuple[bool, str]:
    """通过代理建立一条到目标的隧道，验证代理是否真的可用。

    只看端口能不能连上是不够的——很多代理端口开着但转发不通，所以这里走完整握手。
    """
    started = time.time()
    try:
        sock = socket.create_connection((proxy.host, proxy.port), timeout)
    except OSError as exc:
        return False, f"代理端口连不上：{exc}"
    try:
        sock.settimeout(timeout)
        if proxy.protocol.startswith("socks"):
            _socks5_connect(sock, target, proxy)
        else:
            _http_connect(sock, target, proxy)
        return True, f"{time.time() - started:.2f}s"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _http_connect(sock: socket.socket, target: Tuple[str, int], proxy: ProxyInfo) -> None:
    host, port = target
    headers = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
    if proxy.username:
        import base64
        token = base64.b64encode(f"{proxy.username}:{proxy.password}".encode()).decode()
        headers.append(f"Proxy-Authorization: Basic {token}")
    sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode())
    line = sock.recv(256).decode("latin-1", "replace").split("\r\n")[0]
    if " 200" not in line:
        raise ConnectionError(f"代理拒绝 CONNECT：{line}")


def _socks5_connect(sock: socket.socket, target: Tuple[str, int], proxy: ProxyInfo) -> None:
    host, port = target
    if proxy.username:
        sock.sendall(b"\x05\x02\x00\x02")
    else:
        sock.sendall(b"\x05\x01\x00")
    resp = sock.recv(2)
    if len(resp) < 2 or resp[0] != 5:
        raise ConnectionError("SOCKS5 握手失败")
    if resp[1] == 2:                                  # 需要用户名密码
        user = proxy.username.encode()
        pwd = proxy.password.encode()
        sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(pwd)]) + pwd)
        if sock.recv(2)[1] != 0:
            raise ConnectionError("SOCKS5 认证失败")
    elif resp[1] != 0:
        raise ConnectionError(f"SOCKS5 不支持该认证方式（{resp[1]}）")
    host_b = host.encode()
    sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + struct.pack(">H", port))
    reply = sock.recv(10)
    if len(reply) < 2 or reply[1] != 0:
        raise ConnectionError(f"SOCKS5 连接被拒绝（rep={reply[1] if len(reply) > 1 else '?'}）")


class ProxyProvider:
    kind = "proxy"
    name = "base"
    mock = False

    def is_configured(self) -> bool:
        return False

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind=self.kind, name=self.name,
                              configured=self.is_configured(), mock=self.mock)

    def list_proxies(self, *, limit: int = 50, country: str = "") -> List[ProxyInfo]:
        raise NotImplementedError

    def balance(self) -> Optional[float]:
        return None


class MockProxyProvider(ProxyProvider):
    """模拟代理：不需要密钥，生成一批看起来合理的代理，便于开发和测试。"""

    name = "mock"
    mock = True

    def __init__(self, count: int = 5, *, country: str = "ID"):
        self.count = max(1, count)
        self.country = country

    def is_configured(self) -> bool:
        return True

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind=self.kind, name=self.name, configured=True, mock=True,
                              detail="模拟代理池（未配置真实代理服务时的默认实现）")

    def list_proxies(self, *, limit: int = 50, country: str = "") -> List[ProxyInfo]:
        total = min(limit, self.count)
        return [
            ProxyInfo(host=f"10.0.{index // 250}.{index % 250 + 1}", port=6000 + index,
                      username=f"user{index}", password=f"pass{index:04d}",
                      protocol="http", country=country or self.country, provider=self.name)
            for index in range(1, total + 1)
        ]


class BytefulProxyProvider(ProxyProvider):
    """Byteful / Ping Proxies 真实对接。"""

    name = "byteful"

    def __init__(self, public_key: str = "", private_key: str = "", *, base_url: str = "",
                 timeout: float = 20.0):
        self.public_key = public_key or env("BYTEFUL_PUBLIC_KEY") or env("PINGPROXIES_PUBLIC_KEY")
        self.private_key = private_key or env("BYTEFUL_PRIVATE_KEY") or env("PINGPROXIES_PRIVATE_KEY")
        self.http = HttpClient(base_url or env("BYTEFUL_BASE_URL", "https://api.byteful.com/1.0"),
                               timeout=timeout, provider=self.name,
                               logger=lambda m: print(f"[proxy.byteful] {m}", flush=True))

    def is_configured(self) -> bool:
        return bool(self.public_key and self.private_key)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            kind=self.kind, name=self.name, configured=self.is_configured(),
            detail="" if self.is_configured() else
                   "未设置 BYTEFUL_PUBLIC_KEY / BYTEFUL_PRIVATE_KEY（当前使用 mock 代理）",
            extra={"public_key": mask_secret(self.public_key),
                   "private_key": mask_secret(self.private_key),
                   "base_url": self.http.base_url},
        )

    def _headers(self) -> Dict[str, str]:
        return {"X-API-Public-Key": self.public_key, "X-API-Private-Key": self.private_key}

    def list_proxies(self, *, limit: int = 50, country: str = "") -> List[ProxyInfo]:
        if not self.is_configured():
            raise ProviderError("缺少 Byteful 公私钥", provider=self.name)
        payload = self.http.get("/public/user/proxy/search", headers=self._headers(),
                                params={"limit": limit} if limit else None)
        items = _extract_items(payload)
        result: List[ProxyInfo] = []
        for item in items[:limit]:
            info = self._to_proxy(item)
            if info:
                result.append(info)
        return result

    def balance(self) -> Optional[float]:
        if not self.is_configured():
            return None
        payload = self.http.get("/public/customer/retrieve", headers=self._headers())
        data = payload.get("data") if isinstance(payload, dict) else None
        for source in (data, payload):
            if isinstance(source, dict):
                for key in ("credit", "balance", "credit_balance"):
                    if isinstance(source.get(key), (int, float)):
                        return float(source[key])
        return None

    def _to_proxy(self, item: Any) -> Optional[ProxyInfo]:
        if isinstance(item, str):
            return parse_proxy_line(item)
        if not isinstance(item, dict):
            return None
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        # http_formatted 是官方文档明确给出的字段：host:port:user:pass
        for key in ("http_formatted", "socks5_formatted"):
            formatted = data.get(key)
            if isinstance(formatted, str) and formatted.count(":") == 3:
                info = parse_proxy_line(formatted,
                                        protocol="socks5" if key.startswith("socks") else "http")
                if info:
                    info.country = str(data.get("country_code") or data.get("country") or "")
                    info.asn = str(data.get("asn_name") or data.get("asn_id") or "")
                    info.provider = self.name
                    info.raw = data
                    return info
        host = data.get("ip") or data.get("host") or data.get("ip_address")
        port = data.get("port")
        if host and port:
            return ProxyInfo(host=str(host), port=int(port),
                             username=str(data.get("username") or ""),
                             password=str(data.get("password") or ""),
                             protocol=str(data.get("protocol") or "http").lower(),
                             country=str(data.get("country_code") or ""),
                             asn=str(data.get("asn_name") or ""), provider=self.name, raw=data)
        return None


class StaticProxyProvider(ProxyProvider):
    """自有代理列表：从 PROXY_LIST 环境变量或文件读取。"""

    name = "static"

    def __init__(self, entries: Optional[List[str]] = None, *, file_path: str = ""):
        self.file_path = file_path or DEFAULT_FALLBACK_FILE
        self._entries = entries if entries is not None else self._load()

    def _load(self) -> List[str]:
        raw = env("PROXY_LIST")
        if raw:
            return [part for part in raw.replace(";", "\n").replace(",", "\n").split("\n") if part.strip()]
        if self.file_path and os.path.isfile(self.file_path):
            with open(self.file_path, "r", encoding="utf-8") as handle:
                return handle.readlines()
        return []

    def is_configured(self) -> bool:
        return any(parse_proxy_line(line) for line in self._entries)

    def status(self) -> ProviderStatus:
        count = len(self.parsed())
        return ProviderStatus(
            kind=self.kind, name=self.name, configured=count > 0,
            detail=f"已加载 {count} 条自有代理" if count else
                   "未配置自有代理（设置 PROXY_LIST 或提供 proxies.txt）",
            extra={"source": "PROXY_LIST" if env("PROXY_LIST") else self.file_path},
        )

    def parsed(self) -> List[ProxyInfo]:
        result = []
        for line in self._entries:
            info = parse_proxy_line(line)
            if info:
                info.provider = self.name
                result.append(info)
        return result

    def list_proxies(self, *, limit: int = 50, country: str = "") -> List[ProxyInfo]:
        return self.parsed()[:limit]


def _extract_items(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items", "proxies", "results", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                inner = _extract_items(value)
                if inner:
                    return inner
    return []


def build_proxy_provider(name: str = "") -> ProxyProvider:
    choice = (name or env("PROXY_PROVIDER", "mock")).strip().lower()
    if choice in ("byteful", "ping", "pingproxies", "ping_proxies"):
        provider = BytefulProxyProvider()
        if provider.is_configured():
            return provider
        static = StaticProxyProvider()
        return static if static.is_configured() else MockProxyProvider()
    if choice in ("static", "file", "list"):
        provider = StaticProxyProvider()
        return provider if provider.is_configured() else MockProxyProvider()
    return MockProxyProvider()


_default: Optional[ProxyProvider] = None


def get_proxy_provider(refresh: bool = False) -> ProxyProvider:
    global _default
    if _default is None or refresh:
        _default = build_proxy_provider()
    return _default


def set_proxy_provider(provider: Optional[ProxyProvider]) -> None:
    global _default
    _default = provider
