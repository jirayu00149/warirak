import unittest,tempfile
from pathlib import Path
from warirak_ai.telemetry import open_outbox,enqueue,validate_url
class TelemetryTests(unittest.TestCase):
    def test_stable_event_id_is_retry_safe_and_conflicting_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            db=open_outbox(Path(folder)/'outbox.sqlite');payload=dict(event_id='test-1',mission_id='test',occurred_at='2026-10-27T00:00:00Z',class_id=0,collection_confirmed=True)
            enqueue(db,'collections',payload);enqueue(db,'collections',payload);self.assertEqual(db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],1)
            with self.assertRaises(ValueError):enqueue(db,'collections',{**payload,'class_id':1})
            with self.assertRaises(ValueError):enqueue(db,'collections',{**payload,'collection_confirmed':False})
            db.close()
    def test_token_transport_rejects_insecure_remote_and_credential_urls(self):
        for url in ['http://example.com','https://user:password@example.com','https://example.com?token=secret','https://example.com/api']:
            with self.assertRaises(ValueError):validate_url(url)
        self.assertEqual(validate_url('http://127.0.0.1:4173/'),'http://127.0.0.1:4173');self.assertEqual(validate_url('https://example.com/'),'https://example.com')
if __name__=='__main__':unittest.main()
