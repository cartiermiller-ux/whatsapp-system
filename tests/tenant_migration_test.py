"""Upgrade the committed pre-tenant application database, verify data, then repeat."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def snapshots(path):
    with closing(sqlite3.connect(path)) as db:
        return {table: (columns, db.execute(f'SELECT {", ".join(columns)} FROM "{table}" ORDER BY id').fetchall())
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            for columns in [[row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]]}


class MigrationTests(unittest.TestCase):
    def test_legacy_upgrade_preserves_data_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='wa-tenant-migration-') as temporary:
            directory = Path(temporary)
            archive = directory / 'legacy.tar'
            # HEAD is the deployed pre-tenant revision while this change is under development.
            subprocess.run(['git', 'archive', '--format=tar', '-o', str(archive), 'bd36441'], cwd=ROOT, check=True)
            source = directory / 'legacy'; source.mkdir()
            with tarfile.open(archive) as package:
                package.extractall(source, filter='data')
            database = directory / 'legacy.db'
            environment = dict(os.environ, WHATSAPP_DATABASE_URL='sqlite:///' + database.as_posix(),
                WHATSAPP_SERVICE_CONFIG_FILE=str(directory/'services.json'), USE_REAL_SEND='false',
                AUTO_PROVISION_USERS='false', PYTHONIOENCODING='utf-8')
            code = """import main as m
with m.SessionLocal() as db:
    user=m.create_user(db,'legacy_other','test-pass',tenant='legacy-other',role='operator')
    number=m.NumberPool(phone_number='12025550123',status='pending')
    db.add(number); db.commit()
    db.add(m.AccountPool(number_id=number.id,status='normal')); db.commit()
    db.add(m.RechargeOrder(order_no='LEGACY',amount=10,user_id=user.id,status='pending')); db.commit()
    db.add(m.OperationLog(user_id=user.id,username=user.username,action='login')); db.commit()
    db.add(m.BalanceTransaction(type='recharge',amount=30,balance_before=0,balance_after=30)); db.commit()
print('LEGACY_FIXTURE_READY')
"""
            subprocess.run([sys.executable, '-c', code], cwd=source, env=environment, check=True, capture_output=True)
            before = snapshots(database)
            for _ in range(2):
                result=subprocess.run([sys.executable, '-c', 'import main; print("MIGRATION_READY")'],
                    cwd=ROOT, env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                after = snapshots(database)
                for table,(columns,rows) in before.items():
                    indices=[after[table][0].index(column) for column in columns]
                    retained=[tuple(row[index] for index in indices) for row in after[table][1]]
                    self.assertEqual(retained,rows,table)
            with closing(sqlite3.connect(database)) as db:
                other=db.execute("SELECT id FROM tenant WHERE name='legacy-other'").fetchone()[0]
                for table in ('recharge_order','operation_log'):
                    self.assertEqual(db.execute(f'SELECT tenant_id FROM {table}').fetchone()[0],other)
                for table in ('number_pool','account_pool','balance_transaction'):
                    self.assertEqual(db.execute(f'SELECT tenant_id FROM {table}').fetchone()[0],1)
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT INTO number_pool (phone_number,tenant_id) VALUES ('12025550999',NULL)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
