"""Fail closed before any object-store mutation."""
import base64
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, MagicMock, patch

spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('sharing-storage-fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
verify_exact_cors = fixture.verify_exact_cors

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
        self.env = {'SHARING_ACCEPTANCE_DISPOSABLE': '1', 'SHARING_ACCEPTANCE_CORS_ORIGIN': self.payload['origin']}
        probe = patch.object(fixture, 'verify_exact_cors')
        self.probe = probe.start()
        self.addCleanup(probe.stop)
    def run_seed(self):
        fixture.seed(self.settings, self.get_client, self.payload, self.env)
    def test_valid_exact_destination(self):
        self.run_seed()
        self.client.create_bucket.assert_called_once_with(Bucket=self.bucket)
        self.client.put_bucket_cors.assert_not_called()
        self.probe.assert_called_once_with(self.endpoint, self.payload['origin'])
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
        self.probe.assert_not_called()
    def test_bucket_key_origin_pdf_rejected_before_client(self):
        for key,value in [('bucket','production'),('key','arbitrary.pdf'),('origin','http://remote.example:13420'),
                          ('pdf',base64.b64encode(b'not pdf').decode())]:
            old=self.payload[key];self.payload[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): self.run_seed()
            self.payload[key]=old
        self.get_client.assert_not_called()
    def test_exact_cors_origin_required_before_client_or_mutation(self):
        for value in ('', '*', 'http://remote.example:5180', 'http://localhost:5181'):
            self.env['SHARING_ACCEPTANCE_CORS_ORIGIN'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_seed()
        self.get_client.assert_not_called()
        self.probe.assert_not_called()
    def test_cors_probe_failure_precedes_all_storage_mutations(self):
        self.probe.side_effect = ValueError('synthetic CORS rejection')
        with self.assertRaises(ValueError):
            self.run_seed()
        self.client.create_bucket.assert_not_called()
        self.client.put_object.assert_not_called()
    def test_docker_endpoint_is_restricted_to_explicit_mode(self):
        with self.assertRaises(ValueError): fixture.isolated_endpoint('http://storage:9000','host')
        self.assertEqual(fixture.isolated_endpoint('http://storage:9000','docker'),'http://storage:9000')

class CorsTests(unittest.TestCase):
    def responses(self, positive='http://localhost:5180', negative=None, methods='GET'):
        values = []
        for origin in (positive, negative):
            response = MagicMock()
            response.__enter__.return_value.status = 204
            response.__enter__.return_value.headers = {'Access-Control-Allow-Methods': methods}
            if origin is not None:
                response.__enter__.return_value.headers['Access-Control-Allow-Origin'] = origin
            values.append(response)
        return values
    def test_positive_and_negative_preflight_use_only_verified_endpoint(self):
        with patch.object(fixture, 'urlopen', side_effect=self.responses()) as probe:
            verify_exact_cors('http://127.0.0.1:19200', 'http://localhost:5180')
        self.assertEqual(probe.call_count, 2)
        for invocation in probe.call_args_list:
            self.assertEqual(invocation.args[0].full_url, 'http://127.0.0.1:19200/')
            self.assertEqual(invocation.args[0].method, 'OPTIONS')
            self.assertEqual(invocation.kwargs, {'timeout': 5})
    def test_wildcard_wrong_origin_missing_get_or_negative_allowance_fail(self):
        for options in ({'positive': '*'}, {'positive': None}, {'positive': 'http://localhost:5181'},
                        {'methods': 'POST'}, {'negative': '*'}, {'negative': 'http://127.0.0.1:1'}):
            with self.subTest(options=options), patch.object(fixture, 'urlopen', side_effect=self.responses(**options)):
                with self.assertRaises(ValueError):
                    verify_exact_cors('http://127.0.0.1:19200', 'http://localhost:5180')

if __name__=='__main__': unittest.main()
