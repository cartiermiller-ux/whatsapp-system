"""Isolated management regressions; no provider requests or production auth."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temporary = tempfile.TemporaryDirectory(prefix='wa-workspace-')
os.environ['WHATSAPP_DATABASE_URL'] = 'sqlite:///' + temporary.name + '/test.db'
os.environ['WHATSAPP_SERVICE_CONFIG_FILE'] = temporary.name + '/services.json'
os.environ['WHATSAPP_AUTH_ROOT'] = temporary.name
import main as m
import workspace_api as w
import account_export_api as exports

def archive(phone='12345678901', extra=None):
    creds = {'me': {'id': phone + '@s.whatsapp.net'}, 'noiseKey': {'private': 'fixture'},
             'signedIdentityKey': {'private': 'fixture'}, 'signedPreKey': {'keyPair': 'fixture'},
             'registrationId': 1, 'advSecretKey': 'fixture'}
    content = io.BytesIO()
    with __import__('zipfile').ZipFile(content, 'w') as z:
        z.writestr('manifest.json', json.dumps({'format': 'baileys-multi-file-auth', 'version': 1,
                     'accounts': [{'phone': phone, 'session_path': 'account-1/session'}]}))
        z.writestr('account-1/session/creds.json', json.dumps(creds))
        z.writestr('account-1/session/session-key.json', '{}')
        if extra: z.writestr(extra, '{}')
    return base64.b64encode(content.getvalue()).decode()

class WorkspaceTests(unittest.TestCase):
    def test_six_segment_import_and_nurture_gate(self):
        import account_management_api as management
        key = base64.b64encode(bytes(32)).decode()
        content = ','.join(['12345678980', key, key, key, key, base64.b64encode(b'fixture').decode()])
        result = w.import_credentials(w.CredentialImport(format='six_segment', content=content), self.db, self.user)['data']
        account = self.db.get(m.AccountPool, result['ids'][0])
        self.assertFalse(account.session_enabled)
        self.assertEqual(account.nurture_stage, 'none')
        self.assertIn(management.get_account_row(account.id, self.db)['connection_state'], ('pending_adapter', 'offline'))
        with self.assertRaises(m.HTTPException):
            management.nurture_account(account.id, management.NurtureAction(action='start'), self.db, self.user)
        with self.assertRaises(m.HTTPException):
            w.import_credentials(w.CredentialImport(format='six_segment', content=content), self.db, self.user)
        management.delete_account(account.id, self.db, self.user)
        self.assertFalse(self.db.query(w.ImportedCredential).filter_by(account_id=account.id).first())

    def test_full_params_parser(self):
        key = base64.b64encode(bytes(32)).decode()
        item = dict(jid='12345678981', registrationID=840417454, signPreKeyID=0,
                    phoneUUID='1AF6328D-3870-4124-ACC1-9DEB993F766C', deviceUUID='d55a6a02-8346-a1b0-005b-a2df5ec8a9b0',
                    osVersion='11', manufacturer='fixture', device='fixture', whatsappVersion='fixture',
                    signPreKeySignature=base64.b64encode(bytes(64)).decode())
        for name in ('identityPublicKey', 'identityPrivateKey', 'clientStaticPublicKey', 'clientStaticPrivateKey', 'signPreKeyPublicKey', 'signPreKeyPrivateKey'):
            item[name] = key
        self.assertEqual(w.parse_credentials('full_params', json.dumps(item))[0][0], item['jid'])
        self.assertEqual(len(w.parse_credentials('full_params', json.dumps(item)+'\n'+json.dumps(dict(item,jid='12345678982')))), 2)
        with self.assertRaises(m.HTTPException): w.parse_credentials('full_params', json.dumps([item,item]))
        item['identityPrivateKey'] = 'invalid'
        with self.assertRaises(m.HTTPException): w.parse_credentials('full_params', json.dumps(item))

    def setUp(self):
        self.db = m.SessionLocal(info={'tenant_id': 1})
        self.user = self.db.query(m.User).first()

    def tearDown(self):
        self.db.rollback(); self.db.close()

    def test_groups_and_assignments(self):
        g = w.save_group(w.CollectionRequest(kind='proxy', name='网络 A'), self.db, self.user)['data']['id']
        row = m.ProxyPool(host='127.0.0.1', port=9000, provider='manual', status='free')
        self.db.add(row); self.db.commit()
        w.assign_group(w.Assignment(kind='proxy', ids=[row.id], group_id=g), self.db, self.user)
        self.assertEqual(w.groups('proxy', self.db, self.user)['data'][0]['count'], 1)
        with self.assertRaises(m.HTTPException): w.delete_group(g, self.db, self.user)
        with self.assertRaises(m.HTTPException): w.assign_group(w.Assignment(kind='account',ids=[1],group_id=g),self.db,self.user)
        with self.assertRaises(m.HTTPException): w.assign_group(w.Assignment(kind='proxy',ids=[row.id,999999],group_id=None),self.db,self.user)
        self.assertEqual(row.group_id,g)
        w.rename_group(g,w.CollectionRequest(kind='proxy',name='网络 B'),self.db,self.user)
        w.assign_group(w.Assignment(kind='proxy',ids=[row.id],group_id=None),self.db,self.user)
        w.delete_group(g,self.db,self.user)
        self.assertIsNone(self.db.get(w.Collection,g))

    def test_round_trip_and_export_ownership(self):
        result=w.import_sessions(w.SessionImport(archive=archive()),self.db,self.user)['data']
        account=self.db.get(m.AccountPool,result['ids'][0])
        self.assertFalse(account.session_enabled)
        self.assertTrue(account.full_params_ready)
        exports.build_archive([account.id],self.db,self.user)
        history=w.export_history(self.db,self.user)['data']
        self.assertTrue(history)
        old_count=len(history)
        response=w.download_export(history[0]['id'],self.db,self.user)
        self.assertEqual(response.media_type,'application/zip')
        self.assertEqual(len(w.export_history(self.db,self.user)['data']),old_count)
        outsider=m.User(id=99999,username='other',role='super_admin')
        with self.assertRaises(m.HTTPException): w.download_export(history[0]['id'],self.db,outsider)
        diagnostic=w.inspect_accounts(w.InspectionRequest(name='检查',ids=[account.id]),self.db,self.user)['data']
        self.assertEqual(diagnostic['valid'],1)
        with self.assertRaises(m.HTTPException): w.import_sessions(w.SessionImport(archive=archive()),self.db,self.user)

    def test_unsafe_import_rolls_back(self):
        before=self.db.query(m.AccountPool).count()
        for value in [archive('12345678902','../escape.json'),base64.b64encode(b'not a zip').decode()]:
            with self.assertRaises(m.HTTPException): w.import_sessions(w.SessionImport(archive=value),self.db,self.user)
        self.assertEqual(self.db.query(m.AccountPool).count(),before)

    def test_import_phone_mismatch_removes_files(self):
        content=io.BytesIO()
        with __import__('zipfile').ZipFile(io.BytesIO(base64.b64decode(archive('12345678903')))) as z:
            files={name:z.read(name) for name in z.namelist()}
        manifest=json.loads(files['manifest.json']);manifest['accounts'][0]['phone']='12345678904'
        files['manifest.json']=json.dumps(manifest).encode()
        with __import__('zipfile').ZipFile(content,'w') as z:
            for name,data in files.items():z.writestr(name,data)
        before=set((Path(temporary.name)/'whatsapp_auth').glob('*'))
        with self.assertRaises(m.HTTPException):w.import_sessions(w.SessionImport(archive=base64.b64encode(content.getvalue()).decode()),self.db,self.user)
        self.assertEqual(set((Path(temporary.name)/'whatsapp_auth').glob('*')),before)
        self.assertFalse(self.db.query(m.NumberPool).filter_by(phone_number='12345678904').first())

if __name__=='__main__':
    try: unittest.main()
    finally: m.engine.dispose(); temporary.cleanup()
