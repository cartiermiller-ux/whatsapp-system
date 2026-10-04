"""Operational groups, diagnostics, account imports and export history."""
import base64
import io
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
import main as m
import account_export_api as exports

router = APIRouter(prefix='/api/v1/workspace')

class Collection(m.Base):
    __tablename__ = 'resource_collection'
    __table_args__ = (UniqueConstraint('kind', 'name'),)
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), index=True)
    name = Column(String(100))
    created_at = Column(DateTime, default=datetime.now)

class Inspection(m.Base):
    __tablename__ = 'account_inspection'
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    user_id = Column(Integer)
    result = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

class CollectionRequest(BaseModel):
    kind: Literal['account', 'proxy']
    name: str = Field(min_length=1, max_length=100)

class Assignment(BaseModel):
    kind: Literal['account', 'proxy']
    ids: list[int] = Field(min_length=1, max_length=500)
    group_id: int | None = None

def check_group(db, group_id, kind):
    if group_id is not None:
        row = db.get(Collection, group_id)
        if not row or row.kind != kind:
            raise HTTPException(422, '分组不存在或类型不正确')

@router.get('/groups')
def groups(kind: Literal['account', 'proxy'], db=Depends(m.get_db), user=Depends(m.current_user)):
    model = m.AccountPool if kind == 'account' else m.ProxyPool
    items = db.query(model).all()
    result = []
    for group in db.query(Collection).filter_by(kind=kind).order_by(Collection.id.desc()):
        members = [x for x in items if x.group_id == group.id]
        online = sum(m.get_session(x.session_name).snapshot()['status'] == 'connected' for x in members if kind == 'account' and x.session_name)
        result.append({'id': group.id, 'name': group.name, 'count': len(members), 'online': online,
                       'created_at': m._dt(group.created_at)})
    return {'code': 0, 'data': result}

@router.post('/groups')
def save_group(req: CollectionRequest, db=Depends(m.get_db), user=Depends(m.require_admin)):
    name = req.name.strip()
    if not name or db.query(Collection).filter_by(kind=req.kind, name=name).first():
        raise HTTPException(422, '分组名称为空或已存在')
    row = Collection(kind=req.kind, name=name)
    db.add(row); db.commit()
    m.log_operation(db, 'create_group', target=str(row.id), detail=f'新建{req.kind}分组', user=user)
    return {'code': 0, 'data': {'id': row.id, 'name': row.name}}

@router.put('/groups/{group_id}')
def rename_group(group_id: int, req: CollectionRequest, db=Depends(m.get_db), user=Depends(m.require_admin)):
    check_group(db, group_id, req.kind)
    name = req.name.strip()
    duplicate = db.query(Collection).filter(Collection.kind == req.kind, Collection.name == name, Collection.id != group_id).first()
    if not name or duplicate:
        raise HTTPException(422, '分组名称为空或已存在')
    row = db.get(Collection, group_id); row.name = name; db.commit()
    m.log_operation(db, 'rename_group', target=str(group_id), detail='修改分组名称', user=user)
    return {'code': 0, 'data': {'id': row.id, 'name': name}}

@router.delete('/groups/{group_id}')
def delete_group(group_id: int, db=Depends(m.get_db), user=Depends(m.require_admin)):
    row = db.get(Collection, group_id)
    if not row:
        raise HTTPException(404, '分组不存在')
    model = m.AccountPool if row.kind == 'account' else m.ProxyPool
    if db.query(model).filter_by(group_id=group_id).count():
        raise HTTPException(409, '分组仍有资源，请先移出成员')
    db.delete(row); db.commit()
    m.log_operation(db, 'delete_group', target=str(group_id), user=user)
    return {'code': 0, 'data': {'message': '分组已删除'}}

@router.post('/group-members')
def assign_group(req: Assignment, db=Depends(m.get_db), user=Depends(m.require_admin)):
    check_group(db, req.group_id, req.kind)
    model = m.AccountPool if req.kind == 'account' else m.ProxyPool
    rows = db.query(model).filter(model.id.in_(set(req.ids))).all()
    if len(rows) != len(set(req.ids)):
        raise HTTPException(422, '部分资源不存在')
    for row in rows: row.group_id = req.group_id
    db.commit()
    m.log_operation(db, 'assign_group', target=str(req.group_id or ''), detail=f'{req.kind}资源 {len(rows)} 个', user=user)
    return {'code': 0, 'data': {'updated': len(rows)}}

@router.get('/account-logs')
def account_logs(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), keyword: str = '', db=Depends(m.get_db), user=Depends(m.current_user)):
    q = db.query(m.OperationLog).filter(m.OperationLog.action.in_(['convert_account', 'convert_accounts', 'export_accounts', 'import_sessions', 'assign_group', 'delete_account', 'assign_proxy', 'create_inspection']))
    if keyword: q = q.filter(m.OperationLog.action.contains(keyword) | m.OperationLog.target.contains(keyword))
    return {'code': 0, 'data': {'total': q.count(), 'list': [m.operation_dict(x) if hasattr(m, 'operation_dict') else
        {'id': x.id, 'action': x.action, 'target': x.target, 'result': x.result, 'detail': x.detail, 'username': x.username, 'created_at': m._dt(x.created_at)}
        for x in q.order_by(m.OperationLog.id.desc()).offset((page-1)*size).limit(size)]}}

@router.get('/exports')
def export_history(db=Depends(m.get_db), user=Depends(m.require_admin)):
    q = db.query(m.OperationLog).filter_by(action='export_accounts', user_id=user.id)
    return {'code': 0, 'data': [{'id': row.id, 'filename': f'whatsapp-accounts-{row.id}.zip', 'account_ids': row.target,
            'created_at': m._dt(row.created_at), 'status': 'ready'} for row in q.order_by(m.OperationLog.id.desc()).limit(200)]}

@router.get('/exports/{record_id}/download')
def download_export(record_id: int, db=Depends(m.get_db), user=Depends(m.require_admin)):
    row = db.query(m.OperationLog).filter_by(id=record_id, action='export_accounts', user_id=user.id).first()
    if not row: raise HTTPException(404, '导出记录不存在')
    try: ids = [int(x) for x in row.target.split(',')]
    except ValueError: raise HTTPException(409, '历史导出记录格式无效')
    return exports.build_archive(ids, db, user, record=False)

class InspectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    ids: list[int] = Field(min_length=1, max_length=100)

@router.post('/inspections')
def inspect_accounts(req: InspectionRequest, db=Depends(m.get_db), user=Depends(m.require_admin)):
    if not req.name.strip(): raise HTTPException(422, '请填写检测任务名称')
    accounts = db.query(m.AccountPool).filter(m.AccountPool.id.in_(set(req.ids))).all()
    if len(accounts) != len(set(req.ids)): raise HTTPException(422, '部分账号不存在')
    results = []
    for account in accounts:
        try:
            exports.session_files(account, db)
            valid, reason = True, '会话文件完整；在线状态以实际连接为准'
        except HTTPException as exc:
            valid, reason = False, exc.detail
        snapshot = m.get_session(account.session_name).snapshot() if account.session_name else {}
        results.append({'account_id': account.id, 'session_valid': valid, 'status': snapshot.get('status', 'unlinked'), 'reason': reason})
    row = Inspection(name=req.name.strip(), user_id=user.id, result=json.dumps(results, ensure_ascii=False))
    db.add(row); db.commit()
    m.log_operation(db, 'create_inspection', target=str(row.id), detail=f'检查 {len(results)} 个账号会话', user=user)
    return {'code': 0, 'data': inspection_dict(row)}

def inspection_dict(row):
    results = json.loads(row.result)
    return {'id': row.id, 'name': row.name, 'total': len(results), 'valid': sum(x['session_valid'] for x in results),
            'invalid': sum(not x['session_valid'] for x in results), 'results': results, 'status': 'done', 'created_at': m._dt(row.created_at)}

@router.get('/inspections')
def inspections(db=Depends(m.get_db), user=Depends(m.require_admin)):
    return {'code': 0, 'data': [inspection_dict(x) for x in db.query(Inspection).filter_by(user_id=user.id).order_by(Inspection.id.desc()).limit(200)]}

class SessionImport(BaseModel):
    archive: str = Field(max_length=16*1024*1024)
    group_id: int | None = None
    account_type: Literal['personal', 'business'] = 'personal'

@router.post('/session-import')
def import_sessions(req: SessionImport, db=Depends(m.get_db), user=Depends(m.require_admin)):
    check_group(db, req.group_id, 'account')
    created_dirs = []
    committed = False
    try:
        raw = base64.b64decode(req.archive, validate=True)
        archive = zipfile.ZipFile(io.BytesIO(raw))
        members = archive.infolist()
        if len({x.filename for x in members}) != len(members):
            raise HTTPException(422, '压缩包包含重复路径')
        if len(members) > 5000 or sum(x.file_size for x in members) > exports.MAX_ARCHIVE_BYTES:
            raise HTTPException(413, '压缩包解压后超过限制')
        for entry in members:
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise HTTPException(422, '压缩包包含不安全路径')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 'baileys-multi-file-auth' or manifest.get('version') != 1:
            raise HTTPException(422, '仅支持本系统兼容的完整会话 ZIP；五字段和手机全参需要供应商协议适配')
        records = manifest.get('accounts', [])
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise HTTPException(422, '账号数量无效')
        result = []
        for item in records:
            phone = str(item.get('phone', ''))
            if not re.fullmatch(r'[0-9]{7,20}', phone): raise HTTPException(422, '会话手机号格式无效')
            number = next((n for n in db.query(m.NumberPool).all() if re.sub(r'\D', '', n.phone_number or '') == phone), None)
            if number and db.query(m.AccountPool).filter_by(number_id=number.id).first():
                raise HTTPException(409, '账号已存在，请使用已有登录会话')
            prefix = str(item.get('session_path', '')).rstrip('/') + '/'
            files = [x for x in members if x.filename.startswith(prefix) and x.filename.endswith('.json') and '/' not in x.filename[len(prefix):]]
            if len(files) < 2: raise HTTPException(422, '缺少完整会话文件')
            directory = Path(os.environ.get('WHATSAPP_AUTH_ROOT', str(m.BASE_DIR))).resolve() / 'whatsapp_auth' / ('import_' + uuid.uuid4().hex)
            directory.mkdir(parents=True, mode=0o700); created_dirs.append(directory)
            for entry in files:
                content = archive.read(entry)
                json.loads(content)
                destination = directory / PurePosixPath(entry.filename).name
                destination.write_bytes(content); os.chmod(destination, 0o600)
            if number is None:
                number = m.NumberPool(phone_number=phone, source_type='import', source_channel='会话 ZIP', status='success')
                db.add(number); db.flush()
            account = m.AccountPool(number_id=number.id, session_name=str(directory), group_id=req.group_id,
                                    account_type=req.account_type, device_type='linked', session_enabled=False, status='normal', full_params_ready=True)
            db.add(account); db.flush()
            exports.session_files(account, db)
            number.account_id = account.id; number.status = 'success'
            result.append(account.id)
        db.commit()
        committed = True
        m.log_operation(db, 'import_sessions', target=','.join(map(str, result)), detail=f'导入 {len(result)} 个会话，待连接验证', user=user)
        return {'code': 0, 'data': {'ids': result, 'imported': len(result)}}
    except Exception as exc:
        db.rollback()
        if not committed:
            for directory in created_dirs: shutil.rmtree(directory)
        if isinstance(exc, HTTPException): raise
        raise HTTPException(422, '会话 ZIP 格式无效或文件损坏') from None
