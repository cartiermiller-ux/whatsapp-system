"""Account presentation data, proxy assignment, activity logs and guarded removal."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
import main as m
import operations

router = APIRouter(prefix='/api/v1/accounts')


def account_rows(db):
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
        session = m.get_session(account.session_name).snapshot() if m.WHATSAPP_SESSION_AVAILABLE and account.session_name else {}
        paired = bool(account.session_name and m.read_paired_phone(account.session_name)) if m.WHATSAPP_SESSION_AVAILABLE else False
        connection = 'unlinked' if not account.session_name else 'invalid' if not paired else 'online' if session.get('status') == 'connected' else 'offline'
        if session.get('status') in ('closed','error'):
            connection = 'error'
        count, success = activity.get(account.id, (0,0))
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
            'session_enabled':bool(account.session_enabled), 'full_params_ready': bool(account.full_params_ready), 'session_name': account.session_name or ''})
    return result


def get_account_row(account_id, db):
    return next((row for row in account_rows(db) if row['id'] == account_id), None)


class ProxyAssignment(BaseModel):
    proxy_id: int


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
        number=db.get(m.NumberPool,account.number_id)
        if number:
            number.account_id=None
        m.release_proxy(db,account.number_id)
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
