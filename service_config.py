"""Allowlisted runtime configuration; secret values are never returned by the API."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = Path(os.environ.get('WHATSAPP_SERVICE_CONFIG_FILE', str(Path(__file__).resolve().parent / '.runtime' / 'services.json')))
FIELDS = {
 'MESSAGE_PROVIDER': ('消息通道', 'wasock,mock,wsapi', False),
 'USE_REAL_SEND': ('真实任务执行', 'true,false', False),
 'WA_PROXY_URL': ('WhatsApp 出口代理（HTTP / SOCKS5，含认证信息）', 'text', True),
 'REGISTER_MODE': ('注册模式', 'mock,disabled', False),
 'PROXY_REQUIRED': ('注册必须使用代理', 'true,false', False),
 'WSAPI_MESSAGE_ID_FIELD': ('消息 ID 响应字段（可用点分路径）', 'text', False),
 'WSAPI_URL': ('消息 API 地址', 'url', False), 'WSAPI_TOKEN': ('消息 API 密钥', 'text', True),
 'RECEIPT_WEBHOOK_TOKEN': ('回执回调密钥', 'text', True),
 'SMS_PROVIDER': ('接码平台', 'mock,virtualsms,smsactivate', False),
 'VIRTUALSMS_API_KEY': ('VirtualSMS 密钥', 'text', True),
 'VIRTUALSMS_BASE_URL': ('VirtualSMS 地址', 'url', False),
 'SMS_ACTIVATE_API_KEY': ('SMS Activate 密钥', 'text', True),
 'SMS_ACTIVATE_BASE_URL': ('SMS Activate 地址', 'url', False),
 'PROXY_PROVIDER': ('代理供应商', 'mock,byteful,static', False),
 'BYTEFUL_PUBLIC_KEY': ('Byteful 公钥', 'text', True), 'BYTEFUL_PRIVATE_KEY': ('Byteful 私钥', 'text', True),
 'BYTEFUL_BASE_URL': ('Byteful 地址', 'url', False), 'PROXY_LIST': ('静态代理列表', 'text', True),
 'ACCOUNT_PROVIDER': ('账号供应商', 'mock,http', False),
 'ACCOUNT_API_BASE': ('账号采购 API 地址', 'url', False), 'ACCOUNT_API_TOKEN': ('账号采购密钥', 'text', True),
 'PAYMENT_WEBHOOK_SECRET': ('到账核验回调密钥', 'text', True),
}
DEFAULTS = {'MESSAGE_PROVIDER': 'wasock', 'USE_REAL_SEND': 'false', 'REGISTER_MODE': 'mock', 'PROXY_REQUIRED': 'false', 'SMS_PROVIDER': 'mock', 'PROXY_PROVIDER': 'mock', 'ACCOUNT_PROVIDER': 'mock'}


def load():
    if not CONFIG_PATH.exists():
        return
    values = json.loads(CONFIG_PATH.read_text())
    for name, value in values.items():
        if name in FIELDS:
            os.environ[name] = value


def save(payload):
    values = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    for name, value in payload.items():
        if name not in FIELDS or not isinstance(value, str):
            raise ValueError('配置项无效')
        label, kind, secret = FIELDS[name]
        value = value.strip()
        if len(value) > 20000:
            raise ValueError(f'{label} 内容过长')
        if name == 'WA_PROXY_URL' and value:
            parsed = urlparse(value)
            try:
                port = parsed.port
            except ValueError:
                port = None
            if parsed.scheme not in ('http', 'https', 'socks5', 'socks5h') or not parsed.hostname or not port or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
                raise ValueError('WhatsApp 出口代理必须是有效的 HTTP(S) 或 SOCKS5 地址，且包含端口')
        if kind not in ('text', 'url') and value not in kind.split(','):
            raise ValueError(f'{label} 取值无效')
        if kind == 'url' and value:
            parsed = urlparse(value)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f'{label} 必须是有效的 HTTP(S) 地址，认证信息请填入密钥字段')
        values[name] = value
    if values.get('USE_REAL_SEND', os.environ.get('USE_REAL_SEND', 'false')) == 'true' and values.get('MESSAGE_PROVIDER', os.environ.get('MESSAGE_PROVIDER', 'wasock')) == 'mock':
        raise ValueError('真实执行不能使用模拟消息通道')
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_PATH.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as output:
        os.chmod(temp, 0o600)
        json.dump(values, output, ensure_ascii=False)
    os.replace(temp, CONFIG_PATH)
    for name, value in values.items():
        os.environ[name] = value


def schema():
    return [{'key': name, 'label': label, 'secret': secret, 'configured': bool(os.environ.get(name)),
             'value': '' if secret else os.environ.get(name, DEFAULTS.get(name, '')),
             'options': kind.split(',') if kind not in ('url', 'text') else [], 'type': kind}
            for name, (label, kind, secret) in FIELDS.items() if name != 'WA_PROXY_URL']
