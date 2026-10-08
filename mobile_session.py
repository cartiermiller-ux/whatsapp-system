"""Private stdio bridge to the pinned Cobalt mobile client. No secret payloads in logs."""
from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import uuid

BASE = Path(__file__).resolve().parent
MOBILE_TYPES = ('full_params', 'six_segment')


def is_mobile(account):
    return account.device_type in MOBILE_TYPES and not account.session_name


def session_key(account):
    if not account.tenant_id or not account.id:
        raise ValueError('账号缺少租户或账号标识')
    return f't{account.tenant_id}-a{account.id}'


class MobileRuntime:
    def __init__(self):
        self._process = None
        self._start_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending = {}
        self._states = {}

    def configured(self):
        jar = Path(os.environ.get('WA_MOBILE_ENGINE_JAR', str(BASE/'deploy/mobile-engine/mobile-engine.jar')))
        java = os.environ.get('WA_MOBILE_JAVA') or shutil.which('java')
        return bool(java and jar.is_file())

    def _start(self):
        with self._start_lock:
            if self._process and self._process.poll() is None:
                return self._process
            jar = Path(os.environ.get('WA_MOBILE_ENGINE_JAR', str(BASE/'deploy/mobile-engine/mobile-engine.jar')))
            java = os.environ.get('WA_MOBILE_JAVA') or shutil.which('java')
            if not java or not jar.is_file():
                raise ValueError('手机登录引擎未安装，需要 Java 21+ 和 mobile-engine.jar')
            root = Path(os.environ.get('WHATSAPP_AUTH_ROOT', str(BASE))) / 'whatsapp_auth/mobile'
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(root, 0o700)
            env = dict(os.environ, WA_MOBILE_AUTH_ROOT=str(root.resolve()))
            try:
                process = subprocess.Popen([java, '-Xmx512m', '-jar', str(jar.resolve())],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', env=env, cwd=str(BASE))
            except OSError:
                raise ValueError('手机登录引擎无法启动，请检查 Java 安装') from None
            self._process = process
            threading.Thread(target=self._read, args=(process,), daemon=True).start()
            return process

    def _read(self, process):
        try:
            for line in process.stdout:
                try: message = json.loads(line)
                except (ValueError, TypeError): continue
                with self._state_lock:
                    if message.get('event') == 'connection' and isinstance(message.get('data'), dict):
                        self._states[message['session']] = message['data']
                    pending = self._pending.get(message.get('id'))
                if pending:
                    pending.put(message)
        finally:
            with self._state_lock:
                if self._process is process:
                    for key in self._states:
                        self._states[key] = {'status': 'error', 'error': 'engine_stopped', 'phone': ''}
                    for pending in self._pending.values():
                        pending.put({'ok': False, 'error': 'engine_stopped'})

    def request(self, action, key=None, timeout=15, **payload):
        process = self._start()
        request_id = uuid.uuid4().hex
        pending = queue.Queue()
        with self._state_lock: self._pending[request_id] = pending
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(dict(payload, id=request_id, action=action, session=key))+'\n')
                process.stdin.flush()
            response = pending.get(timeout=timeout)
            if not response.get('ok'):
                codes = {'invalid_credentials': '账号凭据与手机引擎格式不兼容', 'engine_stopped': '手机引擎已停止', 'timeout': '手机引擎操作超时'}
                raise ValueError(codes.get(response.get('error'), '手机引擎操作失败，请检查连接状态'))
            return response.get('data', {})
        except queue.Empty:
            raise TimeoutError('手机引擎响应超时') from None
        except (BrokenPipeError, OSError):
            raise ValueError('手机引擎连接中断') from None
        finally:
            with self._state_lock: self._pending.pop(request_id, None)

    def snapshot(self, key):
        with self._state_lock:
            state = dict(self._states.get(key, {'status': 'idle', 'error': '', 'phone': ''}))
        return state

    def connect(self, account, db):
        from workspace_api import ImportedCredential
        credential = db.query(ImportedCredential).filter_by(account_id=account.id).first()
        if not credential: raise ValueError('账号导入凭据不存在')
        import main as m
        number = db.get(m.NumberPool, account.number_id)
        if not number: raise ValueError('账号关联号码不存在')
        proxy = db.query(m.ProxyPool).filter_by(bound_number_id=number.id).first()
        if not proxy: proxy = db.query(m.ProxyPool).filter_by(is_default=True).first()
        if proxy and proxy.provider != 'mock':
            if proxy.status == 'disabled': raise ValueError('账号代理已停用')
            proxy_url = proxy.address
        else:
            proxy_url = (os.environ.get('WA_PROXY_URL', '') if account.tenant_id == 1 else '')
        key = session_key(account)
        with self._state_lock:
            self._states[key] = {'status': 'starting', 'error': '', 'phone': ''}
        try:
            result = self.request('connect', key, format=credential.format, credentials=json.loads(credential.payload),
                phone=number.phone_number.lstrip('+'), account_type=account.account_type, proxy=proxy_url)
            # Events can arrive before the request reply; don't overwrite a completed login.
            with self._state_lock:
                if self._states[key]['status'] == 'starting': self._states[key] = result
            return self.snapshot(key)
        except Exception:
            with self._state_lock: self._states[key] = {'status': 'error', 'error': 'connect_failed', 'phone': ''}
            raise

    def disconnect(self, account):
        key = session_key(account)
        if self._process and self._process.poll() is None:
            self.request('disconnect', key)
        with self._state_lock: self._states[key] = {'status': 'idle', 'error': '', 'phone': ''}

    def presence(self, account, available):
        return self.request('presence', session_key(account), available=available, timeout=25)

    def send(self, account, target, text):
        return self.request('send', session_key(account), target=target, text=text, timeout=35)

    def close(self):
        with self._start_lock:
            process, self._process = self._process, None
            if process and process.poll() is None:
                try:
                    process.stdin.close()
                    process.wait(timeout=8)
                except (OSError, subprocess.TimeoutExpired): process.kill()


runtime = MobileRuntime()
atexit.register(runtime.close)
