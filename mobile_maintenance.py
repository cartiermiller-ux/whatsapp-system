"""Online maintenance only: no messages, contact imports, or artificial health scores."""
from datetime import datetime, timedelta
import threading
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
import main as m
from mobile_session import runtime, is_mobile, session_key


class MobileProgress(m.TenantOwned, m.Base):
    __tablename__ = 'mobile_progress'
    __table_args__ = (UniqueConstraint('tenant_id', 'account_id', name='uq_mobile_progress_account'),)
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, nullable=False)
    online_seconds = Column(Integer, default=0, nullable=False)
    last_heartbeat = Column(DateTime)
    last_status = Column(String(30), default='idle')
    last_error = Column(String(100), default='')
    next_attempt = Column(DateTime)
    failures = Column(Integer, default=0, nullable=False)


def progress_for(account, db):
    row = db.query(MobileProgress).filter_by(account_id=account.id).first()
    if not row:
        row = MobileProgress(account_id=account.id, online_seconds=0, failures=0, last_status='idle')
        db.add(row); db.flush()
    return row


def maintain_account(account, db, now=None):
    from operations import account_lock
    now = now or datetime.now()
    with account_lock(account):
        progress = progress_for(account, db)
        state = runtime.snapshot(session_key(account))
        status = state.get('status', 'idle')
        if status != progress.last_status:
            db.add(m.OperationLog(action='mobile_connection', target=str(account.id), username='system',
                detail='手机连接状态：'+status, result='success' if status == 'connected' else 'info'))
            if status in ('closed', 'error'):
                progress.failures += 1
                progress.next_attempt = now + timedelta(seconds=min(600, 60 * 2 ** min(progress.failures-1, 3)))
                progress.last_heartbeat = None
            if status == 'connected':
                progress.failures = 0; progress.next_attempt = None
        progress.last_status = status
        progress.last_error = state.get('error', '')[:100]
        if progress.failures >= 3:
            account.session_enabled = False
            if account.nurture_stage == 'nurturing': account.nurture_stage = 'paused'
            progress.last_error = '连续三次连接失败，请检查凭据和代理后手动重新登录'
            return
        if status in ('idle', 'closed', 'error') and (not progress.next_attempt or progress.next_attempt <= now):
            try:
                runtime.connect(account, db)
                progress.last_status = 'starting'
            except (ValueError, TimeoutError):
                progress.failures += 1
                progress.next_attempt = now + timedelta(seconds=60 * progress.failures)
                progress.last_error = '手机引擎启动失败，请检查 Java、引擎文件及代理'
            return
        if status != 'connected': return
        number = db.get(m.NumberPool, account.number_id)
        if not number or state.get('phone') != number.phone_number.lstrip('+'):
            account.session_enabled = False
            runtime.disconnect(account)
            progress.last_error = '登录号码与账号记录不一致'
            return
        number.status = 'success'
        if account.nurture_stage != 'nurturing': return
        if progress.last_heartbeat and (now-progress.last_heartbeat).total_seconds() < 60: return
        try:
            runtime.presence(account, True)
        except (ValueError, TimeoutError):
            progress.last_heartbeat = None
            progress.last_error = '在线保活失败，等待连接检查'
            progress.failures += 1
            progress.next_attempt = now + timedelta(seconds=min(600, 60 * progress.failures))
            try: runtime.disconnect(account)
            except (ValueError, TimeoutError): pass
            progress.last_status = 'idle'
            return
        if progress.last_heartbeat:
            progress.online_seconds += max(0, min(120, int((now-progress.last_heartbeat).total_seconds())))
        progress.last_heartbeat = now
        progress.last_error = ''


_stop = threading.Event()
_worker = None


def loop():
    while not _stop.wait(5):
        if not runtime.configured(): continue
        try:
            with m.system_session() as discovery:
                tenants = [t.id for t in discovery.query(m.Tenant).filter_by(status='active')]
            for tenant_id in tenants:
                with m.SessionLocal(info={'tenant_id': tenant_id}) as db:
                    accounts = db.query(m.AccountPool).filter(m.AccountPool.device_type.in_(('full_params', 'six_segment')),
                        m.AccountPool.status == 'normal', m.AccountPool.session_enabled == True).all()
                    for account in accounts:
                        if _stop.is_set(): return
                        if is_mobile(account): maintain_account(account, db)
                    db.commit()
        except Exception:
            # An isolated tick retries next pass; never print secret-bearing SQL or payloads.
            continue


def start():
    global _worker
    _stop.clear()
    _worker = threading.Thread(target=loop, daemon=True)
    _worker.start()


def stop():
    _stop.set()
    if _worker: _worker.join(timeout=30)
    runtime.close()
