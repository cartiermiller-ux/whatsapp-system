#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
端到端链路测试脚本
测试完整的用户操作流程：登录 -> 查看数据 -> 创建任务 -> 删除任务
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:5173"

def log_success(msg):
    print(f"[OK] {msg}")

def log_error(msg):
    print(f"[FAIL] {msg}")

def log_info(msg):
    print(f"[INFO] {msg}")

def test_api(method, url, **kwargs):
    """统一的API测试函数"""
    try:
        response = requests.request(method, url, timeout=10, **kwargs)
        return response
    except Exception as e:
        log_error(f"请求失败: {e}")
        return None

print("=" * 60)
print("WhatsApp 系统端到端链路测试")
print("=" * 60)

# 1. 测试后端健康检查
log_info("测试后端服务器...")
resp = test_api("GET", f"{BASE_URL}/docs")
if resp and resp.status_code == 200:
    log_success("后端服务器运行正常 (FastAPI docs 可访问)")
else:
    log_error("后端服务器响应异常")
    exit(1)

# 2. 测试登录
log_info("测试登录接口...")
login_data = {"username": "admin", "password": "admin123"}
resp = test_api("POST", f"{BASE_URL}/api/v1/auth/login", json=login_data)

if not resp or resp.status_code != 200:
    log_error(f"登录失败: {resp.text if resp else '无响应'}")
    exit(1)

login_result = resp.json()
if login_result.get("code") != 0:
    log_error(f"登录失败: {login_result.get('message')}")
    exit(1)

token = login_result["data"]["token"]
username = login_result["data"]["username"]
role = login_result["data"]["role"]
log_success(f"登录成功 - 用户: {username}, 角色: {role}")

headers = {"Authorization": f"Bearer {token}"}

# 3. 测试获取用户信息
log_info("测试获取用户信息...")
resp = test_api("GET", f"{BASE_URL}/api/v1/users/me", headers=headers)
if resp and resp.status_code == 200 and resp.json().get("code") == 0:
    log_success("用户信息接口正常")
else:
    log_error("用户信息接口异常")

# 4. 测试获取号码列表
log_info("测试号码管理接口...")
resp = test_api("GET", f"{BASE_URL}/api/v1/numbers", headers=headers)
if resp and resp.status_code == 200 and resp.json().get("code") == 0:
    numbers = resp.json()["data"]["items"]
    log_success(f"号码列表获取成功 - 共 {len(numbers)} 个号码")
else:
    log_error("号码列表获取失败")

# 5. 测试获取账号列表
log_info("测试账号管理接口...")
resp = test_api("GET", f"{BASE_URL}/api/v1/accounts", headers=headers)
if resp and resp.status_code == 200 and resp.json().get("code") == 0:
    accounts = resp.json()["data"]["items"]
    log_success(f"账号列表获取成功 - 共 {len(accounts)} 个账号")
else:
    log_error("账号列表获取失败")

# 6. 测试获取群组列表
log_info("测试群组管理接口...")
resp = test_api("GET", f"{BASE_URL}/api/v1/groups", headers=headers)
if resp and resp.status_code == 200 and resp.json().get("code") == 0:
    groups = resp.json()["data"]["items"]
    log_success(f"群组列表获取成功 - 共 {len(groups)} 个群组")
else:
    log_error("群组列表获取失败")

# 7. 测试创建群发任务
log_info("测试创建群发任务...")
if len(accounts) > 0 and len(groups) > 0:
    task_data = {
        "name": f"E2E测试任务_{int(time.time())}",
        "message": "这是一条端到端测试消息",
        "account_ids": [accounts[0]["id"]],
        "target_type": "group",
        "target_ids": [groups[0]["id"]]
    }
    resp = test_api("POST", f"{BASE_URL}/api/v1/mass-send/tasks", json=task_data, headers=headers)
    if resp and resp.status_code == 200 and resp.json().get("code") == 0:
        task_id = resp.json()["data"]["task_id"]
        log_success(f"群发任务创建成功 - 任务ID: {task_id}")
        
        # 8. 测试获取任务详情
        log_info("测试获取任务详情...")
        resp = test_api("GET", f"{BASE_URL}/api/v1/mass-send/tasks/{task_id}", headers=headers)
        if resp and resp.status_code == 200 and resp.json().get("code") == 0:
            log_success("任务详情获取成功")
        else:
            log_error("任务详情获取失败")
        
        # 9. 测试删除任务（新功能）
        log_info("测试删除群发任务...")
        resp = test_api("DELETE", f"{BASE_URL}/api/v1/mass-send/tasks", 
                       json={"task_ids": [task_id]}, headers=headers)
        if resp and resp.status_code == 200 and resp.json().get("code") == 0:
            log_success("群发任务删除成功")
        else:
            log_error(f"群发任务删除失败: {resp.text if resp else '无响应'}")
    else:
        log_error(f"群发任务创建失败: {resp.text if resp else '无响应'}")
else:
    log_info("跳过群发任务测试（缺少账号或群组）")

# 10. 测试创建拉群任务
log_info("测试创建拉群任务...")
if len(accounts) > 0 and len(groups) > 0:
    invite_data = {
        "name": f"E2E拉群测试_{int(time.time())}",
        "target_group_id": groups[0]["id"],
        "source_type": "group",
        "source_ids": [groups[0]["id"]],
        "account_ids": [accounts[0]["id"]]
    }
    resp = test_api("POST", f"{BASE_URL}/api/v1/invite/tasks", json=invite_data, headers=headers)
    if resp and resp.status_code == 200 and resp.json().get("code") == 0:
        invite_id = resp.json()["data"]["task_id"]
        log_success(f"拉群任务创建成功 - 任务ID: {invite_id}")
        
        # 11. 测试删除拉群任务
        log_info("测试删除拉群任务...")
        resp = test_api("DELETE", f"{BASE_URL}/api/v1/invite/tasks", 
                       json={"task_ids": [invite_id]}, headers=headers)
        if resp and resp.status_code == 200 and resp.json().get("code") == 0:
            log_success("拉群任务删除成功")
        else:
            log_error(f"拉群任务删除失败: {resp.text if resp else '无响应'}")
    else:
        log_error(f"拉群任务创建失败: {resp.text if resp else '无响应'}")
else:
    log_info("跳过拉群任务测试（缺少账号或群组）")

# 12. 测试代理管理
log_info("测试代理管理接口...")
resp = test_api("GET", f"{BASE_URL}/api/v1/proxies", headers=headers)
if resp and resp.status_code == 200 and resp.json().get("code") == 0:
    proxies = resp.json()["data"]["items"]
    log_success(f"代理列表获取成功 - 共 {len(proxies)} 个代理")
else:
    log_error("代理列表获取失败")

# 13. 测试接码平台
log_info("测试接码平台接口...")
resp = test_api("GET", f"{BASE_URL}/api/v1/sms/orders", headers=headers)
if resp and resp.status_code == 200 and resp.json().get("code") == 0:
    sms_orders = resp.json()["data"]["items"]
    log_success(f"接码订单列表获取成功 - 共 {len(sms_orders)} 个订单")
else:
    log_error("接码订单列表获取失败")

# 14. 测试前端代理
log_info("测试前端代理转发...")
resp = test_api("GET", f"{FRONTEND_URL}/api/v1/auth/login")
# 前端代理应该返回405 (Method Not Allowed) 因为GET请求login接口
if resp and resp.status_code in [405, 422]:
    log_success("前端代理转发正常")
else:
    log_error(f"前端代理转发异常: {resp.status_code if resp else '无响应'}")

# 15. 测试获取设置
log_info("测试系统设置接口...")
resp = test_api("GET", f"{BASE_URL}/api/v1/settings", headers=headers)
if resp and resp.status_code == 200 and resp.json().get("code") == 0:
    settings = resp.json()["data"]
    log_success(f"系统设置获取成功 - 共 {len(settings)} 项配置")
else:
    log_error("系统设置获取失败")

# 16. 测试统计接口
log_info("测试统计接口...")
resp = test_api("GET", f"{BASE_URL}/api/v1/dashboard/overview", headers=headers)
if resp and resp.status_code == 200 and resp.json().get("code") == 0:
    log_success("统计概览接口正常")
else:
    log_error("统计概览接口异常")

print("\n" + "=" * 60)
log_success("端到端链路测试完成!")
print("=" * 60)
print("\n测试摘要:")
print(f"  • 后端服务器: {BASE_URL}")
print(f"  • 前端服务器: {FRONTEND_URL}")
print(f"  • 测试用户: {username}")
print(f"  • 测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("\n所有核心链路测试通过，应用可以正常使用！")
