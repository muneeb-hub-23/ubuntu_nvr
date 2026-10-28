"""API contract tests; FFmpeg is mocked so a real camera is not required."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ['NVR_SECRET'] = 'test-only-secret-with-at-least-32-characters'
_test_root = Path(__file__).resolve().parent.parent / '.test-data'
_test_root.mkdir(exist_ok=True)
_temp = tempfile.TemporaryDirectory(dir=_test_root)
os.environ['NVR_DATA'] = _temp.name
from fastapi.testclient import TestClient
import main

def tearDownModule():
    main.db.close()
    _temp.cleanup()

class APITest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.client.headers['x-nvr-key'] = os.environ['NVR_SECRET']
        main.db.execute('DELETE FROM cameras')
        main.db.execute('DELETE FROM settings')
        main.db.commit()
        main.desired.clear()
        main.workers.clear()

    def add(self, **kwargs):
        data = dict(name='Entrance', host='192.168.1.10', username='admin', password='p@ss:word', **kwargs)
        response = self.client.post('/cameras', json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_auth(self):
        self.assertEqual(TestClient(main.app).get('/cameras').status_code, 401)
        self.assertEqual(TestClient(main.app).get('/health').status_code, 200)
        self.assertEqual(self.client.post('/cameras', headers={'sec-fetch-site':'cross-site'}, json={}).status_code, 403)

    def test_crud_encryption_and_preserved_password(self):
        c = self.add()
        self.assertNotIn('password', c)
        stored = main.camera(c['id'])
        self.assertNotIn('p@ss:word', stored['password'])
        self.assertEqual(main.cipher.decrypt(stored['password'].encode()).decode(), 'p@ss:word')
        self.assertIn('p%40ss%3Aword', main.source(stored))
        self.client.put('/cameras/'+c['id'], json={**c, 'name':'Updated', 'password':''})
        self.assertEqual(main.camera(c['id'])['password'], stored['password'])
        self.assertEqual(self.client.get('/cameras').json()[0]['name'], 'Updated')
        self.assertEqual(self.client.delete('/cameras/'+c['id']).status_code, 200)
        self.assertEqual(self.client.get('/cameras').json(), [])

    def test_validation(self):
        for data in [dict(name='x', host='http://bad/path'), dict(name='x', host='a',protocol='file'),dict(name='x',host='a',port=0)]:
            self.assertEqual(self.client.post('/cameras',json=data).status_code,422)

    @patch('onvif.ONVIFCamera')
    def test_onvif_resolution(self, device):
        media = device.return_value.create_media_service.return_value
        media.GetProfiles.return_value = [MagicMock(token='main-profile')]
        media.GetStreamUri.return_value = MagicMock(Uri='rtsp://192.168.1.10:554/video?channel=1')
        c = self.add(protocol='onvif', port=80)
        self.assertEqual(main.source(main.camera(c['id'])), 'rtsp://admin:p%40ss%3Aword@192.168.1.10:554/video?channel=1')
        self.assertEqual(media.GetStreamUri.call_args.args[0]['ProfileToken'], 'main-profile')

    @patch('main.subprocess.Popen')
    def test_stream_recording_and_idempotency(self, popen):
        process=MagicMock()
        process.poll.return_value=None
        popen.return_value=process
        c=self.add(record=True)
        path='/cameras/'+c['id']
        self.assertEqual(self.client.post(path+'/start').status_code,200)
        self.client.post(path+'/start')
        self.assertEqual(popen.call_count,1)
        args=popen.call_args.args[0]
        self.assertIn('libx264',args)
        self.assertIn('-segment_time',args)
        self.assertIn('tcp',args)
        self.assertEqual(self.client.get('/live/'+c['id']+'/secret.txt').status_code,404)
        self.client.post(path+'/stop')
        process.terminate.assert_called_once()
        self.assertNotIn(c['id'],main.desired)

    def test_clock(self):
        self.assertEqual(self.client.put('/settings',json={'timezone':'Invalid/Zone'}).status_code,422)
        self.assertEqual(self.client.put('/settings',json={'mode':'manual'}).status_code,422)
        r=self.client.put('/settings',json={'timezone':'Asia/Karachi','mode':'manual','manual_time':1800000000})
        self.assertEqual(r.status_code,200,r.text)
        self.assertAlmostEqual(r.json()['now'],1800000000,delta=2)
        with patch('ntplib.NTPClient.request',side_effect=Exception('offline')):
            self.assertEqual(self.client.put('/settings',json={'mode':'ntp'}).status_code,502)
        self.assertEqual(self.client.get('/settings').json()['mode'],'manual')

if __name__=='__main__':
    unittest.main()
