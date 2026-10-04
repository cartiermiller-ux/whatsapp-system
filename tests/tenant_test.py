"""Two-tenant adversarial API, ORM, worker, callback and wallet regressions."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temporary = tempfile.TemporaryDirectory(prefix='wa-tenant-')
test_database = os.environ.get('WHATSAPP_TEST_DATABASE_URL')
if test_database:
    from sqlalchemy.engine import make_url
    url = make_url(test_database)
    if url.get_backend_name() != 'postgresql' or not (url.database or '').endswith('_test'):
        raise RuntimeError('Use an isolated PostgreSQL database ending in _test')
os.environ['WHATSAPP_DATABASE_URL'] = test_database or 'sqlite:///' + temporary.name + '/test.db'
os.environ['WHATSAPP_SERVICE_CONFIG_FILE'] = temporary.name + '/services.json'
os.environ['AUTO_PROVISION_USERS'] = 'false'
os.environ['USE_REAL_SEND'] = 'false'
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import aliased
import main as m
import operations as ops
import workspace_api as w


class TenantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(m.app)
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        m.engine.dispose()
        temporary.cleanup()

    def setUp(self):
        type(self).counter += 1
        self.serial = type(self).counter
        self.rows = {}
        for side, amount in [('a', 100), ('b', 250)]:
            name = f'tenant_{self.serial}_{side}'
            with m.SessionLocal() as db:
                user = m.create_user(db, name, 'test-pass', tenant=name, role='agent_admin')
                tenant_id, user_id = user.tenant_id, user.id
            response = self.client.post('/api/v1/auth/login', json={'username': name, 'password': 'test-pass'})
            self.assertEqual(response.status_code, 200)
            auth = {'Authorization': 'Bearer ' + response.json()['data']['token']}
            with m.SessionLocal(info={'tenant_id': tenant_id}) as db:
                number = m.NumberPool(phone_number=f'1202555{self.serial:03d}{side == "b":01d}', status='pending', source_channel=name)
                ad = m.AdMessage(title=name, content='Fixture only')
                proxy = m.ProxyPool(host='127.0.0.1', port=9000+self.serial, provider='manual', status='free', is_default=True)
                collection = w.Collection(kind='account', name=name)
                db.add_all([number, ad, proxy, collection]); db.flush()
                account = m.AccountPool(number_id=number.id, group_id=collection.id, status='normal', health_score=100)
                db.add(account); db.flush()
                group = m.ResourceGroup(group_jid=f'{tenant_id}-123@g.us', group_name=name, owner_account_id=account.id)
                link = m.AdLink(name=name, original_url='https://example.invalid/', short_code=f't{tenant_id}', ad_message_id=ad.id)
                order = m.RechargeOrder(order_no=f'TENANT-{tenant_id}', amount=10, currency='USDT', chain='TRC20',
                    address='fixture-address', user_id=user_id, status='pending', expire_at=datetime.now()+timedelta(hours=1))
                db.add_all([group, link, order]); db.commit()
                m.add_transaction(db, 'recharge', amount, remark=name)
                task = m.MassSendTask(task_name=name, target_type='contact', target_ids=str(number.id),
                    account_ids=str(account.id), message_content='Fixture only', status='pending', mode='mock',
                    scheduled_at=datetime.now()+timedelta(days=1))
                db.add(task); db.commit()
                self.rows[side] = {'tenant': tenant_id, 'user': user_id, 'name': name, 'auth': auth,
                    'number': number.id, 'account': account.id, 'group': group.id, 'ad': ad.id,
                    'proxy': proxy.id, 'collection': collection.id, 'link': link.id, 'order': order.id,
                    'order_no': order.order_no, 'task': task.id, 'balance': amount}

    def request(self, method, path, side='a', **kwargs):
        return self.client.request(method, '/api/v1'+path, headers=self.rows[side]['auth'], **kwargs)

    def test_lists_dashboard_and_wallet(self):
        paths = {'/numbers':'number','/accounts':'account','/groups':'group','/ads/copies':'ad',
                 '/ads/links':'link','/proxies':'proxy','/mass-send/tasks':'task','/balance/recharge/orders':'order'}
        for side in ('a','b'):
            for path, key in paths.items():
                response = self.request('GET', path, side)
                self.assertEqual(response.status_code, 200, (path,response.text))
                data = response.json()['data']
                rows = data['list'] if isinstance(data,dict) else data
                self.assertEqual([row['id'] for row in rows], [self.rows[side][key]], path)
            dashboard = self.request('GET','/dashboard/overview',side).json()['data']
            self.assertEqual(dashboard['accounts']['total'],1)
            self.assertEqual(dashboard['balance']['balance'],self.rows[side]['balance'])
            self.assertEqual(dashboard['resources']['groups'],1)
            self.assertEqual(self.request('GET','/balance',side).json()['data']['balance'],self.rows[side]['balance'])

    def test_foreign_ids_export_controls_and_mutations(self):
        b = self.rows['b']
        attempts = [('GET',f'/accounts/{b["account"]}/logs',None),
                    ('GET',f'/accounts/{b["account"]}/export',None),
                    ('POST',f'/accounts/{b["account"]}/pause',None),
                    ('DELETE',f'/accounts/{b["account"]}',None),
                    ('POST',f'/accounts/{b["account"]}/convert',None),
                    ('GET',f'/mass-send/tasks/{b["task"]}',None),
                    ('GET',f'/tasks/mass-send/{b["task"]}/executions',None),
                    ('POST',f'/tasks/mass-send/{b["task"]}/cancel',None),
                    ('PUT',f'/ads/copies/{b["ad"]}',{'title':'attack'}),
                    ('DELETE',f'/ads/links/{b["link"]}',None),
                    ('POST',f'/balance/recharge/{b["order"]}/cancel',None)]
        for method,path,payload in attempts:
            response = self.request(method,path,json=payload)
            self.assertEqual(response.status_code,404,(method,path,response.text))
        with m.SessionLocal(info={'tenant_id':b['tenant']}) as db:
            self.assertEqual(db.get(m.AccountPool,b['account']).status,'normal')
            self.assertEqual(db.get(m.MassSendTask,b['task']).status,'pending')
            self.assertEqual(db.get(m.RechargeOrder,b['order']).status,'pending')

    def test_cross_tenant_references_rejected(self):
        a,b = self.rows['a'],self.rows['b']
        response=self.request('POST','/mass-send/tasks',json={'task_name':'attack','target_type':'contact',
            'target_ids':[a['number']],'account_ids':[b['account']],'message_content':'Fixture only'})
        self.assertEqual(response.status_code,422)
        response=self.request('POST','/mass-send/tasks',json={'task_name':'attack-target','target_type':'contact',
            'target_ids':[b['number']],'account_ids':[a['account']],'message_content':'Fixture only'})
        self.assertEqual(response.status_code,422)
        response=self.request('POST','/groups/import',json=[{'group_name':'attack','group_jid':'123-456@g.us','owner_account_id':b['account']}])
        self.assertEqual(response.status_code,422)
        response=self.request('POST',f'/accounts/{a["account"]}/proxy',json={'proxy_id':b['proxy']})
        self.assertEqual(response.status_code,422)
        response=self.request('POST','/workspace/group-members',json={'kind':'account','ids':[a['account']],'group_id':b['collection']})
        self.assertEqual(response.status_code,422)
        response=self.request('POST','/ads/links',json={'name':'attack','original_url':'https://example.invalid/','ad_message_id':b['ad']})
        self.assertEqual(response.status_code,400)
        with m.SessionLocal(info={'tenant_id':a['tenant']}) as db:
            db.add(m.AccountPool(number_id=b['number']))
            with self.assertRaises(m.HTTPException): db.flush()
            db.rollback()

    def test_bulk_deletes_and_updates_are_scoped(self):
        a,b = self.rows['a'],self.rows['b']
        response=self.request('DELETE','/ads/copies',json={'ids':[a['ad'],b['ad']]})
        self.assertEqual(response.json()['data']['deleted'],1)
        self.assertEqual(self.request('POST',f'/proxies/{a["proxy"]}/default').status_code,200)
        with m.SessionLocal(info={'tenant_id':b['tenant']}) as db:
            self.assertIsNotNone(db.get(m.AdMessage,b['ad']))
            self.assertTrue(db.get(m.ProxyPool,b['proxy']).is_default)

    def test_orm_aggregates_aliases_and_fail_closed(self):
        a,b = self.rows['a'],self.rows['b']
        with m.SessionLocal(info={'tenant_id':a['tenant']}) as db:
            model=aliased(m.NumberPool)
            self.assertEqual(db.query(model).count(),1)
            self.assertEqual(db.query(func.sum(m.BalanceTransaction.amount)).scalar(),Decimal(100))
            self.assertIsNone(db.get(m.AccountPool,b['account']))
            self.assertEqual(db.query(m.AccountPool).filter_by(id=b['account']).update({'status':'paused'}),0)
            with self.assertRaises(RuntimeError): db.execute(text('SELECT * FROM account_pool'))
            with self.assertRaises(RuntimeError): db.execute(select(m.AccountPool.__table__))
            with self.assertRaises(RuntimeError): db.query(m.AccountPool).update({'tenant_id':b['tenant']})
            db.rollback()
            db.add(m.NumberPool(phone_number='12025559999',tenant_id=b['tenant']))
            with self.assertRaises(m.HTTPException): db.flush()
            db.rollback()
        with m.SessionLocal(info={'tenant_id':None}) as db:
            self.assertEqual(db.query(m.NumberPool).count(),0)
            db.add(m.NumberPool(phone_number='12025559999'))
            with self.assertRaises(m.HTTPException): db.flush()

    def test_background_worker_uses_task_tenant(self):
        b=self.rows['b']
        with m.SessionLocal(info={'tenant_id':b['tenant']}) as db:
            task=db.get(m.MassSendTask,b['task']); task.scheduled_at=None; db.commit()
        ops.run_task('mass-send',b['task'])
        with m.SessionLocal(info={'tenant_id':b['tenant']}) as db:
            task=db.get(m.MassSendTask,b['task'])
            self.assertEqual((task.status,task.accepted),('done',1))
            self.assertTrue(all(row.tenant_id==b['tenant'] for row in db.query(m.TaskExecution).filter_by(task_id=b['task'])))
            self.assertGreater(db.query(m.TaskLog).filter_by(task_id=b['task']).count(),0)
        self.assertEqual(self.request('GET','/balance','a').json()['data']['balance'],100)

    def test_signed_payment_credits_only_order_tenant(self):
        b=self.rows['b']
        body=json.dumps({'order_no':b['order_no'],'tx_hash':'fixture-'+str(b['tenant'])+'x'*20,
            'amount':10,'currency':'USDT','chain':'TRC20','address':'fixture-address','confirmations':30}).encode()
        stamp=str(int(time.time()))
        signature=hmac.new(b'isolated-secret',stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
        with patch.dict(os.environ,{'PAYMENT_WEBHOOK_SECRET':'isolated-secret'}):
            for _ in range(2):
                response=self.client.post('/api/v1/balance/payment-webhook',content=body,
                    headers={'Content-Type':'application/json','X-Payment-Timestamp':stamp,'X-Payment-Signature':signature})
                self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.request('GET','/balance','a').json()['data']['balance'],100)
        self.assertEqual(self.request('GET','/balance','b').json()['data']['balance'],260)

    def test_charges_are_tenant_scoped_and_idempotent(self):
        b=self.rows['b']
        with m.SessionLocal(info={'tenant_id':b['tenant']}) as db:
            task=db.get(m.MassSendTask,b['task'])
            row=m.TaskExecution(task_kind='mass-send',task_id=task.id,target_id=str(b['number']),
                account_id=b['account'],status='succeeded')
            db.add(row); db.flush()
            with patch.object(ops,'task_price',return_value=Decimal('0.012')):
                ops.charge_success(db,task,'mass-send',row); db.commit()
                ops.charge_success(db,task,'mass-send',row); db.commit()
            self.assertEqual(db.query(m.BalanceTransaction).filter_by(type='consume').count(),1)
        self.assertEqual(self.request('GET','/balance','a').json()['data']['balance'],100)
        self.assertEqual(self.request('GET','/balance','b').json()['data']['balance'],249.988)

    def test_receipt_callback_only_updates_account_tenant(self):
        for side in ('a','b'):
            data=self.rows[side]
            with m.SessionLocal(info={'tenant_id':data['tenant']}) as db:
                db.add(m.TaskExecution(task_kind='mass-send',task_id=data['task'],target_id=str(data['number']),
                    account_id=data['account'],status='succeeded',message_id='shared-message',target='fixture@s.whatsapp.net'))
                db.commit()
        with patch.dict(os.environ,{'RECEIPT_WEBHOOK_TOKEN':'fixture-secret'}):
            response=self.client.post('/api/v1/providers/receipts',headers={'Authorization':'Bearer fixture-secret'},
                json={'account_id':self.rows['b']['account'],'message_id':'shared-message','target':'fixture@s.whatsapp.net','status':'read'})
            self.assertEqual(response.status_code,200,response.text)
        for side in ('a','b'):
            with m.SessionLocal(info={'tenant_id':self.rows[side]['tenant']}) as db:
                row=db.query(m.TaskExecution).filter_by(task_id=self.rows[side]['task']).one()
                self.assertEqual(row.read_at is not None,side=='b')

    def test_whatsapp_session_access_cannot_cross_tenants(self):
        b=self.rows['b']
        name='tenant-session-'+str(b['tenant'])
        with m.SessionLocal(info={'tenant_id':b['tenant']}) as db:
            db.get(m.AccountPool,b['account']).session_name=name
            db.add(m.WhatsAppLinkSession(auth_name=name,owner_user_id=b['user'])); db.commit()
        # Even a stale/manipulated selection on a user must not grant session access.
        with m.SessionLocal() as db:
            db.get(m.User,self.rows['a']['user']).whatsapp_session_name=name; db.commit()
        response=self.request('GET','/whatsapp/status',params={'auth_name':name})
        self.assertEqual(response.status_code,403,response.text)
        with m.SessionLocal(info={'tenant_id':self.rows['a']['tenant']}) as db:
            db.get(m.AccountPool,self.rows['a']['account']).session_name=name
            with self.assertRaises(m.HTTPException): db.flush()
            db.rollback()

    def test_platform_business_scope_and_tenant_disabling(self):
        admin=self.client.post('/api/v1/auth/login',json={'username':'admin','password':'admin123'}).json()['data']['token']
        auth={'Authorization':'Bearer '+admin}
        # Platform role does not silently bypass business isolation.
        self.assertEqual(self.client.get('/api/v1/numbers',headers=auth).json()['data']['list'],[])
        response=self.client.put(f'/api/v1/admin/tenants/{self.rows["b"]["tenant"]}',headers=auth,json={'status':'disabled'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.request('GET','/me','b').status_code,401)
        response=self.client.post('/api/v1/auth/login',json={'username':self.rows['b']['name'],'password':'test-pass'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.request('GET','/me','a').status_code,200)

    def test_forged_tenant_inputs_and_platform_permissions(self):
        a,b=self.rows['a'],self.rows['b']
        response=self.client.get('/api/v1/numbers',headers={**a['auth'],'X-Tenant':b['name']},params={'tenant_id':b['tenant']})
        self.assertEqual([r['id'] for r in response.json()['data']['list']],[a['number']])
        for method,path,payload in [('GET','/admin/tenants',None),('GET','/providers/config',None),
            ('PUT','/settings',{'billing_enabled':False}),('POST','/balance/transactions',{'type':'recharge','amount':999}),
            ('POST',f'/balance/recharge/{a["order"]}/confirm',None)]:
            self.assertEqual(self.request(method,path,json=payload).status_code,403,path)
        response=self.request('POST','/admin/users',json={'username':'escape-'+str(self.serial),'password':'test-pass',
            'role':'operator','tenant_id':b['tenant']})
        self.assertEqual(response.status_code,403)

    def test_parallel_requests_never_share_tenant_scope(self):
        def query(index):
            side='a' if index%2 else 'b'
            response=self.request('GET','/balance',side)
            return response.json()['data']['balance']==self.rows[side]['balance']
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertTrue(all(pool.map(query,range(20))))

    def test_resource_uniqueness_is_per_tenant(self):
        a,b=self.rows['a'],self.rows['b']
        with m.SessionLocal(info={'tenant_id':a['tenant']}) as db:
            phone=db.get(m.NumberPool,a['number']).phone_number
            jid=db.get(m.ResourceGroup,a['group']).group_jid
        with m.SessionLocal(info={'tenant_id':b['tenant']}) as db:
            db.add(m.NumberPool(phone_number=phone,status='pending'))
            db.add(m.ResourceGroup(group_jid=jid,group_name='Shared public group'))
            db.add(w.Collection(kind='account',name=a['name']))
            db.commit()
            self.assertEqual(db.query(m.NumberPool).filter_by(phone_number=phone).count(),1)
        with m.SessionLocal(info={'tenant_id':a['tenant']}) as db:
            self.assertEqual(db.query(m.NumberPool).count(),1)

    def test_tenant_change_revokes_tokens_and_clears_selection(self):
        a,b=self.rows['a'],self.rows['b']
        admin=self.client.post('/api/v1/auth/login',json={'username':'admin','password':'admin123'}).json()['data']['token']
        response=self.client.put(f'/api/v1/admin/users/{a["user"]}',headers={'Authorization':'Bearer '+admin},json={'tenant_id':b['tenant']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.request('GET','/me').status_code,401)
        response=self.client.post('/api/v1/auth/login',json={'username':a['name'],'password':'test-pass'})
        auth={'Authorization':'Bearer '+response.json()['data']['token']}
        rows=self.client.get('/api/v1/numbers',headers=auth).json()['data']['list']
        self.assertEqual([row['id'] for row in rows],[b['number']])


if __name__=='__main__':
    unittest.main(verbosity=2)
