# -*- coding: utf-8 -*-
"""第三方对接自测：代理池 / 接码 / 发消息通道 / 账号采购。

全部走 mock 实现，不联网、不需要任何密钥；另有本地假代理服务验证真实连通性探测。
"""
import json
import os
import socket
import sys
import threading
import time

DB_FILE = os.path.join("tests", ".tmp", "integrations_test.db")
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
os.environ["WHATSAPP_DATABASE_URL"] = "sqlite:///./" + DB_FILE
os.environ["MESSAGE_PROVIDER"] = "mock"
sys.path.insert(0, os.getcwd())

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from providers import (MockSmsProvider, MockProxyProvider, MockAccountProvider,  # noqa: E402
                       ProviderError, ProxyInfo, extract_code, parse_proxy_line,
                       set_proxy_provider, set_sms_provider, set_account_provider,
                       test_proxy)
from providers import sms_provider as sms_mod  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, extra=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  | {extra}"))


def section(title):
    print("\n===== " + title + " =====")


# ---------------------------------------------------------------- 纯函数
section("0 解析函数")
check("host:port:user:pass 解析",
      parse_proxy_line("15.32.0.111:6000:yzrxnxD9:6Gh9Hm1Q").url()
      == "http://yzrxnxD9:6Gh9Hm1Q@15.32.0.111:6000")
check("scheme://user:pass@host:port 解析",
      parse_proxy_line("socks5://u:p@1.2.3.4:1080").protocol == "socks5")
check("注释与空行被忽略",
      parse_proxy_line("# 注释") is None and parse_proxy_line("") is None)
check("WhatsApp 的 123-456 提取为 123456", extract_code("Your code is 123-456") == "123456")
check("普通验证码提取", extract_code("code: 98765") == "98765")
check("没有数字时返回空", extract_code("no code here") == "")

# ---------------------------------------------------------------- 真实代理探测
section("1 代理连通性探测（本地假 CONNECT 代理）")


class FakeConnectProxy(threading.Thread):
    """最小可用的 HTTP CONNECT 代理，用来验证 test_proxy 真的会做完整握手。"""

    def __init__(self, require_auth=False):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.host, self.port = self.sock.getsockname()
        self.sock.listen(4)
        self.require_auth = require_auth
        self.seen = []
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        with conn:
            try:
                data = conn.recv(1024).decode("latin-1", "replace")
            except OSError:
                return
            self.seen.append(data)
            if self.require_auth and "Proxy-Authorization" not in data:
                conn.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
            elif data.startswith("CONNECT"):
                conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


proxy_server = FakeConnectProxy()
proxy_server.start()
ok, detail = test_proxy(ProxyInfo(host=proxy_server.host, port=proxy_server.port, protocol="http"),
                        target=("example.com", 443), timeout=5)
check("可用代理探测成功", ok is True, detail)
check("确实发出了 CONNECT 握手", any(s.startswith("CONNECT example.com:443") for s in proxy_server.seen),
      proxy_server.seen[:1])

auth_server = FakeConnectProxy(require_auth=True)
auth_server.start()
ok, detail = test_proxy(ProxyInfo(host=auth_server.host, port=auth_server.port, protocol="http",
                                  username="u", password="p"),
                        target=("example.com", 443), timeout=5)
check("带认证的代理会带上 Proxy-Authorization", ok is True, detail)
ok, detail = test_proxy(ProxyInfo(host=auth_server.host, port=auth_server.port, protocol="http"),
                        target=("example.com", 443), timeout=5)
check("未带认证时被代理拒绝", ok is False and "407" in detail, detail)

ok, detail = test_proxy(ProxyInfo(host="127.0.0.1", port=59998, protocol="http"), timeout=3)
check("端口没人监听时探测失败", ok is False and "连不上" in detail, detail)
auth_server.stop()
proxy_server.stop()

# ---------------------------------------------------------------- 接口
set_sms_provider(MockSmsProvider(code_delay=0))
set_proxy_provider(MockProxyProvider(count=4))
set_account_provider(MockAccountProvider(deliver_after=0))
client = TestClient(main.app)
token = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "admin123"}).json()["data"]["token"]
H = {"Authorization": f"Bearer {token}"}


def api(method, path, **kw):
    return client.request(method, "/api/v1" + path, headers=H, **kw)


section("2 供应商状态")
r = api("GET", "/providers/status")
data = r.json()["data"]
kinds = {i["kind"]: i for i in data["items"]}
check("返回四类供应商", set(kinds) == {"sms", "proxy", "message", "account"}, list(kinds))
check("未配密钥时都是 mock", all(i["mock"] for i in data["items"] if i["kind"] != "message"),
      [(i["kind"], i["mock"]) for i in data["items"]])
check("发出当前通道配置", data["config"]["message_provider"] == "mock", data["config"])
check("代理项带池子统计", "pool" in kinds["proxy"], kinds["proxy"])

section("3 代理池")
r = api("POST", "/proxies/sync", json={"limit": 4})
check("从供应商同步代理", r.json()["data"]["added"] == 4, r.json())
r = api("POST", "/proxies/sync", json={"limit": 4})
check("重复同步不会重复入库", r.json()["data"]["added"] == 0, r.json())
r = api("POST", "/proxies/import", json={"text": "1.2.3.4:8080:u1:p1\n# 注释\n5.6.7.8:1080:u2:p2",
                                         "country": "ID"})
check("手工导入代理", r.json()["data"]["added"] == 2, r.json())
r = api("GET", "/proxies?size=50")
rows = r.json()["data"]["list"]
check("代理列表返回 6 条", len(rows) == 6, len(rows))
check("代理地址含认证信息", any("@" in x["address"] for x in rows), rows[0])
check("默认都是空闲", all(x["status"] == "free" for x in rows))

db = main.SessionLocal()
number = main.NumberPool(phone_number="8613800000009", source_type="virtual", number_segment="861380")
db.add(number)
db.commit()
db.refresh(number)
allocated = main.allocate_proxy(db, number, country="ID")
db.refresh(number)
check("分配代理成功后写回 number_pool.proxy_ip",
      allocated is not None and number.proxy_ip == allocated.address, number.proxy_ip)
check("被分配的代理标记为 in_use 并绑定号码",
      allocated.status == "in_use" and allocated.bound_number_id == number.id,
      (allocated.status, allocated.bound_number_id))
check("分配计数 +1", allocated.used_count == 1, allocated.used_count)
released = main.release_proxy(db, number.id)
db.refresh(allocated)
check("释放后回到空闲", released == 1 and allocated.status == "free" and allocated.bound_number_id is None,
      (released, allocated.status))

r = api("POST", f"/proxies/{allocated.id}/test")
body = r.json()["data"]
check("探测接口有返回", "ok" in body, body)
check("探测结果会累计失败次数", body["proxy"]["fail_count"] >= 1 or body["proxy"]["ok_count"] >= 1,
      body["proxy"])


class DummyProxy:
    def list_proxies(self, *, limit=50, country=""):
        return [ProxyInfo(host="9.9.9.9", port=1, protocol="http", username="a", password="b")]

    name = "dummy"
    mock = False


set_proxy_provider(DummyProxy())
api("POST", "/proxies/sync", json={"limit": 1})
failed_row = db.query(main.ProxyPool).filter_by(host="9.9.9.9").first()
for _ in range(3):
    api("POST", f"/proxies/{failed_row.id}/test")
db.refresh(failed_row)
check("连续失败 3 次后自动停用", failed_row.status == "disabled" and failed_row.fail_count >= 3,
      (failed_row.status, failed_row.fail_count))
db.close()

section("4 接码平台")
r = api("POST", "/sms/orders", json={"service": "wa", "country": "ID"})
order = r.json()["data"]
check("取号成功", r.status_code == 200 and order["phone"], r.text[:200])
check("号码已写入号码池并回填 number_id", order["number_id"] is not None, order)
check("订单状态 waiting（mock 首次查询才出码）", order["status"] in ("waiting", "completed"), order["status"])
r = api("POST", f"/sms/orders/{order['id']}/poll")
polled = r.json()["data"]
check("查询后拿到验证码", polled["code"] == "123456", polled)
check("状态变为 completed", polled["status"] == "completed", polled)
check("短信正文被保留", "WhatsApp" in polled["text"], polled["text"])

r = api("POST", "/sms/orders", json={"service": "wa", "country": "GB"})
second = r.json()["data"]
r = api("POST", f"/sms/orders/{second['id']}/wait", json={"timeout": 10, "interval": 1})
waited = r.json()["data"]
check("等待接口返回验证码", waited["ok"] is True and waited["code"] == "123456", waited)

r = api("POST", "/sms/orders", json={"service": "wa"})
third = r.json()["data"]
r = api("POST", f"/sms/orders/{third['id']}/cancel")
check("取消接码订单", r.json()["data"]["status"] == "cancelled", r.json())
r = api("POST", f"/sms/orders/{third['id']}/cancel")
check("重复取消被拒绝", r.status_code == 400, r.text[:120])
r = api("GET", "/sms/orders?size=10")
check("接码订单列表", r.json()["data"]["total"] == 3, r.json()["data"]["total"])
r = api("POST", "/sms/orders/999999/poll")
check("订单不存在返回 404", r.status_code == 404, r.status_code)


class FailingSms(MockSmsProvider):
    name = "failing"

    def request_number(self, service="wa", country="ID"):
        raise ProviderError("余额不足", provider="failing")


set_sms_provider(FailingSms())
r = api("POST", "/sms/orders", json={"service": "wa"})
check("供应商报错时返回 502 并带上原因",
      r.status_code == 502 and "余额不足" in r.json()["message"], r.text[:160])
set_sms_provider(MockSmsProvider(code_delay=0))

section("5 账号采购")
r = api("GET", "/purchase/products")
products = r.json()["data"]["list"]
check("拿到商品列表", len(products) == 3 and products[0]["product_id"], products[:1])
r = api("POST", "/purchase/orders", json={"product_id": "wa-aged-id", "quantity": 2,
                                          "remark": "补号"})
created = r.json()["data"]
check("创建采购订单", r.status_code == 200 and created["order_no"], r.text[:200])
check("金额按单价 × 数量计算", created["amount"] == 9.0, created)
check("初始状态 pending", created["status"] == "pending", created)
r = api("POST", f"/purchase/orders/{created['id']}/sync")
synced = r.json()["data"]
check("同步后变为已交付", synced["status"] == "delivered", synced)
check("交付返回 2 个账号", len(synced["accounts"]) == 2, synced["accounts"])
r = api("GET", "/purchase/orders?size=10")
check("采购订单列表", r.json()["data"]["total"] == 1, r.json()["data"])
r = api("POST", "/purchase/orders", json={"product_id": "not-exist"})
check("商品不存在返回 502", r.status_code == 502, r.text[:120])
r = api("POST", "/purchase/orders", json={})
check("缺少 product_id 返回 400", r.status_code == 400, r.text[:120])
r = api("DELETE", f"/purchase/orders/{created['id']}")
check("删除采购订单", r.status_code == 200, r.text[:120])
r = api("GET", "/purchase/orders")
check("删除后列表为空", r.json()["data"]["total"] == 0, r.json()["data"])

section("6 注册时自动分配代理")
db = main.SessionLocal()
main.ProxyPool.query.delete() if False else None
for row in db.query(main.ProxyPool).all():
    db.delete(row)
db.commit()
db.add(main.ProxyPool(host="7.7.7.7", port=8080, username="u", password="p",
                      protocol="http", provider="manual", status="free"))
fresh = main.NumberPool(phone_number="8613800000010", source_type="virtual", region="ID")
db.add(fresh)
db.commit()
db.refresh(fresh)
proxy = main.allocate_proxy(db, fresh, country="ID")
db.refresh(fresh)
check("注册流程能拿到代理", proxy is not None, proxy)
check("代理地址写进 proxy_ip", fresh.proxy_ip == "http://u:p@7.7.7.7:8080", fresh.proxy_ip)
db.close()

section("7 发消息通道")
check("MESSAGE_PROVIDER=mock 时始终就绪", main.message_provider_ready()[0] is True)
check("mock 通道发送直接成功", main.send_message("8613800000001@s.whatsapp.net", "hi")[0] is True)
main.MESSAGE_PROVIDER = "wsapi"
main._message_provider = None
ready, reason = main.message_provider_ready()
check("wsapi 未配置 URL 时判定未就绪", ready is False and "WSAPI_URL" in reason, reason)
main.MESSAGE_PROVIDER = "mock"
main._message_provider = None

print("\n" + "=" * 60)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
for name in FAILED:
    print("  - " + name)
sys.exit(1 if FAILED else 0)
