# -*- coding: utf-8 -*-
"""P2 接口端到端自测：广告消息 / 余额计费 / 个人中心 / 系统设置"""
import json
import sys

import requests

BASE = "http://127.0.0.1:8099"
FAILED = []
PASSED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
        print(f"PASS  {name}")
    else:
        FAILED.append(name)
        print(f"FAIL  {name} | {extra}")


def api(method, path, token=None, **kw):
    headers = kw.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.request(method, BASE + path, headers=headers, timeout=20, **kw)
    try:
        body = resp.json()
    except Exception:
        body = None
    return resp.status_code, body


def section(title):
    print("\n===== " + title + " =====")


# ---------- 0. 未登录访问应被拦下 ----------
section("0 鉴权")
status, body = api("GET", "/api/v1/balance")
check("未携带 token 访问余额返回 401", status == 401 and body.get("code") == 401, f"{status} {body}")
status, body = api("GET", "/api/v1/balance", token="1.badtoken")
check("伪造 token 返回 401", status == 401, f"{status} {body}")

# ---------- 1. 登录 ----------
section("1 登录")
status, body = api("POST", "/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass"})
check("密码错误返回 401", status == 401 and "密码" in (body or {}).get("message", ""), f"{status} {body}")

status, body = api("POST", "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
check("内置管理员登录成功", status == 200 and body.get("code") == 0 and body["data"]["token"], f"{status} {body}")
token = body["data"]["token"]
check("登录返回角色超管", body["data"]["role"] == "super_admin", body)
check("登录返回租户", body["data"]["tenant"] == "default", body)

status, body = api("POST", "/api/v1/auth/login", json={"username": "brandnew", "password": "secret123"})
check("首次登录自动开户", status == 200 and body["data"]["username"] == "brandnew", f"{status} {body}")
newbie_token = body["data"]["token"]

status, body = api("GET", "/api/v1/me", token=newbie_token)
check("自动开户用户角色为 agent_admin", body["data"]["role"] == "agent_admin", body)

status, body = api("GET", "/api/v1/me", token="mock-token-legacyuser")
check("兼容历史 mock-token 登录态", status == 200 and body["data"]["username"] == "legacyuser", f"{status} {body}")

# ---------- 2. 广告文案 CRUD ----------
section("2 广告文案 AdMessage")
status, body = api("POST", "/api/v1/ads/copies", token=token, json={
    "title": "巴西促销-葡语", "content": "Ola {name}, confira {link} agora!",
    "language": "pt", "link_url": "https://example.com/promo", "category": "promo"})
check("新建文案成功", status == 200 and body["code"] == 0, f"{status} {body}")
copy_id = body["data"]["id"]
check("自动提取变量", body["data"]["variables"] == ["name", "link"], body["data"])
check("新建文案默认状态 active", body["data"]["status"] == "active", body)

status, body = api("POST", "/api/v1/ads/copies", token=token, json={"title": "空内容", "content": "   "})
check("空文案被拒绝", status == 400 and "不能为空" in body["message"], f"{status} {body}")

created = []
for lang, title in (("zh", "中文文案A"), ("en", "English copy B"), ("es", "Espanol C")):
    status, body = api("POST", "/api/v1/ads/copies", token=token, json={
        "title": title, "content": "Hello {name} -> {link}", "language": lang})
    check(f"新建 {lang} 文案", status == 200, f"{status} {body}")
    created.append(body["data"]["id"])

status, body = api("GET", "/api/v1/ads/copies?page=1&size=10", token=token)
check("文案分页列表", body["data"]["total"] == 4 and len(body["data"]["list"]) == 4, body)
status, body = api("GET", "/api/v1/ads/copies?language=pt", token=token)
check("按语言过滤", body["data"]["total"] == 1, body)
status, body = api("GET", "/api/v1/ads/copies?keyword=English", token=token)
check("关键词搜索", body["data"]["total"] == 1 and body["data"]["list"][0]["title"] == "English copy B", body)

status, body = api("GET", f"/api/v1/ads/copies/{copy_id}", token=token)
check("文案详情", body["data"]["id"] == copy_id, body)
status, body = api("GET", "/api/v1/ads/copies/999999", token=token)
check("文案不存在返回 404", status == 404, f"{status} {body}")

status, body = api("PUT", f"/api/v1/ads/copies/{copy_id}", token=token,
                   json={"content": "Novo {name} com {link} e {group}", "status": "paused"})
check("更新文案", body["data"]["status"] == "paused", body)
check("更新后重算变量", body["data"]["variables"] == ["name", "link", "group"], body["data"])
status, body = api("PUT", f"/api/v1/ads/copies/{copy_id}", token=token, json={"status": "bogus"})
check("非法状态被拒绝", status == 400, f"{status} {body}")

status, body = api("GET", f"/api/v1/ads/copies/{copy_id}/stats", token=token)
check("单条文案效果统计", body["data"]["id"] == copy_id and "click_rate" in body["data"], body)
status, body = api("GET", "/api/v1/ads/stats", token=token)
check("效果统计汇总", body["data"]["totals"]["copies"] == 4, body)

status, body = api("DELETE", "/api/v1/ads/copies", token=token, json={"ids": created[:2]})
check("批量删除文案", body["data"]["deleted"] == 2, body)
status, body = api("GET", "/api/v1/ads/copies", token=token)
check("删除后剩余 2 条", body["data"]["total"] == 2, body)

# ---------- 3. 超链 ----------
section("3 超链 AdLink")
status, body = api("POST", "/api/v1/ads/links", token=token, json={
    "name": "促销主链接", "original_url": "https://example.com/landing",
    "tracking_params": "utm_source=wa&click_id={click_id}", "ad_message_id": copy_id})
check("创建超链", status == 200 and body["data"]["short_code"], f"{status} {body}")
link_id = body["data"]["id"]
short_code = body["data"]["short_code"]
check("短链使用默认域名", body["data"]["short_url"] == f"https://go.wa-link.com/{short_code}", body["data"])
check("短链拼接追踪参数", "utm_source=wa" in body["data"]["target_url"], body["data"])

status, body = api("POST", "/api/v1/ads/links", token=token,
                   json={"name": "坏链接", "original_url": "ftp://x.com"})
check("非法原始链接被拒绝", status == 400, f"{status} {body}")
status, body = api("POST", "/api/v1/ads/links", token=token, json={
    "name": "关联不存在的文案", "original_url": "https://a.com", "ad_message_id": 999999})
check("关联不存在文案被拒绝", status == 400, f"{status} {body}")

status, body = api("PUT", f"/api/v1/ads/links/{link_id}", token=token,
                   json={"domain": "promo.example.net", "name": "促销主链接2"})
check("更新超链域名", body["data"]["short_url"] == f"https://promo.example.net/{short_code}", body["data"])

status, body = api("GET", "/api/v1/ads/links?keyword=促销", token=token)
check("超链关键词搜索", body["data"]["total"] == 1, body)
check("超链列表带默认域名", body["data"]["default_domain"] == "go.wa-link.com", body)

before = body["data"]["list"][0]["click_count"]
resp = requests.get(f"{BASE}/s/{short_code}", allow_redirects=False, timeout=20)
check("短链跳转 302", resp.status_code == 302, resp.status_code)
check("短链携带追踪参数", "utm_source=wa" in resp.headers.get("location", ""), resp.headers.get("location"))
check("click_id 被替换", "{click_id}" not in resp.headers.get("location", ""), resp.headers.get("location"))
status, body = api("GET", f"/api/v1/ads/links?keyword=促销", token=token)
check("点击量累加", body["data"]["list"][0]["click_count"] == before + 1, body["data"]["list"][0])
resp = requests.get(f"{BASE}/s/notexists", allow_redirects=False, timeout=20)
check("未知短链返回 404", resp.status_code == 404, resp.status_code)

# ---------- 4. 系统设置 ----------
section("4 系统设置 Setting")
status, body = api("GET", "/api/v1/settings", token=token)
for key in ("send_interval_min", "send_interval_max", "new_device_cooldown_hours", "daily_send_limit"):
    check(f"设置包含 {key}", key in body["data"], body)
check("设置默认值正确", body["data"]["send_interval_min"] == 5 and body["data"]["daily_send_limit"] == 50, body)
check("历史 4 个字段类型仍为 int", all(isinstance(body["data"][k], int) for k in
      ("send_interval_min", "send_interval_max", "new_device_cooldown_hours", "daily_send_limit")), body)

status, body = api("GET", "/api/v1/settings/schema", token=token)
check("schema 返回字段定义", status == 200 and len(body["data"]) == 10, f"{status} {body}")
check("schema 带分组信息", {i["category"] for i in body["data"]} == {"send", "billing", "general"}, body)

status, body = api("PUT", "/api/v1/settings", token=token,
                   json={"daily_send_limit": 80, "recharge_address": "TXk9Q2DemoAddress0001", "currency": "USDT"})
check("保存参数成功", status == 200 and body["data"]["daily_send_limit"] == 80, f"{status} {body}")
check("保存后回读一致", body["data"]["recharge_address"] == "TXk9Q2DemoAddress0001", body)

status, body = api("PUT", "/api/v1/settings", token=token, json={"daily_send_limit": 99999})
check("超范围参数被拒绝", status == 400 and "不能大于" in body["message"], f"{status} {body}")
status, body = api("PUT", "/api/v1/settings", token=token, json={"unknown_key": 1})
check("未知参数被拒绝", status == 400 and "未知参数" in body["message"], f"{status} {body}")
status, body = api("PUT", "/api/v1/settings", token=token, json={"send_interval_min": 100})
check("间隔下限大于上限被拒绝", status == 400, f"{status} {body}")
status, body = api("PUT", "/api/v1/settings", token=token, json={"daily_send_limit": "abc"})
check("非数字被拒绝", status == 400, f"{status} {body}")
status, body = api("GET", "/api/v1/settings", token=token)
check("被拒绝的写入没有落库", body["data"]["daily_send_limit"] == 80, body)

# ---------- 5. 余额与充值 ----------
section("5 余额 / 流水 / 充值")
status, body = api("GET", "/api/v1/balance", token=token)
check("初始余额为 0", body["data"]["balance"] == 0.0, body)
check("余额币种来自设置", body["data"]["currency"] == "USDT", body)

status, body = api("POST", "/api/v1/balance/recharge", token=token, json={"amount": 1})
check("低于最低充值被拒绝", status == 400 and "不能低于" in body["message"], f"{status} {body}")

status, body = api("POST", "/api/v1/balance/recharge", token=token, json={"amount": 100})
check("创建充值订单", status == 200 and body["data"]["order_no"].startswith("RC"), f"{status} {body}")
order = body["data"]
check("订单带收款地址", order["address"] == "TXk9Q2DemoAddress0001", order)
check("订单带有效期", bool(order["expire_at"]), order)
check("订单初始状态 pending", order["status"] == "pending", order)

status, body = api("GET", "/api/v1/balance/recharge/orders", token=token)
check("充值订单列表", body["data"]["total"] == 1 and body["data"]["min_amount"] == 10, body)

status, body = api("POST", f"/api/v1/balance/recharge/{order['id']}/confirm", token=token)
check("确认到账", status == 200 and body["data"]["balance"] == 100.0, f"{status} {body}")
check("到账后产生充值流水", body["data"]["transaction"]["type"] == "recharge", body)
check("流水前后余额正确",
      body["data"]["transaction"]["balance_before"] == 0.0 and body["data"]["transaction"]["balance_after"] == 100.0,
      body["data"]["transaction"])
status, body = api("POST", f"/api/v1/balance/recharge/{order['id']}/confirm", token=token)
check("重复确认被拒绝", status == 400, f"{status} {body}")

status, body = api("GET", "/api/v1/balance", token=token)
check("余额更新为 100", body["data"]["balance"] == 100.0 and body["data"]["total_recharge"] == 100.0, body)

status, body = api("POST", "/api/v1/balance/transactions", token=token,
                   json={"type": "consume", "amount": 3.5, "country": "BR", "task": "群发任务#1"})
check("管理员手工扣费", status == 200 and body["data"]["amount"] == -3.5, f"{status} {body}")
status, body = api("POST", "/api/v1/balance/transactions", token=token,
                   json={"type": "bogus", "amount": 1})
check("非法流水类型被拒绝", status == 400, f"{status} {body}")

status, body = api("GET", "/api/v1/balance/transactions?page=1&size=10", token=token)
check("流水列表 2 条", body["data"]["total"] == 2, body)
check("流水倒序", body["data"]["list"][0]["type"] == "consume", body["data"]["list"])
status, body = api("GET", "/api/v1/balance/transactions?type=recharge", token=token)
check("按类型过滤流水", body["data"]["total"] == 1, body)
status, body = api("GET", "/api/v1/balance", token=token)
check("扣费后余额 96.5", body["data"]["balance"] == 96.5 and body["data"]["total_consume"] == 3.5, body)

status, body = api("POST", "/api/v1/balance/recharge", token=token, json={"amount": 20})
cancel_id = body["data"]["id"]
status, body = api("POST", f"/api/v1/balance/recharge/{cancel_id}/cancel", token=token)
check("取消充值订单", body["data"]["status"] == "cancelled", body)
status, body = api("POST", f"/api/v1/balance/recharge/{cancel_id}/confirm", token=token)
check("取消后不能确认到账", status == 400, f"{status} {body}")

status, body = api("GET", "/api/v1/balance/rules", token=token)
check("计费规则列表", status == 200 and len(body["data"]) == 8 and body["data"][0]["currency"] == "USDT",
      f"{status} {body}")

# ---------- 6. 个人中心 ----------
section("6 个人中心 User / OperationLog")
status, body = api("GET", "/api/v1/me", token=token)
check("获取当前用户", body["data"]["username"] == "admin", body)
check("不返回密码字段", "password_hash" not in body["data"] and "salt" not in body["data"], body)
check("记录登录次数", body["data"]["login_count"] >= 1 and body["data"]["last_login_at"], body)

status, body = api("PUT", "/api/v1/me", token=token,
                   json={"nickname": "运营管理员", "email": "ops@example.com", "phone": "13800000000"})
check("更新个人资料", body["data"]["nickname"] == "运营管理员", body)
status, body = api("PUT", "/api/v1/me", token=token, json={"email": "not-an-email"})
check("非法邮箱被拒绝", status == 400, f"{status} {body}")

status, body = api("GET", "/api/v1/me/logs?page=1&size=50", token=token)
actions = [row["action"] for row in body["data"]["list"]]
check("操作日志已记录", body["data"]["total"] > 0, body)
for expected in ("login", "create_ad_copy", "update_settings", "confirm_recharge", "update_profile"):
    check(f"日志包含 {expected}", expected in actions, actions)
check("日志字段完整", set(body["data"]["list"][0]) >= {"id", "action", "target", "result", "detail", "created_at"},
      body["data"]["list"][0])

# ---------- 7. 用户管理 ----------
section("7 用户管理")
status, body = api("POST", "/api/v1/admin/users", token=token, json={
    "username": "operator1", "password": "op123456", "nickname": "操作员一号", "role": "operator"})
check("创建用户", status == 200 and body["data"]["role"] == "operator", f"{status} {body}")
op_id = body["data"]["id"]
status, body = api("POST", "/api/v1/admin/users", token=token,
                   json={"username": "operator1", "password": "op123456"})
check("重复用户名被拒绝", status == 400, f"{status} {body}")
status, body = api("POST", "/api/v1/admin/users", token=token, json={"username": "o", "password": "123"})
check("非法用户名/短密码被拒绝", status == 400, f"{status} {body}")

status, body = api("GET", "/api/v1/admin/users", token=token)
check("用户列表", body["data"]["total"] >= 3, body)
status, body = api("POST", "/api/v1/auth/login", json={"username": "operator1", "password": "op123456"})
op_token = body["data"]["token"]
status, body = api("PUT", "/api/v1/settings", token=op_token, json={"daily_send_limit": 60})
check("操作员无权改设置(403)", status == 403, f"{status} {body}")
status, body = api("GET", "/api/v1/settings", token=op_token)
check("操作员可读设置", status == 200, f"{status} {body}")

status, body = api("PUT", f"/api/v1/admin/users/{op_id}", token=token, json={"status": "disabled"})
check("禁用用户", body["data"]["status"] == "disabled", body)
status, body = api("POST", "/api/v1/auth/login", json={"username": "operator1", "password": "op123456"})
check("禁用后无法登录", status == 403, f"{status} {body}")
status, me = api("GET", "/api/v1/me", token=token)
status, body = api("DELETE", f"/api/v1/admin/users/{me['data']['id']}", token=token)
check("不能删除自己", status == 400, f"{status} {body}")
status, body = api("DELETE", f"/api/v1/admin/users/{op_id}", token=token)
check("删除用户", status == 200, f"{status} {body}")

# ---------- 8. 修改密码 ----------
section("8 修改密码")
status, body = api("POST", "/api/v1/me/password", token=token,
                   json={"old_password": "wrong", "new_password": "admin456"})
check("旧密码错误被拒绝", status == 400, f"{status} {body}")
status, body = api("POST", "/api/v1/me/password", token=token,
                   json={"old_password": "admin123", "new_password": "123"})
check("新密码过短被拒绝", status == 400, f"{status} {body}")
status, body = api("POST", "/api/v1/me/password", token=token,
                   json={"old_password": "admin123", "new_password": "admin456"})
check("修改密码成功", status == 200, f"{status} {body}")
status, body = api("GET", "/api/v1/me", token=token)
check("改密后旧 token 失效", status == 401, f"{status} {body}")
status, body = api("POST", "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
check("旧密码无法登录", status == 401, f"{status} {body}")
status, body = api("POST", "/api/v1/auth/login", json={"username": "admin", "password": "admin456"})
check("新密码可以登录", status == 200, f"{status} {body}")
token = body["data"]["token"]
status, body = api("POST", "/api/v1/me/password", token=token,
                   json={"old_password": "admin456", "new_password": "admin123"})
check("密码改回默认值", status == 200, f"{status} {body}")

# ---------- 9. 登出 ----------
section("9 登出")
status, body = api("POST", "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
token = body["data"]["token"]
status, body = api("POST", "/api/v1/auth/logout", token=token)
check("登出成功", status == 200, f"{status} {body}")
status, body = api("GET", "/api/v1/me", token=token)
check("登出后 token 失效", status == 401, f"{status} {body}")

# ---------- 结果 ----------
print("\n" + "=" * 60)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
if FAILED:
    print("失败清单：")
    for name in FAILED:
        print("  - " + name)
sys.exit(1 if FAILED else 0)
