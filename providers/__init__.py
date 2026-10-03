# -*- coding: utf-8 -*-
"""第三方资源对接层。

四类资源、统一用法：

    from providers import get_sms_provider, get_proxy_provider, get_account_provider

    sms = get_sms_provider()
    order = sms.request_number(service="wa", country="ID")
    result = sms.wait_for_code(order.order_id, timeout=180)

    proxies = get_proxy_provider().list_proxies(limit=10)

    purchase = get_account_provider()
    products = purchase.list_products()

发消息通道（get_message_provider）由 main.py 构造并注入 wasock 实现，
因为真实实现依赖 main 里的 socket 与配置。

所有实现都遵循同一条规则：**没配密钥就自动退化为 mock**，
所以整套系统在没有第三方账号的情况下依然能跑通、能测试。
"""
from .base import ProviderError, ProviderStatus, HttpClient, mask_secret, normalize_phone
from .sms_provider import (SmsCode, SmsOrder, SmsProvider, MockSmsProvider,
                           VirtualSmsProvider, SmsActivateProvider, extract_code,
                           build_sms_provider, get_sms_provider, set_sms_provider)
from .proxy_provider import (ProxyInfo, ProxyProvider, MockProxyProvider,
                             BytefulProxyProvider, StaticProxyProvider,
                             parse_proxy_line, test_proxy,
                             build_proxy_provider, get_proxy_provider, set_proxy_provider)
from .message_provider import (MessageProvider, MockMessageProvider,
                               WsapiMessageProvider, WasockMessageProvider,
                               build_message_provider)
from .account_provider import (AccountProduct, PurchaseResult, AccountProvider,
                               MockAccountProvider, HttpAccountProvider,
                               build_account_provider, get_account_provider,
                               set_account_provider)

__all__ = [
    "ProviderError", "ProviderStatus", "HttpClient", "mask_secret", "normalize_phone",
    "SmsCode", "SmsOrder", "SmsProvider", "MockSmsProvider", "VirtualSmsProvider",
    "SmsActivateProvider", "extract_code", "build_sms_provider", "get_sms_provider",
    "set_sms_provider",
    "ProxyInfo", "ProxyProvider", "MockProxyProvider", "BytefulProxyProvider",
    "StaticProxyProvider", "parse_proxy_line", "test_proxy", "build_proxy_provider",
    "get_proxy_provider", "set_proxy_provider",
    "MessageProvider", "MockMessageProvider", "WsapiMessageProvider",
    "WasockMessageProvider", "build_message_provider",
    "AccountProduct", "PurchaseResult", "AccountProvider", "MockAccountProvider",
    "HttpAccountProvider", "build_account_provider", "get_account_provider",
    "set_account_provider",
]
