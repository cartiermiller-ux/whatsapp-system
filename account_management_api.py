"""Account presentation data, proxy assignment, activity logs and guarded removal."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
import main as m
import operations
from typing import Literal
from mobile_session import runtime as mobile_runtime, is_mobile, session_key

router = APIRouter(prefix='/api/v1/accounts')


def account_rows(db):
    from mobile_maintenance import MobileProgress
    mobile_progress = {p.account_id: p for p in db.query(MobileProgress)}
    numbers = {n.id: n for n in db.query(m.NumberPool).all()}
    proxies = {p.bound_number_id: p for p in db.query(m.ProxyPool).filter(m.ProxyPool.bound_number_id.isnot(None)).all()}
    activity = {row.account_id: (row._mapping['count'], row.success) for row in db.query(
        m.TaskLog.account_id, func.count(m.TaskLog.id).label('count'),
        func.sum(m.case((m.TaskLog.result == 'success', 1), else_=0)).label('success')
    ).filter(m.TaskLog.created_at >= datetime.now()-timedelta(days=7), m.TaskLog.account_id > 0,
             m.TaskLog.result.in_(['success','failed','uncertain'])).group_by(m.TaskLog.account_id)}

    result = []
    for account in db.query(m.AccountPool).order_by(m.AccountPool.id).all():
        number, proxy = numbers.get(account.number_id), proxies.get(account.number_id)
        session = mobile_runtime.snapshot(session_key(account)) if is_mobile(account) else m.get_session(account.session_name).snapshot() if m.WHATSAPP_SESSION_AVAILABLE and account.session_name else {}
        paired = bool(account.session_name and m.read_paired_phone(account.session_name)) if m.WHATSAPP_SESSION_AVAILABLE else False
        connection = ('pending_adapter' if account.device_type in ('full_params', 'six_segment') else 'unlinked') if not account.session_name else 'invalid' if not paired else 'online' if session.get('status') == 'connected' else 'offline'
        if is_mobile(account):
            connection = {'connected': 'online', 'starting': 'starting', 'error': 'error', 'closed': 'offline'}.get(session.get('status'), 'offline' if mobile_runtime.configured() else 'pending_adapter')
        if session.get('status') == 'error' or (not is_mobile(account) and session.get('status') == 'closed'):
            connection = 'error'
        count, success = activity.get(account.id, (0,0))
        progress = mobile_progress.get(account.id)
        network_state = 'unknown'
        if proxy:
            if proxy.provider == 'mock':
                network_state = 'mock'
            elif proxy.status == 'disabled':
                network_state = 'failed'
            elif proxy.last_checked_at and (datetime.now()-proxy.last_checked_at).total_seconds() < 300:
                network_state = 'healthy' if proxy.last_check_ok is True else 'failed' if proxy.last_check_ok is False else 'unknown'
            elif proxy.last_checked_at:
                network_state = 'stale'
        abnormal = account.status != 'normal' or account.health_score < 70 or connection in ('invalid','error') or network_state == 'failed'
        result.append({'id': account.id, 'number_id': account.number_id,
            'group_id': account.group_id, 'account_type': account.account_type or 'personal',
            'device_type': account.device_type or 'linked', 'notes': account.notes or '',
            'phone_number': number.phone_number if number else '', 'health_score': account.health_score,
            'health_source': 'recorded', 'status': account.status, 'nurture_stage': account.nurture_stage,
            'created_at': m._dt(account.created_at),
            'nurture_days': max(1,(datetime.now()-account.nurture_started_at).days+1) if account.nurture_started_at else None,
            'account_age_days': max(1,(datetime.now()-account.created_at).days+1) if account.created_at else None,
            'ip': account.current_ip or (proxy.host if proxy else ''),
            'network_country': proxy.country if proxy else '', 'network_state': network_state,
            'latency_ms': proxy.latency_ms if proxy and proxy.last_checked_at else None,
            'proxy_assigned_at': m._dt(proxy.last_used_at) if proxy else None,
            'connection_state': connection, 'abnormal': abnormal,
            'activity_success_rate': m._rate(success or 0,count) if count else None,
            'mobile_status': session.get('status', '') if is_mobile(account) else '',
            'mobile_error': progress.last_error if progress and progress.last_error else session.get('error', '') if is_mobile(account) else '',
            'online_seconds': progress.online_seconds if progress else 0,
            'session_enabled':bool(account.session_enabled), 'full_params_ready': bool(account.full_params_ready), 'session_name': account.session_name or ''})
    return result


def get_account_row(account_id, db):
    return next((row for row in account_rows(db) if row['id'] == account_id), None)


class ProxyAssignment(BaseModel):
    proxy_id: int


class NurtureAction(BaseModel):
    action: Literal['start', 'pause', 'resume', 'finish']


@router.post('/{account_id}/mobile-connect')
def connect_mobile(account_id: int, db=Depends(m.get_db), user=Depends(m.require_admin)):
    account = db.get(m.AccountPool, account_id)
    if not account or not is_mobile(account): raise HTTPException(422, '请选择已导入的手机全参或六段账号')
    if account.status != 'normal': raise HTTPException(409, '请先恢复账号状态')
    with operations.account_lock(account):
        try: state = mobile_runtime.connect(account, db)
        except (ValueError, TimeoutError) as exc: raise HTTPException(422, str(exc)) from None
        account.session_enabled = True
        from mobile_maintenance import progress_for
        progress = progress_for(account, db)
        progress.failures = 0
        progress.last_error = ''
        progress.next_attempt = None
        db.commit()
    m.log_operation(db, 'mobile_connect', target=str(account.id), detail='手机协议登录已发起，等待服务器确认', user=user)
    return {'code': 0, 'data': state}


@router.post('/{account_id}/mobile-disconnect')
def disconnect_mobile(account_id: int, db=Depends(m.get_db), user=Depends(m.require_admin)):
    account = db.get(m.AccountPool, account_id)
    if not account or not is_mobile(account): raise HTTPException(422, '请选择手机协议账号')
    if account_in_use(db, account_id): raise HTTPException(409, '账号被任务使用，请先结束任务')
    with operations.account_lock(account):
        try: mobile_runtime.disconnect(account)
        except (ValueError, TimeoutError) as exc: raise HTTPException(422, str(exc)) from None
        account.session_enabled = False
        if account.nurture_stage == 'nurturing': account.nurture_stage = 'paused'
        db.commit()
    m.log_operation(db, 'mobile_disconnect', target=str(account.id), detail='手机协议连接已断开', user=user)
    return {'code': 0, 'data': {'status': 'idle'}}


@router.post('/{account_id}/nurture')
def nurture_account(account_id: int, req: NurtureAction, db=Depends(m.get_db), user=Depends(m.require_admin)):
    with operations._channel_lock:
        account = db.get(m.AccountPool, account_id)
        if not account: raise HTTPException(404, '账号不存在')
        with operations.account_lock(account):
            if account_in_use(db, account_id): raise HTTPException(409, '账号被未结束任务使用，请先结束任务')
            allowed = {'start': ('none',), 'pause': ('nurturing',), 'resume': ('paused',), 'finish': ('nurturing',)}
            if account.nurture_stage not in allowed[req.action]:
                raise HTTPException(409, '当前养号阶段不支持此操作')
            if req.action != 'pause':
                if account.status != 'normal': raise HTTPException(409, '账号状态异常，请先处理')
                if is_mobile(account):
                    state = mobile_runtime.snapshot(session_key(account))
                    number = db.get(m.NumberPool, account.number_id)
                    if state.get('status') != 'connected' or not number or state.get('phone') != number.phone_number.lstrip('+'):
                        raise HTTPException(409, '手机账号尚未真实在线，请先登录验证')
                    try: mobile_runtime.presence(account, req.action != 'finish')
                    except (ValueError, TimeoutError) as exc: raise HTTPException(422, str(exc)) from None
                elif not account.session_name:
                    raise HTTPException(409, '账号尚未接入真实登录，无法开始或完成养号')
                elif not m.WHATSAPP_SESSION_AVAILABLE or m.get_session(account.session_name).snapshot().get('status') != 'connected':
                    raise HTTPException(409, '账号未在线，请先连接验证')
                if not is_mobile(account):
                    number = db.get(m.NumberPool, account.number_id)
                    import re
                    if not number or m.read_paired_phone(account.session_name) != re.sub(r'\D', '', number.phone_number or ''):
                        raise HTTPException(409, '登录会话与账号号码不一致')
            account.nurture_stage = {'start': 'nurturing', 'pause': 'paused', 'resume': 'nurturing', 'finish': 'done'}[req.action]
            if req.action == 'start': account.nurture_started_at = datetime.now()
            if req.action in ('start', 'resume'): account.session_enabled = True
            if req.action == 'pause':
                account.session_enabled = False
                if is_mobile(account):
                    try: mobile_runtime.disconnect(account)
                    except (ValueError, TimeoutError): pass
            if is_mobile(account):
                from mobile_maintenance import progress_for
                progress_for(account, db).last_heartbeat = datetime.now() if req.action in ('start', 'resume') else None
            db.commit()
            m.log_operation(db, 'nurture_' + req.action, target=str(account.id), detail='养号阶段变更：' + account.nurture_stage, user=user)
            return {'code': 0, 'data': {'stage': account.nurture_stage}}


def account_in_use(db, account_id):
    for model in (m.MassSendTask,m.InviteTask):
        for task in db.query(model).filter(model.status.in_(['pending','running','paused'])):
            if str(account_id) in operations.ids(task.account_ids):
                return True
    return False


@router.get('/{account_id}/logs')
def account_logs(account_id: int, page: int = Query(1,ge=1), size: int = Query(20,ge=1,le=200), db=Depends(m.get_db), user=Depends(m.current_user)):
    if not db.get(m.AccountPool,account_id):
        raise HTTPException(404,'账号不存在')
    q=db.query(m.TaskLog).filter_by(account_id=account_id)
    return {'code':0,'data':{'total':q.count(),'page':page,'size':size,'list':[
        {'id':row.id,'task_id':row.task_id,'task_kind':row.task_kind,'result':row.result,'detail':row.detail,'target':row.target,'created_at':m._dt(row.created_at)}
        for row in q.order_by(m.TaskLog.id.desc()).offset((page-1)*size).limit(size).all()]}}


@router.post('/{account_id}/proxy')
def assign_proxy(account_id: int, req: ProxyAssignment, db=Depends(m.get_db), user=Depends(m.require_admin)):
    if not operations._channel_lock.acquire(blocking=False):
        raise HTTPException(409,'任务正在执行，请结束任务后更换代理')
    try:
        account=db.get(m.AccountPool,account_id)
        proxy=db.get(m.ProxyPool,req.proxy_id)
        if not account or not db.get(m.NumberPool,account.number_id):
            raise HTTPException(404,'账号或关联号码不存在')
        if not proxy or proxy.status != 'free' or proxy.provider == 'mock':
            raise HTTPException(422,'请选择真实、空闲的代理')
        if account_in_use(db,account_id):
            raise HTTPException(409,'账号被未结束任务引用，请先取消任务')
        # This assignment affects the pool; existing socket requires restart to apply the network proxy.
        for previous in db.query(m.ProxyPool).filter_by(bound_number_id=account.number_id):
            previous.status, previous.bound_number_id = 'free', None
        proxy.status,proxy.bound_number_id='in_use',account.number_id
        proxy.last_used_at=datetime.now()
        db.get(m.NumberPool,account.number_id).proxy_ip=proxy.address
        db.commit()
        m.log_operation(db,'assign_account_proxy',target=str(account_id),detail=f'分配代理 #{proxy.id}',user=user)
        return {'code':0,'data':{'message':'代理已分配；下一次关联该账号时使用新代理'}}
    finally:
        operations._channel_lock.release()


@router.delete('/{account_id}')
def delete_account(account_id: int, db=Depends(m.get_db), user=Depends(m.require_admin)):
    if not operations._channel_lock.acquire(blocking=False):
        raise HTTPException(409,'任务正在执行，请结束任务后删除账号')
    try:
        account=db.get(m.AccountPool,account_id)
        if not account:
            raise HTTPException(404,'账号不存在')
        if account_in_use(db,account_id):
            raise HTTPException(409,'账号被未结束任务引用，请先取消任务')
        if account.session_name:
            with operations.account_lock(account):
                m.get_session(account.session_name).stop()
        elif is_mobile(account):
            with operations.account_lock(account):
                mobile_runtime.disconnect(account)
        number=db.get(m.NumberPool,account.number_id)
        if number:
            number.account_id=None
        m.release_proxy(db,account.number_id)
        from workspace_api import ImportedCredential
        for credential in db.query(ImportedCredential).filter_by(account_id=account_id):
            db.delete(credential)
        from mobile_maintenance import MobileProgress
        for progress in db.query(MobileProgress).filter_by(account_id=account_id): db.delete(progress)
        db.delete(account);db.commit()
        m.log_operation(db,'delete_account',target=str(account_id),detail='删除账号登记，登录会话仍保留供重新关联',user=user)
        return {'code':0,'data':{'deleted':account_id}}
    finally:
        operations._channel_lock.release()


def proxy_for_session(db, auth_name):
    account = db.query(m.AccountPool).filter_by(session_name=auth_name).first()
    number = db.get(m.NumberPool, account.number_id) if account else None
    proxy = db.query(m.ProxyPool).filter_by(bound_number_id=number.id).first() if number else None
    if proxy is None:
        proxy = db.query(m.ProxyPool).filter_by(is_default=True).first()
    if proxy and proxy.provider != 'mock':
        if proxy.status == 'disabled':
            raise HTTPException(422, '账号代理已停用，请到资源对接 → 代理池检查代理')
        return proxy.address
    # The legacy environment proxy belongs to the default workspace only.
    return None if db.info.get('tenant_id') == 1 else ''
