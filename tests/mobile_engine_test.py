"""Exercise the real Cobalt jar offline using generated fixtures, never production accounts."""
import base64
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import unittest

JAR = Path(__file__).resolve().parents[1]/'deploy/mobile-engine/target/mobile-engine-1.0.0.jar'


def fixture():
    data = dict(jid='12025550123', registrationID=840417454, signPreKeyID=0,
        phoneUUID='1AF6328D-3870-4124-ACC1-9DEB993F766C', deviceUUID='d55a6a02-8346-a1b0-005b-a2df5ec8a9b0',
        osVersion='11', manufacturer='fixture', device='fixture', roProductDevice='fixture',
        osBuildNumber='fixture', language='en', country='US', whatsappVersion='2.26.35.75',
        signPreKeySignature=base64.b64encode(bytes(64)).decode())
    for prefix in ('identity', 'clientStatic', 'signPreKey'):
        data[prefix+'PrivateKey'] = base64.b64encode(bytes(range(32))).decode()
        data[prefix+'PublicKey'] = base64.b64encode(bytes(range(32,64))).decode()
    return data


@unittest.skipUnless(JAR.is_file() and shutil.which('java'), 'Build the mobile engine and install Java 21+')
class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.start()

    def start(self):
        self.process = subprocess.Popen(['java','-jar',str(JAR)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,encoding='utf-8',env=dict(os.environ,WA_MOBILE_AUTH_ROOT=self.directory.name,
                WA_MOBILE_SIX_VERSION='2.26.35.75', WA_MOBILE_TEST_DIAGNOSTICS='true'))
        self.messages = queue.Queue()
        threading.Thread(target=lambda: [self.messages.put(line) for line in self.process.stdout],daemon=True).start()

    def close(self):
        self.process.stdin.close()
        try: self.process.wait(timeout=15)
        except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
        error = self.process.stderr.read()
        self.process.stdout.close(); self.process.stderr.close()
        return error

    def tearDown(self):
        if self.process.poll() is None: self.close()
        self.directory.cleanup()

    def request(self, action, **data):
        request_id = str(id(data))
        self.process.stdin.write(json.dumps(dict(data, id=request_id, action=action))+'\n'); self.process.stdin.flush()
        while True:
            message = json.loads(self.messages.get(timeout=20))
            if message.get('id') == request_id: return message

    def test_full_params_mapping_and_persistence(self):
        self.assertTrue(self.request('health')['data']['ready'])
        data = fixture()
        args = dict(session='t1-a1', phone=data['jid'], format='full_params', credentials=data, account_type='personal')
        result = self.request('validate', **args)
        if not result['ok']:
            diagnostics = self.close()
            self.fail(result['error']+'\n'+diagnostics)
        self.assertEqual(result['data']['registration_id'], data['registrationID'])
        self.assertEqual(result['data']['device'], 'fixture')
        self.close(); self.start()
        data['registrationID'] = 999
        self.assertEqual(self.request('validate', **args)['data']['registration_id'], 840417454)
        self.assertEqual(self.request('status', session='t1-a1')['data']['status'], 'idle')

    def test_six_parts_and_tenant_separation(self):
        key = base64.b64encode(bytes(range(32))).decode()
        args = dict(phone='12025550123', format='six_segment', credentials=['12025550123',key,key,key,key,key],account_type='personal')
        self.assertTrue(self.request('validate', session='t1-a2', **args)['ok'])
        self.assertTrue(self.request('validate', session='t2-a2', **args)['ok'])
        self.assertTrue((Path(self.directory.name)/'t1-a2').is_dir())
        self.assertTrue((Path(self.directory.name)/'t2-a2').is_dir())
        self.assertFalse(self.request('validate', session='../escape', **args)['ok'])


if __name__ == '__main__': unittest.main()
