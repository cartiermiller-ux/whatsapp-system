"""Isolated API regressions: execution, controls, receipts, config and resources."""
import hashlib
import hmac
import io
import time
import zipfile
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_temp = tempfile.TemporaryDirectory(prefix='wa-operations-')
test_database = os.environ.get('WHATSAPP_TEST_DATABASE_URL')
if test_database:
    from sqlalchemy.engine import make_url
    parsed = make_url(test_database)
    if parsed.get_backend_name() != 'postgresql' or not (parsed.database or '').endswith('_test'):
        raise RuntimeError('External regression database must be PostgreSQL and end in _test')
os.environ['WHATSAPP_DATABASE_URL'] = test_database or ('sqlite:///' + str(Path(_temp.name) / 'test.db'))
os.environ['WHATSAPP_SERVICE_CONFIG_FILE'] = str(Path(_temp.name) / 'services.json')
os.environ['USE_REAL_SEND'] = 'false'
from fastapi.testclient import TestClient
import main as m
import operations as ops


class OperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(m.app)
        cls.client.__enter__()
        response = cls.client.post('/api/v1/auth/login', json={'username': m.DEFAULT_ADMIN_USERNAME, 'password': m.DEFAULT_ADMIN_PASSWORD})
        cls.client.headers['Authorization'] = 'Bearer ' + response.json()['data']['token']
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            number = m.NumberPool(phone_number='8613800000011', status='pending')
            db.add(number); db.flush()
            account = m.AccountPool(number_id=number.id, status='normal', health_score=100, created_at=datetime.now()-timedelta(days=10), session_name='test-auth')
            group = m.ResourceGroup(group_jid='12345@g.us', group_name='测试群', can_invite=True)
            db.add_all([account, number, group]); db.commit()
            cls.account, cls.number, cls.group = account.id, number.id, group.id

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        m.engine.dispose()
        _temp.cleanup()

    def create(self, kind='mass-send', **kwargs):
        path = '/mass-send/tasks' if kind == 'mass-send' else '/invite/tasks'
        req = {'task_name': '测试', 'account_ids': [self.account]}
        req.update({'target_type': 'contact', 'target_ids': [self.number], 'message_content': 'Hi'} if kind == 'mass-send' else {'target_group_id': self.group, 'source_type': 'number_pool', 'source_ids': [self.number]})
        req.update(kwargs)
        response = self.client.post('/api/v1'+path, json=req)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']['task_id']

    def detail(self, kind, task_id):
        path = 'mass-send' if kind == 'mass-send' else 'invite'
        return self.client.get(f'/api/v1/{path}/tasks/{task_id}').json()['data']

    def test_mock_send_no_fabricated_receipt(self):
        task = self.create()
        detail = self.detail('mass-send', task)
        self.assertEqual((detail['status'], detail['sent'], detail['accepted'], detail['delivered'], detail['read'], detail['progress']), ('done', 1, 1, 0, 0, 100))
        execution = self.client.get(f'/api/v1/tasks/mass-send/{task}/executions').json()['data']['list'][0]
        self.assertEqual(execution['status'], 'succeeded')
        logs = self.client.get(f'/api/v1/tasks/mass-send/{task}/logs').json()['data']
        self.assertGreaterEqual(logs['total'], 3)

    def test_pull_group_runs(self):
        task = self.create('pull-group')
        detail = self.detail('pull-group', task)
        self.assertEqual((detail['status'], detail['processed'], detail['succeeded'], detail['failed']), ('done', 1, 1, 0))

    def test_failed_targets_retry_without_duplicate_success(self):
        task = self.create(target_ids=[self.number, 999999])
        detail = self.detail('mass-send', task)
        self.assertEqual((detail['status'], detail['accepted'], detail['failed']), ('failed', 1, 1))
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            db.add(m.NumberPool(id=999999, phone_number='8613800000099', status='pending')); db.commit()
        response = self.client.post(f'/api/v1/tasks/mass-send/{task}/retry')
        self.assertEqual(response.status_code, 200, response.text)
        rows = self.client.get(f'/api/v1/tasks/mass-send/{task}/executions').json()['data']['list']
        self.assertEqual([r['attempts'] for r in rows], [1, 2])
        self.assertEqual(self.detail('mass-send', task)['status'], 'done')

    def test_schedule_pause_resume_cancel(self):
        task = self.create(scheduled_at=(datetime.now()+timedelta(days=1)).isoformat())
        self.assertEqual(self.detail('mass-send', task)['status'], 'pending')
        for action, expected in [('pause','paused'),('resume','pending'),('cancel','cancelled')]:
            response = self.client.post(f'/api/v1/tasks/mass-send/{task}/{action}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.detail('mass-send', task)['status'], expected)
        self.assertEqual(self.client.post(f'/api/v1/tasks/mass-send/{task}/retry').status_code, 409)

    def test_real_send_receipt_monotonic_and_idempotent(self):
        task = self.create(scheduled_at=(datetime.now()+timedelta(days=1)).isoformat())
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            row = db.get(m.MassSendTask, task); row.scheduled_at=None; row.mode='real'; db.commit()
        with patch.object(ops, 'activate_account'), patch.object(m, 'wasock_request', return_value={'success': True, 'message_id':'receipt-test'}), patch.object(m,'send_interval_seconds',return_value=0):
            ops.run_task('mass-send', task)
        self.assertEqual(self.detail('mass-send',task)['delivered'],0)
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            for status in ['read','delivered','read']:
                ops.reconcile_receipt('receipt-test','8613800000011@s.whatsapp.net',status,db)
        detail=self.detail('mass-send',task)
        self.assertEqual((detail['delivered'],detail['read'],detail['failed']),(1,1,0))

    def test_timeout_never_automatically_retries(self):
        task = self.create(scheduled_at=(datetime.now()+timedelta(days=1)).isoformat())
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            row=db.get(m.MassSendTask,task);row.scheduled_at=None;row.mode='real';db.commit()
        with patch.object(ops,'activate_account'),patch.object(m,'wasock_request',side_effect=TimeoutError('lost response')),patch.object(m,'send_interval_seconds',return_value=0):
            ops.run_task('mass-send',task)
        self.assertEqual(self.detail('mass-send',task)['status'],'failed')
        self.assertEqual(self.client.post(f'/api/v1/tasks/mass-send/{task}/retry').status_code,409)
        execution=self.client.get(f'/api/v1/tasks/mass-send/{task}/executions').json()['data']['list'][0]
        path=f'/api/v1/tasks/mass-send/{task}/executions/{execution["id"]}'
        self.assertEqual(self.client.patch(path,json={'status':'succeeded','note':'核对通道记录，确认已成功发送'}).status_code,200)
        self.assertEqual(self.detail('mass-send',task)['accepted'],1)
        self.assertEqual(self.client.patch(path,json={'status':'succeeded','note':'重复核对不应再次计数'}).status_code,409)

    def test_account_presentation_and_guarded_operations(self):
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            number = m.NumberPool(phone_number='12025550101', status='pending')
            db.add(number); db.flush()
            account = m.AccountPool(number_id=number.id, status='normal', health_score=82, nurture_stage='nurturing', nurture_started_at=datetime.now()-timedelta(days=2))
            proxy = m.ProxyPool(provider='static', host='127.0.0.1', port=8080, protocol='http', country='US', status='free', last_check_ok=True, last_checked_at=datetime.now(), latency_ms=86)
            db.add_all([account,proxy]); db.commit()
            account_id,proxy_id=account.id,proxy.id
        response=self.client.post(f'/api/v1/accounts/{account_id}/proxy',json={'proxy_id':proxy_id})
        self.assertEqual(response.status_code,200,response.text)
        rows=self.client.get('/api/v1/accounts').json()['data']
        row=next(r for r in rows if r['id']==account_id)
        self.assertEqual((row['nurture_days'],row['network_state'],row['connection_state'],row['latency_ms']), (3,'healthy','unlinked',86))
        self.assertEqual(self.client.get(f'/api/v1/accounts/{account_id}/logs').status_code,200)
        task=self.create(account_ids=[account_id],scheduled_at=(datetime.now()+timedelta(days=1)).isoformat())
        self.assertEqual(self.client.delete(f'/api/v1/accounts/{account_id}').status_code,409)
        self.client.post(f'/api/v1/tasks/mass-send/{task}/cancel')
        self.assertEqual(self.client.delete(f'/api/v1/accounts/{account_id}').status_code,200)
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            self.assertEqual(db.get(m.ProxyPool,proxy_id).status,'free')

    def test_resource_center_uses_real_linked_accounts_and_sources(self):
        response=self.client.post('/api/v1/numbers/import',json=[{'phone':'12025550991','source_type':'physical','source_channel':'平台 A','region':'US'}, {'phone':'12025550992','source_type':'physical','source_channel':'平台 A'}])
        self.assertEqual(response.status_code,200,response.text)
        self.client.post('/api/v1/groups/import',json=[{'group_name':'来源群','group_jid':'654321@g.us','source_channel':'平台 A'}])
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            number=db.query(m.NumberPool).filter_by(phone_number='12025550992').one()
            account=m.AccountPool(number_id=number.id,status='normal',session_name='resource-test')
            db.add(account);db.flush();number.account_id=account.id;number.status='success';db.commit()
        def read_phone(name):
            return '12025550992' if name=='resource-test' else ''
        with patch.object(m,'read_paired_phone',side_effect=read_phone):
            rows=self.client.get('/api/v1/resources/overview').json()['data']
            row=next(r for r in rows if r['platform']=='平台 A')
            self.assertEqual((row['available_numbers'],row['connected_accounts'],row['groups']),(1,1,1))
            tasks=self.client.get('/api/v1/resources/access-tasks',params={'keyword':'平台 A','status':'success'}).json()['data']
            self.assertEqual(tasks['total'],1)
            numbers=self.client.get('/api/v1/numbers',params={'access_status':'success'}).json()['data']['list']
            self.assertTrue(all(r['linked'] for r in numbers))
        rows=self.client.get('/api/v1/resources/overview').json()['data']
        self.assertEqual(next(r for r in rows if r['platform']=='平台 A')['connected_accounts'],0)

    def test_multi_user_qr_selection_is_independent(self):
        from concurrent.futures import ThreadPoolExecutor
        from whatsapp_session import SessionState
        class FakeSession:
            def __init__(self,name): self.name=name; self.state='waiting_qr'
            def start(self,name,proxy_override=None): return self.snapshot()
            def snapshot(self):
                row=SessionState(auth_name=self.name,status=self.state,node_running=True).to_dict()
                row['qr_image']='qr:'+self.name
                return row
            def stop(self): self.state='idle'; return self.snapshot()
        sessions={}
        def session(name=None):
            return sessions.setdefault(name,FakeSession(name))
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            user=m.create_user(db,'multi-agent','test-password',role='agent_admin')
        token=self.client.post('/api/v1/auth/login',json={'username':'multi-agent','password':'test-password'}).json()['data']['token']
        headers={'Authorization':'Bearer '+token}
        with patch.object(m,'get_session',side_effect=session):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(self.client.post,'/api/v1/whatsapp/start',json={'mode':'new'}),pool.submit(self.client.post,'/api/v1/whatsapp/start',json={'mode':'new'},headers=headers)]
                responses=[future.result() for future in futures]
            self.assertTrue(all(response.status_code==200 for response in responses))
            first,second=[response.json()['data']['auth_name'] for response in responses]
            self.assertNotEqual(first,second)
            self.assertEqual(self.client.get('/api/v1/whatsapp/status').json()['data']['auth_name'],first)
            self.assertEqual(self.client.get('/api/v1/whatsapp/status',headers=headers).json()['data']['auth_name'],second)
            self.assertEqual(self.client.get('/api/v1/whatsapp/status',params={'auth_name':first},headers=headers).status_code,403)
            third=self.client.post('/api/v1/whatsapp/start',json={'mode':'new'}).json()['data']['auth_name']
            self.assertNotEqual(third,first)
            self.assertEqual(self.client.get('/api/v1/whatsapp/status',params={'auth_name':first}).status_code,200)
            self.client.post('/api/v1/whatsapp/stop',json={'auth_name':first})
            self.assertEqual(sessions[second].state,'waiting_qr')

    def test_two_account_tasks_dispatch_concurrently_without_crossing(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from whatsapp_session import auth_path
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            account=m.AccountPool(number_id=self.number,status='normal',health_score=100,created_at=datetime.now()-timedelta(days=10),session_name='concurrent-second')
            db.add(account);db.commit();second_id=account.id
        task_ids=[self.create(account_ids=[account_id],scheduled_at=(datetime.now()+timedelta(days=1)).isoformat()) for account_id in (self.account,second_id)]
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            for task_id in task_ids:
                task=db.get(m.MassSendTask,task_id);task.mode='real';task.scheduled_at=None
            db.commit()
        barrier=threading.Barrier(2)
        dispatched=[]
        def send(payload,**kwargs):
            dispatched.append(payload['authName'])
            barrier.wait(timeout=5)
            return {'success':True,'message_id':'concurrent-'+payload['authName']}
        with patch.object(ops,'activate_account'),patch.object(m,'wasock_request',side_effect=send),patch.object(m,'send_interval_seconds',return_value=0):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=[pool.submit(ops.run_task,'mass-send',task_id) for task_id in task_ids]
                for result in results:result.result(timeout=10)
        self.assertEqual(len(set(dispatched)),2, [self.detail('mass-send',task_id) for task_id in task_ids])
        self.assertIn(str(auth_path('concurrent-second')),dispatched)
        self.assertTrue(all(self.detail('mass-send',task_id)['status']=='done' for task_id in task_ids))

    def test_receipts_are_scoped_to_the_sending_account(self):
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            account=m.AccountPool(number_id=self.number,status='normal',health_score=100)
            db.add(account);db.commit();second_id=account.id
        task_ids=[self.create(account_ids=[account_id]) for account_id in (self.account,second_id)]
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            rows=db.query(m.TaskExecution).filter(m.TaskExecution.task_id.in_(task_ids)).all()
            for row in rows:row.message_id='collision-multi-account'
            db.commit()
            target=rows[0].target
            ops.reconcile_receipt('collision-multi-account',target,'read',db,self.account)
        self.assertEqual(self.detail('mass-send',task_ids[0])['read'],1)
        self.assertEqual(self.detail('mass-send',task_ids[1])['read'],0)
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            with self.assertRaises(m.HTTPException):
                ops.reconcile_receipt('collision-multi-account',target,'read',db)

    def test_shared_account_stop_is_persisted_and_does_not_change_other_selection(self):
        from whatsapp_session import SessionState
        class FakeSession:
            def __init__(self,name): self.name=name;self.status='connected'
            def start(self,name,proxy_override=None):self.status='connected';return self.snapshot()
            def stop(self):self.status='idle';return self.snapshot()
            def snapshot(self):return SessionState(auth_name=self.name,status=self.status,node_running=True).to_dict()
        sessions={}
        def get(name=None):return sessions.setdefault(name,FakeSession(name))
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            account=m.AccountPool(number_id=self.number,status='normal',session_name='shared-account')
            db.add(account);db.commit();account_id=account.id
        with patch.object(m,'get_session',side_effect=get):
            response=self.client.post('/api/v1/whatsapp/switch',json={'account_id':account_id})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.client.post('/api/v1/whatsapp/stop',json={'auth_name':'shared-account'}).status_code,200)
            with m.SessionLocal(info={'tenant_id': 1}) as db:self.assertFalse(db.get(m.AccountPool,account_id).session_enabled)
            self.assertEqual(self.client.post('/api/v1/whatsapp/switch',json={'account_id':account_id}).status_code,200)
            with m.SessionLocal(info={'tenant_id': 1}) as db:self.assertTrue(db.get(m.AccountPool,account_id).session_enabled)

    def test_receipt_auth_required(self):
        self.assertEqual(self.client.post('/api/v1/providers/receipts',json={'message_id':'x','target':'y','status':'read'}).status_code,401)

    def test_secrets_not_returned(self):
        response=self.client.put('/api/v1/providers/config',json={'WSAPI_TOKEN':'test-secret-never-return'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('test-secret-never-return',response.text)
        self.assertNotIn('test-secret-never-return',self.client.get('/api/v1/providers/config').text)
        self.assertEqual(self.client.put('/api/v1/providers/config',json={'MESSAGE_PROVIDER':'invented'}).status_code,422)

    def test_groups_import_export_delete(self):
        response=self.client.post('/api/v1/groups/import',json=[{'group_name':'导入群','group_jid':'98765@g.us'}])
        self.assertEqual(response.status_code,200,response.text)
        rows=self.client.get('/api/v1/groups/export',params={'keyword':'导入'}).json()['data']
        self.assertEqual(len(rows),1)
        response=self.client.request('DELETE','/api/v1/groups',json={'ids':[rows[0]['id']]})
        self.assertEqual(response.json()['data']['count'],1)

    def test_full_account_convert_and_zip(self):
        session = Path(_temp.name) / 'sessions' / 'paired'
        session.mkdir(parents=True, exist_ok=True)
        os.environ['WHATSAPP_AUTH_ROOT'] = str(Path(_temp.name) / 'sessions')
        key = {'public': {'type': 'Buffer', 'data': [1, 2]}, 'private': {'type': 'Buffer', 'data': [3, 4]}}
        creds = {'me': {'id': '8613800000011:5@s.whatsapp.net'}, 'noiseKey': key, 'signedIdentityKey': key,
                 'signedPreKey': {'keyPair': key, 'signature': {'type':'Buffer','data':[5]}, 'keyId':1},
                 'registrationId': 123, 'advSecretKey': 'test-secret-placeholder'}
        raw = json.dumps(creds).encode()
        (session/'creds.json').write_bytes(raw)
        (session/'session-123.0.json').write_text('{"test":"key"}')
        (session/'receipts.json').write_text('{"internal":"not-exported"}')
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            account = db.get(m.AccountPool, self.account); account.session_name = str(session); db.commit()
        response = self.client.post(f'/api/v1/accounts/{self.account}/convert')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('test-secret-placeholder', response.text)
        response = self.client.post('/api/v1/accounts/export', json={'ids':[self.account]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(archive.read(f'account-{self.account}/session/creds.json'), raw)
            self.assertIn(f'account-{self.account}/session/session-123.0.json', archive.namelist())
            self.assertFalse(any('receipts.json' in name for name in archive.namelist()))
        (session/'creds.json').write_text('broken')
        self.assertEqual(self.client.get(f'/api/v1/accounts/{self.account}/export').status_code, 409)

    def test_account_export_requires_conversion(self):
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            account = m.AccountPool(number_id=self.number, status='normal'); db.add(account); db.commit(); account_id=account.id
        self.assertEqual(self.client.post(f'/api/v1/accounts/{account_id}/convert').status_code,409)
        self.assertEqual(self.client.get(f'/api/v1/accounts/{account_id}/export').status_code,409)
        self.assertEqual(TestClient(m.app).post('/api/v1/accounts/export',json={'ids':[self.account]}).status_code,401)

    def test_payment_signature_matching_and_no_duplicate_credit(self):
        os.environ['PAYMENT_WEBHOOK_SECRET']='test-verifier-secret'
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            order=m.RechargeOrder(order_no='SIGNED-TEST',amount=10,currency='USDT',chain='TRC20',address='test-address',status='pending',expire_at=datetime.now()+timedelta(hours=1))
            db.add(order);db.commit();order_id=order.id
            before=m.current_balance(db)
        data={'order_no':'SIGNED-TEST','tx_hash':'a'*64,'amount':'10','currency':'USDT','chain':'TRC20','address':'test-address','confirmations':20}
        def deliver(payload, signature=True):
            body=json.dumps(payload).encode();stamp=str(int(time.time()))
            digest=hmac.new(b'test-verifier-secret',stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
            return self.client.post('/api/v1/balance/payment-webhook',content=body,headers={'Content-Type':'application/json','X-Payment-Timestamp':stamp,'X-Payment-Signature':digest if signature else 'bad'})
        self.assertEqual(deliver(data,False).status_code,401)
        self.assertEqual(deliver({**data,'amount':'20'}).status_code,422)
        self.assertEqual(deliver({**data,'confirmations':1}).status_code,409)
        self.assertEqual(deliver(data).status_code,200)
        self.assertTrue(deliver(data).json()['data']['duplicate'])
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            self.assertEqual(m.current_balance(db),before+10)
            self.assertEqual(db.query(m.BalanceTransaction).filter_by(remark='充值订单 SIGNED-TEST 核验回调到账').count(),1)

    def test_bill_once_for_success_and_not_for_failed_targets(self):
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            m.upsert_setting(db,'billing_enabled','1');db.commit()
            m.add_transaction(db,'recharge',1,remark='test credit')
        task = self.create(target_ids=[self.number,1234567], billing_country='CN', scheduled_at=(datetime.now()+timedelta(days=1)).isoformat())
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            row=db.get(m.MassSendTask,task);row.mode='real';row.scheduled_at=None;db.commit()
        with patch.object(ops,'activate_account'),patch.object(m,'wasock_request',return_value={'success':True,'message_id':'billing-msg'}),patch.object(m,'send_interval_seconds',return_value=0):
            ops.run_task('mass-send',task)
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            self.assertEqual(db.query(m.BalanceTransaction).filter_by(type='consume',task_id=task).count(),1)
            amount=db.query(m.BalanceTransaction).filter_by(type='consume',task_id=task).first().amount
            self.assertEqual(str(amount),'-0.006000')
            m.upsert_setting(db,'billing_enabled','0');db.commit()

    def test_validation_and_missing_task(self):
        self.assertEqual(self.client.get('/api/v1/mass-send/tasks/987654').status_code,404)
        self.assertEqual(self.client.post('/api/v1/mass-send/tasks',json={'task_name':'','target_ids':[],'account_ids':[],'message_content':''}).status_code,422)

if __name__=='__main__':
    unittest.main(verbosity=2)
