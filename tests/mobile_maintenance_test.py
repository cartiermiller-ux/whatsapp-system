"""Isolated regressions for online maintenance, retry limits and real-login gating."""
from datetime import datetime, timedelta
from unittest.mock import patch
import unittest
from workspace_test import m, temporary
import account_management_api as api
import mobile_maintenance as maintenance
from mobile_session import session_key


class FakeRuntime:
    def __init__(self, phone):
        self.state = {'status':'connected','phone':phone,'error':''}
        self.calls = []
        self.fail_presence = False

    def snapshot(self, key): return dict(self.state)
    def configured(self): return True
    def connect(self, account, db):
        self.calls.append('connect'); self.state['status']='starting'; return dict(self.state)
    def disconnect(self, account):
        self.calls.append('disconnect'); self.state['status']='idle'
    def presence(self, account, available):
        self.calls.append(('presence',available))
        if self.fail_presence: raise TimeoutError('fixture')
        return {'success':True}


class MaintenanceTests(unittest.TestCase):
    sequence = 0
    def setUp(self):
        self.db = m.SessionLocal(info={'tenant_id':1})
        self.user = self.db.query(m.User).first()
        MaintenanceTests.sequence += 1
        self.number = m.NumberPool(phone_number=str(12025550123+MaintenanceTests.sequence),status='pending')
        self.db.add(self.number);self.db.flush()
        self.account = m.AccountPool(number_id=self.number.id,device_type='full_params',session_enabled=True,health_score=0)
        self.db.add(self.account);self.db.commit()
        self.fake = FakeRuntime(self.number.phone_number)
        self.patches = [patch.object(maintenance,'runtime',self.fake),patch.object(api,'mobile_runtime',self.fake)]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in self.patches:item.stop()
        self.db.rollback();self.db.close()

    def test_real_connection_required_and_pause_stops(self):
        self.fake.state['status']='idle'
        with self.assertRaises(m.HTTPException): api.nurture_account(self.account.id,api.NurtureAction(action='start'),self.db,self.user)
        self.fake.state['status']='connected'
        api.nurture_account(self.account.id,api.NurtureAction(action='start'),self.db,self.user)
        progress=maintenance.progress_for(self.account,self.db)
        maintenance.maintain_account(self.account,self.db,progress.last_heartbeat+timedelta(seconds=61))
        self.assertEqual(progress.online_seconds,61)
        self.assertEqual(self.number.status,'success')
        self.assertEqual(self.account.health_score,0)
        api.nurture_account(self.account.id,api.NurtureAction(action='pause'),self.db,self.user)
        self.assertFalse(self.account.session_enabled)
        self.assertEqual(self.account.nurture_stage,'paused')
        self.assertIn('disconnect',self.fake.calls)

    def test_failed_heartbeat_does_not_count_time_or_retry_immediately(self):
        self.account.nurture_stage='nurturing'
        progress=maintenance.progress_for(self.account,self.db)
        now=datetime.now();progress.last_heartbeat=now-timedelta(seconds=61)
        self.fake.fail_presence=True
        maintenance.maintain_account(self.account,self.db,now)
        self.assertEqual(progress.online_seconds,0)
        self.assertEqual(progress.failures,1)
        self.assertIsNone(progress.last_heartbeat)
        maintenance.maintain_account(self.account,self.db,now+timedelta(seconds=5))
        self.assertNotIn('connect',self.fake.calls)

    def test_three_failures_stop_reconnecting(self):
        self.account.nurture_stage='nurturing'
        progress=maintenance.progress_for(self.account,self.db)
        progress.failures=2;progress.last_status='starting'
        self.fake.state['status']='error'
        maintenance.maintain_account(self.account,self.db)
        self.assertFalse(self.account.session_enabled)
        self.assertEqual(self.account.nurture_stage,'paused')
        self.assertNotIn('connect',self.fake.calls)

    def test_wrong_phone_stops_session(self):
        self.fake.state['phone']='12025550999'
        maintenance.maintain_account(self.account,self.db)
        self.assertFalse(self.account.session_enabled)
        self.assertIn('disconnect',self.fake.calls)


if __name__=='__main__':
    try: unittest.main()
    finally: m.engine.dispose(); temporary.cleanup()
