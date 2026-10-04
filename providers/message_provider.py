# -*- coding: utf-8 -*-
"""发消息通道（P1）：把"用哪家 API 发消息"收敛成一层。

业务侧（main.py 的 real_mass_send）只调用 send()，换厂商不需要动发送逻辑：

    MESSAGE_PROVIDER = wasock（默认） | wsapi | mock

- wasock：走本机 wasock 的 Node 服务（127.0.0.1:5000），协议见 wasock/node/server.js。
  main.py 里已有实现（wasock_request / send_via_wasock），本模块只做适配说明。
- wsapi：任何"HTTP POST 一个 JSON 就能发消息"的服务，URL 与字段名都可配置：
      WSAPI_URL          例如 https://api.example.com/v1/message/send
      WSAPI_TOKEN        鉴权 token（默认放 Authorization: Bearer）
      WSAPI_AUTH_HEADER  自定义鉴权头名（默认 Authorization）
      WSAPI_AUTH_PREFIX  自定义前缀（默认 "Bearer "）
      WSAPI_CHAT_FIELD   收件人字段名（默认 chat）
      WSAPI_TEXT_FIELD   正文字段名（默认 message）
      WSAPI_SUCCESS_FIELD 成功标志字段（默认 success）
- mock：不真正发送，直接返回成功，用于本地联调。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from .base import HttpClient, ProviderError, ProviderStatus, env, mask_secret


class MessageProvider:
    kind = "message"
    name = "base"
    mock = False

    def is_configured(self) -> bool:
        return False

    def is_ready(self) -> Tuple[bool, str]:
        """发送前的健康检查：服务在不在、登录态有没有。"""
        return (True, "") if self.is_configured() else (False, "未配置")

    def send(self, chat_jid: str, message: str) -> Tuple[bool, str]:
        raise NotImplementedError

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind=self.kind, name=self.name,
                              configured=self.is_configured(), mock=self.mock)


class MockMessageProvider(MessageProvider):
    """只记录不发送，用于本地联调与测试。"""

    name = "mock"
    mock = True

    def __init__(self) -> None:
        self.sent: list = []

    def is_configured(self) -> bool:
        return True

    def is_ready(self) -> Tuple[bool, str]:
        return True, "模拟通道，始终就绪"

    def send(self, chat_jid: str, message: str) -> Tuple[bool, str]:
        if not chat_jid or not message:
            return False, "缺少 chat 或消息内容"
        self.sent.append({"chat": chat_jid, "msg": message})
        return True, ""

    def status(self) -> ProviderStatus:
        return ProviderStatus(kind=self.kind, name=self.name, configured=True, mock=True,
                              detail=f"模拟发送，已记录 {len(self.sent)} 条")


class WsapiMessageProvider(MessageProvider):
    """通用 HTTP 发消息适配器：URL 与字段名全部可配置，不写死任何厂商。"""

    name = "wsapi"

    def __init__(self, url: str = "", token: str = "", **options: Any):
        self.url = url or env("WSAPI_URL")
        self.token = token or env("WSAPI_TOKEN")
        self.auth_header = options.get("auth_header") or env("WSAPI_AUTH_HEADER", "Authorization")
        self.auth_prefix = options.get("auth_prefix")
        if self.auth_prefix is None:
            self.auth_prefix = env("WSAPI_AUTH_PREFIX", "Bearer ")
        self.chat_field = options.get("chat_field") or env("WSAPI_CHAT_FIELD", "chat")
        self.text_field = options.get("text_field") or env("WSAPI_TEXT_FIELD", "message")
        self.success_field = options.get("success_field") or env("WSAPI_SUCCESS_FIELD", "success")
        self.extra_body: Dict[str, Any] = options.get("extra_body") or {}
        self.http = HttpClient("", timeout=float(env("WSAPI_TIMEOUT", "30")), retries=0, provider=self.name)

    def is_configured(self) -> bool:
        return bool(self.url)

    def is_ready(self) -> Tuple[bool, str]:
        if not self.url:
            return False, "未设置 WSAPI_URL"
        return True, ""

    def send(self, chat_jid: str, message: str) -> Tuple[bool, str]:
        result = self.send_result(chat_jid, message)
        return bool(result["success"]), result.get("message", "")

    def send_result(self, chat_jid: str, message: str) -> Dict[str, Any]:
        if not self.is_configured() or not chat_jid or not message:
            return {"success": False, "message": "未设置消息 API 或消息目标、内容为空"}
        headers = {self.auth_header: f"{self.auth_prefix}{self.token}"} if self.token else {}
        body = dict(self.extra_body)
        body[self.chat_field], body[self.text_field] = chat_jid, message
        try:
            payload = self.http.post(self.url, body=body, headers=headers)
        except ProviderError as exc:
            return {"success": False, "uncertain": exc.status is None or exc.status >= 500,
                    "message": "消息 API 请求失败，请检查通道执行记录"}
        if not isinstance(payload, dict):
            return {"success": False, "uncertain": True, "message": "消息 API 响应格式无法确认"}
        flag = payload.get(self.success_field)
        if flag is None:
            flag = str(payload.get("code", payload.get("status", ""))) in ("0", "200", "ok", "OK")
        else:
            flag = flag is True or str(flag).lower() in ("1", "true", "ok", "success")
        message_id = payload
        for part in env("WSAPI_MESSAGE_ID_FIELD", "message_id").split("."):
            message_id = message_id.get(part) if isinstance(message_id, dict) else None
        return {"success": bool(flag), "message": "" if flag else "消息 API 返回失败",
                "message_id": str(message_id or "")}

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            kind=self.kind, name=self.name, configured=self.is_configured(),
            detail="" if self.is_configured() else "未设置 WSAPI_URL（MESSAGE_PROVIDER=wsapi 时必填）",
            extra={"url": self.url, "token": mask_secret(self.token),
                   "chat_field": self.chat_field, "text_field": self.text_field},
        )


class WasockMessageProvider(MessageProvider):
    """wasock 通道的适配器。

    真实实现（socket 通信、登录态判定）留在 main.py，由调用方注入，
    这样 providers 包不需要反向依赖 main，避免循环导入。
    """

    name = "wasock"

    def __init__(self, send_func, ready_func):
        self._send = send_func
        self._ready = ready_func

    def is_configured(self) -> bool:
        return True

    def is_ready(self) -> Tuple[bool, str]:
        return self._ready()

    def send(self, chat_jid: str, message: str) -> Tuple[bool, str]:
        return self._send(chat_jid, message)

    def status(self) -> ProviderStatus:
        ready, detail = self._ready()
        return ProviderStatus(kind=self.kind, name=self.name, configured=True,
                              detail=detail or "通过本机 wasock Node 服务发送",
                              extra={"ready": ready})


def build_message_provider(name: str = "", *, wasock_send=None,
                           wasock_ready=None) -> MessageProvider:
    """按 MESSAGE_PROVIDER 构造发消息通道。

    wasock 需要调用方把 main.py 里的 send_via_wasock / ready 检查注入进来。
    """
    choice = (name or env("MESSAGE_PROVIDER", "wasock")).strip().lower()
    if choice in ("wsapi", "http", "api"):
        return WsapiMessageProvider()
    if choice in ("mock", "none"):
        return MockMessageProvider()
    if wasock_send and wasock_ready:
        return WasockMessageProvider(wasock_send, wasock_ready)
    return MockMessageProvider()
