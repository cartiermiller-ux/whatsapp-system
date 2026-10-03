# -*- coding: utf-8 -*-
"""第三方资源对接的公共基础设施。

设计目标：
  1. 每个资源类型（接码平台 / 代理 IP / 发消息 / 账号采购）都定义一个 Provider 接口，
     具体厂商做成薄适配器，换厂商只改配置或加一个类，不动业务代码。
  2. 没配密钥时自动退化为 Mock 实现，整套系统仍然可以跑通、可以测。
  3. 只用标准库（urllib），后端不引入 requests 之类的额外依赖。
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


class ProviderError(Exception):
    """对接第三方时的统一异常。"""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 payload: Any = None, provider: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload
        self.provider = provider

    def __str__(self) -> str:
        prefix = f"[{self.provider}] " if self.provider else ""
        suffix = f" (HTTP {self.status})" if self.status else ""
        return f"{prefix}{self.message}{suffix}"


@dataclass
class ProviderStatus:
    """给 /api/v1/providers/status 用的状态快照。"""
    kind: str                      # sms / proxy / message / account
    name: str                      # 实现名，如 virtualsms
    configured: bool               # 是否具备真实调用条件
    mock: bool = False             # 是否为模拟实现
    detail: str = ""               # 说明（缺哪个环境变量等）
    balance: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def mask_secret(value: str, keep: int = 4) -> str:
    """密钥只露头尾，避免日志/接口泄露。"""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(float(env(name, str(default))))
    except ValueError:
        return default


class HttpClient:
    """极简 HTTP 客户端：超时 + 有限重试 + JSON 解析。

    只重试"值得重试"的情况：网络异常、超时、5xx、429。
    4xx（参数错、余额不足、密钥无效）直接抛出，重试没有意义。
    """

    def __init__(self, base_url: str = "", *, timeout: float = 15.0, retries: int = 2,
                 backoff: float = 1.0, provider: str = "", logger=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff = backoff
        self.provider = provider
        self.logger = logger or (lambda msg: None)
        self._ssl = ssl.create_default_context()

    def build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        if clean:
            url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(clean)}"
        return url

    def request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None,
                timeout: Optional[float] = None, raw: bool = False) -> Any:
        url = self.build_url(path, params)
        data = None
        send_headers = {"Accept": "application/json", "User-Agent": "whatsapp-system/1.0"}
        send_headers.update(headers or {})
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            send_headers["Content-Type"] = "application/json"

        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=data, headers=send_headers, method=method.upper())
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout,
                                            context=self._ssl) as resp:
                    text = resp.read().decode("utf-8", "replace")
                if raw:
                    return text
                return json.loads(text) if text.strip() else {}
            except urllib.error.HTTPError as exc:
                text = ""
                try:
                    text = exc.read().decode("utf-8", "replace")
                except Exception:
                    pass
                payload: Any = text
                try:
                    payload = json.loads(text) if text.strip() else None
                except ValueError:
                    pass
                message = _extract_message(payload) or f"HTTP {exc.code}"
                last_error = ProviderError(message, status=exc.code, payload=payload,
                                           provider=self.provider)
                if exc.code < 500 and exc.code != 429:
                    raise last_error
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = ProviderError(f"网络异常：{exc}", provider=self.provider)
            if attempt < self.retries:
                time.sleep(self.backoff * (attempt + 1))
        raise last_error or ProviderError("请求失败", provider=self.provider)

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> Any:
        return self.request("POST", path, **kw)


def _extract_message(payload: Any) -> str:
    """从各家五花八门的错误体里尽量抠出一句人话。"""
    if isinstance(payload, str):
        return payload[:200]
    if isinstance(payload, dict):
        for key in ("message", "error", "detail", "msg", "reason", "description"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
            if isinstance(value, dict):
                inner = _extract_message(value)
                if inner:
                    return inner
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            return _extract_message(errors[0])
    return ""


def normalize_phone(raw: str, default_country_code: str = "") -> str:
    """把各种写法的号码整理成纯数字（WhatsApp JID 需要）。"""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if not digits:
        return ""
    if default_country_code and len(digits) <= 11 and not digits.startswith(default_country_code):
        digits = f"{default_country_code}{digits}"
    return digits


def as_list(value: Any) -> List[Any]:
    """第三方返回的 data/items/result 字段名不统一，统一取列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("data", "items", "result", "results", "list", "proxies", "orders"):
            inner = value.get(key)
            if isinstance(inner, list):
                return inner
            if isinstance(inner, dict):
                found = as_list(inner)
                if found:
                    return found
    return []
