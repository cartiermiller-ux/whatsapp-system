"""Resource group import/export/delete endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
import main as m

router = APIRouter(prefix='/api/v1/groups')


class GroupImport(BaseModel):
    group_name: str = Field(min_length=1, max_length=255)
    group_jid: str = Field(min_length=1, max_length=255)
    source_channel: str = Field(default="", max_length=255)
    owner_account_id: int | None = None
    can_speak: bool = True
    can_invite: bool = True
    approval_mode: bool = False


@router.post('/import')
def import_groups(items: list[GroupImport], db=Depends(m.get_db), user=Depends(m.current_user)):
    if not items or len(items) > 5000:
        raise HTTPException(422, '每次导入 1 至 5000 个资源群')
    for item in items:
        if item.owner_account_id is not None and not db.get(m.AccountPool,item.owner_account_id):
            raise HTTPException(422, '所属账号不存在')
        if not __import__('re').fullmatch(r'[0-9-]+@g\.us', item.group_jid):
            raise HTTPException(422, f'群 JID 格式不正确：{item.group_jid}')
    added, updated = 0, 0
    for item in items:
        row = db.query(m.ResourceGroup).filter_by(group_jid=item.group_jid).first()
        if row is None:
            row = m.ResourceGroup(**item.model_dump())
            db.add(row)
            added += 1
        else:
            for key, value in item.model_dump().items():
                if key == 'owner_account_id' and key not in item.model_fields_set:
                    continue
                setattr(row, key, value)
            updated += 1
    db.commit()
    m.log_operation(db, 'import_groups', detail=f'新增 {added} 个，更新 {updated} 个', user=user)
    return {'code': 0, 'data': {'added': added, 'updated': updated}}


@router.get('/export')
def export_groups(keyword: str = '', status: str = '', db=Depends(m.get_db), user=Depends(m.current_user)):
    q = db.query(m.ResourceGroup)
    if keyword:
        q = q.filter(m.ResourceGroup.group_name.contains(keyword))
    if status:
        q = q.filter_by(status=status)
    return {'code': 0, 'data': [{column.name: getattr(row, column.name) for column in m.ResourceGroup.__table__.columns if column.name != 'created_at'} for row in q.order_by(m.ResourceGroup.id).all()]}


@router.delete('')
def delete_groups(req: m.BatchIdsRequest, db=Depends(m.get_db), user=Depends(m.current_user)):
    if not req.ids:
        raise HTTPException(422, '请选择资源群')
    active = db.query(m.InviteTask).filter(m.InviteTask.target_group_id.in_(req.ids), m.InviteTask.status.in_(['pending', 'running', 'paused'])).count()
    mass = db.query(m.MassSendTask).filter(m.MassSendTask.target_type == 'group', m.MassSendTask.status.in_(['pending', 'running', 'paused'])).all()
    if active or any(set(map(str, req.ids)) & set(row.target_ids.split(',')) for row in mass):
        raise HTTPException(409, '资源群被未结束的任务引用，请先取消任务')
    count = db.query(m.ResourceGroup).filter(m.ResourceGroup.id.in_(req.ids)).delete(synchronize_session=False)
    db.commit()
    m.log_operation(db, 'delete_groups', detail=f'删除 {count} 个资源群', user=user)
    return {'code': 0, 'data': {'count': count}}


resources_router = APIRouter(prefix='/api/v1/resources')


def access_rows(db):
    accounts = {a.number_id: a for a in db.query(m.AccountPool).all()}
    result = []
    for number in db.query(m.NumberPool).order_by(m.NumberPool.id.desc()):
        account = accounts.get(number.id)
        paired_phone = m.read_paired_phone(account.session_name) if account and account.session_name and m.WHATSAPP_SESSION_AVAILABLE else ''
        linked = bool(paired_phone and paired_phone == __import__('re').sub(r'\D', '', number.phone_number or ''))
        state = 'success' if linked else 'registering' if number.status == 'registering' else 'failed' if number.status in ('failed','banned') else 'pending'
        reason = number.failure_reason or ''
        if account and not linked and number.status == 'success':
            reason = '历史模拟记录或会话已失效，需要扫码关联已有账号'
        result.append({'id':number.id, 'phone':number.phone_number, 'source_channel':number.source_channel or '未标注来源',
                       'region':number.region or '', 'status':state, 'account_id':account.id if linked else None,
                       'linked':linked, 'reason':reason, 'accessed_at':m._dt(number.register_time) if linked else None})
    return result


@resources_router.get('/access-tasks')
def access_tasks(page:int=Query(1,ge=1), size:int=Query(20,ge=1,le=200), keyword:str='', status:str='', db=Depends(m.get_db), user=Depends(m.current_user)):
    rows = [r for r in access_rows(db) if (not keyword or keyword.lower() in (r['phone']+' '+r['source_channel']).lower()) and (not status or r['status']==status)]
    return {'code':0,'data':{'total':len(rows),'page':page,'size':size,'list':rows[(page-1)*size:page*size]}}


@resources_router.get('/overview')
def resource_overview(db=Depends(m.get_db), user=Depends(m.current_user)):
    platforms = {}
    def platform(source):
        name = (source or '').strip() or '未标注来源'
        return platforms.setdefault(name, {'platform':name,'available_numbers':0,'connected_accounts':0,'groups':0})
    for row in access_rows(db):
        item = platform(row['source_channel'])
        item['available_numbers'] += int(row['status']=='pending')
        item['connected_accounts'] += int(row['linked'])
    for group in db.query(m.ResourceGroup).filter_by(status='active'):
        platform(group.source_channel)['groups'] += 1
    return {'code':0,'data':sorted(platforms.values(),key=lambda r:r['platform'])}
