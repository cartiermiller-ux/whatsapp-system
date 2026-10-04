"""Validate paired accounts and export complete Baileys linked-device sessions."""
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
import main as m
import operations

router = APIRouter(prefix='/api/v1/accounts')
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def session_files(account, db):
    if not account.session_name:
        raise HTTPException(409, '账号尚未扫码关联，没有真实登录会话')
    root = Path(os.environ.get('WHATSAPP_AUTH_ROOT', str(m.BASE_DIR))).resolve()
    directory = Path(account.session_name)
    if not directory.is_absolute():
        directory = m.BASE_DIR / directory
    directory = directory.resolve()
    if directory == root or not directory.is_relative_to(root) or not directory.is_dir():
        raise HTTPException(409, '登录会话目录不存在或不在允许的账号目录内')
    if (directory/'creds.json').is_symlink():
        raise HTTPException(409, '登录凭据不能是符号链接')
    try:
        creds = json.loads((directory/'creds.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise HTTPException(409, 'creds.json 缺失或损坏，请重新扫码关联')
    if not isinstance(creds, dict) or not isinstance(creds.get('me'), dict):
        raise HTTPException(409, '登录凭据格式不正确，请重新扫码关联')
    me = creds.get('me') or {}
    paired = str(me.get('id') or '').split('@')[0].split(':')[0]
    number = db.get(m.NumberPool, account.number_id)
    phone = re.sub(r'\D', '', number.phone_number or '') if number else ''
    if not paired or paired != phone:
        raise HTTPException(409, '登录会话账号与号码池记录不一致，请重新关联正确账号')
    required = ('noiseKey', 'signedIdentityKey', 'signedPreKey', 'registrationId', 'advSecretKey')
    if any(key not in creds or creds[key] in (None, '') for key in required):
        raise HTTPException(409, '登录凭据参数不完整，请重新扫码关联')
    files = {}
    total = 0
    for file in sorted(directory.iterdir()):
        if file.suffix != '.json' or file.name in ('receipts.json',):
            continue
        if file.is_symlink() or not file.is_file():
            raise HTTPException(409, '会话包含不安全的文件路径')
        if total + file.stat().st_size > MAX_ARCHIVE_BYTES:
            raise HTTPException(413, '会话文件过大，请联系管理员处理')
        content = file.read_bytes()
        total += len(content)
        if total > MAX_ARCHIVE_BYTES:
            raise HTTPException(413, '会话文件过大，请联系管理员处理')
        try:
            json.loads(content)
        except ValueError:
            raise HTTPException(409, f'会话文件损坏：{file.name}')
        files[file.name] = content
    if len(files) < 2:
        raise HTTPException(409, '会话密钥文件缺失，请重新扫码关联')
    return files, phone


def convert_one(account_id, db):
    account = db.get(m.AccountPool, account_id)
    if not account:
        raise HTTPException(404, '账号不存在')
    files, phone = session_files(account, db)
    account.full_params_ready = True
    account.converted_at = datetime.now()
    db.commit()
    return {'account_id': account.id, 'phone': phone, 'files': len(files), 'full_params_ready': True}


@router.post('/{account_id}/convert')
def convert_account(account_id: int, db=Depends(m.get_db), user=Depends(m.require_admin)):
    with operations._channel_lock:
        result = convert_one(account_id, db)
        m.log_operation(db, 'convert_account', target=str(account_id), detail='验证完整会话参数成功', user=user)
        return {'code': 0, 'data': result}


@router.post('/convert')
def convert_accounts(req: m.BatchIdsRequest, db=Depends(m.get_db), user=Depends(m.require_admin)):
    if not req.ids or len(req.ids) > 100:
        raise HTTPException(422, '每次转换 1 至 100 个账号')
    converted, failures = [], []
    with operations._channel_lock:
        for account_id in dict.fromkeys(req.ids):
            try:
                converted.append(convert_one(account_id, db))
            except HTTPException as exc:
                failures.append({'id': account_id, 'reason': exc.detail})
        m.log_operation(db, 'convert_accounts', detail=f'成功 {len(converted)} 个，失败 {len(failures)} 个', user=user)
    return {'code': 0, 'data': {'converted': converted, 'failures': failures}}


def build_archive(account_ids, db, user, record=True):
    if not account_ids or len(account_ids) > 100:
        raise HTTPException(422, '每次导出 1 至 100 个账号')
    archive = io.BytesIO()
    manifest = {'format': 'baileys-multi-file-auth', 'version': 1, 'exported_at': datetime.now().isoformat(), 'accounts': []}
    total = 0
    with operations._channel_lock, zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for account_id in dict.fromkeys(account_ids):
            account = db.get(m.AccountPool, account_id)
            if not account:
                raise HTTPException(404, f'账号 #{account_id} 不存在')
            if not account.full_params_ready:
                raise HTTPException(409, f'账号 #{account_id} 尚未转换全参，请先转换')
            try:
                files, phone = session_files(account, db)
            except HTTPException as exc:
                raise HTTPException(exc.status_code, f'账号 #{account_id}：{exc.detail}')
            prefix = f'account-{account_id}/session'
            for name, content in files.items():
                total += len(content)
                if total > MAX_ARCHIVE_BYTES:
                    raise HTTPException(413, '导出超过 100 MB，请减少所选账号')
                output.writestr(f'{prefix}/{name}', content)
            manifest['accounts'].append({'account_id': account_id, 'phone': phone, 'session_path': prefix, 'files': sorted(files)})
        output.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        output.writestr('README.txt', '完整 Baileys 已关联设备登录会话。使用对应 account-ID/session 目录作为 useMultiFileAuthState 的路径。保留全部文件及原始内容。原手机解除设备关联后，此会话将失效。\n')
    if record:
        m.log_operation(db, 'export_accounts', target=','.join(map(str, account_ids)), detail=f'导出 {len(manifest["accounts"])} 个完整会话', user=user)
    return Response(archive.getvalue(), media_type='application/zip', headers={
        'Content-Disposition': 'attachment; filename="whatsapp-accounts.zip"',
        'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'X-Content-Type-Options': 'nosniff'})


@router.post('/export')
def export_accounts(req: m.BatchIdsRequest, db=Depends(m.get_db), user=Depends(m.require_admin)):
    return build_archive(req.ids, db, user)


@router.get('/{account_id}/export')
def export_account(account_id: int, db=Depends(m.get_db), user=Depends(m.require_admin)):
    return build_archive([account_id], db, user)
