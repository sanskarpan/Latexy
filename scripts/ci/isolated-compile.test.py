"""Dependency-free harness guards. No services, TeX, browser, or probes run."""
import argparse
import ast
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


harness = module('isolated-real-compile')
smoke = module('local-job-smoke')
# Extract the pure helper without importing application settings or conftest's
# relaxed recorder fixture. These tests must never launch a security probe.
source = HERE.parents[1] / 'backend/scripts/certify_resume_templates.py'
tree = ast.parse(source.read_text())
helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'require_certified_matrix')
namespace = {}
exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), 'exec'), namespace)  # noqa: S102 -- repository-owned pure helper only
require_matrix = namespace['require_certified_matrix']


class HarnessGuards(unittest.TestCase):
    def test_clean_environment_drops_credentials_and_operator_paths(self):
        with patch.dict(os.environ, {'PATH': '/bin', 'DATABASE_URL': 'remote', 'OPENAI_API_KEY': 'operator',
            'DOCKER_HOST': 'tcp://remote', 'DOCKER_CONFIG': '/operator', 'HOME': '/operator',
            'NODE_OPTIONS': '--require=/operator', 'PLAYWRIGHT_BROWSERS_PATH': '/ci/browsers'}, clear=True):
            environment = harness.clean_environment(Path('/tmp/synthetic-home'))
        self.assertEqual(environment['HOME'], '/tmp/synthetic-home')
        self.assertEqual(environment['PLAYWRIGHT_BROWSERS_PATH'], '/ci/browsers')
        for key in ('DATABASE_URL', 'OPENAI_API_KEY', 'DOCKER_HOST', 'DOCKER_CONFIG', 'NODE_OPTIONS'):
            self.assertNotIn(key, environment)

    def test_context_has_source_allowlist_and_no_dotenv_or_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = root / 'backend'
            backend.mkdir()
            for directory in ('app', 'alembic', 'scripts', 'test'):
                (backend / directory).mkdir()
                (backend / directory / 'candidate.py').write_text('synthetic')
                (backend / directory / '.env.local').write_text('operator')
            (backend / '.aws').mkdir()
            (backend / '.aws/credentials').write_text('operator')
            (backend / '.env').write_text('operator')
            for name in ('requirements.lock', 'requirements-dev.lock', 'alembic.ini', 'pytest.ini', 'Dockerfile.prod'):
                (backend / name).write_text('FROM fake AS production\n')
            (root / 'scripts/ci').mkdir(parents=True)
            (root / 'scripts/ci/local-job-smoke.py').write_text('synthetic')
            target = root / 'context'
            harness.copy_candidate_context(root, target)
            self.assertTrue((target / 'app/candidate.py').exists())
            self.assertTrue((target / 'scripts/ci/local-job-smoke.py').exists())
            self.assertFalse(any(path.name.startswith('.') for path in target.rglob('*')))
            self.assertIn('FROM production AS isolated-ci', (target / 'Dockerfile.prod').read_text())

    def test_readiness_is_not_an_existing_listener_or_infinite_wait(self):
        with (patch.object(harness.time, 'monotonic', side_effect=[0, 0, 1]), patch.object(harness.time, 'sleep'),
              self.assertRaisesRegex(RuntimeError, 'deadline')):
            harness.wait_until_ready(lambda: False, lambda: True, 0.5)
        with self.assertRaisesRegex(RuntimeError, 'exited'):
            harness.wait_until_ready(lambda: True, lambda: False, 1)
        harness.wait_until_ready(lambda: True, lambda: True, 1)

    def test_cleanup_targets_only_registered_owned_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            instance.names = [instance.prefix + '-api', instance.prefix + '-worker']
            instance.network_created = True
            instance.image_attempted = True
            instance.docker = MagicMock()
            self.assertEqual(instance.cleanup(), [])
            calls = [call.args for call in instance.docker.call_args_list]
            self.assertEqual(calls[:2], [('rm', '--force', '--volumes', instance.names[1]),
                                        ('rm', '--force', '--volumes', instance.names[0])])
            self.assertEqual(calls[2], ('network', 'rm', instance.network))
            self.assertEqual(calls[3], ('image', 'rm', instance.image))
            self.assertTrue(all('prune' not in call for call in calls))

    def test_cleanup_reports_owned_container_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            instance.names = [instance.prefix + '-api']
            instance.docker = MagicMock(side_effect=RuntimeError('synthetic'))
            self.assertEqual(instance.cleanup(), instance.names)

    def test_cleanup_timeout_keeps_cleaning_remaining_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            instance.names = [instance.prefix + '-api', instance.prefix + '-worker']
            instance.network_created = True
            instance.image_attempted = instance.image_built = True
            instance.docker = MagicMock(side_effect=[subprocess.TimeoutExpired('docker', 30), None, None,
                                                    OSError('synthetic image cleanup failure')])
            self.assertEqual(instance.cleanup(), [instance.names[1], 'candidate-image'])
            self.assertEqual(instance.docker.call_count, 4)

    def test_process_cleanup_does_not_kill_arbitrary_ports(self):
        process = MagicMock(pid=12345)
        process.poll.return_value = None
        with patch.object(harness.os, 'killpg') as kill:
            harness.stop_owned_process(process)
        kill.assert_called_once_with(12345, harness.signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=15)

    def test_overall_deadline_bounds_commands_but_never_disables_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            instance.deadline = 100
            with patch.object(harness.time, 'monotonic', return_value=90):
                self.assertEqual(instance.phase_timeout(30), 10)
            with patch.object(harness.time, 'monotonic', return_value=101):
                with self.assertRaisesRegex(RuntimeError, 'overall deadline'):
                    instance.phase_timeout(30)
                instance.names = [instance.prefix + '-api']
                instance.docker = MagicMock()
                self.assertEqual(instance.cleanup(), [])
                self.assertTrue(instance.cleaning)
                instance.docker.assert_called_once()

    def test_junit_exact_cases_no_empty_or_skipped_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'result.xml'
            for body in ('<testsuite/>', '<testsuite><testcase><skipped/></testcase></testsuite>',
                         '<testsuite><testcase><failure/></testcase></testsuite>',
                         '<testsuite><testcase><error/></testcase></testsuite>'):
                path.write_text(body)
                with self.assertRaises(RuntimeError):
                    harness.require_junit_cases(path, expected=1)
            path.write_text('<testsuite><testcase/><testcase/></testsuite>')
            self.assertEqual(harness.require_junit_cases(path, expected=2), 2)
            with self.assertRaises(RuntimeError):
                harness.require_junit_cases(path, expected=1)

    def test_browser_proof_requires_two_complete_nonmocked_samples(self):
        sample = {key: True for key in ('websocket_artifact', 'websocket_completed', 'canvas_painted',
            'expected_text_rendered', 'synctex_mappable', 'pdf_geometry_synctex_fingerprint_matches')}
        sample.update(terminal_status='completed', admission_http_status=200)
        good = {'success': True, 'scenario': 'normal-guest-initial-and-latest-source', 'samples': [sample, sample],
            'admission_count': 2, 'runtime_error_count': 0, 'capture_error_count': 0, 'external_request_count': 0}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'browser-proof.json'
            path.write_text(json.dumps(good))
            harness.require_browser_proof(path)
            for updates in ({'success': False}, {'samples': []}, {'samples': [sample]}, {'admission_count': 1},
                            {'external_request_count': 1}, {'runtime_error_count': 1},
                            {'samples': [sample, {**sample, 'canvas_painted': False}]}):
                path.write_text(json.dumps({**good, **updates}))
                with self.assertRaises(RuntimeError):
                    harness.require_browser_proof(path)

    def test_local_origin_rejects_external_and_credential_destinations(self):
        for value in ('https://127.0.0.1:1', 'http://remote:1', 'http://name:secret@localhost:1',
                      'http://localhost:1/path', 'http://localhost:1?secret=x', 'http://localhost:0', 'http://localhost:abc'):
            with self.assertRaises(argparse.ArgumentTypeError):
                smoke.local_origin(value)
        self.assertEqual(smoke.local_origin('http://127.0.0.1:12345/'), 'http://127.0.0.1:12345')

    def test_owned_hindi_fixture_resolves_in_repository_and_backend_image(self):
        self.assertEqual(smoke.hindi_fixture_path(HERE / 'local-job-smoke.py'),
                         HERE.parents[1] / 'backend/app/data/templates/ats_safe/hindi_professional.tex')
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / 'app'
            script = image / 'scripts/ci/local-job-smoke.py'
            script.parent.mkdir(parents=True)
            script.write_text('synthetic')
            self.assertEqual(smoke.hindi_fixture_path(script),
                             image / 'app/data/templates/ats_safe/hindi_professional.tex')

    def test_context_identity_changes_with_candidate_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'candidate.py').write_text('first')
            first = harness.context_digest(root)
            self.assertEqual(first, harness.context_digest(root))
            (root / 'candidate.py').write_text('second')
            self.assertNotEqual(first, harness.context_digest(root))

    def test_single_synthetic_identity_is_sent_on_artifact_reads(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'%PDF-synthetic'
        response.headers.get_content_type.return_value = 'application/pdf'
        with patch.object(smoke, 'urlopen', return_value=response) as opened:
            smoke.request('http://127.0.0.1:1', '/download/synthetic', 'single-device')
        self.assertEqual(opened.call_args.args[0].get_header('X-device-fingerprint'), 'single-device')

    def test_server_artifact_urls_cannot_redirect_to_other_origins_or_jobs(self):
        expected = '/download/synthetic/preview/' + 'a' * 64
        self.assertEqual(smoke.artifact_path(expected, expected), expected)
        for value in ('https://remote/pdf', '/download/other/preview/' + 'a' * 64, None):
            with self.assertRaises(RuntimeError):
                smoke.artifact_path(value, expected)

    def test_geometry_requires_exact_identity_and_finite_page_coordinates(self):
        artifact = {'artifact_id': 'a', 'pdf_sha256': 'p', 'source_sha256': 's', 'content_revision': 1, 'page_count': 1}
        geometry = {**artifact, 'branch': 'draft', 'coordinate_system': 'pdf_points_top_left',
            'pages': [{'page': 1, 'width': 600, 'height': 800}],
            'boxes': [{'page': 1, 'x': 10, 'y': 20, 'width': 100, 'height': 30}]}
        smoke.validate_geometry(geometry, artifact, require_boxes=True)
        for updates in ({'pdf_sha256': 'other'}, {'boxes': []},
                        {'boxes': [{'page': 1, 'x': float('nan'), 'y': 1, 'width': 1, 'height': 1}]},
                        {'boxes': [{'page': 1, 'x': 599, 'y': 1, 'width': 4, 'height': 1}]}):
            with self.assertRaises(RuntimeError):
                smoke.validate_geometry({**geometry, **updates}, artifact, require_boxes=True)

    def test_certificate_fails_closed_on_empty_missing_or_failed_sample(self):
        good = {'fixture': 'required.tex', 'certified': True, 'samples': [{'success': True}]}
        require_matrix([good], ['required.tex'], 1)
        for entries, required, count in (([], [], 1), ([good], ['missing.tex'], 1),
            ([good, good], [], 1), ([good], [], 2),
            ([{**good, 'certified': False}], [], 1), ([{**good, 'samples': []}], [], 1),
            ([{**good, 'samples': [{'success': False}]}], [], 1)):
            with self.assertRaises(RuntimeError):
                require_matrix(entries, required, count)


if __name__ == '__main__':
    unittest.main()
