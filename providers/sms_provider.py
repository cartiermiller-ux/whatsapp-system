# -*- coding: utf-8 -*-
"""接码平台对接：request_number() / wait_for_code()。

支持三种实现，由环境变量 SMS_PROVIDER 选择，**没配密钥时自动退回 mock**：

    SMS_PROVIDER = mock（默认） | virtualsms | smsactivate

已按官方文档核对的接口（2026-10 核对）：

VirtualSMS（https://virtualsms.io/docs）
    认证：请求头 x-api-key: vsms_xxx
    下单：POST /api/v1/customer/purchase        {"service": "wa", "country": "ID"}
    查码：GET  /api/v1/customer/order/{orderId}
    取消：POST /api/v1/customer/cancel/{orderId}
    余额：GET  /api/v1/customer/balance
    返回：{success, order_id, phone_number, status, price, expires_at,
           messages: [{sender, content, received_at}]}
          status ∈ waiting / completed / cancelled / expired

sms-activate 兼容协议（VirtualSMS 也提供该兼容层，很多平台同款）
    取号：GET {base}?action=getNumber&service=wa&country=0&api_key=KEY
          -> ACCESS_NUMBER:<id>:<phone>
    查码：GET {base}?action=getStatus&id=<id>&api_key=KEY
          -> STATUS_WAIT_CODE | STATUS_OK:<code> | STATUS_CANCEL
    取消：GET {base}?action=setStatus&status=8&id=<id>&api_key=KEY
    余额：GET {base}?action=getBalance&api_key=KEY -> ACCESS_BALANCE:<n>

要接入别的平台（例如 SMSTwins），照 SmsProvider 再写一个类即可，
业务侧只调用 request_number() / wait_for_code()，不感知厂商差异。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

from .base import (HttpClient, ProviderError, ProviderStatus, env, env_float,
                   mask_secret, normalize_phone)

# 常见服务代码：service 用厂商的短码，WhatsApp 一般为 wa / whatsapp
DEFAULT_SERVICE = env("SMS_SERVICE", "wa")
DEFAULT_COUNTRY = env("SMS_COUNTRY", "ID")

CODE_PATTERNS = (
    re.compile(r"\b(\d{3})[-\s](\d{3})\b"),   # WhatsApp 常见格式 123-456
    re.compile(r"\b(\d{4,8})\b"),               # 普通 4-8 位验证码
)


def extract_code(text: str) -> str:
    """从短信正文里抠出验证码；WhatsApp 的 123-456 会被拼成 123456。"""
    content = text or ""
    for pattern in CODE_PATTERNS:
        match = pattern.search(content)
        if match:
            groups = [g for g in match.groups() if g]
            return "".join(groups)
    return ""


@dataclass
class SmsOrder:
    order_id: str
    phone: str
    service: str = ""
    country: str = ""
    status: str = "waiting"
    price: Optional[float] = None
    expires_at: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def phone_digits(self) -> str:
        return normalize_phone(self.phone)

    @property
    def code(self) -> str:
        for message in self.messages:
            found = extract_code(str(message.get("content", "")))
            if found:
                return found
        return ""

    @property
    def text(self) -> str:
        return "\n".join(str(m.get("content", "")) for m in self.messages if m.get("content"))

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phone_digits"] = self.phone_digits
        data["code"] = self.code
        data["text"] = self.text
        data.pop("raw", None)          # 原始响应太大，单独用 raw 字段按需取
        return data


@dataclass
class SmsCode:
    ok: bool
    code: str = ""
    text: str = ""
    order: Optional[SmsOrder] = None
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "code": self.code, "text": self.text,
            "detail": self.detail,
            "order": self.order.to_dict() if self.order else None,
        }


class SmsProvider:
    """接码平台接口。业务代码只依赖这两个方法。"""

    kind = "sms"
    name = "base"
    mock = False

    def is_configured(self) -> bool:
        return False

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind=self.kind, name=self.name, configured=self.is_configured(),
                              mock=self.mock, detail="")

    # ---------- 需要子类实现 ----------
    def request_number(self, service: str = DEFAULT_SERVICE,
                       country: str = DEFAULT_COUNTRY) -> SmsOrder:
        raise NotImplementedError

    def poll(self, order_id: str) -> SmsOrder:
        raise NotImplementedError

    def cancel(self, order_id: str) -> bool:
        return False

    def balance(self) -> Optional[float]:
        return None

    # ---------- 通用流程 ----------
    def wait_for_code(self, order_id: str, *, timeout: float = 180.0, interval: float = 5.0,
                      should_stop: Optional[Callable[[], bool]] = None) -> SmsCode:
        """轮询直到收到验证码、订单结束或超时。

        默认 3 秒一次太重，这里 interval 默认 5 秒（VirtualSMS 官方建议 3-5 秒）。
        """
        deadline = time.monotonic() + max(1.0, timeout)
        last: Optional[SmsOrder] = None
        while time.monotonic() < deadline:
            if should_stop and should_stop():
                return SmsCode(ok=False, detail="已取消等待", order=last)
            order = self.poll(order_id)
            last = order
            if order.code:
                return SmsCode(ok=True, code=order.code, text=order.text, order=order)
            if order.status not in ("waiting", "pending", "active", ""):
                return SmsCode(ok=False, detail=f"订单已结束（{order.status}）", order=order)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
        return SmsCode(ok=False, detail=f"等待验证码超时（{int(timeout)} 秒）", order=last)


class MockSmsProvider(SmsProvider):
    """模拟接码：不需要任何密钥，用于开发和测试。

    默认立即返回号码；验证码在 code_delay 秒后出现，用来模拟真实等待。
    """

    name = "mock"
    mock = True

    def __init__(self, *, code_delay: float = 0.0, code: str = "123-456",
                 prefix: str = "62812345"):
        self.code_delay = code_delay
        self.fixed_code = code
        self.prefix = prefix
        self._orders: Dict[str, SmsOrder] = {}
        self._created: Dict[str, float] = {}
        self._seq = 0

    def is_configured(self) -> bool:
        return True

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind=self.kind, name=self.name, configured=True, mock=True,
                              detail="模拟接码平台（未配置真实密钥时的默认实现）")

    def request_number(self, service: str = DEFAULT_SERVICE,
                       country: str = DEFAULT_COUNTRY) -> SmsOrder:
        self._seq += 1
        order_id = f"mock-{int(time.time())}-{self._seq}"
        phone = f"+{self.prefix}{self._seq:04d}"
        order = SmsOrder(order_id=order_id, phone=phone, service=service, country=country,
                         status="waiting", price=0.0)
        self._orders[order_id] = order
        self._created[order_id] = time.monotonic()
        return order

    def poll(self, order_id: str) -> SmsOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise ProviderError(f"订单不存在：{order_id}", provider=self.name)
        if order.status == "waiting" and self.code_delay >= 0:
            if time.monotonic() - self._created.get(order_id, 0) >= self.code_delay:
                order.status = "completed"
                order.messages = [{"sender": "WhatsApp", "content":
                                   f"Your WhatsApp code is {self.fixed_code}", "received_at": None}]
        return order

    def cancel(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order.status == "waiting":
            order.status = "cancelled"
            return True
        return False


class VirtualSmsProvider(SmsProvider):
    """VirtualSMS 真实对接（https://virtualsms.io/docs）。"""

    name = "virtualsms"

    def __init__(self, api_key: str = "", *, base_url: str = "", timeout: float = 15.0):
        self.api_key = api_key or env("VIRTUALSMS_API_KEY")
        self.http = HttpClient(base_url or env("VIRTUALSMS_BASE_URL", "https://virtualsms.io"),
                               timeout=timeout, provider=self.name,
                               logger=lambda m: print(f"[sms.virtualsms] {m}", flush=True))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            kind=self.kind, name=self.name, configured=self.is_configured(),
            detail="" if self.is_configured() else "未设置 VIRTUALSMS_API_KEY（当前使用 mock 接码）",
            extra={"api_key": mask_secret(self.api_key), "base_url": self.http.base_url},
        )

    def _headers(self) -> Dict[str, str]:
        return {"x-api-key": self.api_key}

    def request_number(self, service: str = DEFAULT_SERVICE,
                       country: str = DEFAULT_COUNTRY) -> SmsOrder:
        if not self.is_configured():
            raise ProviderError("缺少 VIRTUALSMS_API_KEY", provider=self.name)
        payload = self.http.post("/api/v1/customer/purchase", headers=self._headers(),
                                 body={"service": service, "country": country})
        return self._to_order(payload, service=service, country=country)

    def poll(self, order_id: str) -> SmsOrder:
        if not self.is_configured():
            raise ProviderError("缺少 VIRTUALSMS_API_KEY", provider=self.name)
        payload = self.http.get(f"/api/v1/customer/order/{order_id}", headers=self._headers())
        return self._to_order(payload)

    def cancel(self, order_id: str) -> bool:
        if not self.is_configured():
            raise ProviderError("缺少 VIRTUALSMS_API_KEY", provider=self.name)
        payload = self.http.post(f"/api/v1/customer/cancel/{order_id}", headers=self._headers())
        return bool(payload.get("success", True)) if isinstance(payload, dict) else True

    def balance(self) -> Optional[float]:
        if not self.is_configured():
            return None
        payload = self.http.get("/api/v1/customer/balance", headers=self._headers())
        if isinstance(payload, dict):
            for key in ("balance", "amount", "credit"):
                if isinstance(payload.get(key), (int, float)):
                    return float(payload[key])
        return None

    @staticmethod
    def _to_order(payload: Any, *, service: str = "", country: str = "") -> SmsOrder:
        if not isinstance(payload, dict):
            raise ProviderError("VirtualSMS 返回了非预期格式", payload=payload,
                                provider="virtualsms")
        if payload.get("success") is False:
            raise ProviderError(str(payload.get("message") or "下单失败"), payload=payload,
                                provider="virtualsms")
        return SmsOrder(
            order_id=str(payload.get("order_id") or payload.get("id") or ""),
            phone=str(payload.get("phone_number") or payload.get("phone") or ""),
            service=str(payload.get("service") or service),
            country=str(payload.get("country") or country),
            status=str(payload.get("status") or "waiting"),
            price=payload.get("price") if isinstance(payload.get("price"), (int, float)) else None,
            expires_at=payload.get("expires_at"),
            messages=payload.get("messages") if isinstance(payload.get("messages"), list) else [],
            raw=payload,
        )


class SmsActivateProvider(SmsProvider):
    """sms-activate 兼容协议，适用于同款协议的平台（VirtualSMS 兼容层、SMSTwins 等）。

    响应是纯文本，且出错时 HTTP 仍是 200，所以这里靠前缀判断成败。
    """

    name = "smsactivate"

    def __init__(self, api_key: str = "", *, base_url: str = "", timeout: float = 20.0):
        self.api_key = api_key or env("SMS_ACTIVATE_API_KEY")
        self.http = HttpClient(base_url or env("SMS_ACTIVATE_BASE_URL",
                                               "https://virtualsms.io/stubs/handler_api.php"),
                               timeout=timeout, provider=self.name,
                               logger=lambda m: print(f"[sms.smsactivate] {m}", flush=True))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            kind=self.kind, name=self.name, configured=self.is_configured(),
            detail="" if self.is_configured() else "未设置 SMS_ACTIVATE_API_KEY（当前使用 mock 接码）",
            extra={"api_key": mask_secret(self.api_key), "base_url": self.http.base_url},
        )

    def _call(self, **params) -> str:
        if not self.is_configured():
            raise ProviderError("缺少 SMS_ACTIVATE_API_KEY", provider=self.name)
        params["api_key"] = self.api_key
        return self.http.request("GET", "", params=params, raw=True).strip()

    def request_number(self, service: str = DEFAULT_SERVICE,
                       country: str = DEFAULT_COUNTRY) -> SmsOrder:
        text = self._call(action="getNumber", service=service, country=country)
        if text.startswith("ACCESS_NUMBER"):
            parts = text.split(":")
            if len(parts) >= 3:
                return SmsOrder(order_id=parts[1], phone=f"+{parts[2]}", service=service,
                                country=country, status="waiting")
        raise ProviderError(text or "取号失败", provider=self.name)

    def poll(self, order_id: str) -> SmsOrder:
        text = self._call(action="getStatus", id=order_id)
        if text == "STATUS_WAIT_CODE":
            return SmsOrder(order_id=order_id, phone="", status="waiting")
        if text.startswith("STATUS_OK"):
            code = text.split(":", 1)[1] if ":" in text else ""
            return SmsOrder(order_id=order_id, phone="", status="completed",
                            messages=[{"sender": "SMS", "content": code, "received_at": None}])
        if text in ("STATUS_CANCEL", "NO_ACTIVATION"):
            return SmsOrder(order_id=order_id, phone="", status="cancelled")
        return SmsOrder(order_id=order_id, phone="", status="waiting", raw={"raw": text})

    def cancel(self, order_id: str) -> bool:
        # sms-activate 里 status=8 表示"取消并退款"
        return self._call(action="setStatus", status="8", id=order_id).startswith("ACCESS")

    def balance(self) -> Optional[float]:
        text = self._call(action="getBalance")
        if text.startswith("ACCESS_BALANCE"):
            try:
                return float(text.split(":")[1])
            except (IndexError, ValueError):
                return None
        return None


def build_sms_provider(name: str = "") -> SmsProvider:
    """按名称构造接码实现；密钥缺失时回退到 mock，保证系统始终可用。"""
    choice = (name or env("SMS_PROVIDER", "mock")).strip().lower()
    if choice in ("virtualsms", "virtual_sms", "vsms"):
        provider = VirtualSmsProvider()
        return provider if provider.is_configured() else MockSmsProvider()
    if choice in ("smsactivate", "sms-activate", "smstwins", "daisysms"):
        provider = SmsActivateProvider()
        return provider if provider.is_configured() else MockSmsProvider()
    return MockSmsProvider()


_default: Optional[SmsProvider] = None


def get_sms_provider(refresh: bool = False) -> SmsProvider:
    """进程内单例，供接口层直接使用。"""
    global _default
    if _default is None or refresh:
        _default = build_sms_provider()
    return _default


def set_sms_provider(provider: Optional[SmsProvider]) -> None:
    """测试用：注入指定的实现。"""
    global _default
    _default = provider
