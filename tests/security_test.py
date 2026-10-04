"""Security regressions against an isolated database; never sends provider requests."""
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temporary = tempfile.TemporaryDirectory(prefix='wa-security-')
os.environ['WHATSAPP_DATABASE_URL'] = 'sqlite:///' + temporary.name + '/test.db'
os.environ['WHATSAPP_SERVICE_CONFIG_FILE'] = temporary.name + '/services.json'
os.environ['AUTO_PROVISION_USERS'] = 'false'
os.environ['USE_REAL_SEND'] = 'false'
os.environ['ALLOWED_ORIGINS'] = 'https://cartier.us.cc'
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
import main as m


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(m.app)
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            cls.operator = m.create_user(db, 'security_operator', 'test-pass', role='operator', tenant='default').id
            cls.agent = m.create_user(db, 'security_agent', 'test-pass', role='agent_admin', tenant='default').id
            cls.other = m.create_user(db, 'security_other', 'test-pass', role='operator', tenant='other').id

    def headers(self, username='admin', password='admin123'):
        response = self.client.post('/api/v1/auth/login', json={'username': username, 'password': password})
        self.assertEqual(response.status_code, 200)
        return {'Authorization': 'Bearer ' + response.json()['data']['token']}

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        m.engine.dispose()
        temporary.cleanup()

    def test_no_provision_or_legacy_impersonation(self):
        self.assertFalse(m.AUTO_PROVISION_USERS)
        self.assertFalse(m.real_send_enabled())
        self.assertFalse(m.app.debug)
        for username in ['unprovisioned', "admin' OR 1=1--"]:
            self.assertEqual(self.client.post('/api/v1/auth/login', json={'username': username, 'password': 'any-pass'}).status_code, 401)
        for token in ['mock-token-admin', 'mock-token-security_agent', '1.forged']:
            self.assertEqual(self.client.get('/api/v1/me', headers={'Authorization': 'Bearer ' + token}).status_code, 401)
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            self.assertIsNone(db.query(m.User).filter_by(username='unprovisioned').first())

    def test_all_business_routes_require_auth(self):
        excluded = {'/api/v1/auth/login', '/api/v1/providers/receipts', '/api/v1/balance/payment-webhook'}
        checked = 0
        for template, methods in m.app.openapi()['paths'].items():
            if not template.startswith('/api/v1/') or template in excluded: continue
            path = re.sub(r'\{[^}]+\}', '1', template)
            for method in methods:
                if method not in ('get', 'post', 'put', 'patch', 'delete'): continue
                response = self.client.request(method, path, json={})
                self.assertEqual(response.status_code, 401, (method, template, response.status_code))
                checked += 1
        self.assertGreater(checked, 80)
        print('Protected business methods:', checked)
        self.assertEqual(self.client.post('/api/v1/providers/receipts', json={'message_id':'m','target':'x','status':'read'}).status_code, 401)

    def test_role_escalation_and_tenant_boundaries(self):
        operator = self.headers('security_operator', 'test-pass')
        self.assertEqual(self.client.get('/api/v1/admin/users', headers=operator).status_code, 403)
        agent = self.headers('security_agent', 'test-pass')
        for role in ['super_admin', 'agent_admin']:
            self.assertEqual(self.client.post('/api/v1/admin/users', headers=agent,
                json={'username':'escalation', 'password':'test-pass','role':role}).status_code, 403)
        self.assertEqual(self.client.put('/api/v1/admin/users/1', headers=agent, json={'password':'attack-pass'}).status_code,403)
        self.assertEqual(self.client.delete(f'/api/v1/admin/users/{self.other}', headers=agent).status_code,403)
        self.assertEqual(self.client.put(f'/api/v1/admin/users/{self.operator}', headers=agent, json={'role':'super_admin'}).status_code,403)
        response = self.client.get('/api/v1/admin/users', headers=agent)
        self.assertTrue(all(row['role']=='operator' and row['tenant']=='default' for row in response.json()['data']['list']))

    def test_cors_and_logout_revocation(self):
        headers = {'Origin':'https://cartier.us.cc','Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'Authorization'}
        response = self.client.options('/api/v1/accounts', headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['access-control-allow-origin'], 'https://cartier.us.cc')
        headers['Origin'] = 'https://untrusted.invalid'
        self.assertEqual(self.client.options('/api/v1/accounts', headers=headers).status_code,400)
        auth = self.headers()
        self.assertEqual(self.client.get('/api/v1/me', headers=auth).status_code,200)
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=auth).status_code,200)
        self.assertEqual(self.client.get('/api/v1/me', headers=auth).status_code,401)

    def test_token_revocation_acceptance(self):
        username = 'token_acceptance_fixture'
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            m.create_user(db, username, 'admin123', role='operator', tenant='default')

        def expect(label, response, status):
            self.assertEqual(response.status_code, status, label)
            print('[PASS]', label)

        def login(password, label):
            response = self.client.post('/api/v1/auth/login',
                json={'username': username, 'password': password})
            expect(label, response, 200)
            return {'Authorization': 'Bearer ' + response.json()['data']['token']}

        auth = login('admin123', '登录成功')
        expect('旧 token 可访问 /me', self.client.get('/api/v1/me', headers=auth), 200)
        expect('登出成功', self.client.post('/api/v1/auth/logout', headers=auth), 200)
        expect('登出后旧 token 失效', self.client.get('/api/v1/me', headers=auth), 401)
        old_auth = login('admin123', '重新登录成功')
        second_auth = login('admin123', '第二个会话登录成功')
        self.assertNotEqual(old_auth, second_auth)
        expect('改密成功', self.client.post('/api/v1/me/password', headers=old_auth,
            json={'old_password': 'admin123', 'new_password': 'admin1234'}), 200)
        for label, headers in [('改密前旧 token 失效', old_auth),
                               ('同账号其他旧会话失效', second_auth)]:
            expect(label, self.client.get('/api/v1/me', headers=headers), 401)
        expect('旧密码不能登录', self.client.post('/api/v1/auth/login',
            json={'username': username, 'password': 'admin123'}), 401)
        new_auth = login('admin1234', '新密码可登录')
        expect('新 token 可访问 /me', self.client.get('/api/v1/me', headers=new_auth), 200)
        expect('新会话登出成功', self.client.post('/api/v1/auth/logout', headers=new_auth), 200)

    def test_audit_covers_security_and_settings_operations(self):
        auth = self.headers()
        response = self.client.post('/api/v1/admin/users', headers=auth, json={'username':'audit_fixture','password':'test-pass','role':'operator'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.delete('/api/v1/admin/users/'+str(response.json()['data']['id']),headers=auth).status_code,200)
        self.assertEqual(self.client.put('/api/v1/settings',headers=auth,json={'daily_send_limit':50}).status_code,200)
        self.assertEqual(self.client.put('/api/v1/settings',headers=auth,json={'recharge_address':'test-address-not-for-payments'}).status_code,200)
        self.assertEqual(self.client.post('/api/v1/balance/recharge',headers=auth,json={'amount':10}).status_code,200)
        response=self.client.post('/api/v1/admin/users',headers=auth,json={'username':'password_audit_fixture','password':'test-pass','role':'operator'})
        self.assertEqual(response.status_code,200)
        fixture_auth=self.headers('password_audit_fixture','test-pass')
        self.assertEqual(self.client.post('/api/v1/me/password',headers=fixture_auth,
            json={'old_password':'test-pass','new_password':'updated-test-pass'}).status_code,200)
        self.assertEqual(self.client.get('/api/v1/me',headers=fixture_auth).status_code,401)
        self.assertEqual(self.client.post('/api/v1/auth/logout',headers=auth).status_code,200)
        with m.SessionLocal(info={'tenant_id': 1}) as db:
            actions = {row.action for row in db.query(m.OperationLog).all()}
        self.assertTrue({'login','logout','create_user','delete_user','update_settings','create_recharge','update_password'}.issubset(actions))


if __name__ == '__main__': unittest.main()
