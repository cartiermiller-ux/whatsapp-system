# -*- coding: utf-8 -*-
"""real_mass_send / USE_REAL_SEND 逻辑自测。

不联网、不连真实 WhatsApp，但**走真实 TCP**：
起一个假 wasock Node 服务（复刻 node/server.js 的"换行分隔 JSON"协议），
让 main.wasock_request / send_via_wasock / real_mass_send 完整跑一遍。
覆盖：传输层健壮性、目标解析（含 ID 冲突）、文案渲染、重试、计数、日志、
前置校验、开关分流、发送间隔、登录态判定。
"""
import json
import os
import shutil
import socket
import sys
import threading
import time
from datetime import datetime, timedelta

DB_FILE = os.path.abspath(os.path.join(os.environ.get("WHATSAPP_TEST_TMP_DIR", os.path.join("tests", ".tmp")), "real_send_test.db"))
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
os.environ["WHATSAPP_DATABASE_URL"] = "sqlite:///" + DB_FILE
sys.path.insert(0, os.getcwd())

import main  # noqa: E402
import operations
from main import (AccountPool, MassSendTask, NumberPool, ResourceGroup,  # noqa: E402
                  SessionLocal, TaskLog)

ORIGINAL_INTERVAL = main.send_interval_seconds
ORIGINAL_IS_LOGGED_IN = main.is_wasock_logged_in
ORIGINAL_ACTIVATE = operations.activate_account
PASSED, FAILED = [], []


def check(name, cond, extra=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  | {extra}"))


def section(title):
    print("\n===== " + title + " =====")


class FakeWasockServer(threading.Thread):
    """假 wasock Node 服务：TCP + 换行分隔 JSON，回 {"type":"response","success":...}。

    用真实 socket 而不是打桩函数，是为了顺带验证拆包、事件穿插、脏数据等真实情况。
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.host, self.port = self.sock.getsockname()
        self.sock.listen(8)
        self.received = []
        self.attempts = {}
        self.fail_chats = set()
        self.fail_times = 0
        self.mode = "ok"          # ok / split / event / garbage / close
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        buffer = b""
        with conn:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    with self._lock:
                        self.received.append(msg)
                        chat = msg.get("chat")
                        self.attempts[chat] = self.attempts.get(chat, 0) + 1

                    if self.mode == "close":
                        return
                    if self.mode == "garbage":
                        conn.sendall(b"<html>not json at all</html>\n")
                        continue
                    if self.mode == "event":
                        conn.sendall(b'{"type":"event","event":"login","qr":"fake"}\n')
                    blob = (json.dumps(self._response(msg)) + "\n").encode("utf-8")
                    if self.mode == "split":
                        conn.sendall(blob[:6])
                        time.sleep(0.03)
                        conn.sendall(blob[6:])
                    else:
                        conn.sendall(blob)

    def _response(self, msg):
        if msg.get("action") != "sendMessage":
            return {"type": "response", "success": True, "message": ""}
        chat = msg.get("chat")
        if chat in self.fail_chats:
            return {"type": "response", "success": False, "message": "Not connected"}
        if self.fail_times and self.attempts.get(chat, 0) <= self.fail_times:
            return {"type": "response", "success": False, "message": "temporary failure"}
        return {"type": "response", "success": True, "message": ""}

    def sent(self):
        with self._lock:
            return [m for m in self.received if m.get("action") == "sendMessage"]

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


def use_server(server, logged_in=True):
    """把 main 指向假服务。调用方负责之后 restore()。"""
    main.WASOCK_HOST = "127.0.0.1"
    main.WASOCK_PORT = server.port
    main.USE_REAL_SEND = True
    os.environ["USE_REAL_SEND"] = "true"
    operations.activate_account = lambda account, db: None if logged_in else (_ for _ in ()).throw(ValueError("未登录"))
    main.is_wasock_logged_in = lambda *a, **k: logged_in
    main.send_interval_seconds = lambda db: 0.0
    main.SEND_RETRY_WAIT = 0.0


def restore():
    main.USE_REAL_SEND = False
    os.environ["USE_REAL_SEND"] = "false"
    operations.activate_account = ORIGINAL_ACTIVATE
    main.WASOCK_HOST = "127.0.0.1"
    main.WASOCK_PORT = 5000
    main.send_interval_seconds = ORIGINAL_INTERVAL
    main.is_wasock_logged_in = ORIGINAL_IS_LOGGED_IN


def make_account(db, hours_old=48, health=90):
    account = AccountPool(number_id=1, device_fingerprint="fp_test", current_ip="1.1.1.1",
                          nurture_stage="ready", health_score=health, status="normal",
                          created_at=datetime.now() - timedelta(hours=hours_old))
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def make_task(db, targets, content, link="", account_id=0, target_type="group"):
    task = MassSendTask(task_name="自测任务", target_type=target_type,
                        target_ids=",".join(str(t) for t in targets),
                        account_ids=str(account_id), message_content=content, link_url=link)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


server = FakeWasockServer()
server.start()

# ---------------------------------------------------------------- 工具函数
section("0 工具函数")
check("手机号转 JID", main.to_whatsapp_jid("8613800000001") == "8613800000001@s.whatsapp.net")
check("带 + 与空格的号码转 JID", main.to_whatsapp_jid("+86 138-0000-0001") == "8613800000001@s.whatsapp.net")
check("群 JID 原样返回", main.to_whatsapp_jid("123456@g.us") == "123456@g.us")
check("空值返回空串", main.to_whatsapp_jid("") == "")

# ---------------------------------------------------------------- 传输层
section("1 传输层（真实 socket，对接假 Node 服务）")
main.WASOCK_HOST, main.WASOCK_PORT = "127.0.0.1", server.port
check("服务在跑时 wasock_is_running() 为真", main.wasock_is_running() is True)
main.WASOCK_PORT = 59999
check("端口没人监听时为假", main.wasock_is_running() is False)
ok, detail = main.send_via_wasock("8613800000001@s.whatsapp.net", "hi")
check("服务没起时返回 False 并给出原因", ok is False and "连接 wasock 服务失败" in detail, detail)
main.WASOCK_PORT = server.port

ok, detail = main.send_via_wasock("8613800000001@s.whatsapp.net", "hello")
check("正常发送返回 True", ok is True and detail == "", (ok, detail))
sent = server.sent()[-1]
check("请求格式符合 server.js 的协议",
      sent["action"] == "sendMessage" and sent["chat"] == "8613800000001@s.whatsapp.net" and sent["msg"] == "hello",
      sent)
check("中文与 emoji 不乱码", main.send_via_wasock("a@s.whatsapp.net", "中文测试 🎉")[0] is True
      and server.sent()[-1]["msg"] == "中文测试 🎉")

server.mode = "split"
check("响应被拆包也能正确解析", main.send_via_wasock("b@s.whatsapp.net", "split")[0] is True)
server.mode = "event"
check("响应前穿插事件行时能跳过事件", main.send_via_wasock("c@s.whatsapp.net", "evt")[0] is True)
server.mode = "garbage"
ok, detail = main.send_via_wasock("d@s.whatsapp.net", "bad")
check("返回非 JSON 时返回 False", ok is False and "无法解析" in detail, detail)
server.mode = "close"
ok, detail = main.send_via_wasock("e@s.whatsapp.net", "closed")
check("服务直接断开时返回 False", ok is False, detail)
server.mode = "ok"
server.fail_chats = {"f@s.whatsapp.net"}
ok, detail = main.send_via_wasock("f@s.whatsapp.net", "will fail")
check("服务返回 success=false 时透出原因", ok is False and detail == "Not connected", detail)
server.fail_chats = set()
check("空 chat 直接拒绝", main.send_via_wasock("", "x")[0] is False)
check("空消息直接拒绝", main.send_via_wasock("a@s.whatsapp.net", "")[0] is False)

# ---------------------------------------------------------------- 目标解析
section("2 目标解析（resource_group.id 与 number_pool.id 同为 1，必须靠 target_type 区分）")
db = SessionLocal()
group = ResourceGroup(group_name="巴西促销群", group_jid="120363000000000001@g.us",
                      group_link="https://chat.whatsapp.com/AAA")
phone_row = NumberPool(phone_number="8613800000001", source_type="physical",
                       number_segment="861380", region="CN")
db.add_all([group, phone_row])
db.commit()
db.refresh(group)
db.refresh(phone_row)
check("构造出真实存在的 ID 冲突", group.id == phone_row.id, (group.id, phone_row.id))

r = main.resolve_send_target(db, group.id, "group")
check("group 模式 -> 群 JID", r["chat"] == "120363000000000001@g.us" and r["kind"] == "group", r)
check("group 模式带出群名（用于 {name}）", r["name"] == "巴西促销群", r)
r = main.resolve_send_target(db, phone_row.id, "contact")
check("contact 模式 -> 号码 JID（同一个 ID 不会串到群里）",
      r["chat"] == "8613800000001@s.whatsapp.net" and r["kind"] == "number", r)
r = main.resolve_send_target(db, 8613900000002, "contact")
check("contact 模式手填手机号 -> JID", r["chat"] == "8613900000002@s.whatsapp.net" and r["kind"] == "phone", r)
r = main.resolve_send_target(db, 999999, "contact")
check("contact 模式未知目标 -> error", r["chat"] == "" and "不存在" in r["error"], r)
r = main.resolve_send_target(db, 999999, "group")
check("group 模式不存在的群 -> error", r["chat"] == "" and "不存在" in r["error"], r)

# ---------------------------------------------------------------- 文案渲染
section("3 文案渲染 render_mass_message")
t = MassSendTask(message_content="Hi {name}, 看这里 {link}", link_url="https://a.com/x")
check("{name}/{link} 替换",
      main.render_mass_message(t, {"name": "巴西促销群"}) == "Hi 巴西促销群, 看这里 https://a.com/x")
check("没有 name 时回落到号码",
      main.render_mass_message(t, {"phone": "8613800000001"}) == "Hi 8613800000001, 看这里 https://a.com/x")
check("文案没写 {link} 时自动附在结尾",
      main.render_mass_message(MassSendTask(message_content="hello", link_url="https://a.com/x"), {})
      == "hello\nhttps://a.com/x")
check("没有超链时不追加",
      main.render_mass_message(MassSendTask(message_content="hello", link_url=""), {}) == "hello")

# ---------------------------------------------------------------- 主流程
section("4 真实发送主流程（group 模式，走真实 socket）")
account = make_account(db)
use_server(server)
task = make_task(db, [group.id, 999999], "你好 {name} -> {link}",
                 "https://promo.example.com", account.id, target_type="group")
before = len(server.sent())
main.dispatch_mass_send(task.id, db)
db.refresh(task)
msgs = server.sent()[before:]
check("群模式发到群 JID", [m["chat"] for m in msgs] == ["120363000000000001@g.us"], [m["chat"] for m in msgs])
check("发出去的是渲染后的文案",
      msgs[0]["msg"].startswith("你好 巴西促销群") and msgs[0]["msg"].endswith("https://promo.example.com"), msgs[0])
check("所有目标进入处理进度，包含失败目标", task.sent == 2 and task.failed == 1, (task.sent, task.failed))
check("发送成功与真实送达分开计数", task.accepted == 1 and task.delivered == 0, (task.accepted, task.delivered))
check("部分目标失败时标记任务异常", task.status == "failed", task.status)
logs = db.query(TaskLog).filter(TaskLog.task_id == task.id, TaskLog.account_id == account.id).all()
check("可解析目标记 success、不可解析记 failed",
      sorted(l.result for l in logs) == ["failed", "success"], [l.result for l in logs])
check("TaskLog 归属执行账号", all(l.account_id == account.id for l in logs), [l.account_id for l in logs])
check("TaskLog action=mass_send", all(l.action == "mass_send" for l in logs), [l.action for l in logs])

section("5 真实发送主流程（contact 模式，同一批 ID 走号码）")
before = len(server.sent())
task_c = make_task(db, [phone_row.id, 8613900000002], "hi {phone}", "", account.id, target_type="contact")
main.dispatch_mass_send(task_c.id, db)
db.refresh(task_c)
chats = [m["chat"] for m in server.sent()[before:]]
check("联系人模式发到号码 JID（不是群）",
      chats == ["8613800000001@s.whatsapp.net", "8613900000002@s.whatsapp.net"], chats)
check("{phone} 变量被替换", server.sent()[-1]["msg"] == "hi 8613900000002", server.sent()[-1])

# ---------------------------------------------------------------- 失败与重试
section("6 发送失败与重试")
main.SEND_RETRY_TIMES = 1
server.fail_chats = {"8613800000001@s.whatsapp.net"}
before = len(server.sent())
task2 = make_task(db, [phone_row.id, 8613900000002], "hello", "", account.id, target_type="contact")
main.dispatch_mass_send(task2.id, db)
db.refresh(task2)
check("失败目标不计入 accepted，回执未到不计送达", task2.accepted == 1 and task2.delivered == 0, (task2.accepted, task2.delivered))
check("可解析目标都计入 sent", task2.sent == 2, task2.sent)
check("部分失败时任务状态为 failed", task2.status == "failed", task2.status)
attempts = {m["chat"]: 0 for m in []}
for m in server.sent()[before:]:
    attempts[m["chat"]] = attempts.get(m["chat"], 0) + 1
check("首次执行不隐式重复发送", attempts.get("8613800000001@s.whatsapp.net") == 1, attempts)
server.fail_chats = set()

server.fail_times = 1
server.attempts["120363000000000001@g.us"] = 0
main.SEND_RETRY_TIMES = 1
task3 = make_task(db, [group.id], "retry me", "", account.id, target_type="group")
main.dispatch_mass_send(task3.id, db)
db.refresh(task3)
check("明确失败会记录原因，等待显式重试", task3.failed == 1 and task3.status == "failed", (task3.failed, task3.status))
server.fail_times = 0
ops_req = main.BackgroundTasks()
ops_user = type('User', (), {'username': 'test'})()
operations.control('mass-send', task3.id, 'retry', ops_req, db, ops_user)
main.dispatch_mass_send(task3.id, db)
db.refresh(task3)
check("显式重试成功，仍等待真实送达回执", task3.accepted == 1 and task3.delivered == 0 and task3.status == 'done', (task3.accepted,task3.delivered,task3.status))
server.fail_times = 0

server.fail_chats = {"120363000000000001@g.us"}
main.SEND_RETRY_TIMES = 0
task4 = make_task(db, [group.id], "all fail", "", account.id, target_type="group")
main.dispatch_mass_send(task4.id, db)
db.refresh(task4)
check("全部失败时任务状态 failed", task4.status == "failed", task4.status)
server.fail_chats = set()
main.SEND_RETRY_TIMES = 1

# ---------------------------------------------------------------- 前置校验
section("7 前置校验")
main.WASOCK_PORT = 59999        # 假装 Node 服务没起来
task5 = make_task(db, [group.id], "no service", "", account.id, target_type="group")
main.dispatch_mass_send(task5.id, db)
db.refresh(task5)
check("Node 服务没跑时任务失败且不发送", task5.status == "failed", task5.status)
main.WASOCK_PORT = server.port

use_server(server, logged_in=False)
task6 = make_task(db, [group.id], "no login", "", account.id, target_type="group")
main.dispatch_mass_send(task6.id, db)
db.refresh(task6)
check("未登录时任务失败", task6.status == "failed", task6.status)

use_server(server)
fresh = make_account(db, hours_old=1)
task7 = make_task(db, [group.id], "cooldown", "", fresh.id, target_type="group")
main.dispatch_mass_send(task7.id, db)
db.refresh(task7)
check("新设备冷却期内拒绝真实发送", task7.status == "failed", task7.status)

low = make_account(db, hours_old=48, health=40)
task8 = make_task(db, [group.id], "low health", "", low.id, target_type="group")
main.dispatch_mass_send(task8.id, db)
db.refresh(task8)
check("健康度过低拒绝真实发送", task8.status == "failed", task8.status)

task9 = make_task(db, [], "no target", "", account.id, target_type="group")
main.dispatch_mass_send(task9.id, db)
db.refresh(task9)
check("没有目标时任务失败", task9.status == "failed", task9.status)

# ---------------------------------------------------------------- 开关分流
section("8 USE_REAL_SEND 开关分流")
restore()
check("默认（未设环境变量）为 False", main.USE_REAL_SEND is False, main.USE_REAL_SEND)
simulated, real_called = {"n": 0}, {"n": 0}
main.simulate_mass_send = lambda task_id, d: simulated.__setitem__("n", simulated["n"] + 1)
main.real_mass_send = lambda task_id, d: real_called.__setitem__("n", real_called["n"] + 1)
task10 = make_task(db, [group.id], "switch", "", account.id)
main.dispatch_mass_send(task10.id, db)
check("开关 False -> 走 simulate_mass_send",
      simulated["n"] == 1 and real_called["n"] == 0, (simulated, real_called))
main.USE_REAL_SEND = True
os.environ["USE_REAL_SEND"] = "true"
main.dispatch_mass_send(task10.id, db)
check("开关 True -> 走 real_mass_send", real_called["n"] == 1, real_called)
restore()

# ---------------------------------------------------------------- 间隔节流
section("9 发送间隔取自系统设置")
main.upsert_setting(db, "send_interval_min", "3")
main.upsert_setting(db, "send_interval_max", "9")
db.commit()
intervals = [main.send_interval_seconds(db) for _ in range(40)]
check("间隔落在设置区间内", all(3.0 <= v <= 9.0 for v in intervals), (min(intervals), max(intervals)))
check("间隔是随机的", len({round(v, 3) for v in intervals}) > 1, intervals[:5])
db.close()

# ---------------------------------------------------------------- 登录态判定
section("10 登录态判定 is_wasock_logged_in")
AUTH_DIR = os.path.join("tests", ".tmp", "auth_probe")
shutil.rmtree(AUTH_DIR, ignore_errors=True)


def write_creds(payload, extra_files=0, valid_json=True):
    shutil.rmtree(AUTH_DIR, ignore_errors=True)
    os.makedirs(AUTH_DIR, exist_ok=True)
    with open(os.path.join(AUTH_DIR, "creds.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) if valid_json else "{not json")
    for i in range(extra_files):
        with open(os.path.join(AUTH_DIR, f"pre-key-{i}.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")


check("目录不存在 -> False", main.is_wasock_logged_in(os.path.join("tests", ".tmp", "nope")) is False)
write_creds({"me": {"id": "123@s.whatsapp.net"}})
check("只有 creds.json（无其他文件）-> False（对齐 isauthvalid 的文件数判断）",
      main.is_wasock_logged_in(AUTH_DIR) is False)
write_creds({"me": {"id": "123@s.whatsapp.net"}}, extra_files=2)
check("me.id 存在 -> True（registered 可能为 false，不能只看它）",
      main.is_wasock_logged_in(AUTH_DIR) is True)
write_creds({"registered": True}, extra_files=2)
check("registered=true 也认 -> True", main.is_wasock_logged_in(AUTH_DIR) is True)
write_creds({"me": {}}, extra_files=2)
check("me 为空对象 -> False", main.is_wasock_logged_in(AUTH_DIR) is False)
write_creds({}, extra_files=2)
check("既没 registered 也没 me -> False", main.is_wasock_logged_in(AUTH_DIR) is False)
write_creds({}, extra_files=2, valid_json=False)
check("creds.json 损坏 -> False", main.is_wasock_logged_in(AUTH_DIR) is False)
shutil.rmtree(AUTH_DIR, ignore_errors=True)

server.stop()
print("\n" + "=" * 60)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
for name in FAILED:
    print("  - " + name)
sys.exit(1 if FAILED else 0)
