"""Read-only runtime checks. Failure exits nonzero for systemd/journal monitoring."""
import json
import os
import subprocess
import sys
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, text


def check_runtime():
    results = []
    for service in ('whatsapp-api', 'whatsapp-wasock'):
        try:
            result = subprocess.run(['systemctl', 'is-active', '--quiet', service],
                                    timeout=10, capture_output=True)
            ready = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ready = False
        results.append({'check': service, 'ok': ready})

    try:
        request = Request('http://127.0.0.1:8000/openapi.json')
        with urlopen(request, timeout=10) as response:
            document = json.loads(response.read(4 * 1024 * 1024))
        ready = document.get('openapi') is not None and '/api/v1/me' in document.get('paths', {})
    except Exception:
        ready = False
    results.append({'check': 'api_http', 'ok': ready})

    database_url = os.environ.get('WHATSAPP_DATABASE_URL') or os.environ.get('DATABASE_URL')
    engine = None
    try:
        if not database_url or not database_url.startswith(('postgresql:', 'postgresql+')):
            raise ValueError('Explicit PostgreSQL URL required')
        engine = create_engine(database_url, connect_args={'connect_timeout': 5,
            'options': '-c statement_timeout=5000'}, pool_pre_ping=True)
        with engine.connect() as connection:
            ready = connection.execute(text('SELECT 1')).scalar() == 1
    except Exception:
        ready = False
    finally:
        if engine is not None:
            engine.dispose()
    results.append({'check': 'postgresql', 'ok': ready})
    # Never log exception details: URLs and provider errors can expose credentials.
    print(json.dumps({'healthy': all(item['ok'] for item in results), 'checks': results}))
    return all(item['ok'] for item in results)


if __name__ == '__main__':
    sys.exit(0 if check_runtime() else 1)
