# -*- coding: utf-8 -*-
"""账号采购（P2）：对接"账号星球"这类成品号供应商。

说明：账号星球的开放 API 目前**没有公开文档**，所以这里不臆造接口，
而是提供一个可配置的通用 HTTP 适配器 + 模拟实现：

    ACCOUNT_PROVIDER = mock（默认） | http

拿到供应商接口文档后，用环境变量把路径和字段名填上即可，不用改代码：

    ACCOUNT_API_BASE       例如 https://api.example.com
    ACCOUNT_API_TOKEN      鉴权 token
    ACCOUNT_API_AUTH_HEADER / ACCOUNT_API_AUTH_PREFIX
    ACCOUNT_API_PRODUCTS_PATH   商品列表路径，默认 /products
    ACCOUNT_API_ORDER_PATH      下单路径，默认 /orders
    ACCOUNT_API_QUERY_PATH      查单路径，默认 /orders/{order_no}
    ACCOUNT_API_ITEMS_FIELD     列表字段名，默认 data

如果供应商的协议差异较大，照 AccountProvider 再写一个类即可，
业务侧只依赖 list_products / create_order / query_order。
"""
from __future__ import annotations

import random
import string
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .base import HttpClient, ProviderError, ProviderStatus, as_list, env, mask_secret


@dataclass
class AccountProduct:
    product_id: str
    name: str
    price: float = 0.0
    currency: str = "USDT"
    country: str = ""
    stock: int = 0
    description: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


@dataclass
class PurchaseResult:
    order_no: str
    status: str = "pending"          # pending / paid / delivered / failed / cancelled
    quantity: int = 1
    amount: float = 0.0
    currency: str = "USDT"
    accounts: List[str] = field(default_factory=list)   # 交付的账号
    message: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


class AccountProvider:
    kind = "account"
    name = "base"
    mock = False

    def is_configured(self) -> bool:
        return False

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind=self.kind, name=self.name,
                              configured=self.is_configured(), mock=self.mock)

    def list_products(self) -> List[AccountProduct]:
        raise NotImplementedError

    def create_order(self, product_id: str, quantity: int = 1, **kwargs) -> PurchaseResult:
        raise NotImplementedError

    def query_order(self, order_no: str) -> PurchaseResult:
        raise NotImplementedError


class MockAccountProvider(AccountProvider):
    """模拟供应商：给出几个商品和会"自动交付"的订单，便于把模块跑通。"""

    name = "mock"
    mock = True

    def __init__(self, *, deliver_after: float = 0.0):
        self.deliver_after = deliver_after
        self._orders: Dict[str, PurchaseResult] = {}
        self._created: Dict[str, float] = {}

    def is_configured(self) -> bool:
        return True

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind=self.kind, name=self.name, configured=True, mock=True,
                              detail="模拟账号供应商（未配置真实接口时的默认实现）")

    def list_products(self) -> List[AccountProduct]:
        return [
            AccountProduct(product_id="wa-new-id", name="WhatsApp 新号（印尼）", price=1.2,
                           country="ID", stock=120, description="刚注册、未养号"),
            AccountProduct(product_id="wa-aged-id", name="WhatsApp 老号（印尼，30天+）", price=4.5,
                           country="ID", stock=35, description="已过新手期，适合群发"),
            AccountProduct(product_id="wa-aged-br", name="WhatsApp 老号（巴西，30天+）", price=5.0,
                           country="BR", stock=18, description="巴西本地号段"),
        ]

    def create_order(self, product_id: str, quantity: int = 1, **kwargs) -> PurchaseResult:
        products = {p.product_id: p for p in self.list_products()}
        product = products.get(product_id)
        if product is None:
            raise ProviderError(f"商品不存在：{product_id}", provider=self.name)
        quantity = max(1, int(quantity))
        if product.stock < quantity:
            raise ProviderError(f"库存不足（剩 {product.stock}）", provider=self.name)
        order_no = "MP" + "".join(random.choices(string.digits, k=10))
        result = PurchaseResult(order_no=order_no, status="pending", quantity=quantity,
                                amount=round(product.price * quantity, 4),
                                currency=product.currency, message="已下单，等待供应商交付")
        self._orders[order_no] = result
        self._created[order_no] = time.monotonic()
        return result

    def query_order(self, order_no: str) -> PurchaseResult:
        result = self._orders.get(order_no)
        if result is None:
            raise ProviderError(f"订单不存在：{order_no}", provider=self.name)
        if result.status == "pending" and \
                time.monotonic() - self._created.get(order_no, 0) >= self.deliver_after:
            result.status = "delivered"
            result.message = "已交付"
            result.accounts = [f"62812{random.randint(1000000, 9999999)}"
                               for _ in range(result.quantity)]
        return result


class HttpAccountProvider(AccountProvider):
    """通用 HTTP 供应商适配器：路径与字段名全部来自环境变量。"""

    name = "http"

    def __init__(self, base_url: str = "", token: str = "", **options: Any):
        self.base_url = base_url or env("ACCOUNT_API_BASE")
        self.token = token or env("ACCOUNT_API_TOKEN")
        self.auth_header = options.get("auth_header") or env("ACCOUNT_API_AUTH_HEADER", "Authorization")
        self.auth_prefix = options.get("auth_prefix")
        if self.auth_prefix is None:
            self.auth_prefix = env("ACCOUNT_API_AUTH_PREFIX", "Bearer ")
        self.products_path = options.get("products_path") or env("ACCOUNT_API_PRODUCTS_PATH", "/products")
        self.order_path = options.get("order_path") or env("ACCOUNT_API_ORDER_PATH", "/orders")
        self.query_path = options.get("query_path") or env("ACCOUNT_API_QUERY_PATH", "/orders/{order_no}")
        self.items_field = options.get("items_field") or env("ACCOUNT_API_ITEMS_FIELD", "data")
        self.http = HttpClient(self.base_url, timeout=float(env("ACCOUNT_API_TIMEOUT", "20")),
                               provider=self.name)

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {}
        if self.token:
            headers[self.auth_header] = f"{self.auth_prefix}{self.token}"
        return headers

    def list_products(self) -> List[AccountProduct]:
        payload = self.http.get(self.products_path, headers=self._headers())
        items = as_list(payload)
        if not items and isinstance(payload, dict):
            items = as_list(payload.get(self.items_field))
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            result.append(AccountProduct(
                product_id=str(item.get("id") or item.get("product_id") or item.get("sku") or ""),
                name=str(item.get("name") or item.get("title") or ""),
                price=_to_float(item.get("price") or item.get("amount")),
                currency=str(item.get("currency") or "USDT"),
                country=str(item.get("country") or ""),
                stock=int(_to_float(item.get("stock") or item.get("quantity") or 0)),
                description=str(item.get("description") or ""),
                raw=item,
            ))
        return [p for p in result if p.product_id]

    def create_order(self, product_id: str, quantity: int = 1, **kwargs) -> PurchaseResult:
        body = {"product_id": product_id, "quantity": max(1, int(quantity))}
        body.update({k: v for k, v in kwargs.items() if v is not None})
        payload = self.http.post(self.order_path, body=body, headers=self._headers())
        return _to_result(payload, quantity=quantity)

    def query_order(self, order_no: str) -> PurchaseResult:
        path = self.query_path.format(order_no=order_no, order_id=order_no)
        payload = self.http.get(path, headers=self._headers())
        return _to_result(payload)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            kind=self.kind, name=self.name, configured=self.is_configured(),
            detail="" if self.is_configured() else "未设置 ACCOUNT_API_BASE（当前使用 mock 供应商）",
            extra={"base_url": self.base_url, "token": mask_secret(self.token),
                   "products_path": self.products_path, "order_path": self.order_path},
        )


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_result(payload: Any, *, quantity: int = 1) -> PurchaseResult:
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise ProviderError("供应商返回了非预期格式", payload=payload)
    if data.get("success") is False:
        raise ProviderError(str(data.get("message") or "下单失败"), payload=payload)
    accounts = data.get("accounts") or data.get("items") or []
    if isinstance(accounts, list):
        accounts = [a if isinstance(a, str) else str(a.get("phone") or a.get("account") or a)
                    for a in accounts]
    else:
        accounts = []
    return PurchaseResult(
        order_no=str(data.get("order_no") or data.get("order_id") or data.get("id") or ""),
        status=str(data.get("status") or "pending"),
        quantity=int(_to_float(data.get("quantity") or quantity)) or quantity,
        amount=_to_float(data.get("amount") or data.get("total")),
        currency=str(data.get("currency") or "USDT"),
        accounts=accounts,
        message=str(data.get("message") or ""),
        raw=data,
    )


def build_account_provider(name: str = "") -> AccountProvider:
    choice = (name or env("ACCOUNT_PROVIDER", "mock")).strip().lower()
    if choice in ("http", "api", "xingqiu", "accountplanet"):
        provider = HttpAccountProvider()
        return provider if provider.is_configured() else MockAccountProvider()
    return MockAccountProvider()


_default: Optional[AccountProvider] = None


def get_account_provider(refresh: bool = False) -> AccountProvider:
    global _default
    if _default is None or refresh:
        _default = build_account_provider()
    return _default


def set_account_provider(provider: Optional[AccountProvider]) -> None:
    global _default
    _default = provider
