# -*- coding: utf-8 -*-
"""群发任务 HTTP 链路：开关关闭时必须走 simulate_mass_send，且 target_type 正确落库"""
import sys
import time

import requests

API = "http://127.0.0.1:8099/api/v1"
FAILED = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  | {extra}"))
    if not cond:
        FAILED.append(name)


r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"}, timeout=15)
H = {"Authorization": "Bearer " + r.json()["data"]["token"]}

r = requests.post(f"{API}/mass-send/tasks", headers=H, timeout=15, json={
    "task_name": "HTTP 自测任务", "target_type": "contact",
    "target_ids": [1, 2], "account_ids": [1],
    "message_content": "hi {name} {link}", "link_url": "https://x.test"})
check("创建群发任务成功", r.status_code == 200 and r.json()["code"] == 0, r.text[:200])
task_id = r.json()["data"]["task_id"]

deadline = time.time() + 15
detail = {}
while time.time() < deadline:
    detail = requests.get(f"{API}/mass-send/tasks/{task_id}", headers=H, timeout=15).json()["data"]
    if detail["status"] in ("done", "failed"):
        break
    time.sleep(0.5)

check("开关关闭时任务由 simulate_mass_send 跑完", detail.get("status") == "done", detail)
check("模拟发送覆盖全部目标", detail.get("sent") == 2, detail)
check("详情返回 target_type", detail.get("target_type") == "contact", detail)

r = requests.get(f"{API}/mass-send/tasks?page=1&size=10", headers=H, timeout=15)
rows = r.json()["data"]["list"]
row = [x for x in rows if x["id"] == task_id][0]
check("列表返回 target_type", row.get("target_type") == "contact", row)
check("列表保留了旧任务的默认 target_type",
      all("target_type" in x for x in rows), rows)

r = requests.post(f"{API}/mass-send/tasks", headers=H, timeout=15, json={
    "task_name": "默认 group 模式", "target_ids": [1], "account_ids": [1],
    "message_content": "no target_type field"})
check("不传 target_type 时默认 group", r.status_code == 200, r.text[:200])
tid2 = r.json()["data"]["task_id"]
time.sleep(2.5)
detail2 = requests.get(f"{API}/mass-send/tasks/{tid2}", headers=H, timeout=15).json()["data"]
check("默认模式同样正常跑完", detail2.get("status") == "done", detail2)
check("默认 target_type=group", detail2.get("target_type") == "group", detail2)

requests.post(f"{API}/auth/logout", headers=H, timeout=15)
print("\n" + ("全部通过" if not FAILED else f"失败 {len(FAILED)} 项"))
sys.exit(1 if FAILED else 0)
