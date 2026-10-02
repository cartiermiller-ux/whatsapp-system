# -*- coding: utf-8 -*-
"""real_mass_send / USE_REAL_SEND 逻辑自测。

用假 bot 替掉 wasock，不联网、不启动 Node 服务，只验证发送逻辑本身：
目标解析（含 ID 冲突）、文案渲染、间隔节流、计数、日志、失败与前置校验、开关分流。
"""
import os
import sys
from datetime import datetime, timedelta

DB_FILE = os.path.join("tests", ".tmp", "real_send_test.db")
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
os.environ["WHATSAPP_DATABASE_URL"] = "sqlite:///./" + DB_FILE
sys.path.insert(0, os.getcwd())

import main  # noqa: E402
from main import (AccountPool, MassSendTask, NumberPool, ResourceGroup,  # noqa: E402
                  SessionLocal, TaskLog)

ORIGINAL_INTERVAL = main.send_interval_seconds
ORIGINAL_IS_LOGGED_IN = main.is_wasock_logged_in
ORIGINAL_GET_BOT = main.get_wasock_bot
PASSED, FAILED = [], []


def check(name, cond, extra=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  | {extra}"))


def section(title):
    print("\n===== " + title + " =====")


class FakeNodeJS:
    """记录所有发给 Node 服务的消息；可指定某些 chat 永远失败、或前 N 次失败。"""

    def __init__(self, fail_chats=(), fail_times=0):
        self.calls = []
        self.fail_chats = set(fail_chats)
        self.fail_times = fail_times
        self.attempts = {}

    def send(self, message):
        self.calls.append(message)
        if message.get("action") != "sendMessage":
            return {"type": "response", "success": True, "message": ""}
        chat = message.get("chat")
        self.attempts[chat] = self.attempts.get(chat, 0) + 1
        if chat in self.fail_chats:
            return {"type": "response", "success": False, "message": "Not connected"}
        if self.attempts[chat] <= self.fail_times:
            return {"type": "response", "success": False, "message": "temporary failure"}
        return {"type": "response", "success": True, "message": ""}

    def sent(self):
        return [c for c in self.calls if c.get("action") == "sendMessage"]


class FakeBot:
    def __init__(self, **kwargs):
        self.nodeJS = FakeNodeJS(**kwargs)


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


def enable_real_send(bot, logged_in=True):
    """打开开关，并把 wasock 相关的外部依赖换成假实现。"""
    main.USE_REAL_SEND = True
    main.WASOCK_AVAILABLE = True
    main.is_wasock_logged_in = lambda *a, **k: logged_in
    main.send_interval_seconds = lambda db: 0.0
    main.SEND_RETRY_WAIT = 0.0
    seen = {"bot": 0}

    def fake_get_bot():
        seen["bot"] += 1
        return bot

    main.get_wasock_bot = fake_get_bot
    return seen


def restore():
    """把 enable_real_send 打过的补丁全部还原，避免影响后面的用例。"""
    main.USE_REAL_SEND = False
    main.send_interval_seconds = ORIGINAL_INTERVAL
    main.is_wasock_logged_in = ORIGINAL_IS_LOGGED_IN
    main.get_wasock_bot = ORIGINAL_GET_BOT


# ---------------------------------------------------------------- 工具函数
section("0 工具函数")
check("手机号转 JID", main.to_whatsapp_jid("8613800000001") == "8613800000001@s.whatsapp.net")
check("带 + 与空格的号码转 JID", main.to_whatsapp_jid("+86 138-0000-0001") == "8613800000001@s.whatsapp.net")
check("群 JID 原样返回", main.to_whatsapp_jid("123456@g.us") == "123456@g.us")
check("空值返回空串", main.to_whatsapp_jid("") == "")

# ---------------------------------------------------------------- 目标解析
section("1 目标解析（resource_group.id 与 number_pool.id 同为 1，必须靠 target_type 区分）")
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
section("2 文案渲染 render_mass_message")
t = MassSendTask(message_content="Hi {name}, 看这里 {link}", link_url="https://a.com/x")
check("{name}/{link} 替换",
      main.render_mass_message(t, {"name": "巴西促销群"}) == "Hi 巴西促销群, 看这里 https://a.com/x")
check("没有 name 时回落到号码",
      main.render_mass_message(t, {"phone": "8613800000001"}) == "Hi 8613800000001, 看这里 https://a.com/x")
t2 = MassSendTask(message_content="hello", link_url="https://a.com/x")
check("文案没写 {link} 时自动附在结尾", main.render_mass_message(t2, {}) == "hello\nhttps://a.com/x")
t3 = MassSendTask(message_content="hello", link_url="")
check("没有超链时不追加", main.render_mass_message(t3, {}) == "hello")

# ---------------------------------------------------------------- 主流程
section("3 真实发送主流程（group 模式）")
account = make_account(db)
fake = FakeBot()
seen = enable_real_send(fake)
task = make_task(db, [group.id, 999999], "你好 {name} -> {link}",
                 "https://promo.example.com", account.id, target_type="group")
main.dispatch_mass_send(task.id, db)
db.refresh(task)
msgs = fake.nodeJS.sent()
check("开关打开时走 real_mass_send（拉起 bot）", seen["bot"] == 1, seen)
check("群模式发到群 JID", [m["chat"] for m in msgs] == ["120363000000000001@g.us"], [m["chat"] for m in msgs])
check("发出去的是渲染后的文案",
      msgs[0]["msg"].startswith("你好 巴西促销群") and msgs[0]["msg"].endswith("https://promo.example.com"), msgs[0])
check("计数 sent=1（不可解析的目标不算已发送）", task.sent == 1, task.sent)
check("计数 delivered=1", task.delivered == 1, task.delivered)
check("任务状态 done", task.status == "done", task.status)
logs = db.query(TaskLog).filter_by(task_id=task.id).all()
check("可解析目标记 success、不可解析记 failed",
      sorted(l.result for l in logs) == ["failed", "success"], [l.result for l in logs])
check("TaskLog 归属执行账号", all(l.account_id == account.id for l in logs), [l.account_id for l in logs])
check("TaskLog action=mass_send", all(l.action == "mass_send" for l in logs), [l.action for l in logs])

section("4 真实发送主流程（contact 模式，同一批 ID 走号码）")
fake_c = FakeBot()
enable_real_send(fake_c)
task_c = make_task(db, [phone_row.id, 8613900000002], "hi {phone}", "", account.id, target_type="contact")
main.dispatch_mass_send(task_c.id, db)
db.refresh(task_c)
chats = [m["chat"] for m in fake_c.nodeJS.sent()]
check("联系人模式发到号码 JID（不是群）",
      chats == ["8613800000001@s.whatsapp.net", "8613900000002@s.whatsapp.net"], chats)
check("{phone} 变量被替换", fake_c.nodeJS.sent()[0]["msg"] == "hi 8613800000001", fake_c.nodeJS.sent()[0])

# ---------------------------------------------------------------- 失败与重试
section("5 发送失败与重试")
main.SEND_RETRY_TIMES = 1
fake2 = FakeBot(fail_chats=["8613800000001@s.whatsapp.net"])
enable_real_send(fake2)
task2 = make_task(db, [phone_row.id, 8613900000002], "hello", "", account.id, target_type="contact")
main.dispatch_mass_send(task2.id, db)
db.refresh(task2)
check("失败目标不计入 delivered", task2.delivered == 1, task2.delivered)
check("可解析目标都计入 sent", task2.sent == 2, task2.sent)
check("部分成功时任务仍为 done", task2.status == "done", task2.status)
check("失败目标重试 1 次（共 2 次尝试）",
      fake2.nodeJS.attempts.get("8613800000001@s.whatsapp.net") == 2, fake2.nodeJS.attempts)

fake3 = FakeBot(fail_times=1)
enable_real_send(fake3)
task3 = make_task(db, [group.id], "retry me", "", account.id, target_type="group")
main.dispatch_mass_send(task3.id, db)
db.refresh(task3)
check("首次失败后重试成功则计入 delivered", task3.delivered == 1 and task3.status == "done",
      (task3.delivered, task3.status))

fake4 = FakeBot(fail_chats=["120363000000000001@g.us"])
enable_real_send(fake4)
task4 = make_task(db, [group.id], "all fail", "", account.id, target_type="group")
main.dispatch_mass_send(task4.id, db)
db.refresh(task4)
check("全部失败时任务状态 failed", task4.status == "failed", task4.status)

# ---------------------------------------------------------------- 前置校验
section("6 前置校验")
fake5 = FakeBot()
enable_real_send(fake5, logged_in=False)
task5 = make_task(db, [group.id], "no login", "", account.id, target_type="group")
main.dispatch_mass_send(task5.id, db)
db.refresh(task5)
check("未登录时任务失败且不发送",
      task5.status == "failed" and len(fake5.nodeJS.sent()) == 0, task5.status)

main.WASOCK_AVAILABLE = False
main.WASOCK_IMPORT_ERROR = "No module named 'wasock'"
task6 = make_task(db, [group.id], "no lib", "", account.id, target_type="group")
main.dispatch_mass_send(task6.id, db)
db.refresh(task6)
check("未安装 wasock 时任务失败", task6.status == "failed", task6.status)
main.WASOCK_AVAILABLE = True

fresh = make_account(db, hours_old=1)
fake7 = FakeBot()
enable_real_send(fake7)
task7 = make_task(db, [group.id], "cooldown", "", fresh.id, target_type="group")
main.dispatch_mass_send(task7.id, db)
db.refresh(task7)
check("新设备冷却期内拒绝真实发送",
      task7.status == "failed" and len(fake7.nodeJS.sent()) == 0, task7.status)

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
section("7 USE_REAL_SEND 开关分流")
restore()
check("开关默认是 False", main.USE_REAL_SEND is False, main.USE_REAL_SEND)
simulated, real_called = {"n": 0}, {"n": 0}
main.simulate_mass_send = lambda task_id, d: simulated.__setitem__("n", simulated["n"] + 1)
main.real_mass_send = lambda task_id, d: real_called.__setitem__("n", real_called["n"] + 1)
task10 = make_task(db, [group.id], "switch", "", account.id)
main.dispatch_mass_send(task10.id, db)
check("开关 False -> 走 simulate_mass_send",
      simulated["n"] == 1 and real_called["n"] == 0, (simulated, real_called))
main.USE_REAL_SEND = True
main.dispatch_mass_send(task10.id, db)
check("开关 True -> 走 real_mass_send", real_called["n"] == 1, real_called)
restore()

# ---------------------------------------------------------------- 间隔节流
section("8 发送间隔取自系统设置")
main.upsert_setting(db, "send_interval_min", "3")
main.upsert_setting(db, "send_interval_max", "9")
db.commit()
intervals = [main.send_interval_seconds(db) for _ in range(40)]
check("间隔落在设置区间内", all(3.0 <= v <= 9.0 for v in intervals), (min(intervals), max(intervals)))
check("间隔是随机的", len({round(v, 3) for v in intervals}) > 1, intervals[:5])
db.close()

# ---------------------------------------------------------------- 登录态判定
section("9 登录态判定 is_wasock_logged_in")
import json  # noqa: E402
import shutil  # noqa: E402

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

print("\n" + "=" * 60)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
for name in FAILED:
    print("  - " + name)
sys.exit(1 if FAILED else 0)
