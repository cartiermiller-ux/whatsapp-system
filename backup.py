"""Consistent database backups; PostgreSQL passwords never enter command arguments."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import uuid
from sqlalchemy.engine import make_url

BASE = Path(__file__).resolve().parent


def database_url():
    return os.environ.get('WHATSAPP_DATABASE_URL') or os.environ.get('DATABASE_URL') or 'sqlite:///' + (BASE / 'whatsapp.db').as_posix()


def backup_database(url, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    parsed = make_url(url)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    suffix = '.db' if parsed.get_backend_name() == 'sqlite' else '.dump'
    destination = directory / ('whatsapp-' + stamp + suffix)
    temporary = destination.with_suffix(suffix + '.partial')
    try:
        with temporary.open('xb'):
            pass
        temporary.chmod(0o600)
        if parsed.get_backend_name() == 'sqlite':
            source = Path(parsed.database).resolve()
            if not source.is_file():
                raise ValueError('Source database does not exist')
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as connection:
                with sqlite3.connect(temporary) as output:
                    connection.backup(output)
                    if output.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('SQLite backup integrity check failed')
        elif parsed.get_backend_name() == 'postgresql':
            environment = os.environ.copy()
            environment['PGPASSWORD'] = parsed.password or ''
            command = ['pg_dump', '--format=custom', '--no-owner', '--no-acl',
                       '--host', parsed.host or '127.0.0.1', '--port', str(parsed.port or 5432),
                       '--username', parsed.username or '', '--dbname', parsed.database,
                       '--file', str(temporary)]
            subprocess.run(command, env=environment, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            subprocess.run(['pg_restore', '--list', str(temporary)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        else:
            raise ValueError('Unsupported database backend')
        if temporary.stat().st_size == 0:
            raise ValueError('Empty backup')
        temporary.replace(destination)
        destination.chmod(0o600)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', default=os.environ.get('WHATSAPP_BACKUP_DIR', str(BASE / 'backup')))
    args = parser.parse_args()
    try:
        print('BACKUP_OK', backup_database(database_url(), args.output_dir))
    except Exception as error:
        raise SystemExit('BACKUP_FAILED: ' + type(error).__name__)
