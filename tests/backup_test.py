import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup import backup_database


class BackupTests(unittest.TestCase):
    def test_wal_snapshot_and_uncommitted_write(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.db'
            with sqlite3.connect(source) as connection:
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)')
                connection.execute('INSERT INTO sample VALUES (1,?)',('committed',))
                connection.commit()
                connection.execute('INSERT INTO sample VALUES (2,?)',('uncommitted',))
                snapshot=backup_database('sqlite:///'+source.as_posix(),Path(directory)/'backup')
                with sqlite3.connect(snapshot) as restore:
                    self.assertEqual(restore.execute('SELECT * FROM sample').fetchall(),[(1,'committed')])
                    self.assertEqual(restore.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                if os.name!='nt':self.assertEqual(snapshot.stat().st_mode & 0o777,0o600)

    def test_missing_source_leaves_no_partial_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'backup'
            with self.assertRaises(ValueError):backup_database('sqlite:///'+directory+'/missing.db',output)
            self.assertEqual(list(output.iterdir()),[])


if __name__=='__main__':unittest.main()
