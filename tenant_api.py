"""Platform-only tenant administration; business pages retain their own tenant scope."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
import main as m

router = APIRouter(prefix='/api/v1/admin/tenants')


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class TenantStatus(BaseModel):
    status: Literal['active', 'disabled']


@router.get('')
def list_tenants(db=Depends(m.get_db), user=Depends(m.require_platform_admin)):
    return {'code': 0, 'data': [{'id': row.id, 'name': row.name, 'status': row.status,
        'created_at': m._dt(row.created_at), 'users': db.query(m.User).filter_by(tenant_id=row.id).count()}
        for row in db.query(m.Tenant).order_by(m.Tenant.id)]}


@router.post('')
def create_tenant(req: TenantCreate, db=Depends(m.get_db), user=Depends(m.require_platform_admin)):
    name = req.name.strip()
    if not name or db.query(m.Tenant).filter_by(name=name).first():
        raise HTTPException(422, '租户名称为空或已存在')
    row = m.Tenant(name=name)
    db.add(row); db.commit(); db.refresh(row)
    m.log_operation(db, 'create_tenant', target=str(row.id), detail='创建租户', user=user)
    return {'code': 0, 'data': {'id': row.id, 'name': row.name, 'status': row.status}}


@router.put('/{tenant_id}')
def update_tenant(tenant_id: int, req: TenantStatus, db=Depends(m.get_db), user=Depends(m.require_platform_admin)):
    row = db.get(m.Tenant, tenant_id)
    if row is None:
        raise HTTPException(404, '租户不存在')
    if tenant_id == user.tenant_id and req.status == 'disabled':
        raise HTTPException(422, '不能停用当前登录账号所属租户')
    row.status = req.status
    if row.status == 'disabled':
        for member in db.query(m.User).filter_by(tenant_id=tenant_id):
            m.revoke_user_tokens(member.id)
    db.commit()
    m.log_operation(db, 'update_tenant', target=str(row.id), detail=f'租户状态 {row.status}', user=user)
    return {'code': 0, 'data': {'id': row.id, 'name': row.name, 'status': row.status}}
