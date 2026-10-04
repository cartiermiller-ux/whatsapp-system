import os, tempfile, pathlib, sys
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory() as folder:
    os.environ['WHATSAPP_DATABASE_URL']='sqlite:///'+folder+'/test.db'
    os.environ['WHATSAPP_SERVICE_CONFIG_FILE']=folder+'/services.json'
    import main as m
    import whatsapp_session as w
    import service_config
    with m.SessionLocal() as db:
        with patch.dict(os.environ,{'WA_PROXY_URL':'http://test:secret@127.0.0.1:8123'}):
            m.migrate_exit_proxy(db)
            m.migrate_exit_proxy(db)
            rows=db.query(m.ProxyPool).filter_by(is_default=True).all()
            assert len(rows)==1
            row=rows[0]
            assert w.proxy_url()==row.address
            assert 'secret' not in str(m.proxy_dict(row))
            mock=m.ProxyPool(host='127.0.0.1',port=8999,provider='mock',status='free')
            second=m.ProxyPool(host='127.0.0.1',port=8124,provider='manual',status='free')
            db.add_all([mock,second]);db.commit()
            user=m.User(username='proxy-test',role='super_admin')
            db.add(user);db.commit()
            try: m.set_default_proxy(mock.id,db,user)
            except m.HTTPException as exc: assert exc.status_code==422
            else: raise AssertionError('mock accepted')
            m.set_default_proxy(second.id,db,user)
            assert db.query(m.ProxyPool).filter_by(is_default=True).count()==1
            assert w.proxy_url()==second.address
            m.edit_pool_proxy(second.id,{'text':'http://new:private@127.0.0.1:8125'},db,user)
            assert w.proxy_url()==second.address and second.port==8125
            second.status='disabled';db.commit()
            try: w.proxy_url()
            except w.SessionError: pass
            else: raise AssertionError('disabled default silently bypassed')
            assert not any(f['key']=='WA_PROXY_URL' for f in service_config.schema())
    m.engine.dispose()
print('PASS: migration idempotence, default selection, mock rejection, credential masking, edit, disabled guard, single configuration entry')