import unittest,json
from unittest.mock import patch
from warirak_ai.camera_publish import publish_frame
class CameraPublishTests(unittest.TestCase):
    def test_device_credential_is_sent_to_the_exact_origin(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'accepted':True}).encode()
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.return_value=Response()
            self.assertTrue(publish_frame('https://example.com','test-device',b'jpeg','2026-10-27T00:00:00Z','frame-1')['accepted'])
            request=build.return_value.open.call_args.args[0];headers={k.lower():v for k,v in request.header_items()}
            self.assertEqual(request.full_url,'https://example.com/api/device/frame');self.assertEqual(request.data,b'jpeg');self.assertEqual(headers['authorization'],'Bearer test-device');self.assertEqual(headers['x-frame-id'],'frame-1')
    def test_missing_token_and_oversized_frame_fail_before_network(self):
        with self.assertRaises(ValueError):publish_frame('https://example.com',None,b'x','time','id')
        with self.assertRaises(ValueError):publish_frame('https://example.com','test',b'x'*262145,'time','id')
        with self.assertRaises(ValueError):publish_frame('http://remote.example.com','test',b'x','time','id')
if __name__=='__main__':unittest.main()
