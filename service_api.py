"""Service configuration and read-only health checks."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from providers import get_sms_provider, get_proxy_provider, get_account_provider
import main as m
import operations
import service_config

router = APIRouter(prefix='/api/v1/providers')
_health = {'checked_at': None, 'items': []}


@router.get('/config')
def read_config(user=Depends(m.require_platform_admin)):
    return {'code': 0, 'data': service_config.schema()}


@router.put('/config')
def update_config(payload: dict[str, str], db=Depends(m.get_db), user=Depends(m.require_platform_admin)):
    # Avoid live provider replacement during an in-flight external request.
    if not operations._channel_lock.acquire(blocking=False):
        raise HTTPException(409, '任务正在执行，请暂停任务后修改服务配置')
    try:
        active = db.query(m.MassSendTask).filter_by(status='running').count()+db.query(m.InviteTask).filter_by(status='running').count()
        if active:
            raise HTTPException(409,'有任务正在执行，请结束任务后修改服务配置')
        service_config.save(payload)
        m.MESSAGE_PROVIDER = __import__('os').environ.get('MESSAGE_PROVIDER', 'wasock')
        m.PROXY_REQUIRED = __import__('os').environ.get('PROXY_REQUIRED', 'false') == 'true'
        m._message_provider = None
        get_sms_provider(refresh=True)
        get_proxy_provider(refresh=True)
        get_account_provider(refresh=True)
        _health.update(checked_at=None, items=[])
        m.log_operation(db, 'configure_services', target=', '.join(payload), detail='服务配置已更新（密钥不记录）', user=user)
        return {'code': 0, 'data': service_config.schema()}
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    finally:
        operations._channel_lock.release()


@router.get('/health')
def cached_health(user=Depends(m.current_user)):
    return {'code': 0, 'data': _health}


@router.post('/health')
def check_health(user=Depends(m.require_platform_admin)):
    items = []
    for provider in (m.get_message_provider(), get_sms_provider(), get_proxy_provider(), get_account_provider()):
        result = {'kind': provider.kind, 'name': provider.name, 'state': 'unknown', 'detail': ''}
        try:
            if provider.mock:
                result.update(state='mock', detail='模拟服务，不代表真实服务可用')
            elif not provider.is_configured():
                result.update(state='unconfigured', detail='缺少服务配置')
            elif provider.kind == 'message':
                if provider.name == 'wasock':
                    ready, detail = provider.is_ready()
                    result.update(state='healthy' if ready else 'failed', detail=detail or 'WhatsApp 会话已连接')
                else:
                    result.update(state='unknown', detail='HTTP 消息通道未提供无副作用探测接口；不发送测试消息')
            elif provider.kind == 'sms':
                balance = provider.balance()
                result.update(state='healthy' if balance is not None else 'unknown', detail='余额查询成功' if balance is not None else '供应商未提供余额探测')
            elif provider.kind == 'account':
                provider.list_products()
                result.update(state='healthy', detail='商品查询成功')
            else:
                proxies = provider.list_proxies(limit=1)
                if not proxies:
                    result.update(state='failed', detail='没有可用代理')
                else:
                    ok, detail = m.test_proxy_conn(proxies[0], timeout=5)
                    result.update(state='healthy' if ok else 'failed', detail=detail)
        except Exception:
            # Provider exceptions can include request URLs or credential fragments.
            result.update(state='failed', detail='服务探测失败，请检查密钥、网络及供应商状态')
        items.append(result)
    _health.update(checked_at=m._dt(datetime.now()), items=items)
    return {'code': 0, 'data': _health}
