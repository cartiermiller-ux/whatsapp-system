"""Persistent task execution, task controls and receipt reconciliation."""
from datetime import datetime, timezone
from decimal import Decimal
import os
import threading
import time
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
import main as m

router = APIRouter(prefix="/api/v1")
_channel_lock = threading.RLock()  # ledger / short database writes, never the whole task
_account_locks = {}
from contextlib import nullcontext, contextmanager
_task_locks = {}
_lock_guard = threading.Lock()
_stop = threading.Event()
_scheduler = None


def account_session_lock(auth_name):
    from whatsapp_session import auth_path
    key = str(auth_path(auth_name).resolve())
    with _lock_guard:
        return _account_locks.setdefault(key, threading.RLock())


@contextmanager
def session_control_guard(auth_name):
    lock = account_session_lock(auth_name)
    if not lock.acquire(blocking=False):
        raise HTTPException(409,'此账号正在执行任务，请暂停或等待当前操作完成；其他账号可正常使用')
    try:
        yield
    finally:
        lock.release()


def account_lock(account):
    return account_session_lock(account.session_name or f'account-{account.id}')


def task_model(kind):
    if kind == "mass-send":
        return m.MassSendTask
    if kind == "pull-group":
        return m.InviteTask
    raise HTTPException(404, "任务类型不存在")


def ids(value):
    return list(dict.fromkeys(x.strip() for x in (value or "").split(",") if x.strip()))


def get_task(kind, task_id, db):
    task = db.get(task_model(kind), task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


def targets(kind, task):
    return ids(task.target_ids if kind == "mass-send" else task.source_ids)


def due_at(value):
    # Database timestamps use local server wall time; convert offset dates once.
    return value.astimezone().replace(tzinfo=None) if value and value.tzinfo else value


def create_task(kind, req, background, db):
    account_ids = list(dict.fromkeys(req.account_ids))
    target_ids = list(dict.fromkeys(req.target_ids if kind == "mass-send" else req.source_ids))
    if not req.task_name.strip() or not target_ids or not account_ids:
        raise HTTPException(422, "任务名称、目标和执行账号不能为空")
    accounts = db.query(m.AccountPool).filter(m.AccountPool.id.in_(account_ids)).all()
    if len(accounts) != len(account_ids) or any(a.status != "normal" for a in accounts):
        raise HTTPException(422, "执行账号不存在或不可用")
    country = req.billing_country.strip().upper()
    if country and country not in {r['country'] for r in m.BILLING_RULES}:
        raise HTTPException(422, "不支持该计费国家")
    if kind == "mass-send":
        if m.real_send_enabled() and m.get_setting(db, 'billing_enabled', False) and not country:
            raise HTTPException(422, '已启用任务计费，请填写计费国家')
        if req.target_type not in ("group", "contact") or not req.message_content.strip():
            raise HTTPException(422, "目标类型无效或消息为空")
        if req.ad_message_id and not db.get(m.AdMessage, req.ad_message_id):
            raise HTTPException(422, "关联广告文案不存在")
        task = m.MassSendTask(task_name=req.task_name.strip(), target_type=req.target_type,
                              target_ids=','.join(map(str, target_ids)), account_ids=','.join(map(str, account_ids)),
                              message_content=req.message_content, link_url=req.link_url,
                              ad_message_id=req.ad_message_id, billing_country=country,
                              scheduled_at=due_at(req.scheduled_at), mode="real" if m.real_send_enabled() else "mock")
    else:
        group = db.get(m.ResourceGroup, req.target_group_id)
        if not group or group.status != "active" or not group.can_invite:
            raise HTTPException(422, "目标群不存在、已停用或不可拉人")
        if req.source_type not in ("number_pool", "contact"):
            raise HTTPException(422, "拉人来源类型无效")
        task = m.InviteTask(task_name=req.task_name.strip(), target_group_id=req.target_group_id,
                            source_type=req.source_type, source_ids=','.join(map(str, target_ids)),
                            account_ids=','.join(map(str, account_ids)), billing_country=country,
                            scheduled_at=due_at(req.scheduled_at), mode="real" if m.real_send_enabled() else "mock")
    db.add(task)
    db.commit()
    for target in target_ids:
        db.add(m.TaskExecution(task_kind=kind, task_id=task.id, target_id=str(target)))
    db.commit()
    if not task.scheduled_at or task.scheduled_at <= datetime.now():
        background.add_task(run_task, kind, task.id)
    return {"code": 0, "data": {"task_id": task.id, "status": task.status, "mode": task.mode}}


def write_log(db, kind, task_id, result, detail, row=None, action=None):
    db.add(m.TaskLog(task_id=task_id, task_kind=kind, account_id=row.account_id if row else 0,
                     target=row.target if row else "", action=action or kind.replace('-', '_'),
                     result=result, detail=detail))


def sync_counts(kind, task, db):
    rows = db.query(m.TaskExecution).filter_by(task_kind=kind, task_id=task.id).all()
    succeeded = sum(r.status == "succeeded" for r in rows)
    failed = sum(r.status in ("failed", "uncertain") for r in rows)
    if kind == "mass-send":
        task.sent = succeeded + failed
        task.accepted = succeeded
        task.delivered = sum(r.delivered_at is not None for r in rows)
        task.read_count = sum(r.read_at is not None for r in rows)
        if task.ad_message_id:
            ad = db.get(m.AdMessage, task.ad_message_id)
            if ad:
                # Flush task changes before SQL aggregation.
                db.flush()
                totals = db.query(func.sum(m.MassSendTask.accepted), func.sum(m.MassSendTask.delivered), func.sum(m.MassSendTask.read_count)).filter_by(ad_message_id=ad.id).first()
                ad.sent, ad.delivered, ad.read_count = [int(n or 0) for n in totals]
    else:
        task.processed, task.succeeded = succeeded + failed, succeeded
    task.failed = failed
    return rows


def ensure_records(kind, task, db):
    existing = {r.target_id for r in db.query(m.TaskExecution).filter_by(task_kind=kind, task_id=task.id)}
    # Old completed tasks lack target history: never recreate and re-send their targets.
    if not existing and task.status == "done":
        raise HTTPException(409, "历史已完成任务没有执行记录，不能安全重试")
    for target in targets(kind, task):
        if target not in existing:
            db.add(m.TaskExecution(task_kind=kind, task_id=task.id, target_id=target))
    db.commit()


def select_account(db, task, row):
    eligible = []
    for account_id in ids(task.account_ids):
        account = db.get(m.AccountPool, int(account_id))
        if not account or account.status != "normal":
            continue
        allowed, _ = m.can_send(account, db)
        if task.mode == 'mock' or allowed:
            eligible.append(account)
    if not eligible:
        raise ValueError("没有可用执行账号（状态、冷却、健康度或每日上限限制）")
    return eligible[(row.id - 1) % len(eligible)]


def activate_account(account, db):
    # A running socket must belong to the selected account, not merely any logged-in account.
    if m.MESSAGE_PROVIDER != "wasock":
        return
    if not account.session_name:
        raise ValueError("执行账号没有 WhatsApp 登录会话，请先扫码关联")
    if not account.session_enabled:
        raise ValueError('执行账号已主动断开，请在账号页重新连接')
    session = m.get_session(account.session_name)
    snapshot = session.snapshot()
    if snapshot.get('auth_name') != account.session_name or snapshot.get('status') != 'connected':
        number = db.get(m.NumberPool, account.number_id)
        result = session.start(auth_name=account.session_name, proxy_override=number.proxy_ip or None if number else None)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = session.snapshot()
            if state.get('status') == 'connected':
                return
            if state.get('status') in ('waiting_qr', 'error', 'unavailable', 'closed'):
                raise ValueError(state.get('last_error') or "执行账号尚未连接，请先扫码登录")
            time.sleep(.2)
        raise ValueError("执行账号连接超时")


def dispatch_target(kind, task, row, account, db):
    if kind == "mass-send":
        target = m.resolve_send_target(db, int(row.target_id), task.target_type or 'group')
        if target.get('error') or not target.get('chat'):
            raise ValueError(target.get('error') or '目标地址无效')
        row.target = target['chat']
        message = m.render_mass_message(task, target)
        if task.mode == 'mock':
            return {"success": True, "message_id": "", "mock": True}
        activate_account(account, db)
        if m.MESSAGE_PROVIDER == 'wasock':
            try:
                return m.wasock_request({'action': 'sendMessage', 'authName': str(__import__('whatsapp_session').auth_path(account.session_name)), 'chat': row.target, 'msg': message}, timeout=m.WASOCK_SEND_TIMEOUT)
            except ValueError as exc:
                raise TimeoutError('通道响应无法确认') from exc
        if m.get_message_provider().mock:
            raise ValueError("真实执行模式禁止使用模拟消息通道")
        response = m.get_message_provider().send_result(row.target, message)
        if response.get('uncertain'):
            raise TimeoutError('HTTP 通道响应丢失或服务端错误，无法确认执行结果')
        return response
    group = db.get(m.ResourceGroup, task.target_group_id)
    if not group or group.status != 'active' or not group.can_invite:
        raise ValueError('目标群不存在、已停用或不可拉人')
    if task.source_type == 'number_pool':
        number = db.get(m.NumberPool, int(row.target_id))
        if not number:
            raise ValueError('来源号码不存在')
        row.target = m.to_whatsapp_jid(number.phone_number)
    else:
        if not m.PHONE_PATTERN.match(row.target_id):
            raise ValueError('联系人来源必须填写完整手机号')
        row.target = m.to_whatsapp_jid(row.target_id)
    if not row.target:
        raise ValueError('来源号码无效')
    if task.mode == 'mock':
        return {'success': True, 'mock': True}
    if m.MESSAGE_PROVIDER != 'wasock':
        raise ValueError('当前消息通道不支持拉群；请选择 wasock')
    activate_account(account, db)
    try:
        return m.wasock_request({'action': 'addParticipants', 'authName': str(__import__('whatsapp_session').auth_path(account.session_name)), 'chat': group.group_jid, 'participants': [row.target]}, timeout=m.WASOCK_SEND_TIMEOUT)
    except ValueError as exc:
        raise TimeoutError('通道响应无法确认') from exc


def task_price(db, task, kind):
    if task.mode == 'mock' or not m.get_setting(db, 'billing_enabled', False):
        return Decimal('0')
    if kind == 'pull-group':
        return Decimal(str(m.get_setting(db, 'invite_unit_price', 0)))
    if not task.billing_country:
        raise ValueError('已启用自动计费，但任务缺少计费国家')
    rule = next((r for r in m.BILLING_RULES if r['country'] == task.billing_country), None)
    if not rule:
        raise ValueError('计费国家无有效价格')
    return Decimal(str(rule['unit_price']))


def charge_success(db, task, kind, row):
    if row.charged:
        return
    amount = task_price(db, task, kind)
    if not amount:
        return
    before = m.current_balance(db)
    db.add(m.BalanceTransaction(type='consume', amount=-amount, balance_before=before,
                                balance_after=before-amount, currency=m.get_setting(db, 'currency', 'USDT'),
                                country=task.billing_country, task=task.task_name, task_type=kind,
                                task_id=task.id, result='success', remark=f'执行明细 #{row.id} 成功执行'))
    row.charged = True


def run_task(kind, task_id, mode=None):
    # Discovery may span tenants; execution and billing always use the task owner.
    with m.system_session() as lookup:
        tenant_id = lookup.query(task_model(kind).tenant_id).filter_by(id=task_id).scalar()
        tenant = lookup.get(m.Tenant, tenant_id) if tenant_id else None
        if not tenant or tenant.status != 'active':
            return
    key = (kind, task_id)
    with _lock_guard:
        lock = _task_locks.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        return
    try:
        with m.SessionLocal(info={'tenant_id': tenant_id}) as db:
            with _channel_lock:
                task = get_task(kind, task_id, db)
                if _stop.is_set() or task.status not in ('pending','running'):
                    return
                if task.scheduled_at and task.scheduled_at > datetime.now():
                    return
                if not targets(kind, task):
                    raise ValueError('任务没有可用目标')
                task.mode = mode or task.mode or ('real' if m.real_send_enabled() else 'mock')
                ensure_records(kind, task, db)
                task.status, task.last_error = 'running', ''
                write_log(db, kind, task_id, 'running', '任务开始执行')
                db.commit()
                row_ids = [r.id for r in db.query(m.TaskExecution).filter_by(task_kind=kind, task_id=task_id, status='pending').order_by(m.TaskExecution.id)]
            for row_id in row_ids:
                db.expire_all()
                task = get_task(kind, task_id, db)
                tenant = db.get(m.Tenant, tenant_id)
                if not tenant or tenant.status != 'active':
                    task.status, task.last_error = 'paused', '租户已停用，任务暂停'
                    db.commit()
                    break
                row = db.get(m.TaskExecution, row_id)
                if task.status != 'running' or _stop.is_set():
                    break
                try:
                    account = select_account(db, task, row)
                except Exception as exc:
                    with _channel_lock:
                        row.status, row.error = 'failed', str(exc)[:2000]
                        task.last_error = row.error
                        write_log(db,kind,task_id,'failed',row.error,row)
                        sync_counts(kind,task,db); db.commit()
                    continue
                with account_lock(account):
                    db.refresh(task); db.refresh(account); db.refresh(row)
                    if task.status != 'running' or _stop.is_set():
                        break
                    price = task_price(db, task, kind)
                    # Billable requests hold the ledger lock until their result is known,
                    # preventing two accounts from spending the same available funds.
                    # Free requests run in parallel across accounts.
                    with _channel_lock if price else nullcontext():
                        try:
                            with _channel_lock:
                                row.account_id = account.id
                                if account.status != 'normal':
                                    raise ValueError('执行账号已暂停或异常')
                                if price and m.current_balance(db) < price:
                                    raise ValueError('余额不足，请充值后重试')
                                row.status = 'executing'; row.attempts += 1
                                db.commit()
                            with db.no_autoflush:
                                response = dispatch_target(kind, task, row, account, db)
                            if not response.get('success'):
                                raise ValueError(str(response.get('message') or '通道执行失败'))
                            with _channel_lock:
                                row.status, row.error = 'succeeded', ''
                                row.message_id = str(response.get('message_id') or '')
                                charge_success(db,task,kind,row)
                                apply_saved_receipt(db,row)
                                write_log(db,kind,task_id,'success','模拟执行成功' if task.mode=='mock' else '通道已接受请求；回执单独更新',row)
                                sync_counts(kind,task,db); db.commit()
                        except (TimeoutError, OSError) as exc:
                            with _channel_lock:
                                row.status, row.error = 'uncertain', f'执行结果不确定，请先核对通道记录：{exc}'
                                task.last_error = row.error
                                write_log(db,kind,task_id,'uncertain',row.error,row)
                                sync_counts(kind,task,db); db.commit()
                        except Exception as exc:
                            with _channel_lock:
                                row.status, row.error = 'failed', str(exc)[:2000]
                                task.last_error = row.error
                                write_log(db,kind,task_id,'failed',row.error,row)
                                sync_counts(kind,task,db); db.commit()
                    if task.mode != 'mock':
                        deadline = time.monotonic()+m.send_interval_seconds(db)
                        while time.monotonic() < deadline and not _stop.wait(.2):
                            db.refresh(task)
                            if task.status != 'running':
                                break
            with _channel_lock:
                db.refresh(task)
                rows = sync_counts(kind,task,db)
                if task.status == 'running' and not _stop.is_set():
                    task.status = 'pending' if any(r.status in ('pending','executing') for r in rows) else 'failed' if task.failed else 'done'
                    write_log(db,kind,task_id,task.status,f'任务结束，失败 {task.failed} 个目标')
                db.commit()
    except Exception as exc:
        with m.SessionLocal(info={'tenant_id': tenant_id}) as db:
            task = db.get(task_model(kind), task_id)
            if task:
                for interrupted in db.query(m.TaskExecution).filter_by(task_kind=kind,task_id=task_id,status='executing'):
                    interrupted.status = 'uncertain'
                    interrupted.error = '执行中发生内部错误，通道结果需人工核对'
                task.status = 'failed'
                task.last_error = str(exc)[:2000]
                sync_counts(kind,task,db)
                write_log(db, kind, task_id, 'failed', task.last_error)
                db.commit()
    finally:
        lock.release()


def task_detail(kind, task_id, db):
    task = get_task(kind, task_id, db)
    total = len(targets(kind, task))
    data = {'task_id': task.id, 'task_name': task.task_name, 'status': task.status,
            'account_ids': [int(x) for x in ids(task.account_ids)], 'targets': total,
            'failed': task.failed or 0, 'last_error': task.last_error or '',
            'mode': task.mode or 'legacy', 'scheduled_at': m._dt(task.scheduled_at), 'created_at': m._dt(task.created_at)}
    if kind == 'mass-send':
        data.update(target_type=task.target_type, target_ids=[int(x) for x in ids(task.target_ids)],
                    message_content=task.message_content, link_url=task.link_url,
                    sent=task.sent or 0, accepted=task.accepted or 0, delivered=task.delivered or 0,
                    read=task.read_count or 0, ad_message_id=task.ad_message_id)
        processed = task.sent or 0
    else:
        data.update(target_group_id=task.target_group_id, source_type=task.source_type,
                    source_ids=[int(x) for x in ids(task.source_ids)], processed=task.processed or 0,
                    succeeded=task.succeeded or 0)
        processed = task.processed or 0
    data['progress'] = m._rate(processed, total)
    return data


def apply_saved_receipt(db, row):
    if not row.message_id:
        return
    receipt = db.query(m.ReceiptEvent).filter_by(message_id=f'{row.account_id}:{row.message_id}', target=row.target).first()
    if receipt is None:
        owners = {r.account_id for r in db.query(m.TaskExecution).filter_by(message_id=row.message_id,target=row.target,status='succeeded')}
        if len(owners) <= 1:
            receipt = db.query(m.ReceiptEvent).filter_by(message_id=row.message_id,target=row.target).first()
    if receipt:
        now = receipt.received_at
        row.delivered_at = row.delivered_at or now
        if receipt.status == 'read':
            row.read_at = row.read_at or now


def reconcile_receipt(message_id, target, status, db, account_id=None):
    if not message_id or not target or status not in ('delivered', 'read'):
        raise HTTPException(422, '回执字段无效')
    if account_id is not None and not db.get(m.AccountPool, account_id):
        raise HTTPException(422, '回执账号不存在或不属于当前租户')
    q = db.query(m.TaskExecution).filter_by(message_id=message_id, target=target, task_kind='mass-send', status='succeeded')
    if account_id is not None:
        q = q.filter_by(account_id=account_id)
    else:
        owners = {r.account_id for r in q.all()}
        if len(owners) > 1:
            raise HTTPException(422, '回执对应多个账号，必须指定 account_id')
        if not owners:
            raise HTTPException(422,'回执尚未匹配执行记录，请指定 account_id')
        account_id = next(iter(owners))
    receipt_key = f'{account_id}:{message_id}' if account_id is not None else message_id
    event = db.query(m.ReceiptEvent).filter_by(message_id=receipt_key, target=target).first()
    if not event:
        event = m.ReceiptEvent(message_id=receipt_key, target=target, status=status)
        db.add(event)
    elif event.status == 'read' or event.status == status:
        return q.count()
    elif status == 'read':
        event.status = 'read'
    db.flush()
    rows = q.all()
    for row in rows:
        apply_saved_receipt(db, row)
        task = db.get(m.MassSendTask, row.task_id)
        if task:
            sync_counts('mass-send', task, db)
    db.commit()
    return len(rows)


class ReceiptRequest(BaseModel):
    account_id: int | None = None
    message_id: str = Field(min_length=1, max_length=255)
    target: str = Field(min_length=1, max_length=255)
    status: str


@router.post('/providers/receipts')
def receipt_callback(req: ReceiptRequest, authorization: str = Header(''), db=Depends(m.get_db)):
    import secrets
    expected = os.environ.get('RECEIPT_WEBHOOK_TOKEN', '')
    if not expected or not secrets.compare_digest(authorization, 'Bearer ' + expected):
        raise HTTPException(401, '回执认证失败')
    with m.system_session() as lookup:
        if req.account_id is not None:
            tenant_id = lookup.query(m.AccountPool.tenant_id).filter_by(id=req.account_id).scalar()
        else:
            owners = lookup.query(m.TaskExecution.account_id, m.TaskExecution.tenant_id).filter_by(
                message_id=req.message_id, target=req.target, task_kind='mass-send', status='succeeded').distinct().all()
            if len(owners) != 1:
                raise HTTPException(422, '回执未唯一匹配账号，请指定 account_id')
            req.account_id, tenant_id = owners[0]
    if tenant_id is None:
        raise HTTPException(422, '回执账号不存在')
    m.bind_tenant(db, tenant_id)
    with _channel_lock:
        return {'code': 0, 'data': {'matched': reconcile_receipt(req.message_id, req.target, req.status, db, req.account_id)}}


@router.get('/tasks/{kind}/{task_id}/executions')
def executions(kind: str, task_id: int, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200), db=Depends(m.get_db), user=Depends(m.current_user)):
    task = get_task(kind, task_id, db)
    q = db.query(m.TaskExecution).filter_by(task_kind=kind, task_id=task_id)
    rows = q.order_by(m.TaskExecution.id).offset((page-1)*size).limit(size).all()
    return {'code': 0, 'data': {'total': q.count(), 'page': page, 'size': size,
        'list': [{'id': r.id, 'target_id': r.target_id, 'target': r.target, 'account_id': r.account_id,
                  'status': r.status, 'attempts': r.attempts, 'error': r.error, 'message_id': r.message_id,
                  'delivered_at': m._dt(r.delivered_at), 'read_at': m._dt(r.read_at), 'charged': r.charged} for r in rows]}}


@router.get('/tasks/{kind}/{task_id}/logs')
def logs(kind: str, task_id: int, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200), db=Depends(m.get_db), user=Depends(m.current_user)):
    get_task(kind, task_id, db)
    q = db.query(m.TaskLog).filter_by(task_kind=kind, task_id=task_id)
    return {'code': 0, 'data': {'total': q.count(), 'page': page, 'size': size,
        'list': [{'id': r.id, 'account_id': r.account_id, 'target': r.target, 'action': r.action, 'result': r.result,
                  'detail': r.detail or '历史日志未保存详细原因', 'created_at': m._dt(r.created_at)}
                 for r in q.order_by(m.TaskLog.id.desc()).offset((page-1)*size).limit(size).all()]}}


class ExecutionResolution(BaseModel):
    status: str
    note: str = Field(min_length=5, max_length=1000)
    message_id: str = Field(default='', max_length=255)


@router.patch('/tasks/{kind}/{task_id}/executions/{execution_id}')
def resolve_execution(kind: str, task_id: int, execution_id: int, req: ExecutionResolution, db=Depends(m.get_db), user=Depends(m.require_admin)):
    if req.status not in ('succeeded', 'failed'):
        raise HTTPException(422, '核对结果只能是成功或失败')
    with _channel_lock:
        task = get_task(kind, task_id, db)
        row = db.query(m.TaskExecution).filter_by(id=execution_id, task_kind=kind, task_id=task_id).first()
        if not row:
            raise HTTPException(404, '执行记录不存在')
        if row.status != 'uncertain':
            raise HTTPException(409, '仅可核对结果不确定的目标')
        row.status, row.error = req.status, '' if req.status == 'succeeded' else req.note
        row.message_id = req.message_id
        if row.status == 'succeeded':
            charge_success(db, task, kind, row)
            apply_saved_receipt(db, row)
        write_log(db, kind, task_id, req.status, f'{user.username} 人工核对：{req.note}', row, 'resolve')
        sync_counts(kind, task, db)
        if not task.failed and not db.query(m.TaskExecution).filter_by(task_kind=kind, task_id=task_id, status='pending').count():
            task.status = 'done'
            task.last_error = ''
        db.commit()
        return {'code': 0, 'data': task_detail(kind, task_id, db)}


@router.post('/tasks/{kind}/{task_id}/{action}')
def control(kind: str, task_id: int, action: str, background: BackgroundTasks, db=Depends(m.get_db), user=Depends(m.current_user)):
    task = get_task(kind, task_id, db)
    allowed = {'pause': ('pending', 'running'), 'cancel': ('pending', 'running', 'paused'),
               'resume': ('paused',), 'retry': ('failed',)}
    if action not in allowed:
        raise HTTPException(404, '操作不存在')
    if task.status not in allowed[action]:
        raise HTTPException(409, '当前任务状态不允许该操作')
    if action == 'retry':
        ensure_records(kind, task, db)
        if db.query(m.TaskExecution).filter_by(task_kind=kind, task_id=task_id, status='uncertain').count():
            raise HTTPException(409, '存在结果不确定的目标，请先核对通道记录，禁止直接重发')
        db.query(m.TaskExecution).filter_by(task_kind=kind, task_id=task_id, status='failed').update({'status': 'pending', 'error': ''})
    task.status = {'pause': 'paused', 'cancel': 'cancelled', 'resume': 'pending', 'retry': 'pending'}[action]
    write_log(db, kind, task_id, task.status, f'{user.username} 执行 {action}', action=action)
    db.commit()
    if action in ('resume', 'retry'):
        background.add_task(run_task, kind, task_id)
    return {'code': 0, 'data': task_detail(kind, task_id, db)}


def fetch_links(group_ids, db):
    if not group_ids:
        raise HTTPException(422,'请选择资源群')
    if not m.real_send_enabled() or m.MESSAGE_PROVIDER != 'wasock':
        raise HTTPException(409,'获取真实群链接需要启用真实 wasock 通道并登录账号')
    updated, failures = 0, []
    from whatsapp_session import auth_path
    for group_id in dict.fromkeys(group_ids):
        try:
            group = db.get(m.ResourceGroup,group_id)
            if not group:
                raise ValueError('资源群不存在')
            account = db.get(m.AccountPool,group.owner_account_id) if group.owner_account_id else None
            if not account or not account.session_name:
                raise ValueError('资源群没有关联执行账号，请先设置所属账号')
            with account_lock(account):
                activate_account(account,db)
                result = m.wasock_request({'action':'groupInviteCode','authName':str(auth_path(account.session_name)),'chat':group.group_jid})
                if not result.get('success') or not result.get('code'):
                    raise ValueError(result.get('message') or '未获取到群链接')
                with _channel_lock:
                    group.group_link = 'https://chat.whatsapp.com/'+result['code']
                    db.commit()
                    updated += 1
        except Exception as exc:
            db.rollback()
            failures.append({'id':group_id,'reason':str(exc)})
    return {'code':0,'data':{'updated':updated,'failures':failures,'message':f'已更新 {updated} 个群链接，失败 {len(failures)} 个'}}


def poll_receipts():
    if m.MESSAGE_PROVIDER != 'wasock' or not m.real_send_enabled():
        return
    try:
        offset = 0
        while not _stop.is_set():
            result = m.wasock_request({'action': 'getReceipts', 'offset': offset, 'limit': 500}, timeout=2)
            if not result.get('success'):
                return
            with m.system_session() as lookup:
                from whatsapp_session import auth_path
                account_by_path = {str(auth_path(a.session_name).resolve()):(a.id, a.tenant_id) for a in lookup.query(m.AccountPool).filter(m.AccountPool.session_name != '', m.AccountPool.session_name.isnot(None))}
            for receipt in result.get('receipts', []):
                name = receipt.get('auth_name')
                owner = account_by_path.get(str(auth_path(name).resolve())) if name else None
                if owner is None:
                    continue
                account_id, tenant_id = owner
                with _channel_lock, m.SessionLocal(info={'tenant_id': tenant_id}) as db:
                    reconcile_receipt(receipt['message_id'],receipt['target'],receipt['status'],db,account_id)
            next_offset = result.get('next_offset')
            if next_offset is None or next_offset <= offset:
                return
            offset = next_offset
    except Exception:
        pass  # Health endpoint reports outages; retained receipts are retried next poll.


def restore_sessions():
    if not m.WHATSAPP_SESSION_AVAILABLE:
        return
    with m.system_session() as lookup:
        active = {t.id for t in lookup.query(m.Tenant).filter_by(status='active')}
        names = [(a.session_name,a.tenant_id) for a in lookup.query(m.AccountPool).filter_by(status='normal',session_enabled=True) if a.session_name and a.tenant_id in active]
    for name,tenant_id in names:
        if _stop.is_set():
            break
        if not m.read_paired_phone(name):
            continue
        session = m.get_session(name)
        if session.snapshot()['status'] in ('connected','starting','waiting_qr'):
            continue
        lock = account_session_lock(name)
        if not lock.acquire(blocking=False):
            continue
        try:
            from account_management_api import proxy_for_session
            with m.SessionLocal(info={'tenant_id': tenant_id}) as db:
                session.start(name,proxy_override=proxy_for_session(db, name))
        finally:
            lock.release()


def scheduler_loop():
    restored_at = 0
    while not _stop.wait(2):
        with m.system_session() as db:
            for kind in ('mass-send', 'pull-group'):
                tasks = db.query(task_model(kind)).filter(task_model(kind).status == 'pending', task_model(kind).mode.in_(['real', 'mock'])).all()
                for task in tasks:
                    if not task.scheduled_at or task.scheduled_at <= datetime.now():
                        key = (kind, task.id)
                        with _lock_guard:
                            lock = _task_locks.get(key)
                        if lock is None or not lock.locked():
                            threading.Thread(target=run_task, args=(kind, task.id), daemon=True).start()
        poll_receipts()
        if time.monotonic()-restored_at > 30:
            restored_at = time.monotonic()
            threading.Thread(target=restore_sessions,daemon=True).start()


def startup():
    global _scheduler
    _stop.clear()
    __import__('mobile_maintenance').start()
    with m.system_session() as lookup:
        tenant_ids = [t.id for t in lookup.query(m.Tenant).all()]
    for tenant_id in tenant_ids:
        with m.SessionLocal(info={'tenant_id': tenant_id}) as db:
            # An interrupted external call may have succeeded: surface uncertainty instead of duplicating it.
            for row in db.query(m.TaskExecution).filter_by(status='executing').all():
                row.status = 'uncertain'
                row.error = '进程中断，通道执行结果需人工核对'
            for kind in ('mass-send', 'pull-group'):
                for legacy in db.query(task_model(kind)).filter(task_model(kind).status.in_(['pending', 'running']), task_model(kind).mode == '').all():
                    legacy.status = 'paused'
                    legacy.last_error = '历史任务缺少执行记录，请核对后手动恢复'
                for task in db.query(task_model(kind)).filter_by(status='running').all():
                    rows = sync_counts(kind, task, db)
                    if any(r.status == 'uncertain' for r in rows):
                        task.status, task.last_error = 'failed', '存在进程中断的执行记录，请核对后处理'
                    else:
                        task.status = 'pending'
            db.commit()
    _scheduler = threading.Thread(target=scheduler_loop, daemon=True)
    _scheduler.start()


def shutdown():
    _stop.set()
    __import__('mobile_maintenance').stop()
    if _scheduler:
        _scheduler.join(timeout=3)
    if m.WHATSAPP_SESSION_AVAILABLE:
        __import__('whatsapp_session').detach_sessions()


def register(app):
    app.include_router(router)
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lifespan(application):
        startup()
        try:
            yield
        finally:
            shutdown()
    app.router.lifespan_context = lifespan
