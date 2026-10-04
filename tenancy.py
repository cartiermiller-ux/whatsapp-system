"""Database tenant boundaries, independent of HTTP and background execution contexts."""
from sqlalchemy import Column, ForeignKey, Integer, MetaData, event, inspect, text
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.orm import Session, declared_attr, with_loader_criteria
from fastapi import HTTPException


class TenantOwned:
    @declared_attr
    def tenant_id(cls):
        return Column(Integer, ForeignKey('tenant.id'), nullable=False, index=True)


class TenantSession(Session):
    def bulk_save_objects(self, *args, **kwargs):
        raise RuntimeError('Use validated ORM writes instead of legacy bulk writes')

    def bulk_insert_mappings(self, *args, **kwargs):
        raise RuntimeError('Use validated ORM writes instead of legacy bulk writes')

    def bulk_update_mappings(self, *args, **kwargs):
        raise RuntimeError('Use validated ORM writes instead of legacy bulk writes')

    def get(self, entity, ident, **kwargs):
        row = super().get(entity, ident, **kwargs)
        if isinstance(row, TenantOwned) and not self.info.get('system_scope'):
            if row.tenant_id != self.info.get('tenant_id'):
                return None
        return row


def bind_tenant(db, tenant_id):
    if not isinstance(tenant_id, int) or tenant_id < 1:
        raise HTTPException(403, '用户未绑定有效租户')
    previous = db.info.get('tenant_id')
    if previous != tenant_id and any(isinstance(row, TenantOwned) for row in db.identity_map.values()):
        raise RuntimeError('Cannot switch a database session with loaded business resources')
    db.info.update(tenant_id=tenant_id, system_scope=False)


def tenant_query(db, model, user):
    """Explicit helper, backed by the same mandatory session-level boundary."""
    bind_tenant(db, user.tenant_id)
    return db.query(model).filter(model.tenant_id == user.tenant_id)


@event.listens_for(TenantSession, 'do_orm_execute')
def enforce_query_scope(state):
    if state.session.info.get('system_scope'):
        return
    if not state.is_orm_statement:
        raise RuntimeError('Raw SQL/Core statements are forbidden in a tenant session')
    if state.is_update:
        fields = {getattr(key, 'key', key) for key in state.statement._values or {}}
        protected = {'tenant_id'} | {field for references in REFERENCES.values() for field in references}
        if fields & protected:
            raise RuntimeError('Ownership and resource references require validated ORM writes')
    tenant_id = state.session.info.get('tenant_id', -1) or -1
    if state.is_select or state.is_update or state.is_delete:
        state.statement = state.statement.options(with_loader_criteria(
            TenantOwned, lambda model: model.tenant_id == tenant_id,
            include_aliases=True, propagate_to_loaders=True))
    elif state.is_insert:
        raise RuntimeError('Use scoped ORM objects instead of bulk inserts')


# Relationships without database foreign keys must still belong to the same tenant.
REFERENCES = {
    'number_pool': {'account_id': 'account_pool'},
    'account_pool': {'number_id': 'number_pool', 'group_id': 'resource_collection'},
    'resource_group': {'owner_account_id': 'account_pool'},
    'proxy_pool': {'bound_number_id': 'number_pool', 'group_id': 'resource_collection'},
    'mass_send_task': {'ad_message_id': 'ad_message'},
    'invite_task': {'target_group_id': 'resource_group'},
    'ad_link': {'ad_message_id': 'ad_message'},
    'sms_order': {'number_id': 'number_pool'},
    'payment_receipt': {'order_id': 'recharge_order'},
}


@event.listens_for(TenantSession, 'before_flush')
def enforce_write_scope(db, flush_context, instances):
    system = db.info.get('system_scope')
    tenant_id = db.info.get('tenant_id')
    models = {model.__table__.name: model for model in TenantOwned.__subclasses__()}
    for row in db.new:
        if isinstance(row, TenantOwned) and row.tenant_id is None:
            row.tenant_id = tenant_id
    # Models are direct subclasses of TenantOwned alongside the declarative Base.
    for row in set(db.new) | set(db.dirty) | set(db.deleted):
        if not isinstance(row, TenantOwned):
            continue
        if row in db.new and row.tenant_id is None:
            row.tenant_id = tenant_id
        if row.tenant_id is None or (not system and row.tenant_id != tenant_id):
            raise HTTPException(403, '不能操作其他租户的数据')
        history = inspect(row).attrs.tenant_id.history
        if history.deleted and history.deleted[0] != row.tenant_id:
            raise HTTPException(403, '业务资源不允许变更租户归属')
        if row in db.deleted:
            continue
        if row.__tablename__ in ('mass_send_task', 'invite_task'):
            arrays = {'account_ids': 'account_pool'}
            if row.__tablename__ == 'mass_send_task':
                arrays['target_ids'] = 'resource_group' if row.target_type == 'group' else 'number_pool'
            else:
                arrays['source_ids'] = 'number_pool'
            for field, table in arrays.items():
                if row not in db.new and not inspect(row).attrs[field].history.has_changes():
                    continue
                for value in (getattr(row, field, '') or '').split(','):
                    if not value.strip().isdigit():
                        raise HTTPException(422, '任务关联资源 ID 无效')
                    owner = db.connection().execute(text(f'SELECT tenant_id FROM "{table}" WHERE id=:id'), {'id': int(value)}).scalar()
                    if owner is not None and owner != row.tenant_id:
                        raise HTTPException(422, '任务关联资源不属于当前租户')
        if row.__tablename__ in ('account_pool', 'whatsapp_link_session'):
            field = 'session_name' if row.__tablename__ == 'account_pool' else 'auth_name'
            name = getattr(row, field, '')
            if name and (row in db.new or inspect(row).attrs[field].history.has_changes()):
                from whatsapp_session import auth_path
                path = auth_path(name).resolve()
                for table, column in [('account_pool', 'session_name'), ('whatsapp_link_session', 'auth_name')]:
                    candidates = db.connection().execute(text(f'SELECT "{column}" FROM "{table}" WHERE tenant_id<>:tenant AND "{column}" IS NOT NULL AND "{column}"<>\'\''), {'tenant': row.tenant_id}).scalars()
                    if any(auth_path(candidate).resolve() == path for candidate in candidates):
                        raise HTTPException(422, '登录会话不能跨租户共享')
        if row.__tablename__ in ('recharge_order', 'operation_log', 'whatsapp_link_session', 'account_inspection'):
            owner_field = 'owner_user_id' if row.__tablename__ == 'whatsapp_link_session' else 'user_id'
            owner_id = getattr(row, owner_field, None)
            if owner_id and (row in db.new or inspect(row).attrs[owner_field].history.has_changes()):
                owner_tenant = db.connection().execute(text('SELECT tenant_id FROM sys_user WHERE id=:id'), {'id': owner_id}).scalar()
                if owner_tenant != row.tenant_id:
                    raise HTTPException(422, '所属用户不属于当前租户')
        references = dict(REFERENCES.get(row.__tablename__, {}))
        if row.__tablename__ in ('task_log', 'task_execution'):
            kind = row.task_kind or 'mass-send'
            references.update(task_id='mass_send_task' if kind == 'mass-send' else 'invite_task', account_id='account_pool')
        if row.__tablename__ == 'balance_transaction' and row.task_id:
            references['task_id'] = 'mass_send_task' if row.task_type in ('mass-send', 'mass_send') else 'invite_task'
        for field, table in references.items():
            value = getattr(row, field, None)
            if not value:
                continue
            target = next((item for item in db.new if isinstance(item, models[table]) and item.id == value), None)
            if target is None:
                target = db.get(models[table], value)
            if target is None or target.tenant_id != row.tenant_id:
                raise HTTPException(422, '关联资源不存在或不属于当前租户')


SCOPED_UNIQUES = {'number_pool': ('phone_number',), 'resource_group': ('group_jid',),
                 'resource_collection': ('kind', 'name')}


def migrate_unique_scope(connection, table):
    fields = SCOPED_UNIQUES.get(table.name)
    if fields is None:
        return
    inspector = inspect(connection)
    constraints = [item for item in inspector.get_unique_constraints(table.name) if tuple(item['column_names']) == fields]
    indexes = [item for item in inspector.get_indexes(table.name)
               if item['unique'] and tuple(item['column_names']) == fields and not item.get('duplicates_constraint')]
    if constraints or indexes:
        if connection.dialect.name == 'sqlite':
            # SQLite autoindexes cannot be dropped. Rebuild only these three resource tables.
            temporary_metadata = MetaData()
            table.metadata.tables['tenant'].to_metadata(temporary_metadata)
            rebuilt = table.to_metadata(temporary_metadata, name='_tenant_rebuild_' + table.name)
            connection.execute(CreateTable(rebuilt))
            names = ','.join('"'+column.name+'"' for column in table.columns)
            connection.execute(text(f'INSERT INTO "{rebuilt.name}" ({names}) SELECT {names} FROM "{table.name}"'))
            connection.execute(text(f'DROP TABLE "{table.name}"'))
            connection.execute(text(f'ALTER TABLE "{rebuilt.name}" RENAME TO "{table.name}"'))
            for index in table.indexes:
                connection.execute(CreateIndex(index))
        else:
            for item in constraints:
                name = connection.dialect.identifier_preparer.quote(item['name'])
                connection.execute(text(f'ALTER TABLE "{table.name}" DROP CONSTRAINT {name}'))
            for item in indexes:
                name = connection.dialect.identifier_preparer.quote(item['name'])
                connection.execute(text(f'DROP INDEX {name}'))
    columns = ','.join('"'+name+'"' for name in ('tenant_id',)+fields)
    if any(tuple(item['column_names']) == ('tenant_id',)+fields for item in inspect(connection).get_unique_constraints(table.name)):
        return
    connection.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_{table.name}_tenant_resource" ON "{table.name}" ({columns})'))


def migrate_tenants(engine, metadata):
    """Idempotent migration; failures abort startup rather than serve unscoped data."""
    tenant_tables = sorted([table.name for table in metadata.tables.values()
                     if 'tenant_id' in table.c], key=lambda name: (name != 'sys_user', name == 'payment_receipt', name))
    with engine.begin() as connection:
        if engine.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(73165005)'))
        connection.execute(text("INSERT INTO tenant (id,name,status,created_at) VALUES (1,'default','active',CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"))
        if engine.dialect.name == 'postgresql':
            connection.execute(text("SELECT setval(pg_get_serial_sequence('tenant','id'), COALESCE(MAX(id),1), true) FROM tenant"))
        columns = {table: {col['name'] for col in inspect(connection).get_columns(table)} for table in tenant_tables}
        names = connection.execute(text("SELECT DISTINCT COALESCE(NULLIF(TRIM(tenant),''),'default') FROM sys_user")).scalars().all()
        for name in sorted(names):
            connection.execute(text("INSERT INTO tenant (name,status,created_at) VALUES (:name,'active',CURRENT_TIMESTAMP) ON CONFLICT (name) DO NOTHING"), {'name': name})
        for table in tenant_tables:
            missing = 'tenant_id' not in columns[table]
            if missing:
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN tenant_id INTEGER REFERENCES tenant(id)'))
            if table == 'sys_user':
                connection.execute(text("UPDATE sys_user SET tenant_id=(SELECT id FROM tenant WHERE name=COALESCE(NULLIF(TRIM(sys_user.tenant),''),'default')) WHERE tenant_id IS NULL"))
            else:
                # Only ownership backed by an explicit user/order relation is inferred.
                owner = {'recharge_order': 'user_id', 'operation_log': 'user_id',
                         'whatsapp_link_session': 'owner_user_id', 'account_inspection': 'user_id'}.get(table)
                if owner:
                    connection.execute(text(f'UPDATE "{table}" SET tenant_id=(SELECT tenant_id FROM sys_user WHERE sys_user.id="{table}".{owner}) WHERE tenant_id IS NULL'))
                if table == 'payment_receipt':
                    connection.execute(text('UPDATE payment_receipt SET tenant_id=(SELECT tenant_id FROM recharge_order WHERE recharge_order.id=payment_receipt.order_id) WHERE tenant_id IS NULL'))
                connection.execute(text(f'UPDATE "{table}" SET tenant_id=1 WHERE tenant_id IS NULL'))
            migrate_unique_scope(connection, metadata.tables[table])
            connection.execute(text(f'CREATE INDEX IF NOT EXISTS "ix_{table}_tenant_id" ON "{table}" (tenant_id)'))
            if engine.dialect.name == 'postgresql':
                connection.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN tenant_id SET NOT NULL'))
            else:
                # SQLite cannot ALTER COLUMN NOT NULL; protect upgraded legacy tables too.
                for action in ('INSERT', 'UPDATE'):
                    connection.execute(text(f'''CREATE TRIGGER IF NOT EXISTS "tenant_{table}_{action.lower()}"
                        BEFORE {action} ON "{table}" WHEN NEW.tenant_id IS NULL OR
                        NOT EXISTS (SELECT 1 FROM tenant WHERE id=NEW.tenant_id)
                        BEGIN SELECT RAISE(ABORT, 'invalid tenant'); END'''))
        if engine.dialect.name == 'postgresql':
            connection.execute(text("SELECT setval(pg_get_serial_sequence('tenant','id'), COALESCE(MAX(id),1), true) FROM tenant"))
