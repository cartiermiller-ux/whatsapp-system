"""Copy a frozen SQLite snapshot to an empty PostgreSQL database and verify every row.

Destination comes from MIGRATION_DATABASE_URL, not command arguments. Never imports
main or starts schedulers. A failed verification rolls the entire copy back.
"""
import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
from sqlalchemy import MetaData, create_engine, select, text, func, String
from sqlalchemy.engine import make_url


def fingerprint(connection, table):
    digest = hashlib.sha256()
    query = select(table).order_by(*table.primary_key.columns)
    count = 0
    def normalize(value):
        if isinstance(value, (datetime, date)): return value.isoformat()
        if isinstance(value, Decimal): return str(value.normalize())
        return value
    for row in connection.execute(query).mappings():
        payload = {key: normalize(value) for key, value in row.items()}
        digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode())
        digest.update(b'\n')
        count += 1
    return count, digest.hexdigest()


def migrate(snapshot, destination_url):
    if make_url(destination_url).get_backend_name() != 'postgresql':
        raise ValueError('Destination must be PostgreSQL')
    snapshot = Path(snapshot).resolve()
    if not snapshot.is_file(): raise ValueError('Snapshot not found')
    source = create_engine('sqlite:///' + snapshot.as_posix())
    destination = create_engine(destination_url)
    metadata = MetaData()
    metadata.reflect(source)
    target_metadata = MetaData()
    for table in metadata.sorted_tables:
        copied = table.to_metadata(target_metadata)
        for column in copied.columns:
            column.type = column.type.as_generic()
            # Legacy SQLite ALTER defaults use integer booleans and SQLite expressions.
            column.server_default = None
    reports = []
    try:
        with source.connect() as incoming, destination.begin() as outgoing:
            if outgoing.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")).scalar():
                raise ValueError('Destination must contain no tables')
            target_metadata.create_all(outgoing)
            for table in metadata.sorted_tables:
                target = target_metadata.tables[table.name]
                rows = incoming.execute(select(table)).mappings()
                for batch in rows.partitions(500):
                    values = [dict(row) for row in batch]
                    for row in values:
                        for column in target.columns:
                            value = row[column.name]
                            if isinstance(column.type, String) and column.type.length and value is not None and len(value) > column.type.length:
                                raise ValueError('Overlong value in ' + table.name + '.' + column.name)
                    if values: outgoing.execute(target.insert(), values)
                before, after = fingerprint(incoming, table), fingerprint(outgoing, target)
                if before != after: raise ValueError('Data verification failed: ' + table.name)
                reports.append({'table': table.name, 'rows': before[0], 'sha256': before[1]})
                for column in target.primary_key.columns:
                    sequence = outgoing.execute(text('SELECT pg_get_serial_sequence(:table_name,:column_name)'),
                                                {'table_name': table.name, 'column_name': column.name}).scalar()
                    if sequence:
                        maximum = outgoing.execute(select(func.max(column))).scalar()
                        outgoing.execute(text('SELECT setval(CAST(:sequence AS regclass),:value,:called)'),
                                         {'sequence': sequence, 'value': max(maximum or 1, 1), 'called': maximum is not None})
        return reports
    finally:
        source.dispose()
        destination.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    try:
        report = migrate(args.source, os.environ['MIGRATION_DATABASE_URL'])
        output = Path(args.report)
        with output.open('w') as handle:
            output.chmod(0o600)
            json.dump(report, handle, indent=2)
        print('MIGRATION_OK', len(report), 'tables', sum(row['rows'] for row in report), 'rows; all fingerprints matched')
    except Exception as error:
        # SQLAlchemy exception strings may include private row values or passwords.
        print('MIGRATION_FAILED', type(error).__name__, file=sys.stderr)
        sys.exit(1)
