from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, Query, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean, DECIMAL, Numeric, Text, func, or_,
    inspect, text, UniqueConstraint, case,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from tenancy import TenantOwned, TenantSession, bind_tenant, tenant_query, migrate_tenants
from sqlalchemy import ForeignKey
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import hashlib, hmac, json, os, random, re, secrets, socket, time

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

import service_config
service_config.load()

# ---------- 数据库 ----------
# 默认库固定放在项目目录下（锚定 main.py），而不是跟着启动时的 cwd 走；
# 否则从别的目录启动 uvicorn 会静默连到另一个空库。
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_URL = f"sqlite:///{(BASE_DIR / 'whatsapp.db').as_posix()}"
DATABASE_URL = os.environ.get("WHATSAPP_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, class_=TenantSession, info={"tenant_id": None})

def system_session():
    """Explicit privileged session for migrations and scheduler discovery only."""
    return SessionLocal(info={"system_scope": True})
Base = declarative_base()

# ---------- 模型 ----------
class Tenant(Base):
    __tablename__ = "tenant"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    status = Column(String(20), default="active", nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class NumberPool(TenantOwned, Base):
    __tablename__ = "number_pool"
    __table_args__ = (UniqueConstraint('tenant_id', 'phone_number', name='uq_number_pool_tenant_phone'),)
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), index=True)
    source_type = Column(String(20))
    source_channel = Column(String(50))
    number_segment = Column(String(20))
    region = Column(String(50))
    trust_score = Column(Integer, default=50)
    status = Column(String(20), default="pending")
    proxy_ip = Column(String(255), default="")
    failure_reason = Column(Text, default="")
    register_time = Column(DateTime, nullable=True)
    account_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

class AccountPool(TenantOwned, Base):
    __tablename__ = "account_pool"
    id = Column(Integer, primary_key=True, index=True)
    number_id = Column(Integer, index=True)
    group_id = Column(Integer, nullable=True, index=True)
    account_type = Column(String(20), default='personal')
    device_type = Column(String(20), default='linked')
    notes = Column(String(500), default='')
    device_fingerprint = Column(String(255))
    current_ip = Column(String(45))
    nurture_stage = Column(String(20), default="none")
    health_score = Column(Integer, default=100)
    status = Column(String(20), default="normal")
    nurture_started_at = Column(DateTime, nullable=True)
    session_enabled = Column(Boolean, default=True)
    full_params_ready = Column(Boolean, default=False)
    converted_at = Column(DateTime, nullable=True)
    session_name = Column(String(64), default="")   # 该账号用的 WhatsApp 登录态目录
    created_at = Column(DateTime, default=datetime.now)

class MassSendTask(TenantOwned, Base):
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
    accepted = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    last_error = Column(Text, default="")
    mode = Column(String(20), default="")
    scheduled_at = Column(DateTime, nullable=True)
    billing_country = Column(String(10), default="")
    ad_message_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

class WhatsAppLinkSession(TenantOwned, Base):
    __tablename__ = 'whatsapp_link_session'
    id = Column(Integer, primary_key=True)
    auth_name = Column(String(255), unique=True, index=True)
    owner_user_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.now)

class ResourceGroup(TenantOwned, Base):
    __tablename__ = "resource_group"
    __table_args__ = (UniqueConstraint('tenant_id', 'group_jid', name='uq_resource_group_tenant_jid'),)
    id = Column(Integer, primary_key=True, index=True)
    group_name = Column(String(255))
    source_channel = Column(String(255), default="")
    group_jid = Column(String(255))
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

class InviteTask(TenantOwned, Base):
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
    processed = Column(Integer, default=0)
    succeeded = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    last_error = Column(Text, default="")
    mode = Column(String(20), default="")
    scheduled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

class TaskLog(TenantOwned, Base):
    __tablename__ = "task_log"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer)
    account_id = Column(Integer)
    task_kind = Column(String(20), default="mass-send", index=True)
    target = Column(String(255), default="")
    detail = Column(Text, default="")
    action = Column(String(50))
    result = Column(String(20))
    created_at = Column(DateTime, default=datetime.now)

class TaskExecution(TenantOwned, Base):
    """每个目标一条持久化执行记录；成功目标不因重试再次执行。"""
    __tablename__ = "task_execution"
    __table_args__ = (UniqueConstraint("task_kind", "task_id", "target_id"),)
    id = Column(Integer, primary_key=True)
    task_kind = Column(String(20), index=True)
    task_id = Column(Integer, index=True)
    target_id = Column(String(64))
    target = Column(String(255), default="")
    account_id = Column(Integer, default=0)
    status = Column(String(20), default="pending")
    attempts = Column(Integer, default=0)
    error = Column(Text, default="")
    message_id = Column(String(255), default="", index=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    charged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class ReceiptEvent(TenantOwned, Base):
    __tablename__ = "receipt_event"
    __table_args__ = (UniqueConstraint("message_id", "target"),)
    id = Column(Integer, primary_key=True)
    message_id = Column(String(255))
    target = Column(String(255))
    status = Column(String(20))
    received_at = Column(DateTime, default=datetime.now)

# ---------- P2 模型：广告消息 ----------
class AdMessage(TenantOwned, Base):
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

class AdLink(TenantOwned, Base):
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
class BalanceTransaction(TenantOwned, Base):
    """租户流水账本。余额 = 当前租户流水 amount 之和。"""
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

class RechargeOrder(TenantOwned, Base):
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
    tenant = Column(String(64), default="default")  # compatibility display name
    tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=False, index=True)
    whatsapp_session_name = Column(String(255), default="")
    status = Column(String(20), default="active")         # active / disabled
    last_login_at = Column(DateTime, nullable=True)
    login_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class OperationLog(TenantOwned, Base):
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

# ---------- 集成相关模型：代理池 / 接码订单 / 采购订单 ----------
class ProxyPool(TenantOwned, Base):
    """代理 IP 池。来源可以是供应商同步（Byteful/Ping Proxies）或手工导入。"""
    __tablename__ = "proxy_pool"
    id = Column(Integer, primary_key=True, index=True)
    host = Column(String(128))
    port = Column(Integer, default=0)
    username = Column(String(128), default="")
    password = Column(String(128), default="")
    protocol = Column(String(16), default="http")        # http / socks5
    country = Column(String(32), default="")
    asn = Column(String(128), default="")
    provider = Column(String(32), default="")            # mock / byteful / static
    status = Column(String(16), default="free", index=True)   # free / in_use / disabled
    bound_number_id = Column(Integer, nullable=True, index=True)
    used_count = Column(Integer, default=0)
    ok_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    last_check_ok = Column(Boolean, nullable=True)
    is_default = Column(Boolean, default=False)
    group_id = Column(Integer, nullable=True, index=True)
    proxy_type = Column(String(20), default='static')
    latency_ms = Column(Integer, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    @property
    def address(self) -> str:
        """完整代理地址；number_pool.proxy_ip 存的就是这个字符串。"""
        if self.username:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"


class SmsOrder(TenantOwned, Base):
    """接码平台的取号订单。"""
    __tablename__ = "sms_order"
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(32), default="")            # virtualsms / smsactivate / mock
    remote_order_id = Column(String(128), default="", index=True)
    phone = Column(String(32), default="")
    phone_digits = Column(String(32), default="")
    service = Column(String(32), default="wa")
    country = Column(String(32), default="")
    status = Column(String(20), default="waiting", index=True)   # waiting/completed/cancelled/expired
    price = Column(Numeric(18, 6), nullable=True)
    code = Column(String(32), default="")
    text = Column(Text, default="")
    number_id = Column(Integer, nullable=True, index=True)       # 关联 number_pool.id
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PurchaseOrder(TenantOwned, Base):
    """账号采购订单（对接账号星球这类成品号供应商）。"""
    __tablename__ = "purchase_order"
    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(64), default="", index=True)
    provider = Column(String(32), default="")            # mock / http
    product_id = Column(String(64), default="")
    product_name = Column(String(255), default="")
    quantity = Column(Integer, default=1)
    unit_price = Column(Numeric(18, 6), default=0)
    amount = Column(Numeric(18, 6), default=0)
    currency = Column(String(10), default="USDT")
    status = Column(String(20), default="pending", index=True)   # pending/paid/delivered/failed/cancelled
    accounts = Column(Text, default="")                  # 交付的账号，逗号分隔
    message = Column(String(500), default="")
    remark = Column(String(500), default="")
    created_by = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------- 全局参数定义（默认值 / 类型 / 取值范围 / 分组） ----------
SETTING_DEFS: Dict[str, Dict[str, Any]] = {
    "billing_enabled": {
        "default": False, "type": "bool", "category": "billing",
        "label": "任务自动计费", "description": "仅对真实任务成功执行计费；启用后群发任务必须填写计费国家",
    },
    "invite_unit_price": {
        "default": 0, "type": "float", "category": "billing", "min": 0, "max": 10000,
        "label": "拉群成功单价", "description": "每成功添加一人费用；0 表示免费，模拟任务不扣费",
    },
    "payment_min_confirmations": {
        "default": 20, "type": "int", "category": "billing", "min": 1, "max": 1000,
        "label": "到账最少确认数", "description": "来自受信任到账核验服务的链上确认数门槛",
    },
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
AUTO_PROVISION_USERS = os.environ.get("AUTO_PROVISION_USERS", "false").strip().lower() == "true"
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
    name = (fields.get("tenant") or "default").strip()
    tenant = db.query(Tenant).filter_by(name=name).first()
    if tenant is None:
        tenant = Tenant(name=name)
        db.add(tenant); db.flush()
    fields.update(tenant=name, tenant_id=tenant.id)
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
    db = SessionLocal(info={"tenant_id": 1})
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
    "mass_send_task": {
        "target_type": "VARCHAR(20) DEFAULT 'group'", "accepted": "INTEGER DEFAULT 0",
        "failed": "INTEGER DEFAULT 0", "last_error": "TEXT DEFAULT ''", "mode": "VARCHAR(20) DEFAULT ''",
        "scheduled_at": "DATETIME", "billing_country": "VARCHAR(10) DEFAULT ''", "ad_message_id": "INTEGER",
    },
    "invite_task": {
        "processed": "INTEGER DEFAULT 0", "succeeded": "INTEGER DEFAULT 0", "failed": "INTEGER DEFAULT 0",
        "last_error": "TEXT DEFAULT ''", "mode": "VARCHAR(20) DEFAULT ''", "scheduled_at": "DATETIME",
    },
    "sys_user": {"whatsapp_session_name": "VARCHAR(255) DEFAULT ''"},
    "resource_group": {"source_channel": "VARCHAR(255) DEFAULT ''"},
    "proxy_pool": {"last_check_ok": "BOOLEAN", "is_default": "BOOLEAN DEFAULT 0", "group_id": "INTEGER", "proxy_type": "VARCHAR(20) DEFAULT 'static'"},
    "task_log": {"task_kind": "VARCHAR(20) DEFAULT 'mass-send'", "target": "VARCHAR(255) DEFAULT ''", "detail": "TEXT DEFAULT ''"},
    # 注册时自动分配的代理，存完整代理地址（http://user:pass@host:port）
    "number_pool": {"proxy_ip": "VARCHAR(255)", "failure_reason": "TEXT DEFAULT ''"},
    # 该账号用的是哪个 WhatsApp 登录态目录（支持多账号）
    "account_pool": {"session_name": "VARCHAR(64) DEFAULT ''", "session_enabled": "BOOLEAN DEFAULT 1", "full_params_ready": "BOOLEAN DEFAULT 0", "converted_at": "DATETIME", "nurture_started_at": "DATETIME", "group_id": "INTEGER", "account_type": "VARCHAR(20) DEFAULT 'personal'", "device_type": "VARCHAR(20) DEFAULT 'linked'", "notes": "VARCHAR(500) DEFAULT ''"},
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
                    if engine.dialect.name == 'postgresql':
                        ddl = ddl.replace('BOOLEAN DEFAULT 0', 'BOOLEAN DEFAULT FALSE').replace('BOOLEAN DEFAULT 1', 'BOOLEAN DEFAULT TRUE').replace('DATETIME', 'TIMESTAMP WITHOUT TIME ZONE')
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
migrate_tenants(engine, Base.metadata)
seed_defaults()

# ---------- Pydantic ----------
class NumberImport(BaseModel):
    phone: str
    source_type: str
    source_channel: str = ""
    region: str = ""

class RegisterRequest(BaseModel):
    number_ids: List[int]

class MassSendRequest(BaseModel):
    task_name: str
    target_type: str = "group"      # group=资源群 / contact=联系人（号码池 ID 或手机号）
    target_ids: List[int]
    account_ids: List[int]
    message_content: str
    link_url: str = ""
    scheduled_at: Optional[datetime] = None
    billing_country: str = ""
    ad_message_id: Optional[int] = None

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
    scheduled_at: Optional[datetime] = None

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
    tenant: str = Field(default="default", max_length=64)
    tenant_id: Optional[int] = Field(default=None, ge=1)

class UserUpdate(BaseModel):
    nickname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    tenant: Optional[str] = Field(default=None, max_length=64)
    tenant_id: Optional[int] = Field(default=None, ge=1)
    status: Optional[str] = None
    password: Optional[str] = None

# ---------- FastAPI ----------
app = FastAPI(title="WhatsApp 超链群发系统 MVP", debug=False)
ALLOWED_ORIGINS = [origin.strip() for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",") if origin.strip()]
if '*' in ALLOWED_ORIGINS:
    raise RuntimeError('ALLOWED_ORIGINS 必须填写明确域名，不能使用通配符')
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                   allow_credentials=False, allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
                   allow_headers=['Authorization', 'Content-Type', 'X-Tenant'])

def get_db():
    db = SessionLocal(info={"tenant_id": None})
    try:
        yield db
    finally:
        db.close()

def require_login(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    return current_user(authorization, db)


def api_access_guard(request: Request, authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    # Provider callbacks verify their own shared secret/HMAC instead of browser sessions.
    public = {
        ('POST', '/api/v1/auth/login'),
        ('POST', '/api/v1/providers/receipts'),
        ('POST', '/api/v1/balance/payment-webhook'),
    }
    if request.url.path.startswith('/api/v1/') and (request.method, request.url.path) not in public:
        return current_user(authorization, db)


app.router.dependencies.append(Depends(api_access_guard))

# ---------- 号码导入 ----------
@app.post("/api/v1/numbers/import", dependencies=[Depends(require_login)])
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
            region=item.region,
            trust_score=0
        ))
        imported += 1
    db.commit()
    return {"code": 0, "data": {"imported": imported, "failed": failed}}

# ---------- 模拟注册 ----------
def simulate_register(number_id: int, db: Session):
    number = db.query(NumberPool).filter_by(id=number_id).first()
    if not number:
        return
    # 注册前自动分配代理 IP（池子空时会尝试从供应商同步一次）
    proxy = allocate_proxy(db, number, country=number.region or "")
    if proxy is None and PROXY_REQUIRED:
        number.status = "failed"
        number.failure_reason = "没有可用代理"
        db.commit()
        print(f"[register] 号码 #{number.id} 失败：没有可用代理（PROXY_REQUIRED=true）", flush=True)
        return
    number.status = "registering"
    db.commit()
    time.sleep(2)
    if os.environ.get("REGISTER_MODE", "mock") != "mock":
        number.status = "failed"
        number.failure_reason = "未配置真实注册通道；请使用扫码关联已有账号"
        db.commit()
        return
    success = random.random() > 0.3
    if success:
        number.status = "success"
        number.failure_reason = ""
        number.register_time = datetime.now()
        account = AccountPool(
            number_id=number.id,
            device_fingerprint=f"fp_{random.randint(100000,999999)}",
            current_ip=f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
            nurture_stage="nurturing", nurture_started_at=datetime.now(),
            health_score=random.randint(80, 100)
        )
        db.add(account)
        db.commit()
        number.account_id = account.id
    else:
        number.status = "failed"
        number.failure_reason = "模拟注册失败（非真实注册结果）"
    db.commit()

@app.post("/api/v1/register/batch", dependencies=[Depends(require_login)])
def batch_register(req: RegisterRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    for nid in req.number_ids:
        background.add_task(simulate_register, nid, db)
    return {"code": 0, "data": {"message": "注册任务已提交", "count": len(req.number_ids)}}

# ---------- 查询注册状态 ----------
@app.get("/api/v1/register/status", dependencies=[Depends(require_login)])
def register_status(db: Session = Depends(get_db)):
    numbers = db.query(NumberPool).all()
    return {
        "code": 0,
        "data": {
            "mode": os.environ.get("REGISTER_MODE", "mock"),
            "total": len(numbers),
            "success": len([n for n in numbers if n.status == "success"]),
            "failed": len([n for n in numbers if n.status == "failed"]),
            "pending": len([n for n in numbers if n.status == "pending"]),
            "details": [{"id": n.id, "phone": n.phone_number, "status": n.status} for n in numbers]
        }
    }

# ---------- 号码池列表 ----------
@app.get("/api/v1/numbers", dependencies=[Depends(require_login)])
def list_numbers(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    access_status: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from resource_api import access_rows
    access = {r["id"]: r for r in access_rows(db)}
    q = db.query(NumberPool)
    if access_status:
        q = q.filter(NumberPool.id.in_([nid for nid, row in access.items() if row["status"] == access_status]))
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
                "created_at": n.created_at, "access_status": access[n.id]["status"], "linked": access[n.id]["linked"],
            } for n in rows],
        },
    }

# ---------- 账号列表 ----------
@app.get("/api/v1/accounts", dependencies=[Depends(require_login)])
def list_accounts(db: Session = Depends(get_db)):
    from account_management_api import account_rows
    return {"code": 0, "data": account_rows(db)}

# ---------- 账号详情 ----------
@app.get("/api/v1/accounts/{account_id}", dependencies=[Depends(require_login)])
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
            "full_params_ready": bool(acc.full_params_ready),
            "nurture_stage": acc.nurture_stage,
            "health_score": acc.health_score,
            "status": acc.status, "created_at": acc.created_at,
        },
    }

# ---------- 暂停账号 ----------
@app.post("/api/v1/accounts/{account_id}/pause", dependencies=[Depends(require_login)])
def pause_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(AccountPool).filter_by(id=account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    acc.status = "paused"
    db.commit()
    return {"code": 0, "message": "paused"}

# ---------- 恢复账号 ----------
@app.post("/api/v1/accounts/{account_id}/resume", dependencies=[Depends(require_login)])
def resume_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(AccountPool).filter_by(id=account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    acc.status = "normal"
    db.commit()
    return {"code": 0, "message": "resumed"}

# ---------- 创建群发任务 ----------
def simulate_mass_send(task_id: int, db: Session):
    from operations import run_task
    run_task("mass-send", task_id, mode="mock")

@app.post("/api/v1/mass-send/tasks", dependencies=[Depends(require_login)])
def create_mass_send(req: MassSendRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    from operations import create_task
    return create_task("mass-send", req, background, db)

# ---------- 群发任务列表 ----------
@app.get("/api/v1/mass-send/tasks", dependencies=[Depends(require_login)])
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
@app.get("/api/v1/mass-send/tasks/{task_id}", dependencies=[Depends(require_login)])
def get_mass_send(task_id: int, db: Session = Depends(get_db)):
    from operations import task_detail
    return {"code": 0, "data": task_detail("mass-send", task_id, db)}

# ---------- 登录 ----------
@app.post("/api/v1/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    username = (req.username or "").strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="用户名或密码不能为空")
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user = db.query(User).filter_by(username=username).first()
    if user is None:
        if not AUTO_PROVISION_USERS:
            log_operation(db, "login", target=username, result="failed",
                          detail="用户不存在", username=username)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        # Only explicitly enabled development provisioning may create an account.
        user = create_user(db, username, req.password, nickname=username,
                           role="agent_admin", tenant="default")
    elif not verify_password(user, req.password):
        log_operation(db, "login", target=username, result="failed",
                      detail="密码错误", username=username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    tenant = db.get(Tenant, user.tenant_id)
    if not tenant or tenant.status != "active":
        raise HTTPException(403, "租户不可用")
    bind_tenant(db, user.tenant_id)
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
            "tenant": user.tenant or "default", "tenant_id": user.tenant_id,
        },
    }

# ---------- 资源群列表 ----------
@app.get("/api/v1/groups", dependencies=[Depends(require_login)])
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
                "status": g.status, "source_channel": g.source_channel, "owner_account_id": g.owner_account_id,
            } for g in rows],
        },
    }

# ---------- 拉群任务 ----------
@app.post("/api/v1/invite/tasks", dependencies=[Depends(require_login)])
def create_invite_task(req: InviteTaskRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    from operations import create_task
    return create_task("pull-group", req, background, db)

@app.get("/api/v1/invite/tasks", dependencies=[Depends(require_login)])
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
@app.delete("/api/v1/numbers", dependencies=[Depends(require_login)])
def delete_numbers(req: BatchIdsRequest, db: Session = Depends(get_db)):
    if not req.ids:
        return {"code": 0, "message": "deleted", "count": 0}
    count = db.query(NumberPool).filter(NumberPool.id.in_(req.ids)).delete(synchronize_session=False)
    db.commit()
    return {"code": 0, "message": "deleted", "count": count}

# ---------- 号码导出 ----------
@app.get("/api/v1/numbers/export", dependencies=[Depends(require_login)])
def export_numbers(db: Session = Depends(get_db)):
    from resource_api import access_rows
    access = {r["id"]: r for r in access_rows(db)}
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
            "status": n.status, "access_status": access[n.id]["status"], "linked": access[n.id]["linked"],
            "created_at": n.created_at.isoformat() if n.created_at else None,
        } for n in numbers],
    }

# ---------- 注册失败归因 ----------
@app.get("/api/v1/register/analysis", dependencies=[Depends(require_login)])
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
                "source_channel": n.source_channel, "reason": n.failure_reason or "历史记录未保存失败原因",
            } for n in failed],
        },
    }

# ---------- 批量获取群链接 ----------
@app.post("/api/v1/groups/fetch-links", dependencies=[Depends(require_login)])
def fetch_group_links(req: BatchIdsRequest, db: Session = Depends(get_db)):
    from operations import fetch_links
    return fetch_links(req.ids, db)

# ---------- 拉群任务详情 ----------
@app.get("/api/v1/invite/tasks/{task_id}", dependencies=[Depends(require_login)])
def get_invite_task(task_id: int, db: Session = Depends(get_db)):
    from operations import task_detail
    return {"code": 0, "data": task_detail("pull-group", task_id, db)}

# ============================================================
# 真实发送（wasock）—— 由 USE_REAL_SEND 开关控制
# ============================================================
# 总开关：默认关闭，群发任务走 simulate_mass_send（模拟发送，不联网）。
# 打开方式（必须在启动后端之前设好环境变量）：
#     $env:USE_REAL_SEND="true"; python -m uvicorn main:app --reload
# 启动时的快照，仅用于日志展示；真正判断走 real_send_enabled()（运行时读，改完不用重启）
USE_REAL_SEND = os.environ.get("USE_REAL_SEND", "false").strip().lower() == "true"


def _env_file_value(name: str) -> str:
    """从项目目录下的 .env 取一个值。每次调用重新读盘，改完不用重启后端。"""
    try:
        text = (BASE_DIR / ".env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if key == name:
            return value.strip().strip('"').strip("'")
    return ""


def real_send_enabled() -> bool:
    """真实发送总开关：环境变量优先，其次项目目录下的 .env。

    默认 false —— 账号养好之前必须保持关闭，不然群发会真的把消息发出去。
    运行时读取，所以改完 .env 不用重启后端，下一个任务就生效。
    """
    value = os.environ.get("USE_REAL_SEND")
    if value in (None, ""):
        value = _env_file_value("USE_REAL_SEND")
    return str(value or "").strip().lower() == "true"

# wasock 的会话由 connect_whatsapp.py 负责建立并保持运行，后端只往它的 Node 服务发指令。
# 这里不 import wasock：后端不需要、也不应该去拉起第二个 Node 进程抢 5000 端口。
WASOCK_HOST = os.environ.get("WASOCK_HOST", "127.0.0.1")
WASOCK_PORT = int(os.environ.get("WASOCK_PORT", "5000"))
WASOCK_AUTH_NAME = "whatsapp_auth"      # 与 connect_whatsapp.py 的登录态目录保持一致
WASOCK_TIMEOUT = 10.0                   # 普通指令超时
WASOCK_SEND_TIMEOUT = 60.0              # 发消息超时（群发/大群可能较慢）
SEND_RETRY_TIMES = 1                    # 单条消息失败后的重试次数
SEND_RETRY_WAIT = 2.0                   # 重试前等待秒数
PHONE_PATTERN = re.compile(r"^\d{8,15}$")


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


def wasock_is_running(timeout: float = 2.0) -> bool:
    """探测 wasock 的 Node 服务是否在监听（连接是否健康）。"""
    try:
        with socket.create_connection((WASOCK_HOST, WASOCK_PORT), timeout):
            return True
    except OSError:
        return False


def wasock_request(payload: Dict[str, Any], timeout: float = WASOCK_TIMEOUT) -> Dict[str, Any]:
    """向 wasock 的 Node 服务发一条 JSON 行指令并读取响应。

    协议见 wasock 的 node/server.js：TCP + 换行分隔的 JSON。
      请求  {"action": "sendMessage", "chat": "<jid>", "msg": "<文本>"}
      响应  {"type": "response", "success": true, "message": ""}

    注意：登录二维码等事件（type=event）只会推给当初发起 start 的那个连接，
    本连接正常只会收到自己的响应；这里仍做防御性跳过，避免把事件误当响应，
    同时按行读取，兼容响应被拆包或与事件粘在一起的情况。
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    with socket.create_connection((WASOCK_HOST, WASOCK_PORT), timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(data)
        buffer = b""
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" not in buffer:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("wasock 服务关闭了连接")
                buffer += chunk
                if len(buffer) > 1 << 20:
                    raise ValueError("wasock 响应过大")
            line, buffer = buffer.split(b"\n", 1)
            text = line.decode("utf-8", "ignore").strip()
            if not text:
                continue
            message = json.loads(text)
            if isinstance(message, dict) and ("success" in message or message.get("type") == "response"):
                return message
            if time.monotonic() > deadline:
                raise TimeoutError("等待 wasock 响应超时")


def send_via_wasock(chat_jid: str, message: str) -> Tuple[bool, str]:
    """通过已在运行的 wasock 服务发一条消息，返回 (是否成功, 失败原因)。

    比用户的原始版本多返回一个失败原因：任务日志和排查都需要它。
    """
    if not chat_jid:
        return False, "缺少 chat id"
    if not message:
        return False, "消息内容为空"
    try:
        response = wasock_request(
            {"action": "sendMessage", "chat": chat_jid, "msg": message},
            timeout=WASOCK_SEND_TIMEOUT,
        )
    except TimeoutError:
        return False, f"等待 wasock 响应超时（{WASOCK_HOST}:{WASOCK_PORT}）"
    except OSError as exc:
        return False, f"连接 wasock 服务失败（{WASOCK_HOST}:{WASOCK_PORT}）：{exc}"
    except ValueError as exc:
        return False, f"wasock 响应无法解析：{exc}"
    if response.get("success"):
        return True, ""
    return False, str(response.get("message") or "发送失败（wasock 未返回成功）")


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
    from operations import run_task
    run_task("mass-send", task_id, mode="real")


def dispatch_mass_send(task_id: int, db: Session):
    if real_send_enabled():
        real_mass_send(task_id, db)
    else:
        simulate_mass_send(task_id, db)


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
        "tenant_id": user.tenant_id,
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
        user = db.query(User).filter_by(id=info["user_id"]).first()
        if user and user.tenant_id == info.get("tenant_id"):
            return user
        TOKEN_STORE.pop(token, None)
        return None
    return None


def current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    user = resolve_token(db, bearer_token(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录状态已失效，请重新登录")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant or tenant.status != "active":
        raise HTTPException(403, "租户不可用")
    bind_tenant(db, user.tenant_id)
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role not in ("super_admin", "agent_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_platform_admin(user: User = Depends(current_user)) -> User:
    if user.role != 'super_admin':
        raise HTTPException(403, '需要平台管理员权限')
    return user


def log_operation(db: Session, action: str, target: str = "", result: str = "success",
                  detail: str = "", user: Optional[User] = None,
                  username: str = "", user_id: Optional[int] = None):
    try:
        if user is not None:
            bind_tenant(db, user.tenant_id)
        elif not db.info.get("tenant_id"):
            bind_tenant(db, 1)
        db.add(OperationLog(
            tenant_id=user.tenant_id if user else (db.info.get("tenant_id") or 1),
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
        "tenant": user.tenant or "default", "tenant_id": user.tenant_id, "status": user.status,
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
    with system_session() as lookup:
        owner = lookup.query(AdLink.tenant_id).filter_by(short_code=short_code).scalar()
    if owner is None:
        raise HTTPException(404, '短链不存在或已停用')
    bind_tenant(db, owner)
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
    """Mandatory session criteria restrict this aggregate to the bound tenant."""
    total = db.query(func.coalesce(func.sum(BalanceTransaction.amount), 0)).scalar()
    return _dec(total)


def add_transaction(db: Session, tx_type: str, amount: Any, *, country: str = "",
                    task: str = "", task_type: str = "", task_id: Optional[int] = None,
                    result: str = "success", remark: str = "") -> BalanceTransaction:
    with operations._channel_lock:
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
                               user: User = Depends(require_platform_admin)):
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
                     user: User = Depends(require_platform_admin)):
    """管理员人工审核确认；与签名回调共用原子入账流程。"""
    from finance_api import credit_order
    with operations._channel_lock:
        return credit_order(order_id, db, user=user)


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
    if user.role != 'super_admin':
        q = q.filter(User.tenant_id == user.tenant_id, User.role == 'operator')
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
    if req.tenant_id is not None:
        tenant = db.get(Tenant, req.tenant_id)
        if not tenant or tenant.status != 'active':
            raise HTTPException(422, '租户不存在或已停用')
        req.tenant = tenant.name
    username = (req.username or "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=400, detail="用户名需为 2-64 位字母、数字、下划线、点、@ 或短横线")
    if len(req.password or "") < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")
    if db.query(User).filter_by(username=username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    role = req.role if req.role in USER_ROLES else "operator"
    if user.role != 'super_admin' and (role != 'operator' or (req.tenant or 'default').strip() != user.tenant):
        raise HTTPException(status_code=403, detail="只能创建本租户的运营用户")
    row = create_user(db, username, req.password, nickname=(req.nickname or username).strip(),
                      email=(req.email or "").strip(), phone=(req.phone or "").strip(),
                      role=role, tenant=(req.tenant or "default").strip() or "default")
    log_operation(db, "create_user", target=row.username, detail=f"新建用户（{role}）", user=user)
    return {"code": 0, "data": user_dict(row)}


@app.put("/api/v1/admin/users/{user_id}")
def update_user_api(user_id: int, req: UserUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    if req.tenant_id is not None:
        tenant = db.get(Tenant, req.tenant_id)
        if not tenant or tenant.status != 'active':
            raise HTTPException(422, '租户不存在或已停用')
        req.tenant = tenant.name
    row = db.query(User).filter_by(id=user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role != 'super_admin' and (row.role != 'operator' or row.tenant_id != user.tenant_id
                                      or req.role not in (None, 'operator')
                                      or req.tenant not in (None, user.tenant)):
        raise HTTPException(status_code=403, detail="只能管理本租户的运营用户")
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
        name = req.tenant.strip()[:64] or "default"
        tenant = db.query(Tenant).filter_by(name=name).first()
        if tenant is None:
            tenant = Tenant(name=name); db.add(tenant); db.flush()
        if row.tenant_id != tenant.id:
            revoke_user_tokens(row.id)
            row.whatsapp_session_name = ""
        row.tenant, row.tenant_id = name, tenant.id
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
    if user.role != 'super_admin' and (row.role != 'operator' or row.tenant_id != user.tenant_id):
        raise HTTPException(status_code=403, detail="只能管理本租户的运营用户")
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
                    user: User = Depends(require_platform_admin)):
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


# ============================================================
# 第三方资源对接：代理 IP / 接码平台 / 发消息通道 / 账号采购
# ============================================================
try:
    from providers import (ProviderError, get_sms_provider, get_proxy_provider,
                           get_account_provider, build_message_provider,
                           parse_proxy_line, test_proxy as test_proxy_conn)
    PROVIDERS_AVAILABLE = True
    PROVIDERS_IMPORT_ERROR = ""
except Exception as _providers_exc:          # providers 包缺失时其余功能照常可用
    ProviderError = Exception
    PROVIDERS_AVAILABLE = False
    PROVIDERS_IMPORT_ERROR = f"{type(_providers_exc).__name__}: {_providers_exc}"

# 没有可用代理时是否要中断注册（默认否：尽力而为，缺代理只记日志）
try:
    from whatsapp_session import (get_session, is_node_running, read_paired_phone,
                                   next_auth_name, list_auth_dirs, remove_auth_dir,
                                   DEFAULT_AUTH_NAME)
    WHATSAPP_SESSION_AVAILABLE = True
except Exception as _session_exc:              # 缺 wasock 时其余功能照常
    WHATSAPP_SESSION_AVAILABLE = False
    WHATSAPP_SESSION_ERROR = f"{type(_session_exc).__name__}: {_session_exc}"

PROXY_REQUIRED = os.environ.get("PROXY_REQUIRED", "false").strip().lower() == "true"
# 发消息通道：wasock（默认）/ wsapi / mock
MESSAGE_PROVIDER = os.environ.get("MESSAGE_PROVIDER", "wasock").strip().lower()
_message_provider = None


def _require_providers():
    if not PROVIDERS_AVAILABLE:
        raise HTTPException(status_code=503, detail=f"providers 包不可用：{PROVIDERS_IMPORT_ERROR}")


# ---------------------------------------------------------------- 代理 IP
def proxy_dict(row: ProxyPool) -> Dict[str, Any]:
    return {
        "id": row.id, "host": row.host, "port": row.port,
        "protocol": row.protocol, "username": row.username,
        "address": f"{row.protocol}://{row.host}:{row.port}", "country": row.country or "", "asn": row.asn or "",
        "is_default": bool(row.is_default),
        "group_id": row.group_id, "proxy_type": row.proxy_type or 'static',
        "provider": row.provider or "", "status": row.status,
        "bound_number_id": row.bound_number_id, "used_count": row.used_count or 0,
        "ok_count": row.ok_count or 0, "fail_count": row.fail_count or 0,
        "latency_ms": row.latency_ms, "last_checked_at": _dt(row.last_checked_at),
        "last_used_at": _dt(row.last_used_at), "created_at": _dt(row.created_at),
    }


def sync_proxy_pool(db: Session, *, limit: int = 50, country: str = "") -> Dict[str, Any]:
    """从代理供应商拉取代理写入代理池，按 host:port 去重。"""
    _require_providers()
    provider = get_proxy_provider()
    items = provider.list_proxies(limit=limit, country=country)
    added = updated = 0
    for info in items:
        row = db.query(ProxyPool).filter_by(host=info.host, port=info.port).first()
        if row is None:
            row = ProxyPool(host=info.host, port=info.port, status="free")
            db.add(row)
            added += 1
        else:
            updated += 1
        row.username = info.username or ""
        row.password = info.password or ""
        row.protocol = info.protocol or "http"
        row.country = country or info.country or row.country or ""
        row.asn = info.asn or ""
        row.provider = provider.name
    db.commit()
    return {"provider": provider.name, "fetched": len(items), "added": added, "updated": updated}


def allocate_proxy(db: Session, number: Optional[NumberPool] = None, *,
                   country: str = "", auto_sync: bool = True) -> Optional[ProxyPool]:
    """给号码分配一个空闲代理；池子空时先从供应商同步一次。

    分配成功会同时把完整代理地址写进 number_pool.proxy_ip。
    """
    def pick() -> Optional[ProxyPool]:
        query = db.query(ProxyPool).filter(ProxyPool.status == "free")
        if country:
            query = query.filter(or_(ProxyPool.country == country, ProxyPool.country == ""))
        return query.order_by(ProxyPool.id).first()

    proxy = pick()
    if proxy is None and auto_sync:
        try:
            sync_proxy_pool(db)
        except Exception as exc:
            print(f"[proxy] 同步代理池失败：{exc}", flush=True)
        proxy = pick()
    if proxy is None:
        return None

    proxy.status = "in_use"
    proxy.bound_number_id = number.id if number else None
    proxy.used_count = (proxy.used_count or 0) + 1
    proxy.last_used_at = datetime.now()
    if number is not None:
        number.proxy_ip = proxy.address
    db.commit()
    return proxy


def release_proxy(db: Session, number_id: int) -> int:
    """释放某个号码占用的代理。"""
    rows = db.query(ProxyPool).filter_by(bound_number_id=number_id).all()
    for row in rows:
        row.status = "free"
        row.bound_number_id = None
    if rows:
        db.commit()
    return len(rows)


def check_proxy(db: Session, row: ProxyPool, *, target: str = "web.whatsapp.com",
                port: int = 443) -> Dict[str, Any]:
    """实测代理连通性并累计成功率（只看端口开着不算，要真正建立隧道）。"""
    _require_providers()
    info = parse_proxy_line(f"{row.protocol}://{row.username}:{row.password}@{row.host}:{row.port}")
    ok, detail = test_proxy_conn(info, target=(target, port)) if info else (False, "代理配置无法解析")
    row.last_checked_at = datetime.now()
    row.last_check_ok = ok
    if ok:
        row.ok_count = (row.ok_count or 0) + 1
        try:
            row.latency_ms = int(float(detail.replace("s", "")) * 1000)
        except ValueError:
            row.latency_ms = None
    else:
        row.fail_count = (row.fail_count or 0) + 1
        row.status = "disabled" if (row.fail_count or 0) >= 3 else row.status
    db.commit()
    return {"ok": ok, "detail": detail, "proxy": proxy_dict(row)}


# ---------------------------------------------------------------- 接码平台
def sms_order_dict(row: SmsOrder) -> Dict[str, Any]:
    return {
        "id": row.id, "provider": row.provider, "order_id": row.remote_order_id,
        "phone": row.phone, "phone_digits": row.phone_digits, "service": row.service,
        "country": row.country, "status": row.status,
        "price": _money(row.price) if row.price is not None else None,
        "code": row.code or "", "text": row.text or "", "number_id": row.number_id,
        "expires_at": _dt(row.expires_at), "created_at": _dt(row.created_at),
        "updated_at": _dt(row.updated_at),
    }


def apply_sms_order(db: Session, row: SmsOrder, order) -> SmsOrder:
    """把供应商返回的订单状态写回本地。"""
    if order.phone:
        row.phone = order.phone
        row.phone_digits = order.phone_digits
    row.status = order.status or row.status
    if order.price is not None:
        row.price = _dec(order.price)
    if order.expires_at:
        try:
            row.expires_at = datetime.fromisoformat(str(order.expires_at).replace("Z", "+00:00"))
            if row.expires_at.tzinfo is not None:
                row.expires_at = row.expires_at.replace(tzinfo=None)
        except ValueError:
            pass
    code = order.code
    if code:
        row.code = code
        row.text = order.text
    row.updated_at = datetime.now()
    db.commit()
    return row


def link_sms_number(db: Session, row: SmsOrder) -> Optional[NumberPool]:
    """把接码号码写进号码池，方便后续注册流程直接引用。"""
    digits = row.phone_digits or normalize_phone_simple(row.phone)
    if not digits:
        return None
    number = db.query(NumberPool).filter_by(phone_number=digits).first()
    if number is None:
        number = NumberPool(phone_number=digits, source_type="sms_platform",
                            source_channel=row.provider, number_segment=digits[:6],
                            region=row.country or "CN", trust_score=40, status="pending")
        db.add(number)
        db.commit()
        db.refresh(number)
    row.number_id = number.id
    db.commit()
    return number


def normalize_phone_simple(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


# ---------------------------------------------------------------- 发消息通道
def _wasock_ready() -> Tuple[bool, str]:
    if not wasock_is_running():
        return False, 'wasock Node 服务未运行，请在账号页启动关联'
    try:
        result = wasock_request({'action':'listSessions'},timeout=2)
        count = sum(row.get('status')=='connected' for row in result.get('sessions',[]))
        return (True, f'{count} 个 WhatsApp 账号在线') if count else (False, '没有已连接的 WhatsApp 账号')
    except Exception:
        return False, '会话服务状态无法读取，请确认 Node 服务已升级'


def message_provider_ready() -> Tuple[bool, str]:
    """发消息前的健康检查，按当前通道分流。"""
    if MESSAGE_PROVIDER in ("mock",):
        return True, "模拟发消息通道"
    if MESSAGE_PROVIDER in ("wsapi", "http", "api"):
        _require_providers()
        return get_message_provider().is_ready()
    return _wasock_ready()


def get_message_provider():
    """发消息通道单例（wasock 的真实实现从本模块注入）。"""
    global _message_provider
    if _message_provider is None:
        _require_providers()
        _message_provider = build_message_provider(
            MESSAGE_PROVIDER, wasock_send=send_via_wasock, wasock_ready=_wasock_ready)
    return _message_provider


def send_message(chat_jid: str, text: str) -> Tuple[bool, str]:
    """发消息的唯一出口：换厂商只改这一层。"""
    if MESSAGE_PROVIDER in ("mock",):
        return True, ""
    if MESSAGE_PROVIDER in ("wsapi", "http", "api"):
        return get_message_provider().send(chat_jid, text)
    return send_via_wasock(chat_jid, text)


# ---------------------------------------------------------------- 接口：供应商状态
def provider_status_items(db: Session) -> List[Dict[str, Any]]:
    """四类供应商的状态快照（看板与资源对接页共用）。"""
    if not PROVIDERS_AVAILABLE:
        return []
    items = [
        get_message_provider().status().to_dict(),
        get_sms_provider().status().to_dict(),
        get_proxy_provider().status().to_dict(),
        get_account_provider().status().to_dict(),
    ]
    for item in items:
        if item["kind"] == "proxy":
            item["pool"] = {
                "free": db.query(ProxyPool).filter_by(status="free").count(),
                "in_use": db.query(ProxyPool).filter_by(status="in_use").count(),
                "disabled": db.query(ProxyPool).filter_by(status="disabled").count(),
            }
    return items


@app.get("/api/v1/providers/status")
def providers_status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not PROVIDERS_AVAILABLE:
        return {"code": 0, "data": {"available": False, "error": PROVIDERS_IMPORT_ERROR, "items": []}}
    return {"code": 0, "data": {
        "available": True, "items": provider_status_items(db),
        "config": {"message_provider": MESSAGE_PROVIDER, "proxy_required": PROXY_REQUIRED},
    }}


# ---------------------------------------------------------------- 接口：代理池
@app.get("/api/v1/proxies")
def list_proxies(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                 status: Optional[str] = None, country: Optional[str] = None,
                 proxy_type: Optional[str] = None, group_id: Optional[int] = None,
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    migrate_exit_proxy(db)
    q = db.query(ProxyPool)
    if status:
        q = q.filter(ProxyPool.status == status)
    if country:
        q = q.filter(ProxyPool.country == country)
    if proxy_type:
        q = q.filter(ProxyPool.proxy_type == proxy_type)
    if group_id is not None:
        q = q.filter(ProxyPool.group_id == group_id)
    total = q.count()
    rows = q.order_by(ProxyPool.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"code": 0, "data": {"total": total, "page": page, "size": size,
                                "list": [proxy_dict(r) for r in rows]}}


@app.post("/api/v1/proxies/sync")
def sync_proxies(payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    payload = payload or {}
    try:
        result = sync_proxy_pool(db, limit=int(payload.get("limit") or 50),
                                 country=str(payload.get("country") or ""))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"同步代理失败：{exc}")
    log_operation(db, "sync_proxy", target=result["provider"],
                  detail=f"新增 {result['added']} 条代理", user=user)
    return {"code": 0, "data": result}


def migrate_exit_proxy(db):
    """Preserve the formerly configured exit in the resource pool without echoing credentials."""
    if db.info.get('tenant_id') != 1:
        return
    if db.query(ProxyPool).filter_by(is_default=True).first():
        return
    from whatsapp_session import setting
    info = parse_proxy_line(setting('WA_PROXY_URL', ''))
    if not info:
        return
    row = db.query(ProxyPool).filter_by(host=info.host, port=info.port, protocol=info.protocol, username=info.username, password=info.password).first()
    if row is None:
        row = ProxyPool(host=info.host, port=info.port, protocol=info.protocol,
                        username=info.username, password=info.password, provider='manual', status='free')
        db.add(row)
    if row.provider != 'mock' and row.status != 'disabled':
        row.is_default = True
        db.commit()


@app.post('/api/v1/proxies/{proxy_id}/default')
def set_default_proxy(proxy_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = db.get(ProxyPool, proxy_id)
    if not row or row.provider == 'mock' or row.status == 'disabled':
        raise HTTPException(422, '请选择真实且未停用的代理')
    db.query(ProxyPool).update({ProxyPool.is_default: False})
    row.is_default = True
    db.commit()
    log_operation(db, 'default_proxy', target=str(row.id), detail='设置 WhatsApp 默认出口；重新连接后生效', user=user)
    return {'code': 0, 'data': proxy_dict(row)}


@app.put('/api/v1/proxies/{proxy_id}')
def edit_pool_proxy(proxy_id: int, payload: Dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = db.get(ProxyPool, proxy_id)
    if not row:
        raise HTTPException(404, '代理不存在')
    if row.bound_number_id or row.status == 'in_use':
        raise HTTPException(409, '请先解除账号代理分配，再编辑代理')
    info = parse_proxy_line(str(payload.get('text') or ''))
    if not info:
        raise HTTPException(422, '请输入有效的完整 HTTP 或 SOCKS5 代理地址')
    row.host, row.port, row.protocol = info.host, info.port, info.protocol
    row.username, row.password = info.username, info.password
    row.provider, row.status = 'manual', 'free'
    row.last_check_ok = row.latency_ms = row.last_checked_at = None
    db.commit()
    log_operation(db, 'edit_proxy', target=str(row.id), detail='更新代理配置', user=user)
    return {'code': 0, 'data': proxy_dict(row)}


@app.post("/api/v1/proxies/import")
def import_proxies(payload: Dict[str, Any], db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
    """手工导入代理：text 每行一个 host:port:user:pass 或 socks5://...。"""
    _require_providers()
    from workspace_api import check_group
    check_group(db, payload.get('group_id'), 'proxy')
    if payload.get('proxy_type', 'static') not in ('static', 'dynamic'):
        raise HTTPException(422, '代理类型无效')
    lines = str(payload.get("text") or "").replace(";", "\n").replace(",", "\n").split("\n")
    added = skipped = 0
    for line in lines:
        info = parse_proxy_line(line)
        if info is None:
            if line.strip():
                skipped += 1
            continue
        if db.query(ProxyPool).filter_by(host=info.host, port=info.port).first():
            skipped += 1
            continue
        db.add(ProxyPool(host=info.host, port=info.port, username=info.username,
                         password=info.password, protocol=info.protocol,
                         country=str(payload.get("country") or ""), provider="manual",
                         group_id=payload.get('group_id'), proxy_type=payload.get('proxy_type', 'static'),
                         status="free"))
        added += 1
    db.commit()
    log_operation(db, "import_proxy", target=f"{added} 条", detail="手工导入代理", user=user)
    return {"code": 0, "data": {"added": added, "skipped": skipped}}


@app.post("/api/v1/proxies/{proxy_id}/test")
def test_one_proxy(proxy_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    row = db.query(ProxyPool).filter_by(id=proxy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="代理不存在")
    return {"code": 0, "data": check_proxy(db, row)}


@app.post("/api/v1/proxies/{proxy_id}/release")
def release_one_proxy(proxy_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    row = db.query(ProxyPool).filter_by(id=proxy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="代理不存在")
    row.status = "free"
    row.bound_number_id = None
    db.commit()
    return {"code": 0, "data": proxy_dict(row)}


# ---------------------------------------------------------------- 接口：接码平台
@app.get("/api/v1/sms/orders")
def list_sms_orders(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                    status: Optional[str] = None, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    q = db.query(SmsOrder)
    if status:
        q = q.filter(SmsOrder.status == status)
    total = q.count()
    rows = q.order_by(SmsOrder.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"code": 0, "data": {"total": total, "page": page, "size": size,
                                "list": [sms_order_dict(r) for r in rows]}}


@app.post("/api/v1/sms/orders")
def create_sms_order(payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    """向接码平台取一个号，并自动写进号码池。"""
    _require_providers()
    payload = payload or {}
    provider = get_sms_provider()
    service = str(payload.get("service") or "wa")
    country = str(payload.get("country") or "ID")
    try:
        order = provider.request_number(service=service, country=country)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"取号失败：{exc}")
    row = SmsOrder(provider=provider.name, remote_order_id=order.order_id, phone=order.phone,
                   phone_digits=order.phone_digits, service=service, country=country,
                   status=order.status or "waiting",
                   price=_dec(order.price) if order.price is not None else None)
    db.add(row)
    db.commit()
    db.refresh(row)
    link_sms_number(db, row)
    db.refresh(row)
    log_operation(db, "create_sms_order", target=row.phone,
                  detail=f"接码取号（{provider.name}）", user=user)
    return {"code": 0, "data": sms_order_dict(row)}


@app.post("/api/v1/sms/orders/{order_id}/poll")
def poll_sms_order(order_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """查一次验证码。"""
    _require_providers()
    row = db.query(SmsOrder).filter_by(id=order_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="接码订单不存在")
    if not row.remote_order_id:
        raise HTTPException(status_code=400, detail="该订单没有远端单号，无法查询")
    try:
        order = get_sms_provider().poll(row.remote_order_id)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"查询验证码失败：{exc}")
    apply_sms_order(db, row, order)
    db.refresh(row)
    return {"code": 0, "data": sms_order_dict(row)}


@app.post("/api/v1/sms/orders/{order_id}/wait")
def wait_sms_order(order_id: int, payload: Optional[Dict[str, Any]] = None,
                   db: Session = Depends(get_db), user: User = Depends(current_user)):
    """阻塞等待验证码（默认最多 180 秒）。"""
    _require_providers()
    payload = payload or {}
    row = db.query(SmsOrder).filter_by(id=order_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="接码订单不存在")
    timeout = min(float(payload.get("timeout") or 180), 600.0)
    result = get_sms_provider().wait_for_code(row.remote_order_id, timeout=timeout,
                                              interval=float(payload.get("interval") or 5))
    if result.order:
        apply_sms_order(db, row, result.order)
        db.refresh(row)
    if result.ok:
        log_operation(db, "sms_code_received", target=row.phone,
                      detail=f"收到验证码（{row.provider}）", user=user)
    return {"code": 0, "data": {"ok": result.ok, "code": result.code,
                                "detail": result.detail, "order": sms_order_dict(row)}}


@app.post("/api/v1/sms/orders/{order_id}/cancel")
def cancel_sms_order(order_id: int, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    _require_providers()
    row = db.query(SmsOrder).filter_by(id=order_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="接码订单不存在")
    if row.status != "waiting":
        raise HTTPException(status_code=400, detail=f"订单状态为 {row.status}，无法取消")
    try:
        ok = get_sms_provider().cancel(row.remote_order_id)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"取消失败：{exc}")
    if ok:
        row.status = "cancelled"
        db.commit()
    log_operation(db, "cancel_sms_order", target=row.phone, detail="取消接码订单", user=user)
    return {"code": 0, "data": sms_order_dict(row)}


# ---------------------------------------------------------------- 接口：账号采购
def purchase_order_dict(row: PurchaseOrder) -> Dict[str, Any]:
    return {
        "id": row.id, "order_no": row.order_no, "provider": row.provider,
        "product_id": row.product_id, "product_name": row.product_name,
        "quantity": row.quantity, "unit_price": _money(row.unit_price),
        "amount": _money(row.amount), "currency": row.currency, "status": row.status,
        "accounts": [a for a in (row.accounts or "").split(",") if a],
        "message": row.message or "", "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": _dt(row.created_at), "updated_at": _dt(row.updated_at),
    }


@app.get("/api/v1/purchase/products")
def list_purchase_products(db: Session = Depends(get_db), user: User = Depends(current_user)):
    _require_providers()
    provider = get_account_provider()
    try:
        products = provider.list_products()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"获取商品失败：{exc}")
    return {"code": 0, "data": {"provider": provider.name,
                                "list": [p.to_dict() for p in products]}}


@app.get("/api/v1/purchase/orders")
def list_purchase_orders(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                         status: Optional[str] = None, keyword: Optional[str] = None,
                         db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(PurchaseOrder)
    if status:
        q = q.filter(PurchaseOrder.status == status)
    if keyword:
        q = q.filter(PurchaseOrder.order_no.contains(keyword)
                     | PurchaseOrder.product_name.contains(keyword))
    total = q.count()
    rows = q.order_by(PurchaseOrder.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"code": 0, "data": {"total": total, "page": page, "size": size,
                                "list": [purchase_order_dict(r) for r in rows]}}


@app.post("/api/v1/purchase/orders")
def create_purchase_order(payload: Dict[str, Any], db: Session = Depends(get_db),
                          user: User = Depends(require_admin)):
    """创建采购订单。"""
    _require_providers()
    product_id = str(payload.get("product_id") or "").strip()
    if not product_id:
        raise HTTPException(status_code=400, detail="缺少 product_id")
    quantity = max(1, int(payload.get("quantity") or 1))
    provider = get_account_provider()
    try:
        products = {p.product_id: p for p in provider.list_products()}
        result = provider.create_order(product_id, quantity)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"下单失败：{exc}")
    product = products.get(product_id)
    row = PurchaseOrder(
        order_no=result.order_no, provider=provider.name, product_id=product_id,
        product_name=product.name if product else str(payload.get("product_name") or product_id),
        quantity=result.quantity or quantity,
        unit_price=_dec(product.price if product else result.amount / max(1, quantity)),
        amount=_dec(result.amount), currency=result.currency or "USDT",
        status=result.status, accounts=",".join(result.accounts),
        message=result.message, remark=str(payload.get("remark") or ""),
        created_by=user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_operation(db, "create_purchase_order", target=row.order_no,
                  detail=f"采购 {row.quantity} 个账号（{row.product_name}）", user=user)
    return {"code": 0, "data": purchase_order_dict(row)}


@app.post("/api/v1/purchase/orders/{order_id}/sync")
def sync_purchase_order(order_id: int, db: Session = Depends(get_db),
                        user: User = Depends(current_user)):
    """向供应商查询最新状态（交付后会把账号写进订单）。"""
    _require_providers()
    row = db.query(PurchaseOrder).filter_by(id=order_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    try:
        result = get_account_provider().query_order(row.order_no)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"查询订单失败：{exc}")
    row.status = result.status or row.status
    row.accounts = ",".join(result.accounts) or row.accounts
    row.message = result.message or row.message
    row.quantity = result.quantity or row.quantity
    if result.amount:
        row.amount = _dec(result.amount)
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return {"code": 0, "data": purchase_order_dict(row)}


# ============================================================
# 面板内扫码登录 WhatsApp（支持多个账号）
# ============================================================
def current_session_name(user=None) -> str:
    if not WHATSAPP_SESSION_AVAILABLE:
        return ""
    return (user.whatsapp_session_name or "") if user is not None else (get_session().snapshot().get("auth_name") or "")


def whatsapp_status_dict(db: Session, auth_name=None) -> Dict[str, Any]:
    """会话状态 + 二维码 + 当前会话对应的账号。"""
    if not WHATSAPP_SESSION_AVAILABLE:
        return {"status": "unavailable", "qr_image": "", "node_running": False,
                "registered": False, "paired_phone": "", "auth_name": "",
                "account_id": None, "number_id": None,
                "hint": f"会话模块不可用：{WHATSAPP_SESSION_ERROR}"}
    if auth_name == "":
        from whatsapp_session import SessionState
        status = SessionState(node_running=is_node_running()).to_dict()
    else:
        status = get_session(auth_name).snapshot()
    auth_name = status.get("auth_name") or ""
    status["auth_name"] = auth_name
    phone = read_paired_phone(auth_name) if auth_name else ""
    status["paired_phone"] = phone

    number = db.query(NumberPool).filter_by(phone_number=phone).first() if phone else None
    account = None
    if number is not None:
        account = (db.query(AccountPool).filter_by(id=number.account_id).first()
                   if number.account_id else None)
        if account is None:
            account = db.query(AccountPool).filter_by(number_id=number.id).first()
    status["number_id"] = number.id if number else None
    status["account_id"] = account.id if account else None
    status["registered"] = account is not None

    # 这个登录态目录已经配过号、而当前会话又不是它 —— 说明可以切过去
    if not auth_name and phone:
        status["hint"] = "已有登录态，点「使用已登录账号」接入"
    elif status["status"] == "waiting_qr":
        if phone:
            # 已配对的目录不会再有二维码，这里必须说清楚，否则用户会以为卡住了
            status["hint"] = (f"正在以 {phone} 上线…这个登录态已经配对过，不会再出二维码。"
                              f"想关联别的号请点「关联新账号（扫码）」")
        else:
            status["hint"] = "手机 WhatsApp → 设置 → 已关联的设备 → 关联新设备，扫描二维码"
    elif status["status"] == "connected":
        if status["registered"]:
            status["hint"] = f"已以 {phone} 上线，并已登记为账号 #{account.id}"
        else:
            status["hint"] = "已登录，点「完成账号接入」即可用于运营"
    elif status["status"] == "starting":
        status["hint"] = "正在建立会话，稍候…"
    elif status["status"] in ("error", "closed"):
        status["hint"] = status.get("last_error") or "会话已断开，可重新启动"
    elif not status["node_running"]:
        status["hint"] = "点「关联新账号」扫码，或点「使用已登录账号」接入已有的号"
    else:
        status["hint"] = status.get("last_error") or "服务已在运行，点「使用已登录账号」接入"
    return status


def pick_start_auth_name(mode: str, want: str, db: Session) -> str:
    """决定这次用哪个登录态目录。

    new     -> 一个全新的空目录，必然会出二维码（用于关联新账号）
    current -> 已登记账号在用的目录；没有就用默认目录
    """
    if mode == "new":
        return next_auth_name()
    if want:
        return want
    account = (db.query(AccountPool)
               .filter(AccountPool.session_name.isnot(None), AccountPool.session_name != "")
               .order_by(AccountPool.id).first())
    if account and account.session_name:
        return account.session_name
    return DEFAULT_AUTH_NAME


def resolve_user_session(auth_name, user, db):
    """Pending QR belongs to its creator; registered accounts are shared by this workspace."""
    from whatsapp_session import auth_path
    name = auth_name or current_session_name(user)
    if not name:
        return ''
    path = auth_path(name).resolve()
    allowed = False
    if not allowed:
        allowed = any(auth_path(link.auth_name).resolve()==path for link in db.query(WhatsAppLinkSession).filter_by(owner_user_id=user.id))
    if not allowed:
        allowed = any(auth_path(account.session_name).resolve() == path for account in db.query(AccountPool).filter(AccountPool.session_name != '', AccountPool.session_name.isnot(None)))
    if not allowed:
        raise HTTPException(403, '没有访问该扫码会话的权限')
    return name


@app.get('/api/v1/whatsapp/status')
def whatsapp_status(auth_name: str = '', db: Session = Depends(get_db), user: User = Depends(current_user)):
    name = resolve_user_session(auth_name, user, db)
    return {'code': 0, 'data': whatsapp_status_dict(db, name)}


@app.get('/api/v1/whatsapp/sessions')
def whatsapp_sessions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not WHATSAPP_SESSION_AVAILABLE:
        return {'code':0,'data':{'list':[],'active':'','next':''}}
    active = current_session_name(user)
    accounts = db.query(AccountPool).filter(AccountPool.session_name != '', AccountPool.session_name.isnot(None)).all()
    numbers = {n.id:n for n in db.query(NumberPool).all()}
    items = []
    for account in accounts:
        name = account.session_name
        snapshot = get_session(name).snapshot()
        phone = read_paired_phone(name)
        items.append({'auth_name':name,'paired_phone':phone,'paired':bool(phone),'files':0,
                      'account_id':account.id,'number_id':account.number_id,'active':name==active,
                      'status':snapshot['status']})
    return {'code':0,'data':{'list':items,'active':active,'next':''}}


@app.post('/api/v1/whatsapp/start')
def whatsapp_start(payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not WHATSAPP_SESSION_AVAILABLE:
        raise HTTPException(503, f'会话模块不可用：{WHATSAPP_SESSION_ERROR}')
    payload = payload or {}
    mode = str(payload.get('mode') or 'current')
    if mode not in ('new','current'):
        raise HTTPException(422,'启动方式无效')
    if mode == 'new':
        import uuid
        name = f'{DEFAULT_AUTH_NAME}_u{user.id}_{uuid.uuid4().hex[:12]}'
        db.add(WhatsAppLinkSession(auth_name=name,owner_user_id=user.id))
    else:
        name = resolve_user_session(str(payload.get('auth_name') or ''),user,db)
        if not name:
            account = db.query(AccountPool).filter(AccountPool.session_name != '', AccountPool.session_name.isnot(None)).order_by(AccountPool.id).first()
            if not account:
                raise HTTPException(409,'没有已关联账号，请选择关联新账号扫码')
            name = account.session_name
    from account_management_api import proxy_for_session
    with operations.session_control_guard(name):
        for account in db.query(AccountPool).filter_by(session_name=name):
            account.session_enabled = True
        user.whatsapp_session_name = name; db.commit()
        get_session(name).start(name, proxy_override=proxy_for_session(db,name))
    log_operation(db,'whatsapp_start',target=name,detail=f'启动独立账号会话（{mode}）',user=user)
    return {'code':0,'data':whatsapp_status_dict(db,name)}


@app.post('/api/v1/whatsapp/switch')
def whatsapp_switch(payload: Dict[str, Any], db: Session = Depends(get_db), user: User = Depends(current_user)):
    account = db.get(AccountPool,payload.get('account_id'))
    if not account or not account.session_name:
        raise HTTPException(404,'账号不存在或尚未绑定登录会话')
    from account_management_api import proxy_for_session
    with operations.session_control_guard(account.session_name):
        account.session_enabled = True
        user.whatsapp_session_name = account.session_name; db.commit()
        get_session(account.session_name).start(account.session_name,proxy_override=proxy_for_session(db,account.session_name))
    log_operation(db,'whatsapp_select',target=account.session_name,detail=f'选择账号 #{account.id}，其他账号保持连接',user=user)
    return {'code':0,'data':whatsapp_status_dict(db,account.session_name)}


@app.post('/api/v1/whatsapp/stop')
def whatsapp_stop(payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    name = resolve_user_session((payload or {}).get('auth_name',''),user,db)
    if not name:
        raise HTTPException(409,'请先选择账号')
    with operations.session_control_guard(name):
        get_session(name).stop()
        for account in db.query(AccountPool).filter_by(session_name=name):
            account.session_enabled = False
        db.commit()
    log_operation(db,'whatsapp_stop',target=name,detail='断开指定账号会话，其他账号保持连接',user=user)
    return {'code':0,'data':whatsapp_status_dict(db,name)}


@app.post("/api/v1/whatsapp/register-account")
def whatsapp_register_account(payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db),
                              user: User = Depends(require_admin)):
    """把当前会话的号登记进号码池 / 账号池，并记住它用的是哪个登录态目录。"""
    if not WHATSAPP_SESSION_AVAILABLE:
        raise HTTPException(status_code=503, detail=f"会话模块不可用：{WHATSAPP_SESSION_ERROR}")
    auth_name = resolve_user_session((payload or {}).get('auth_name',''),user,db)
    phone = read_paired_phone(auth_name) if auth_name else ""
    if not phone:
        raise HTTPException(status_code=400, detail="还没有完成扫码登录，无法登记")

    number = db.query(NumberPool).filter_by(phone_number=phone).first()
    if number is None:
        number = NumberPool(phone_number=phone, source_type="physical",
                            source_channel="扫码关联", number_segment=phone[:6],
                            region="", trust_score=80, status="success",
                            register_time=datetime.now())
        db.add(number)
        db.commit()
        db.refresh(number)
    else:
        number.status = "success"
        if not number.register_time:
            number.register_time = datetime.now()
        db.commit()

    account = db.query(AccountPool).filter_by(number_id=number.id).first()
    if account is None:
        account = AccountPool(number_id=number.id, device_fingerprint=f"scanned_{number.id}",
                              current_ip="", nurture_stage="ready", health_score=100,
                              status="normal")
        db.add(account)
        db.commit()
        db.refresh(account)
        number.account_id = account.id
    else:
        account.nurture_stage = "ready"
        account.status = "normal"
        number.account_id = account.id
    # 记住这个账号对应哪个登录态目录，之后才能一键切回来
    account.session_name = auth_name
    account.session_enabled = True
    db.commit()

    log_operation(db, "whatsapp_register_account", target=phone,
                  detail=f"扫码登录的号已登记为账号 #{account.id}（登录态 {auth_name}）", user=user)
    return {"code": 0, "data": {
        "number_id": number.id, "account_id": account.id, "phone": phone,
        "auth_name": auth_name,
        "message": f"已登记为账号 #{account.id}（登录态 {auth_name}），可在群发任务里选择",
    }}


@app.post("/api/v1/whatsapp/unlink")
def whatsapp_unlink(payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    """解绑：删除登录态目录（不可恢复，手机上也要移除该设备）。"""
    if not WHATSAPP_SESSION_AVAILABLE:
        raise HTTPException(status_code=503, detail=f"会话模块不可用：{WHATSAPP_SESSION_ERROR}")
    payload = payload or {}
    auth_name = resolve_user_session(str(payload.get("auth_name") or "").strip(),user,db)
    if not auth_name:
        raise HTTPException(status_code=400, detail="没有指定要解绑的登录态")
    with operations.session_control_guard(auth_name):
        from account_management_api import account_in_use
        for account in db.query(AccountPool).filter_by(session_name=auth_name):
            if account_in_use(db,account.id):
                raise HTTPException(409,'该账号被未结束任务使用，请先取消任务')
        get_session(auth_name).stop()
        removed = remove_auth_dir(auth_name)
        for account in db.query(AccountPool).filter_by(session_name=auth_name).all():
            account.session_name = ''
            account.session_enabled = False
            account.full_params_ready = False
            account.converted_at = None
        for selected in db.query(User).filter_by(whatsapp_session_name=auth_name, tenant_id=user.tenant_id):
            selected.whatsapp_session_name = ''
        db.commit()
    log_operation(db, "whatsapp_unlink", target=auth_name, detail="解绑登录态", user=user)
    return {"code": 0, "data": {"removed": removed, "auth_name": auth_name,
                                "message": f"已删除登录态目录 {auth_name}"}}


@app.delete("/api/v1/purchase/orders/{order_id}")
def delete_purchase_order(order_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_admin)):
    row = db.query(PurchaseOrder).filter_by(id=order_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="采购订单不存在")
    order_no = row.order_no
    db.delete(row)
    db.commit()
    log_operation(db, "delete_purchase_order", target=order_no, detail="删除采购订单", user=user)
    return {"code": 0, "data": {"deleted": 1}}


# ---------- 数据看板 ----------
def aggregate_tasks(tasks: List[MassSendTask]) -> Dict[str, Any]:
    """把一批任务的计数汇总成看板口径。"""
    sent = sum((t.accepted or 0) if t.mode else (t.sent or 0) for t in tasks)
    delivered = sum(t.delivered or 0 for t in tasks)
    read = sum(t.read_count or 0 for t in tasks)
    return {
        "mock_tasks": sum(t.mode == "mock" for t in tasks),
        "legacy_tasks": sum(not t.mode for t in tasks),
        "tasks": len(tasks), "sent": sent, "delivered": delivered, "read": read,
        "failed": sum(t.failed or 0 for t in tasks),
        "success_rate": _rate(delivered, sent),
        "read_rate": _rate(read, delivered),
    }


def task_brief(task: MassSendTask) -> Dict[str, Any]:
    sent = task.sent or 0
    delivered = task.delivered or 0
    targets = len([x for x in (task.target_ids or "").split(",") if x.strip()])
    return {
        "id": task.id, "task_name": task.task_name or "", "status": task.status,
        "target_type": task.target_type or "group", "targets": targets,
        "sent": sent, "delivered": delivered, "read": task.read_count or 0,
        "failed": task.failed or 0,
        "progress": _rate(sent, targets) if targets else 0.0,
        "created_at": _dt(task.created_at),
    }


@app.get("/api/v1/dashboard/today", dependencies=[Depends(require_login)])
def dashboard_today(db: Session = Depends(get_db)):
    """今日概览：只统计今天创建的任务（此前是把所有任务累加，口径不对）。"""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tasks = db.query(MassSendTask).filter(MassSendTask.created_at >= today_start).all()
    data = aggregate_tasks(tasks)
    return {"code": 0, "data": data}


@app.get("/api/v1/dashboard/overview")
def dashboard_overview(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """首页聚合接口：一次请求返回看板需要的全部数据。

    首屏只发一个请求，避免并发多个接口造成的空白等待与错误提示刷屏。
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    today_tasks = db.query(MassSendTask).filter(MassSendTask.created_at >= today_start).all()
    yesterday_tasks = (db.query(MassSendTask)
                       .filter(MassSendTask.created_at >= yesterday_start,
                               MassSendTask.created_at < today_start).all())
    all_tasks = db.query(MassSendTask).all()
    accounts = db.query(AccountPool).all()

    active_tasks = (db.query(MassSendTask)
                    .filter(MassSendTask.status.in_(("pending", "running")))
                    .order_by(MassSendTask.id.desc()).limit(5).all())

    invite_tasks = db.query(InviteTask).all()
    combined_tasks = [{**task_brief(t), "kind": "mass-send"} for t in all_tasks]
    combined_tasks += [{
        "id": t.id, "task_name": t.task_name or "", "status": t.status,
        "kind": "pull-group", "created_at": _dt(t.created_at),
        "targets": len([x for x in (t.source_ids or "").split(",") if x.strip()]),
        "sent": t.processed or 0, "delivered": None,
        "progress": _rate(t.processed or 0, len([x for x in (t.source_ids or "").split(",") if x.strip()])),
    } for t in invite_tasks]
    combined_tasks.sort(key=lambda t: (t["created_at"] or "", t["id"]), reverse=True)
    task_counts = {
        "running": sum(t["status"] == "running" for t in combined_tasks),
        "pending": sum(t["status"] == "pending" for t in combined_tasks),
        "done": sum(t["status"] == "done" for t in combined_tasks),
        "failed": sum(t["status"] == "failed" for t in combined_tasks),
    }

    def account_count(status: str) -> int:
        return len([a for a in accounts if a.status == status])

    providers = provider_status_items(db)

    return {"code": 0, "data": {
        "today": aggregate_tasks(today_tasks),
        "yesterday": aggregate_tasks(yesterday_tasks),
        "total": aggregate_tasks(all_tasks),
        "balance": {
            "balance": _money(current_balance(db)),
            "currency": str(get_setting(db, "currency", "USDT")),
            "pending_orders": db.query(RechargeOrder).filter_by(status="pending").count(),
        },
        "accounts": {
            "total": len(accounts),
            "normal": account_count("normal"),
            "watch": account_count("watch"),
            "paused": account_count("paused"),
            "banned": account_count("banned"),
        },
        "active_tasks": [task_brief(t) for t in active_tasks],
        "recent_tasks": combined_tasks[:5],
        "task_counts": task_counts,
        "resources": {
            "available_numbers": db.query(NumberPool).filter_by(status="pending").count(),
            "groups": db.query(ResourceGroup).filter_by(status="active").count(),
        },
        "providers": providers,
        "generated_at": _dt(datetime.now()),
    }}

# Operational endpoints and lifecycle use the same models/database as the core API.
import operations
operations.register(app)
import service_api, resource_api, finance_api, account_export_api, account_management_api
app.include_router(service_api.router)
app.include_router(resource_api.router)
app.include_router(resource_api.resources_router)
Base.metadata.create_all(bind=engine)
app.include_router(finance_api.router)
app.include_router(account_export_api.router)
app.include_router(account_management_api.router)
import workspace_api
Base.metadata.create_all(bind=engine)
migrate_tenants(engine, Base.metadata)
app.include_router(workspace_api.router)
import tenant_api
app.include_router(tenant_api.router)
