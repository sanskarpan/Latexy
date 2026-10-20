"""Fail closed before any object-store mutation."""
import base64
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('sharing-storage-fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.endpoint = 'http://127.0.0.1:19200'
        self.bucket = 'latexy-sharing-' + 'a' * 32
        self.settings = SimpleNamespace(ENVIRONMENT='test', DEPLOY_TARGET='local', OPENAI_API_KEY='',
            RESEND_API_KEY='', MINIO_ENDPOINT=self.endpoint, MINIO_BUCKET=self.bucket)
        self.payload = dict(mode='host', endpoint=self.endpoint, bucket=self.bucket, origin='http://localhost:13420',
            key='compilations/11111111-1111-1111-1111-111111111111/accepted.pdf',
            pdf=base64.b64encode(b'%PDF-1.4 synthetic').decode())
        self.client = Mock(); self.client.meta.endpoint_url = self.endpoint
        self.get_client = Mock(return_value=self.client)
        self.env = {'SHARING_ACCEPTANCE_DISPOSABLE': '1'}
    def run_seed(self):
        fixture.seed(self.settings, self.get_client, self.payload, self.env)
    def test_valid_exact_destination(self):
        self.run_seed()
        self.client.create_bucket.assert_called_once_with(Bucket=self.bucket)
        self.client.put_bucket_cors.assert_called_once()
        self.client.put_object.assert_called_once()
    def test_opt_in_and_mode_required(self):
        for mode,opt in [('host',''),('unexpected','1')]:
            self.payload['mode']=mode; self.env['SHARING_ACCEPTANCE_DISPOSABLE']=opt
            with self.assertRaises(ValueError): self.run_seed()
        self.get_client.assert_not_called()
    def test_remote_and_credential_endpoints_rejected(self):
        for endpoint in ['https://storage.example:9000','http://remote.example:9000','http://user:pass@localhost:9000',
                         'http://localhost:9000/path','http://localhost:9000?x=y','http://localhost:80','http://storage:9001']:
            self.payload['endpoint']=endpoint
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError): self.run_seed()
        self.get_client.assert_not_called()
    def test_effective_settings_rejected_before_client(self):
        for key,value in [('ENVIRONMENT','production'),('DEPLOY_TARGET','modal'),('OPENAI_API_KEY','synthetic'),
                          ('RESEND_API_KEY','synthetic'),('MINIO_ENDPOINT','http://remote.example:9000'),('MINIO_BUCKET','unowned')]:
            old=getattr(self.settings,key);setattr(self.settings,key,value)
            with self.subTest(key=key), self.assertRaises(ValueError): self.run_seed()
            setattr(self.settings,key,old)
        self.get_client.assert_not_called()
    def test_cached_client_mismatch_precedes_all_mutations(self):
        self.client.meta.endpoint_url='http://remote.example:9000'
        with self.assertRaises(ValueError): self.run_seed()
        self.client.create_bucket.assert_not_called();self.client.put_bucket_cors.assert_not_called();self.client.put_object.assert_not_called()
    def test_bucket_key_origin_pdf_rejected_before_client(self):
        for key,value in [('bucket','production'),('key','arbitrary.pdf'),('origin','http://remote.example:13420'),
                          ('pdf',base64.b64encode(b'not pdf').decode())]:
            old=self.payload[key];self.payload[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): self.run_seed()
            self.payload[key]=old
        self.get_client.assert_not_called()
    def test_docker_endpoint_is_restricted_to_explicit_mode(self):
        with self.assertRaises(ValueError): fixture.isolated_endpoint('http://storage:9000','host')
        self.assertEqual(fixture.isolated_endpoint('http://storage:9000','docker'),'http://storage:9000')

if __name__=='__main__': unittest.main()
