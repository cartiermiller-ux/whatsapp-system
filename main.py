from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, Query, Header
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean, DECIMAL, Numeric, Text, func, or_,
    inspect, text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import hashlib, hmac, json, os, random, re, secrets, threading, time

# ---------- 号码来源类型统一 ----------
# 对外统一使用英文枚举，兼容历史/手填的中文值
SOURCE_TYPE_ALIASES = {
    "physical": "physical", "实体卡": "physical",
    "virtual": "virtual", "虚拟号": "virtual",
    "sms_platform": "sms_platform", "sms": "sms_platform", "接码平台": "sms_platform",
}


def normalize_source_type(value: str) -> str:
    key = (value or "").strip()
    return SOURCE_TYPE_ALIASES.get(key, key)

# ---------- 数据库 ----------
DATABASE_URL = os.environ.get("WHATSAPP_DATABASE_URL", "sqlite:///./whatsapp.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ---------- 模型 ----------
class NumberPool(Base):
    __tablename__ = "number_pool"
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), unique=True, index=True)
    source_type = Column(String(20))
    source_channel = Column(String(50))
    number_segment = Column(String(20))
    region = Column(String(50))
    trust_score = Column(Integer, default=50)
    status = Column(String(20), default="pending")
    register_time = Column(DateTime, nullable=True)
    account_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

class AccountPool(Base):
    __tablename__ = "account_pool"
    id = Column(Integer, primary_key=True, index=True)
    number_id = Column(Integer, index=True)
    device_fingerprint = Column(String(255))
    current_ip = Column(String(45))
    nurture_stage = Column(String(20), default="none")
    health_score = Column(Integer, default=100)
    status = Column(String(20), default="normal")
    created_at = Column(DateTime, default=datetime.now)

class MassSendTask(Base):
    __tablename__ = "mass_send_task"
    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(255))
    target_type = Column(String(20), default="group")   # group=资源群 / contact=联系人
    target_ids = Column(Text)
    account_ids = Column(Text)
    message_content = Column(Text)
    link_url = Column(String(500))
    status = Column(String(20), default="pending")
    sent = Column(Integer, default=0)
    delivered = Column(Integer, default=0)
    read_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

class ResourceGroup(Base):
    __tablename__ = "resource_group"
    id = Column(Integer, primary_key=True, index=True)
    group_name = Column(String(255))
    group_jid = Column(String(255), unique=True)
    group_link = Column(String(500))
    owner_account_id = Column(Integer)
    number_segment = Column(String(20))
    can_speak = Column(Boolean, default=True)
    can_invite = Column(Boolean, default=True)
    approval_mode = Column(Boolean, default=False)
    group_owner = Column(String(255))
    admins = Column(Text)
    marketing_score = Column(Integer, default=50)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.now)

class InviteTask(Base):
    __tablename__ = "invite_task"
    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(255))
    target_group_id = Column(Integer)
    source_type = Column(String(20))
    source_ids = Column(Text)
    account_ids = Column(Text)
    strategy = Column(Text)
    billing_country = Column(String(50))
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=datetime.now)

class TaskLog(Base):
    __tablename__ = "task_log"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer)
    account_id = Column(Integer)
    action = Column(String(50))
    result = Column(String(20))
    created_at = Column(DateTime, default=datetime.now)

# ---------- P2 模型：广告消息 ----------
class AdMessage(Base):
    """广告文案（多语言）。变量以 {name} / {link} 形式写在 content 中。"""
    __tablename__ = "ad_message"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255))
    content = Column(Text)
    language = Column(String(10), default="zh", index=True)
    link_url = Column(String(500), default="")
    variables = Column(String(500), default="")
    category = Column(String(50), default="")
    status = Column(String(20), default="active", index=True)   # active / paused / draft
    sent = Column(Integer, default=0)
    delivered = Column(Integer, default=0)
    read_count = Column(Integer, default=0)
    click_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class AdLink(Base):
    """超链：短链生成 / 域名伪装 / 追踪参数。"""
    __tablename__ = "ad_link"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    original_url = Column(String(1000))
    short_code = Column(String(32), unique=True, index=True)
    domain = Column(String(255), default="")
    tracking_params = Column(String(500), default="")
    ad_message_id = Column(Integer, nullable=True, index=True)
    click_count = Column(Integer, default=0)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

# ---------- P2 模型：余额与计费 ----------
class BalanceTransaction(Base):
    """余额流水账本。余额 = 全部流水 amount 之和（不额外维护余额字段，避免对不上）。"""
    __tablename__ = "balance_transaction"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(30), index=True)                 # recharge 充值 / consume 消费 / refund 退款 / adjust 调整
    amount = Column(Numeric(18, 6), default=0)            # 正数入账，负数扣费
    balance_before = Column(Numeric(18, 6), default=0)
    balance_after = Column(Numeric(18, 6), default=0)
    currency = Column(String(10), default="USDT")
    country = Column(String(50), default="")              # 计费国家
    task = Column(String(255), default="")                # 关联任务名（展示用）
    task_type = Column(String(30), default="")            # mass_send / invite
    task_id = Column(Integer, nullable=True)
    result = Column(String(20), default="success")
    remark = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.now, index=True)

class RechargeOrder(Base):
    """USDT 充值订单。"""
    __tablename__ = "recharge_order"
    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(64), unique=True, index=True)
    amount = Column(Numeric(18, 6), default=0)
    currency = Column(String(10), default="USDT")
    chain = Column(String(20), default="TRC20")
    address = Column(String(128), default="")             # 收款地址（取自系统设置）
    tx_hash = Column(String(128), default="")
    status = Column(String(20), default="pending", index=True)   # pending / paid / cancelled / expired
    user_id = Column(Integer, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    expire_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

# ---------- P2 模型：用户与操作日志 ----------
class User(Base):
    __tablename__ = "sys_user"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True)
    password_hash = Column(String(255), default="")
    salt = Column(String(64), default="")
    nickname = Column(String(64), default="")
    email = Column(String(128), default="")
    phone = Column(String(32), default="")
    role = Column(String(30), default="operator")         # super_admin / agent_admin / operator
    tenant = Column(String(64), default="default")
    status = Column(String(20), default="active")         # active / disabled
    last_login_at = Column(DateTime, nullable=True)
    login_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class OperationLog(Base):
    """用户操作日志（个人中心 —— 时间 / 操作 / 对象 / 结果）。"""
    __tablename__ = "operation_log"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    username = Column(String(64), default="")
    action = Column(String(64))
    target = Column(String(255), default="")
    result = Column(String(20), default="success")
    detail = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.now, index=True)

# ---------- P2 模型：系统设置 ----------
class Setting(Base):
    """全局参数（键值对）。字段定义见 SETTING_DEFS，类型 / 取值范围以定义为准。"""
    __tablename__ = "setting"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, index=True)
    value = Column(String(500), default="")
    category = Column(String(32), default="general")
    value_type = Column(String(16), default="str")
    label = Column(String(128), default="")
    description = Column(String(255), default="")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

# ---------- 全局参数定义（默认值 / 类型 / 取值范围 / 分组） ----------
SETTING_DEFS: Dict[str, Dict[str, Any]] = {
    "send_interval_min": {
        "default": 5, "type": "int", "category": "send", "min": 1, "max": 600,
        "label": "发送间隔下限（秒）", "description": "同一账号两条消息之间的最小间隔",
    },
    "send_interval_max": {
        "default": 30, "type": "int", "category": "send", "min": 1, "max": 3600,
        "label": "发送间隔上限（秒）", "description": "同一账号两条消息之间的最大间隔",
    },
    "new_device_cooldown_hours": {
        "default": 24, "type": "int", "category": "send", "min": 0, "max": 720,
        "label": "新设备冷却（小时）", "description": "新注册设备在冷却期内不参与发送",
    },
    "daily_send_limit": {
        "default": 50, "type": "int", "category": "send", "min": 1, "max": 1000,
        "label": "单账号每日发送上限", "description": "超过上限的账号当天不再发送（发送策略检查会读取该值）",
    },
    "currency": {
        "default": "USDT", "type": "str", "category": "billing", "max_len": 10,
        "label": "结算币种", "description": "余额与流水的展示币种",
    },
    "min_recharge_amount": {
        "default": 10, "type": "float", "category": "billing", "min": 0.01, "max": 1000000,
        "label": "单笔最低充值", "description": "创建充值订单时的最小金额",
    },
    "recharge_chain": {
        "default": "TRC20", "type": "str", "category": "billing", "max_len": 20,
        "label": "充值链", "description": "如 TRC20 / ERC20",
    },
    "recharge_address": {
        "default": "", "type": "str", "category": "billing", "max_len": 128,
        "label": "收款地址", "description": "创建充值订单时下发给用户的收款地址",
    },
    "recharge_expire_minutes": {
        "default": 30, "type": "int", "category": "billing", "min": 5, "max": 1440,
        "label": "订单有效期（分钟）", "description": "超时未到账的充值订单自动置为已过期",
    },
    "short_link_domain": {
        "default": "go.wa-link.com", "type": "str", "category": "general", "max_len": 255,
        "label": "短链默认域名", "description": "超链未单独指定伪装域名时使用",
    },
}

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"
AUTO_PROVISION_USERS = True        # MVP：首次登录自动开户；接真实权限体系时置为 False
TOKEN_TTL_HOURS = 72
MONEY_SCALE = 6

# ---------- 通用小工具 ----------
def _dt(value):
    """datetime -> ISO 字符串，便于前端 dayjs 解析。"""
    return value.isoformat() if isinstance(value, datetime) else value

def _rate(part: int, total: int) -> float:
    return round((part or 0) / total * 100, 2) if total else 0.0

def _money(value: Any) -> float:
    return round(float(value or 0), MONEY_SCALE)

def _dec(value: Any) -> Decimal:
    return Decimal(str(round(float(value or 0), MONEY_SCALE)))

# ---------- 密码 ----------
def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()

def set_password(user: "User", password: str):
    user.salt = secrets.token_hex(16)
    user.password_hash = hash_password(password, user.salt)

def verify_password(user: Optional["User"], password: str) -> bool:
    if not user or not user.password_hash or not user.salt:
        return False
    return hmac.compare_digest(user.password_hash, hash_password(password, user.salt))

def create_user(db: Session, username: str, password: str, **fields) -> "User":
    user = User(username=username, **fields)
    set_password(user, password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

# ---------- 设置读写 ----------
def _coerce_setting(raw: Any, value_type: str) -> Any:
    try:
        if value_type == "int":
            return int(float(raw))
        if value_type == "float":
            return float(raw)
        if value_type == "bool":
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
    except (TypeError, ValueError):
        pass
    return "" if raw is None else str(raw)

def get_setting(db: Session, key: str, default: Any = None) -> Any:
    """读设置：DB 无记录时回落到定义中的默认值。"""
    definition = SETTING_DEFS.get(key)
    row = db.query(Setting).filter_by(key=key).first()
    if row is None:
        if default is not None:
            return default
        return definition["default"] if definition else None
    return _coerce_setting(row.value, (definition or {}).get("type") or row.value_type or "str")

def settings_snapshot(db: Session) -> Dict[str, Any]:
    """全部设置的扁平快照（保持 /api/v1/settings 的历史返回结构）。"""
    return {key: get_setting(db, key) for key in SETTING_DEFS}

def validate_setting(key: str, value: Any):
    """校验单个设置项，返回 (存库字符串, 错误信息)。"""
    definition = SETTING_DEFS.get(key)
    if not definition:
        return None, f"未知参数：{key}"
    value_type = definition["type"]
    if value_type == "bool":
        return ("1" if str(value).strip().lower() in ("1", "true", "yes", "on") else "0"), None
    if value_type == "str":
        text = "" if value is None else str(value).strip()
        max_len = definition.get("max_len", 500)
        if len(text) > max_len:
            return None, f"{definition['label']} 长度不能超过 {max_len}"
        return text, None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{definition['label']} 必须是数字"
    if value_type == "int":
        if number != int(number):
            return None, f"{definition['label']} 必须是整数"
        number = int(number)
    low, high = definition.get("min"), definition.get("max")
    if low is not None and number < low:
        return None, f"{definition['label']} 不能小于 {low}"
    if high is not None and number > high:
        return None, f"{definition['label']} 不能大于 {high}"
    return str(number), None

def upsert_setting(db: Session, key: str, raw_value: str):
    definition = SETTING_DEFS[key]
    row = db.query(Setting).filter_by(key=key).first()
    if row is None:
        row = Setting(key=key)
        db.add(row)
    row.value = raw_value
    row.category = definition["category"]
    row.value_type = definition["type"]
    row.label = definition["label"]
    row.description = definition.get("description", "")
    row.updated_at = datetime.now()

def seed_defaults():
    """建表后补齐默认设置与内置管理员，保证空库开箱可用。"""
    db = SessionLocal()
    try:
        existing = {row.key for row in db.query(Setting).all()}
        for key in SETTING_DEFS:
            if key not in existing:
                upsert_setting(db, key, str(SETTING_DEFS[key]["default"]))
        db.commit()
        if db.query(User).count() == 0:
            create_user(
                db, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD,
                nickname="超级管理员", role="super_admin", tenant="default",
            )
    finally:
        db.close()

# 轻量迁移：create_all 只建新表，不会给已存在的表补字段
REQUIRED_COLUMNS: Dict[str, Dict[str, str]] = {
    "mass_send_task": {"target_type": "VARCHAR(20) DEFAULT 'group'"},
}


def ensure_columns():
    """按需补字段。多进程同时启动时可能撞车，这里只记录不抛出，避免影响服务启动。"""
    inspector = inspect(engine)
    for table, columns in REQUIRED_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name in existing:
                continue
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                print(f"[migrate] {table} 补充字段 {name}", flush=True)
            except Exception as exc:
                current = {col["name"] for col in inspect(engine).get_columns(table)}
                if name in current:
                    continue        # 另一个进程刚好先加上了，属正常
                print(f"[migrate] {table}.{name} 迁移失败（不影响启动）："
                      f"{type(exc).__name__}: {exc}", flush=True)


Base.metadata.create_all(bind=engine)
ensure_columns()
seed_defaults()

# ---------- Pydantic ----------
class NumberImport(BaseModel):
    phone: str
    source_type: str
    source_channel: str = ""

class RegisterRequest(BaseModel):
    number_ids: List[int]

class MassSendRequest(BaseModel):
    task_name: str
    target_type: str = "group"      # group=资源群 / contact=联系人（号码池 ID 或手机号）
    target_ids: List[int]
    account_ids: List[int]
    message_content: str
    link_url: str = ""

class LoginRequest(BaseModel):
    username: str
    password: str

class InviteTaskRequest(BaseModel):
    task_name: str
    target_group_id: int
    source_type: str = "number_pool"
    source_ids: List[int] = []
    account_ids: List[int] = []
    billing_country: str = ""

class BatchIdsRequest(BaseModel):
    ids: List[int] = []

# ---------- P2 入参 ----------
class AdCopyCreate(BaseModel):
    title: str
    content: str
    language: str = "zh"
    link_url: str = ""
    category: str = ""
    status: str = "active"

class AdCopyUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    language: Optional[str] = None
    link_url: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None

class AdLinkCreate(BaseModel):
    name: str
    original_url: str
    domain: str = ""
    tracking_params: str = ""
    ad_message_id: Optional[int] = None

class AdLinkUpdate(BaseModel):
    name: Optional[str] = None
    original_url: Optional[str] = None
    domain: Optional[str] = None
    tracking_params: Optional[str] = None
    ad_message_id: Optional[int] = None
    status: Optional[str] = None

class RechargeCreate(BaseModel):
    amount: float
    chain: str = ""

class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

class UserCreate(BaseModel):
    username: str
    password: str
    nickname: str = ""
    email: str = ""
    phone: str = ""
    role: str = "operator"
    tenant: str = "default"

class UserUpdate(BaseModel):
    nickname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    tenant: Optional[str] = None
    status: Optional[str] = None
    password: Optional[str] = None

# ---------- FastAPI ----------
app = FastAPI(title="WhatsApp 超链群发系统 MVP")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- 号码导入 ----------
@app.post("/api/v1/numbers/import")
def import_numbers(data: List[NumberImport], db: Session = Depends(get_db)):
    imported, failed = 0, 0
    for item in data:
        if db.query(NumberPool).filter_by(phone_number=item.phone).first():
            failed += 1
            continue
        db.add(NumberPool(
            phone_number=item.phone,
            source_type=normalize_source_type(item.source_type),
            source_channel=item.source_channel,
            number_segment=item.phone[:6],
            region="CN",
            trust_score=random.randint(40, 90)
        ))
        imported += 1
    db.commit()
    return {"code": 0, "data": {"imported": imported, "failed": failed}}

# ---------- 模拟注册 ----------
def simulate_register(number_id: int, db: Session):
    number = db.query(NumberPool).filter_by(id=number_id).first()
    if not number:
        return
    number.status = "registering"
    db.commit()
    time.sleep(2)
    success = random.random() > 0.3
    if success:
        number.status = "success"
        number.register_time = datetime.now()
        account = AccountPool(
            number_id=number.id,
            device_fingerprint=f"fp_{random.randint(100000,999999)}",
            current_ip=f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
            nurture_stage="nurturing",
            health_score=random.randint(80, 100)
        )
        db.add(account)
        db.commit()
        number.account_id = account.id
    else:
        number.status = "failed"
    db.commit()

@app.post("/api/v1/register/batch")
def batch_register(req: RegisterRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    for nid in req.number_ids:
        background.add_task(simulate_register, nid, db)
    return {"code": 0, "data": {"message": "注册任务已提交", "count": len(req.number_ids)}}

# ---------- 查询注册状态 ----------
@app.get("/api/v1/register/status")
def register_status(db: Session = Depends(get_db)):
    numbers = db.query(NumberPool).all()
    return {
        "code": 0,
        "data": {
            "total": len(numbers),
            "success": len([n for n in numbers if n.status == "success"]),
            "failed": len([n for n in numbers if n.status == "failed"]),
            "pending": len([n for n in numbers if n.status == "pending"]),
            "details": [{"id": n.id, "phone": n.phone_number, "status": n.status} for n in numbers]
        }
    }

# ---------- 号码池列表 ----------
@app.get("/api/v1/numbers")
def list_numbers(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db)
):
    q = db.query(NumberPool)
    if status:
        q = q.filter(NumberPool.status == status)
    if source_type:
        q = q.filter(NumberPool.source_type == normalize_source_type(source_type))
    if keyword:
        q = q.filter(NumberPool.phone_number.contains(keyword))
    total = q.count()
    rows = q.order_by(NumberPool.id.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "code": 0,
        "data": {
            "total": total, "page": page, "size": size,
            "list": [{
                "id": n.id, "phone_number": n.phone_number,
                "source_type": n.source_type, "source_channel": n.source_channel,
                "number_segment": n.number_segment, "region": n.region,
                "trust_score": n.trust_score, "status": n.status,
                "register_time": n.register_time, "account_id": n.account_id,
                "created_at": n.created_at,
            } for n in rows],
        },
    }

# ---------- 账号列表 ----------
@app.get("/api/v1/accounts")
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(AccountPool).all()
    return {
        "code": 0,
        "data": [{
            "id": a.id, "number_id": a.number_id,
            "health_score": a.health_score, "status": a.status,
            "nurture_stage": a.nurture_stage, "ip": a.current_ip
        } for a in accounts]
    }

# ---------- 账号详情 ----------
@app.get("/api/v1/accounts/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(AccountPool).filter_by(id=account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    number = db.query(NumberPool).filter_by(id=acc.number_id).first()
    return {
        "code": 0,
        "data": {
            "id": acc.id, "number_id": acc.number_id,
            "phone_number": number.phone_number if number else None,
            "device_fingerprint": acc.device_fingerprint,
            "current_ip": acc.current_ip,
            "nurture_stage": acc.nurture_stage,
            "health_score": acc.health_score,
            "status": acc.status, "created_at": acc.created_at,
        },
    }

# ---------- 暂停账号 ----------
@app.post("/api/v1/accounts/{account_id}/pause")
def pause_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(AccountPool).filter_by(id=account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    acc.status = "paused"
    db.commit()
    return {"code": 0, "message": "paused"}

# ---------- 恢复账号 ----------
@app.post("/api/v1/accounts/{account_id}/resume")
def resume_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(AccountPool).filter_by(id=account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    acc.status = "normal"
    db.commit()
    return {"code": 0, "message": "resumed"}

# ---------- 创建群发任务 ----------
def simulate_mass_send(task_id: int, db: Session):
    task = db.query(MassSendTask).filter_by(id=task_id).first()
    if not task:
        return
    task.status = "running"
    db.commit()
    total = len(task.target_ids.split(","))
    for i in range(total):
        time.sleep(0.5)
        task.sent += 1
        if random.random() > 0.05:
            task.delivered += 1
        if random.random() > 0.4:
            task.read_count += 1
        db.commit()
    task.status = "done"
    db.commit()

@app.post("/api/v1/mass-send/tasks")
def create_mass_send(req: MassSendRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    task = MassSendTask(
        task_name=req.task_name,
        target_type="contact" if req.target_type == "contact" else "group",
        target_ids=",".join(map(str, req.target_ids)),
        account_ids=",".join(map(str, req.account_ids)),
        message_content=req.message_content,
        link_url=req.link_url
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    background.add_task(dispatch_mass_send, task.id, db)
    return {"code": 0, "data": {"task_id": task.id, "status": "pending"}}

# ---------- 群发任务列表 ----------
@app.get("/api/v1/mass-send/tasks")
def list_mass_send(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    q = db.query(MassSendTask)
    if status:
        q = q.filter(MassSendTask.status == status)
    total = q.count()
    rows = q.order_by(MassSendTask.id.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "code": 0,
        "data": {
            "total": total, "page": page, "size": size,
            "list": [{
                "id": t.id, "task_name": t.task_name, "status": t.status,
                "target_type": t.target_type or "group",
                "sent": t.sent, "delivered": t.delivered, "read": t.read_count,
                "created_at": t.created_at,
            } for t in rows],
        },
    }

# ---------- 查询群发任务 ----------
@app.get("/api/v1/mass-send/tasks/{task_id}")
def get_mass_send(task_id: int, db: Session = Depends(get_db)):
    task = db.query(MassSendTask).filter_by(id=task_id).first()
    if not task:
        return {"code": 404, "message": "任务不存在"}
    return {
        "code": 0,
        "data": {
            "task_id": task.id, "status": task.status,
            "target_type": task.target_type or "group",
            "sent": task.sent, "delivered": task.delivered, "read": task.read_count
        }
    }

# ---------- 数据看板 ----------
@app.get("/api/v1/dashboard/today")
def dashboard_today(db: Session = Depends(get_db)):
    tasks = db.query(MassSendTask).all()
    return {
        "code": 0,
        "data": {
            "sent": sum(t.sent for t in tasks),
            "delivered": sum(t.delivered for t in tasks),
            "read": sum(t.read_count for t in tasks)
        }
    }

# ---------- 登录 ----------
@app.post("/api/v1/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    username = (req.username or "").strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="用户名或密码不能为空")

    user = db.query(User).filter_by(username=username).first()
    if user is None:
        if not AUTO_PROVISION_USERS:
            log_operation(db, "login", target=username, result="failed",
                          detail="用户不存在", username=username)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        # 历史行为是任意用户名都能登录，这里保留「首次登录自动开户」
        user = create_user(db, username, req.password, nickname=username,
                           role="agent_admin", tenant="default")
    elif not verify_password(user, req.password):
        log_operation(db, "login", target=username, result="failed",
                      detail="密码错误", username=username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    user.last_login_at = datetime.now()
    user.login_count = (user.login_count or 0) + 1
    db.commit()

    log_operation(db, "login", target=username, result="success", detail="登录成功", user=user)
    return {
        "code": 0,
        "data": {
            "token": issue_token(user),
            "username": user.username,
            "role": user.role,
            "tenant": user.tenant or "default",
        },
    }

# ---------- 资源群列表 ----------
@app.get("/api/v1/groups")
def list_groups(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    q = db.query(ResourceGroup)
    if keyword:
        q = q.filter(ResourceGroup.group_name.contains(keyword))
    if status:
        q = q.filter(ResourceGroup.status == status)
    total = q.count()
    rows = q.order_by(ResourceGroup.marketing_score.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "code": 0,
        "data": {
            "total": total, "page": page, "size": size,
            "list": [{
                "id": g.id, "group_name": g.group_name, "group_jid": g.group_jid,
                "group_link": g.group_link, "can_speak": g.can_speak,
                "can_invite": g.can_invite, "approval_mode": g.approval_mode,
                "group_owner": g.group_owner, "marketing_score": g.marketing_score,
                "status": g.status,
            } for g in rows],
        },
    }

# ---------- 拉群任务 ----------
@app.post("/api/v1/invite/tasks")
def create_invite_task(req: InviteTaskRequest, db: Session = Depends(get_db)):
    task = InviteTask(
        task_name=req.task_name,
        target_group_id=req.target_group_id,
        source_type=req.source_type,
        source_ids=",".join(map(str, req.source_ids)),
        account_ids=",".join(map(str, req.account_ids)),
        billing_country=req.billing_country,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"code": 0, "data": {"task_id": task.id, "status": task.status}}

@app.get("/api/v1/invite/tasks")
def list_invite_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db)
):
    q = db.query(InviteTask)
    total = q.count()
    rows = q.order_by(InviteTask.id.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "code": 0,
        "data": {
            "total": total, "page": page, "size": size,
            "list": [{
                "id": t.id, "task_name": t.task_name,
                "target_group_id": t.target_group_id,
                "status": t.status, "created_at": t.created_at,
            } for t in rows],
        },
    }

# 余额 / 流水 / 系统设置接口见文件末尾的 P2 段落（已由真实数据模型实现）

# ---------- 发送策略检查（参数来自系统设置） ----------
def can_send(account, db: Session):
    # 新设备冷却：小时数可在「系统设置 - 发送策略」中调整
    cooldown_hours = get_setting(db, "new_device_cooldown_hours", 24)
    if account.created_at and (datetime.now() - account.created_at).total_seconds() < cooldown_hours * 3600:
        return False, f"新设备冷却中（{cooldown_hours} 小时）"
    # 健康度过低
    if account.health_score < 60:
        return False, "健康度过低"
    # 每日发送上限
    daily_limit = get_setting(db, "daily_send_limit", 50)
    today_sent = db.query(TaskLog).filter(
        TaskLog.account_id == account.id,
        TaskLog.created_at >= datetime.now().replace(hour=0, minute=0, second=0)
    ).count()
    if today_sent >= daily_limit:
        return False, f"今日发送已达上限（{daily_limit} 条）"
    return True, "OK"

# ---------- 号码批量删除 ----------
@app.delete("/api/v1/numbers")
def delete_numbers(req: BatchIdsRequest, db: Session = Depends(get_db)):
    if not req.ids:
        return {"code": 0, "message": "deleted", "count": 0}
    count = db.query(NumberPool).filter(NumberPool.id.in_(req.ids)).delete(synchronize_session=False)
    db.commit()
    return {"code": 0, "message": "deleted", "count": count}

# ---------- 号码导出 ----------
@app.get("/api/v1/numbers/export")
def export_numbers(db: Session = Depends(get_db)):
    numbers = db.query(NumberPool).order_by(NumberPool.id).all()
    return {
        "code": 0,
        "data": [{
            "id": n.id,
            "phone": n.phone_number,
            "source_type": n.source_type,
            "source_channel": n.source_channel,
            "number_segment": n.number_segment,
            "region": n.region,
            "trust_score": n.trust_score,
            "status": n.status,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        } for n in numbers],
    }

# ---------- 注册失败归因 ----------
@app.get("/api/v1/register/analysis")
def register_analysis(db: Session = Depends(get_db)):
    failed = db.query(NumberPool).filter_by(status="failed").all()
    return {
        "code": 0,
        "data": {
            "total": len(failed),
            "details": [{
                "id": n.id,
                "phone": n.phone_number,
                "source_type": n.source_type,
                "source_channel": n.source_channel,
            } for n in failed],
        },
    }

# ---------- 批量获取群链接 ----------
@app.post("/api/v1/groups/fetch-links")
def fetch_group_links(req: BatchIdsRequest, db: Session = Depends(get_db)):
    # wasock 接入后改为协议真实获取群链接
    return {"code": 0, "data": {"updated": 0, "message": "待 wasock 接入"}}

# ---------- 拉群任务详情 ----------
@app.get("/api/v1/invite/tasks/{task_id}")
def get_invite_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(InviteTask).filter_by(id=task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "code": 0,
        "data": {
            "task_id": task.id,
            "task_name": task.task_name,
            "target_group_id": task.target_group_id,
            "status": task.status,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        },
    }

# ============================================================
# 真实发送（wasock）—— 由 USE_REAL_SEND 开关控制
# ============================================================
# 总开关：保持 False 时群发任务走 simulate_mass_send（模拟发送，不联网）；
#         置为 True 后走 real_mass_send，通过 wasock 调 WhatsApp 协议真实发送。
USE_REAL_SEND = False

WASOCK_AUTH_NAME = "whatsapp_auth"      # 与 connect_whatsapp.py 的登录态目录保持一致
WASOCK_LOGGER_LEVEL = "warn"            # 排查真实发送时可改成 "debug"
SEND_RETRY_TIMES = 1                    # 单条消息失败后的重试次数
SEND_RETRY_WAIT = 2.0                   # 重试前等待秒数
PHONE_PATTERN = re.compile(r"^\d{8,15}$")

try:
    from wasock import WhatsAppSocket, Browser as WasockBrowser
    WASOCK_AVAILABLE = True
    WASOCK_IMPORT_ERROR = ""
except Exception as _wasock_exc:        # 未安装 wasock 时后端仍可正常跑模拟发送
    WhatsAppSocket = None
    WasockBrowser = None
    WASOCK_AVAILABLE = False
    WASOCK_IMPORT_ERROR = f"{type(_wasock_exc).__name__}: {_wasock_exc}"

_wasock_bot = None
_wasock_lock = threading.Lock()


def is_wasock_logged_in(auth_name: str = WASOCK_AUTH_NAME) -> bool:
    """登录态是否可用，判定口径对齐 wasock 自带的 assets/isauthvalid.js。"""
    base = Path(auth_name)
    if not base.is_dir():
        return False
    if len([p for p in base.iterdir() if p.is_file()]) <= 1:
        return False
    creds = base / "creds.json"
    if not creds.is_file():
        return False
    try:
        data = json.loads(creds.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    # Baileys 配对成功后主要看 me.id；registered 在部分版本/流程里可能一直是 false，
    # 只看 registered 会误判成"未登录"，所以两者取或。
    me = data.get("me")
    return bool(data.get("registered") or (isinstance(me, dict) and me.get("id")))


def on_wasock_connection(data):
    """记录 WhatsApp 连接状态，真实发送出问题时便于定位。"""
    data = data or {}
    if data.get("status") == "open":
        print("[wasock] WhatsApp 连接已建立", flush=True)
    else:
        print(f"[wasock] 连接关闭：statusCode={data.get('statusCode')} "
              f"reason={data.get('reason')}", flush=True)


def get_wasock_bot():
    """惰性创建全局 wasock 会话；开关关闭时直接返回 None，不会拉起 Node 服务。

    注意两点：
      1. wasock 的 Node 服务固定监听 127.0.0.1:5000，一个进程只能有一个会话，
         因此这里不做多账号并发（account_ids 目前只取首个账号做策略校验与日志归属）。
      2. 不在应用启动时就连接：避免后端一启动就占用 5000 端口，
         和手动运行的 connect_whatsapp.py 互相抢占。
    """
    global _wasock_bot
    if not USE_REAL_SEND or not WASOCK_AVAILABLE:
        return None
    with _wasock_lock:
        if _wasock_bot is None:
            bot = WhatsAppSocket(
                authName=WASOCK_AUTH_NAME,
                loggerLevel=WASOCK_LOGGER_LEVEL,
                browserInfo=WasockBrowser.ubuntu("Chrome"),
            )
            bot.on("connection", on_wasock_connection)
            # 不能用 bot.start()：它内部会 input() 阻塞线程，服务端没有交互终端
            bot.nodeJS.send({"action": "start"})
            _wasock_bot = bot
        return _wasock_bot


def close_wasock_bot():
    """关闭全局 wasock 会话（测试或需要重新扫码时调用）。"""
    global _wasock_bot
    with _wasock_lock:
        if _wasock_bot is not None:
            try:
                _wasock_bot.end()
            finally:
                _wasock_bot = None


def to_whatsapp_jid(value: str) -> str:
    """把手机号 / 群 JID 规范成 WhatsApp chat id。"""
    value = (value or "").strip()
    if not value:
        return ""
    if "@" in value:                        # 已经是 xxx@s.whatsapp.net / xxx@g.us
        return value
    digits = re.sub(r"\D", "", value)
    return f"{digits}@s.whatsapp.net" if digits else ""


def resolve_send_target(db: Session, target_id: int, target_type: str = "group") -> Dict[str, Any]:
    """把任务里的目标 ID 解析成可发送的 chat。

    必须带上 target_type：resource_group 和 number_pool 的主键各自从 1 开始，
    只按 ID 猜会把消息发到错误的会话，所以这里严格按任务声明的类型解析。
      * group   -> ResourceGroup.group_jid
      * contact -> NumberPool.phone_number，取不到再当作手填手机号
    解析不出来时返回 error，由调用方记为失败，不会静默跳过。
    """
    if target_type == "contact":
        number = db.query(NumberPool).filter_by(id=target_id).first()
        if number:
            chat = to_whatsapp_jid(number.phone_number)
            return {
                "id": target_id, "kind": "number", "name": "",
                "phone": number.phone_number or "", "chat": chat,
                "error": "" if chat else f"号码池 #{target_id} 的号码格式不正确",
            }
        raw = str(target_id).strip()
        if PHONE_PATTERN.match(raw):
            return {"id": target_id, "kind": "phone", "name": "", "phone": raw,
                    "chat": to_whatsapp_jid(raw), "error": ""}
        return {"id": target_id, "kind": "unknown", "name": "", "phone": "", "chat": "",
                "error": f"联系人目标 {target_id} 不存在（既不是号码池 ID，也不是手机号）"}

    group = db.query(ResourceGroup).filter_by(id=target_id).first()
    if group:
        chat = to_whatsapp_jid(group.group_jid or "")
        return {
            "id": target_id, "kind": "group", "name": group.group_name or "",
            "phone": "", "chat": chat,
            "error": "" if chat else f"资源群 #{target_id} 没有可用的 group_jid",
        }
    return {"id": target_id, "kind": "unknown", "name": "", "phone": "", "chat": "",
            "error": f"资源群 {target_id} 不存在"}


def render_mass_message(task: MassSendTask, target: Dict[str, Any]) -> str:
    """渲染文案变量；文案里没写 {link} 时自动把超链接附在结尾。"""
    content = task.message_content or ""
    link = (task.link_url or "").strip()
    text = (content
            .replace("{name}", target.get("name") or target.get("phone") or "朋友")
            .replace("{phone}", target.get("phone") or "")
            .replace("{link}", link))
    if link and "{link}" not in content:
        text = f"{text}\n{link}" if text else link
    return text.strip()


def send_whatsapp_message(bot, chat: str, text: str) -> Tuple[bool, str]:
    """通过 wasock 发一条消息，对应 node/server.js 的 sendMessage action。"""
    if not chat:
        return False, "缺少 chat id"
    if not text:
        return False, "消息内容为空"
    try:
        response = bot.nodeJS.send({"action": "sendMessage", "chat": chat, "msg": text})
    except Exception as exc:
        return False, f"发送异常 {type(exc).__name__}: {exc}"
    if isinstance(response, dict) and response.get("success"):
        return True, ""
    message = response.get("message") if isinstance(response, dict) else response
    return False, str(message or "发送失败（wasock 未返回成功）")


def send_interval_seconds(db: Session) -> float:
    """两条消息之间的随机间隔，取值来自系统设置的 send_interval_min / max。"""
    try:
        low = float(get_setting(db, "send_interval_min", 5) or 5)
        high = float(get_setting(db, "send_interval_max", 30) or 30)
    except (TypeError, ValueError):
        low, high = 5.0, 30.0
    if high < low:
        low, high = high, low
    return random.uniform(low, high)


def record_send_log(db: Session, task: MassSendTask, account_id: int, result: str):
    """写一条任务日志（TaskLog 没有 detail 字段，失败原因打到服务端日志）。"""
    db.add(TaskLog(task_id=task.id, account_id=account_id or 0,
                   action="mass_send", result=result))
    db.commit()


def fail_task(db: Session, task: MassSendTask, reason: str, account_id: int = 0):
    """真实发送的前置条件不满足：标记失败并留下可读原因。"""
    task.status = "failed"
    db.commit()
    record_send_log(db, task, account_id, "failed")
    print(f"[real_mass_send] 任务 #{task.id} 未执行：{reason}", flush=True)


def real_mass_send(task_id: int, db: Session):
    """真实发送：通过 wasock 逐条调用 WhatsApp 协议发送。

    与 simulate_mass_send 的差异：
      * 发送前会做登录态 / wasock 可用性 / 发送策略三道前置校验，不满足就 fail 并说明原因；
      * 每条消息按系统设置里的 send_interval_min/max 随机间隔发送，并写 TaskLog；
      * 文案支持 {name} / {phone} / {link} 变量，未写 {link} 时自动附上超链。
    """
    task = db.query(MassSendTask).filter_by(id=task_id).first()
    if not task:
        return

    account_ids = [int(x) for x in (task.account_ids or "").split(",") if x.strip().isdigit()]
    primary_account_id = account_ids[0] if account_ids else 0

    target_ids = [int(x) for x in (task.target_ids or "").split(",") if x.strip().isdigit()]
    if not target_ids:
        fail_task(db, task, "任务没有可用的目标 ID", primary_account_id)
        return

    if not WASOCK_AVAILABLE:
        fail_task(db, task, f"未安装 wasock（{WASOCK_IMPORT_ERROR}）", primary_account_id)
        return

    if not is_wasock_logged_in():
        fail_task(db, task,
                  f"没有可用的 WhatsApp 登录态（{WASOCK_AUTH_NAME}/creds.json），"
                  f"请先运行 connect_whatsapp.py 扫码登录", primary_account_id)
        return

    # 发送策略校验：新设备冷却 / 健康度 / 每日上限，参数来自系统设置
    account = db.query(AccountPool).filter_by(id=primary_account_id).first() if primary_account_id else None
    if account:
        allowed, reason = can_send(account, db)
        if not allowed:
            fail_task(db, task, f"账号 #{account.id} 不满足发送策略：{reason}", primary_account_id)
            return

    bot = get_wasock_bot()
    if bot is None:
        fail_task(db, task, "wasock 会话初始化失败", primary_account_id)
        return

    task.status = "running"
    db.commit()

    target_type = task.target_type or "group"
    success = 0
    for target_id in target_ids:
        target = resolve_send_target(db, target_id, target_type)
        if target["error"]:
            record_send_log(db, task, primary_account_id, "failed")
            print(f"[real_mass_send] 任务 #{task.id} 跳过目标：{target['error']}", flush=True)
            continue

        text = render_mass_message(task, target)
        ok, detail = False, ""
        for attempt in range(SEND_RETRY_TIMES + 1):
            ok, detail = send_whatsapp_message(bot, target["chat"], text)
            if ok:
                break
            print(f"[real_mass_send] 任务 #{task.id} 第 {attempt + 1} 次发送失败："
                  f"{target['chat']} -> {detail}", flush=True)
            if attempt < SEND_RETRY_TIMES:
                time.sleep(SEND_RETRY_WAIT)

        task.sent += 1
        if ok:
            success += 1
            task.delivered += 1
        record_send_log(db, task, primary_account_id, "success" if ok else "failed")
        db.commit()

        time.sleep(send_interval_seconds(db))

    task.status = "done" if success else "failed"
    db.commit()
    print(f"[real_mass_send] 任务 #{task.id} 结束：成功 {success} / 共 {len(target_ids)} 个目标，"
          f"状态 {task.status}", flush=True)


def dispatch_mass_send(task_id: int, db: Session):
    """群发入口：按 USE_REAL_SEND 决定走真实发送还是模拟发送（当前默认模拟）。"""
    if USE_REAL_SEND:
        real_mass_send(task_id, db)
    else:
        simulate_mass_send(task_id, db)

# ============================================================
# P2 —— 广告消息 / 余额计费 / 个人中心 / 系统设置
# ============================================================

# ---------- 统一错误结构 ----------
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """把 HTTPException 也包装成 { code, message }，前端拦截器可直接提示。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.detail},
    )

# ---------- 登录态 / 当前用户 ----------
TOKEN_STORE: Dict[str, Dict[str, Any]] = {}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{2,64}$")


def bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def issue_token(user: User) -> str:
    token = f"{user.id}.{secrets.token_urlsafe(24)}"
    TOKEN_STORE[token] = {
        "user_id": user.id,
        "username": user.username,
        "issued_at": datetime.now(),
        "expire_at": datetime.now() + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return token


def revoke_user_tokens(user_id: int):
    for token, info in list(TOKEN_STORE.items()):
        if info.get("user_id") == user_id:
            TOKEN_STORE.pop(token, None)


def get_or_create_user(db: Session, username: str) -> Optional[User]:
    username = (username or "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        return None
    user = db.query(User).filter_by(username=username).first()
    if user is None and AUTO_PROVISION_USERS:
        user = create_user(db, username, secrets.token_urlsafe(12), nickname=username,
                           role="agent_admin", tenant="default")
    return user


def resolve_token(db: Session, token: str) -> Optional[User]:
    if not token:
        return None
    info = TOKEN_STORE.get(token)
    if info:
        if info.get("expire_at") and info["expire_at"] < datetime.now():
            TOKEN_STORE.pop(token, None)
            return None
        return db.query(User).filter_by(id=info["user_id"]).first()
    # 兼容改造前的 mock-token-<username>，避免已有登录态直接失效
    if token.startswith("mock-token-"):
        return get_or_create_user(db, token[len("mock-token-"):])
    return None


def current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    user = resolve_token(db, bearer_token(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录状态已失效，请重新登录")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role not in ("super_admin", "agent_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def log_operation(db: Session, action: str, target: str = "", result: str = "success",
                  detail: str = "", user: Optional[User] = None,
                  username: str = "", user_id: Optional[int] = None):
    try:
        db.add(OperationLog(
            user_id=user.id if user else user_id,
            username=((user.username if user else username) or "")[:64],
            action=action, target=(target or "")[:255],
            result=result, detail=(detail or "")[:500],
        ))
        db.commit()
    except Exception:
        db.rollback()


def user_dict(user: User) -> Dict[str, Any]:
    return {
        "id": user.id, "username": user.username, "nickname": user.nickname or "",
        "email": user.email or "", "phone": user.phone or "", "role": user.role,
        "tenant": user.tenant or "default", "status": user.status,
        "last_login_at": _dt(user.last_login_at), "login_count": user.login_count or 0,
        "created_at": _dt(user.created_at), "updated_at": _dt(user.updated_at),
    }


def log_dict(row: OperationLog) -> Dict[str, Any]:
    return {
        "id": row.id, "action": row.action, "target": row.target or "",
        "result": row.result, "detail": row.detail or "", "created_at": _dt(row.created_at),
    }


# ============================================================
# 1. 广告消息：文案 CRUD + 超链管理 + 效果统计
# ============================================================
VARIABLE_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
AD_STATUSES = ("active", "paused", "draft")
AD_LANGUAGES = ("zh", "en", "es", "pt")


def extract_variables(content: str) -> str:
    """从文案中提取 {name} {link} 形式的变量（去重、保序）。"""
    seen: List[str] = []
    for name in VARIABLE_PATTERN.findall(content or ""):
        if name not in seen:
            seen.append(name)
    return ",".join(seen)


def ad_copy_dict(row: AdMessage) -> Dict[str, Any]:
    return {
        "id": row.id, "title": row.title or "", "content": row.content or "",
        "language": row.language or "zh", "link_url": row.link_url or "",
        "variables": [v for v in (row.variables or "").split(",") if v],
        "category": row.category or "", "status": row.status or "draft",
        "sent": row.sent or 0, "delivered": row.delivered or 0,
        "read": row.read_count or 0, "click": row.click_count or 0,
        "delivery_rate": _rate(row.delivered, row.sent),
        "read_rate": _rate(row.read_count, row.delivered),
        "click_rate": _rate(row.click_count, row.read_count),
        "created_at": _dt(row.created_at), "updated_at": _dt(row.updated_at),
    }


def get_ad_copy_or_404(db: Session, copy_id: int) -> AdMessage:
    row = db.query(AdMessage).filter_by(id=copy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="文案不存在")
    return row


@app.get("/api/v1/ads/copies")
def list_ad_copies(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    language: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = db.query(AdMessage)
    if language:
        q = q.filter(AdMessage.language == language)
    if status:
        q = q.filter(AdMessage.status == status)
    if keyword:
        q = q.filter(AdMessage.title.contains(keyword) | AdMessage.content.contains(keyword))
    total = q.count()
    rows = q.order_by(AdMessage.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"code": 0, "data": {"total": total, "page": page, "size": size,
                                "list": [ad_copy_dict(r) for r in rows]}}


@app.post("/api/v1/ads/copies")
def create_ad_copy(req: AdCopyCreate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    title = (req.title or "").strip()
    content = (req.content or "").strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="文案标题与内容不能为空")
    status = req.status if req.status in AD_STATUSES else "active"
    row = AdMessage(
        title=title, content=content,
        language=(req.language or "zh").strip() or "zh",
        link_url=(req.link_url or "").strip(),
        variables=extract_variables(content),
        category=(req.category or "").strip(), status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_operation(db, "create_ad_copy", target=row.title, detail=f"新建文案 #{row.id}", user=user)
    return {"code": 0, "data": ad_copy_dict(row)}


@app.get("/api/v1/ads/copies/{copy_id}")
def get_ad_copy(copy_id: int, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    return {"code": 0, "data": ad_copy_dict(get_ad_copy_or_404(db, copy_id))}


@app.put("/api/v1/ads/copies/{copy_id}")
def update_ad_copy(copy_id: int, req: AdCopyUpdate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    row = get_ad_copy_or_404(db, copy_id)
    if req.title is not None:
        if not req.title.strip():
            raise HTTPException(status_code=400, detail="文案标题不能为空")
        row.title = req.title.strip()
    if req.content is not None:
        if not req.content.strip():
            raise HTTPException(status_code=400, detail="文案内容不能为空")
        row.content = req.content.strip()
        row.variables = extract_variables(row.content)
    if req.language is not None:
        row.language = req.language.strip() or row.language
    if req.link_url is not None:
        row.link_url = req.link_url.strip()
    if req.category is not None:
        row.category = req.category.strip()
    if req.status is not None:
        if req.status not in AD_STATUSES:
            raise HTTPException(status_code=400, detail=f"状态只能是 {'/'.join(AD_STATUSES)}")
        row.status = req.status
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    log_operation(db, "update_ad_copy", target=row.title, detail=f"更新文案 #{row.id}", user=user)
    return {"code": 0, "data": ad_copy_dict(row)}


@app.delete("/api/v1/ads/copies/{copy_id}")
def delete_ad_copy(copy_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    row = get_ad_copy_or_404(db, copy_id)
    title = row.title or f"#{copy_id}"     # 删除后实例已失效，先取出用于日志
    db.delete(row)
    db.commit()
    log_operation(db, "delete_ad_copy", target=title, detail=f"删除文案 #{copy_id}", user=user)
    return {"code": 0, "data": {"deleted": 1}}


@app.delete("/api/v1/ads/copies")
def delete_ad_copies(req: BatchIdsRequest, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    if not req.ids:
        return {"code": 0, "data": {"deleted": 0}}
    count = db.query(AdMessage).filter(AdMessage.id.in_(req.ids)).delete(synchronize_session=False)
    db.commit()
    log_operation(db, "delete_ad_copy", target=f"{count} 条", detail="批量删除文案", user=user)
    return {"code": 0, "data": {"deleted": count}}


@app.get("/api/v1/ads/copies/{copy_id}/stats")
def ad_copy_stats(copy_id: int, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    row = get_ad_copy_or_404(db, copy_id)
    data = ad_copy_dict(row)
    return {"code": 0, "data": {
        "id": data["id"], "title": data["title"], "language": data["language"],
        "status": data["status"], "sent": data["sent"], "delivered": data["delivered"],
        "read": data["read"], "click": data["click"],
        "delivery_rate": data["delivery_rate"], "read_rate": data["read_rate"],
        "click_rate": data["click_rate"],
    }}


@app.get("/api/v1/ads/stats")
def ad_stats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(AdMessage).order_by(AdMessage.click_count.desc(), AdMessage.id.desc()).all()
    sent = sum(r.sent or 0 for r in rows)
    delivered = sum(r.delivered or 0 for r in rows)
    read = sum(r.read_count or 0 for r in rows)
    click = sum(r.click_count or 0 for r in rows)
    return {"code": 0, "data": {
        "totals": {
            "copies": len(rows), "sent": sent, "delivered": delivered,
            "read": read, "click": click,
            "delivery_rate": _rate(delivered, sent),
            "read_rate": _rate(read, delivered),
            "click_rate": _rate(click, read),
        },
        "list": [{
            "id": r.id, "title": r.title or "", "language": r.language or "zh",
            "status": r.status or "draft", "sent": r.sent or 0,
            "delivered": r.delivered or 0, "read": r.read_count or 0,
            "click": r.click_count or 0,
            "delivery_rate": _rate(r.delivered, r.sent),
            "read_rate": _rate(r.read_count, r.delivered),
            "click_rate": _rate(r.click_count, r.read_count),
        } for r in rows],
    }}


# ---------- 超链管理 ----------
def generate_short_code(db: Session, length: int = 7) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not db.query(AdLink).filter_by(short_code=code).first():
            return code


def build_short_url(db: Session, link: AdLink) -> str:
    domain = (link.domain or "").strip() or str(get_setting(db, "short_link_domain", "go.wa-link.com"))
    domain = domain.replace("https://", "").replace("http://", "").strip("/")
    return f"https://{domain}/{link.short_code}"


def link_dict(db: Session, link: AdLink) -> Dict[str, Any]:
    target = link.original_url or ""
    if link.tracking_params:
        target = f"{target}{'&' if '?' in target else '?'}{link.tracking_params}"
    return {
        "id": link.id, "name": link.name or "", "original_url": link.original_url or "",
        "short_code": link.short_code, "short_url": build_short_url(db, link),
        "domain": link.domain or "", "tracking_params": link.tracking_params or "",
        "target_url": target, "ad_message_id": link.ad_message_id,
        "click_count": link.click_count or 0, "status": link.status or "active",
        "created_at": _dt(link.created_at), "updated_at": _dt(link.updated_at),
    }


def get_ad_link_or_404(db: Session, link_id: int) -> AdLink:
    row = db.query(AdLink).filter_by(id=link_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="超链不存在")
    return row


@app.get("/api/v1/ads/links")
def list_ad_links(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = db.query(AdLink)
    if status:
        q = q.filter(AdLink.status == status)
    if keyword:
        q = q.filter(AdLink.name.contains(keyword) | AdLink.original_url.contains(keyword)
                    | AdLink.short_code.contains(keyword))
    total = q.count()
    rows = q.order_by(AdLink.id.desc()).offset((page - 1) * size).limit(size).all()
    default_domain = str(get_setting(db, "short_link_domain", "go.wa-link.com"))
    return {"code": 0, "data": {"total": total, "page": page, "size": size,
                                "default_domain": default_domain,
                                "list": [link_dict(db, r) for r in rows]}}


@app.post("/api/v1/ads/links")
def create_ad_link(req: AdLinkCreate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    name = (req.name or "").strip()
    original_url = (req.original_url or "").strip()
    if not name or not original_url:
        raise HTTPException(status_code=400, detail="超链名称与原始链接不能为空")
    if not original_url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="原始链接需以 http:// 或 https:// 开头")
    if req.ad_message_id is not None and not db.query(AdMessage).filter_by(id=req.ad_message_id).first():
        raise HTTPException(status_code=400, detail="关联的文案不存在")
    row = AdLink(
        name=name, original_url=original_url,
        short_code=generate_short_code(db),
        domain=(req.domain or "").strip(),
        tracking_params=(req.tracking_params or "").strip(),
        ad_message_id=req.ad_message_id, status="active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_operation(db, "create_ad_link", target=row.name, detail=f"生成短链 {row.short_code}", user=user)
    return {"code": 0, "data": link_dict(db, row)}


@app.put("/api/v1/ads/links/{link_id}")
def update_ad_link(link_id: int, req: AdLinkUpdate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    row = get_ad_link_or_404(db, link_id)
    if req.name is not None:
        if not req.name.strip():
            raise HTTPException(status_code=400, detail="超链名称不能为空")
        row.name = req.name.strip()
    if req.original_url is not None:
        url = req.original_url.strip()
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="原始链接需以 http:// 或 https:// 开头")
        row.original_url = url
    if req.domain is not None:
        row.domain = req.domain.strip()
    if req.tracking_params is not None:
        row.tracking_params = req.tracking_params.strip()
    if req.ad_message_id is not None:
        row.ad_message_id = req.ad_message_id or None
    if req.status is not None:
        row.status = req.status
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    log_operation(db, "update_ad_link", target=row.name, detail=f"更新超链 #{row.id}", user=user)
    return {"code": 0, "data": link_dict(db, row)}


@app.delete("/api/v1/ads/links/{link_id}")
def delete_ad_link(link_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    row = get_ad_link_or_404(db, link_id)
    name = row.name or f"#{link_id}"       # 删除后实例已失效，先取出用于日志
    db.delete(row)
    db.commit()
    log_operation(db, "delete_ad_link", target=name, detail=f"删除超链 #{link_id}", user=user)
    return {"code": 0, "data": {"deleted": 1}}


@app.get("/s/{short_code}")
def redirect_short_link(short_code: str, db: Session = Depends(get_db)):
    """短链跳转（本地演示用，顺带累计点击量）。"""
    link = db.query(AdLink).filter_by(short_code=short_code).first()
    if not link or link.status != "active":
        raise HTTPException(status_code=404, detail="短链不存在或已停用")
    link.click_count = (link.click_count or 0) + 1
    db.commit()
    params = (link.tracking_params or "").replace("{click_id}", secrets.token_hex(8))
    target = link.original_url or ""
    if params:
        target = f"{target}{'&' if '?' in target else '?'}{params}"
    return RedirectResponse(url=target, status_code=302)


# ============================================================
# 2. 余额与计费：流水账本 + 充值订单
# ============================================================
# 计费规则目前为内置默认值，后续可迁移到独立表由后台维护
BILLING_RULES: List[Dict[str, Any]] = [
    {"country": "CN", "country_name": "中国", "dimension": "按成功发送条数", "unit_price": 0.006},
    {"country": "US", "country_name": "美国", "dimension": "按成功发送条数", "unit_price": 0.012},
    {"country": "GB", "country_name": "英国", "dimension": "按成功发送条数", "unit_price": 0.012},
    {"country": "BR", "country_name": "巴西", "dimension": "按成功发送条数", "unit_price": 0.009},
    {"country": "ID", "country_name": "印尼", "dimension": "按成功发送条数", "unit_price": 0.008},
    {"country": "IN", "country_name": "印度", "dimension": "按成功发送条数", "unit_price": 0.007},
    {"country": "MX", "country_name": "墨西哥", "dimension": "按成功发送条数", "unit_price": 0.010},
    {"country": "RU", "country_name": "俄罗斯", "dimension": "按成功发送条数", "unit_price": 0.011},
]
TRANSACTION_TYPES = ("recharge", "consume", "refund", "adjust")


def current_balance(db: Session) -> Decimal:
    """余额 = 全部流水之和，账本即余额。"""
    total = db.query(func.coalesce(func.sum(BalanceTransaction.amount), 0)).scalar()
    return _dec(total)


def add_transaction(db: Session, tx_type: str, amount: Any, *, country: str = "",
                    task: str = "", task_type: str = "", task_id: Optional[int] = None,
                    result: str = "success", remark: str = "") -> BalanceTransaction:
    before = current_balance(db)
    delta = _dec(amount)
    row = BalanceTransaction(
        type=tx_type, amount=delta, balance_before=before, balance_after=before + delta,
        currency=str(get_setting(db, "currency", "USDT")), country=country or "",
        task=task or "", task_type=task_type or "", task_id=task_id,
        result=result, remark=remark or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def transaction_dict(row: BalanceTransaction) -> Dict[str, Any]:
    return {
        "id": row.id, "type": row.type, "amount": _money(row.amount),
        "balance_before": _money(row.balance_before), "balance_after": _money(row.balance_after),
        "currency": row.currency, "country": row.country or "", "task": row.task or "",
        "task_type": row.task_type or "", "task_id": row.task_id, "result": row.result,
        "remark": row.remark or "", "created_at": _dt(row.created_at),
    }


def order_dict(order: RechargeOrder) -> Dict[str, Any]:
    return {
        "id": order.id, "order_no": order.order_no, "amount": _money(order.amount),
        "currency": order.currency, "chain": order.chain, "address": order.address,
        "tx_hash": order.tx_hash or "", "status": order.status, "user_id": order.user_id,
        "paid_at": _dt(order.paid_at), "expire_at": _dt(order.expire_at),
        "created_at": _dt(order.created_at),
    }


def expire_pending_orders(db: Session) -> int:
    """惰性清理：把超时未到账的订单标记为已过期。"""
    stale = db.query(RechargeOrder).filter(
        RechargeOrder.status == "pending",
        RechargeOrder.expire_at.isnot(None),
        RechargeOrder.expire_at < datetime.now(),
    ).all()
    for order in stale:
        order.status = "expired"
    if stale:
        db.commit()
    return len(stale)


def get_order_or_404(db: Session, order_id: int) -> RechargeOrder:
    order = db.query(RechargeOrder).filter_by(id=order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="充值订单不存在")
    return order


@app.get("/api/v1/balance")
def get_balance(db: Session = Depends(get_db), user: User = Depends(current_user)):
    recharge_total = db.query(func.coalesce(func.sum(BalanceTransaction.amount), 0)).filter(
        BalanceTransaction.type == "recharge").scalar()
    consume_total = db.query(func.coalesce(func.sum(BalanceTransaction.amount), 0)).filter(
        BalanceTransaction.type == "consume").scalar()
    return {"code": 0, "data": {
        "balance": _money(current_balance(db)),
        "currency": str(get_setting(db, "currency", "USDT")),
        "total_recharge": _money(recharge_total),
        "total_consume": abs(_money(consume_total)),
        "pending_orders": db.query(RechargeOrder).filter_by(status="pending").count(),
        "updated_at": _dt(datetime.now()),
    }}


@app.get("/api/v1/balance/transactions")
def list_balance_transactions(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    type: Optional[str] = None,
    country: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = db.query(BalanceTransaction)
    if type:
        q = q.filter(BalanceTransaction.type == type)
    if country:
        q = q.filter(BalanceTransaction.country == country)
    if keyword:
        q = q.filter(BalanceTransaction.task.contains(keyword)
                    | BalanceTransaction.remark.contains(keyword))
    total = q.count()
    rows = q.order_by(BalanceTransaction.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"code": 0, "data": {"total": total, "page": page, "size": size,
                                "list": [transaction_dict(r) for r in rows]}}


@app.post("/api/v1/balance/transactions")
def create_balance_transaction(payload: Dict[str, Any], db: Session = Depends(get_db),
                               user: User = Depends(require_admin)):
    """手工入账 / 扣费（管理员调账）。"""
    tx_type = str(payload.get("type") or "adjust")
    if tx_type not in TRANSACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"流水类型只能是 {'/'.join(TRANSACTION_TYPES)}")
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="金额必须是数字")
    if amount == 0:
        raise HTTPException(status_code=400, detail="金额不能为 0")
    if tx_type == "consume" and amount > 0:
        amount = -amount
    row = add_transaction(
        db, tx_type, amount,
        country=str(payload.get("country") or ""),
        task=str(payload.get("task") or ""),
        remark=str(payload.get("remark") or "管理员手工调账"),
    )
    log_operation(db, "create_transaction", target=row.remark,
                  detail=f"手工调账 {_money(row.amount)}", user=user)
    return {"code": 0, "data": transaction_dict(row)}


@app.post("/api/v1/balance/recharge")
def create_recharge(req: RechargeCreate, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    try:
        amount = _money(req.amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="充值金额必须是数字")
    min_amount = float(get_setting(db, "min_recharge_amount", 10))
    if amount < min_amount:
        raise HTTPException(status_code=400, detail=f"单笔充值不能低于 {min_amount}")
    if amount > 1000000:
        raise HTTPException(status_code=400, detail="单笔充值金额过大")
    address = str(get_setting(db, "recharge_address", "") or "").strip()
    if not address:
        raise HTTPException(status_code=400,
                            detail="尚未配置收款地址，请先在「系统设置 - 计费与充值」中填写")
    expire_minutes = int(get_setting(db, "recharge_expire_minutes", 30))
    order = RechargeOrder(
        order_no=f"RC{datetime.now():%Y%m%d%H%M%S}{secrets.randbelow(10000):04d}",
        amount=_dec(amount),
        currency=str(get_setting(db, "currency", "USDT")),
        chain=(req.chain or str(get_setting(db, "recharge_chain", "TRC20"))).strip(),
        address=address, status="pending", user_id=user.id,
        expire_at=datetime.now() + timedelta(minutes=expire_minutes),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    log_operation(db, "create_recharge", target=order.order_no,
                  detail=f"创建充值订单 {order.amount} {order.currency}", user=user)
    return {"code": 0, "data": order_dict(order)}


@app.get("/api/v1/balance/recharge/orders")
def list_recharge_orders(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    expire_pending_orders(db)
    q = db.query(RechargeOrder)
    if status:
        q = q.filter(RechargeOrder.status == status)
    total = q.count()
    rows = q.order_by(RechargeOrder.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"code": 0, "data": {
        "total": total, "page": page, "size": size,
        "list": [order_dict(r) for r in rows],
        "address": str(get_setting(db, "recharge_address", "") or ""),
        "chain": str(get_setting(db, "recharge_chain", "TRC20")),
        "currency": str(get_setting(db, "currency", "USDT")),
        "min_amount": float(get_setting(db, "min_recharge_amount", 10)),
    }}


@app.post("/api/v1/balance/recharge/{order_id}/confirm")
def confirm_recharge(order_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_admin)):
    """模拟到账确认（链上回调接入前的过渡实现）。"""
    order = get_order_or_404(db, order_id)
    if order.status == "paid":
        raise HTTPException(status_code=400, detail="订单已到账，请勿重复确认")
    if order.status != "pending":
        raise HTTPException(status_code=400, detail=f"订单状态为 {order.status}，无法确认到账")
    if order.expire_at and order.expire_at < datetime.now():
        order.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="订单已过期，请重新创建充值订单")
    order.status = "paid"
    order.paid_at = datetime.now()
    order.tx_hash = order.tx_hash or f"mock-{secrets.token_hex(16)}"
    db.commit()
    tx = add_transaction(db, "recharge", order.amount,
                         remark=f"充值订单 {order.order_no} 到账")
    log_operation(db, "confirm_recharge", target=order.order_no,
                  detail=f"确认到账 {order.amount} {order.currency}", user=user)
    return {"code": 0, "data": {
        "order": order_dict(order), "transaction": transaction_dict(tx),
        "balance": _money(current_balance(db)),
    }}


@app.post("/api/v1/balance/recharge/{order_id}/cancel")
def cancel_recharge(order_id: int, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    order = get_order_or_404(db, order_id)
    if order.status != "pending":
        raise HTTPException(status_code=400, detail=f"订单状态为 {order.status}，无法取消")
    order.status = "cancelled"
    db.commit()
    log_operation(db, "cancel_recharge", target=order.order_no, detail="取消充值订单", user=user)
    return {"code": 0, "data": order_dict(order)}


@app.get("/api/v1/balance/rules")
def list_billing_rules(db: Session = Depends(get_db), user: User = Depends(current_user)):
    currency = str(get_setting(db, "currency", "USDT"))
    return {"code": 0, "data": [{**rule, "currency": currency} for rule in BILLING_RULES]}


# ============================================================
# 3. 个人中心：账号信息 / 修改密码 / 操作日志
# ============================================================
@app.post("/api/v1/auth/logout")
def logout(authorization: Optional[str] = Header(None), user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    token = bearer_token(authorization)
    if token:
        TOKEN_STORE.pop(token, None)
    log_operation(db, "logout", target=user.username, detail="退出登录", user=user)
    return {"code": 0, "data": {"message": "已退出登录"}}


@app.get("/api/v1/me")
def get_me(user: User = Depends(current_user)):
    return {"code": 0, "data": user_dict(user)}


@app.put("/api/v1/me")
def update_me(req: ProfileUpdate, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    if req.nickname is not None:
        user.nickname = req.nickname.strip()[:64]
    if req.email is not None:
        email = req.email.strip()
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HTTPException(status_code=400, detail="邮箱格式不正确")
        user.email = email[:128]
    if req.phone is not None:
        user.phone = req.phone.strip()[:32]
    user.updated_at = datetime.now()
    db.commit()
    db.refresh(user)
    log_operation(db, "update_profile", target=user.username, detail="更新个人资料", user=user)
    return {"code": 0, "data": user_dict(user)}


@app.post("/api/v1/me/password")
def change_password(req: PasswordChange, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    if not verify_password(user, req.old_password or ""):
        log_operation(db, "update_password", target=user.username, result="failed",
                      detail="当前密码错误", user=user)
        raise HTTPException(status_code=400, detail="当前密码不正确")
    new_password = req.new_password or ""
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度至少 6 位")
    if new_password == req.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    set_password(user, new_password)
    user.updated_at = datetime.now()
    db.commit()
    revoke_user_tokens(user.id)     # 改密后所有登录态失效，需要重新登录
    log_operation(db, "update_password", target=user.username, detail="修改密码成功",
                  user_id=user.id, username=user.username)
    return {"code": 0, "data": {"message": "密码已更新，请使用新密码重新登录"}}


@app.get("/api/v1/me/logs")
def list_my_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    action: Optional[str] = None,
    result: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = db.query(OperationLog).filter(
        or_(OperationLog.user_id == user.id, OperationLog.username == user.username))
    if action:
        q = q.filter(OperationLog.action == action)
    if result:
        q = q.filter(OperationLog.result == result)
    total = q.count()
    rows = q.order_by(OperationLog.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"code": 0, "data": {"total": total, "page": page, "size": size,
                                "list": [log_dict(r) for r in rows]}}


# ---------- 用户管理（管理员） ----------
USER_ROLES = ("super_admin", "agent_admin", "operator")


@app.get("/api/v1/admin/users")
def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    q = db.query(User)
    if keyword:
        q = q.filter(User.username.contains(keyword) | User.nickname.contains(keyword))
    if role:
        q = q.filter(User.role == role)
    if status:
        q = q.filter(User.status == status)
    total = q.count()
    rows = q.order_by(User.id.asc()).offset((page - 1) * size).limit(size).all()
    return {"code": 0, "data": {"total": total, "page": page, "size": size,
                                "list": [user_dict(r) for r in rows]}}


@app.post("/api/v1/admin/users")
def create_user_api(req: UserCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    username = (req.username or "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=400, detail="用户名需为 2-64 位字母、数字、下划线、点、@ 或短横线")
    if len(req.password or "") < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")
    if db.query(User).filter_by(username=username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    role = req.role if req.role in USER_ROLES else "operator"
    row = create_user(db, username, req.password, nickname=(req.nickname or username).strip(),
                      email=(req.email or "").strip(), phone=(req.phone or "").strip(),
                      role=role, tenant=(req.tenant or "default").strip() or "default")
    log_operation(db, "create_user", target=row.username, detail=f"新建用户（{role}）", user=user)
    return {"code": 0, "data": user_dict(row)}


@app.put("/api/v1/admin/users/{user_id}")
def update_user_api(user_id: int, req: UserUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    row = db.query(User).filter_by(id=user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.role is not None:
        if req.role not in USER_ROLES:
            raise HTTPException(status_code=400, detail=f"角色只能是 {'/'.join(USER_ROLES)}")
        if row.id == user.id and req.role != row.role:
            raise HTTPException(status_code=400, detail="不能修改自己的角色")
        row.role = req.role
    if req.status is not None:
        if req.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="状态只能是 active / disabled")
        if row.id == user.id and req.status != "active":
            raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
        row.status = req.status
    if req.nickname is not None:
        row.nickname = req.nickname.strip()[:64]
    if req.email is not None:
        row.email = req.email.strip()[:128]
    if req.phone is not None:
        row.phone = req.phone.strip()[:32]
    if req.tenant is not None:
        row.tenant = req.tenant.strip()[:64] or "default"
    if req.password:
        if len(req.password) < 6:
            raise HTTPException(status_code=400, detail="密码长度至少 6 位")
        set_password(row, req.password)
        revoke_user_tokens(row.id)
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    log_operation(db, "update_user", target=row.username, detail="更新用户信息", user=user)
    return {"code": 0, "data": user_dict(row)}


@app.delete("/api/v1/admin/users/{user_id}")
def delete_user_api(user_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    row = db.query(User).filter_by(id=user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    if row.id == user.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    if row.username == DEFAULT_ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="内置管理员账号不可删除")
    username = row.username                 # 删除后实例已失效，先取出用于日志
    db.delete(row)
    db.commit()
    revoke_user_tokens(user_id)
    log_operation(db, "delete_user", target=username, detail="删除用户", user=user)
    return {"code": 0, "data": {"deleted": 1}}


# ============================================================
# 4. 系统设置：读取 / 保存全局参数
# ============================================================
def setting_schema(db: Session) -> List[Dict[str, Any]]:
    items = []
    for key, definition in SETTING_DEFS.items():
        items.append({
            "key": key, "label": definition["label"],
            "description": definition.get("description", ""),
            "type": definition["type"], "category": definition["category"],
            "min": definition.get("min"), "max": definition.get("max"),
            "max_len": definition.get("max_len"),
            "default": definition["default"],
            "value": get_setting(db, key),
            "updated_at": _dt(row.updated_at) if (row := db.query(Setting).filter_by(key=key).first()) else None,
        })
    return items


@app.get("/api/v1/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """扁平结构，保持历史返回契约。"""
    return {"code": 0, "data": settings_snapshot(db)}


@app.get("/api/v1/settings/schema")
def get_settings_schema(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"code": 0, "data": setting_schema(db)}


@app.put("/api/v1/settings")
def update_settings(payload: Dict[str, Any], db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    if not payload:
        raise HTTPException(status_code=400, detail="没有需要保存的参数")
    unknown = [key for key in payload if key not in SETTING_DEFS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知参数：{', '.join(unknown)}")

    prepared: Dict[str, str] = {}
    for key, value in payload.items():
        stored, error = validate_setting(key, value)
        if error:
            raise HTTPException(status_code=400, detail=error)
        prepared[key] = stored

    # 跨字段校验：发送间隔下限不能大于上限
    merged = settings_snapshot(db)
    merged.update({k: _coerce_setting(v, SETTING_DEFS[k]["type"]) for k, v in prepared.items()})
    if merged["send_interval_min"] > merged["send_interval_max"]:
        raise HTTPException(status_code=400, detail="发送间隔下限不能大于上限")

    for key, stored in prepared.items():
        upsert_setting(db, key, stored)
    db.commit()
    log_operation(db, "update_settings", target=", ".join(prepared.keys()),
                  detail=f"更新 {len(prepared)} 项全局参数", user=user)
    return {"code": 0, "data": settings_snapshot(db)}