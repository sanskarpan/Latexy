"""Dependency-free harness guards. No services, TeX, browser, or probes run."""
import argparse
import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
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


def compile_fixture():
    """Wire-shaped public envelope + worker payload, without runtime imports."""
    job_id = '3bf24854-afeb-4bc7-a322-6a520f25bb9a'
    pdf = b'%PDF-1.4\nsynthetic protocol bytes for a helper unit test\n'
    prefix = '/download/' + job_id + '/preview/' + 'a' * 64
    artifact = {'artifact_id': 'a' * 64, 'job_id': job_id,
        'source_sha256': hashlib.sha256(smoke.MINIMAL_SOURCE.encode()).hexdigest(),
        'render_source_sha256': hashlib.sha256(smoke.MINIMAL_SOURCE.encode()).hexdigest(),
        'content_revision': 1, 'document_id': 'guest', 'branch': 'draft', 'owner_epoch': 1, 'run_id': None,
        'compiler': 'pdflatex', 'settings_sha256': 'b' * 64,
        'pdf_sha256': hashlib.sha256(pdf).hexdigest(), 'pdf_size': len(pdf), 'page_count': 1,
        'preview_url': prefix, 'geometry_url': prefix + '/geometry'}
    result = {'success': True, 'job_id': job_id, 'pdf_job_id': job_id, 'compilation_time': 1.23,
        'pdf_size': len(pdf), 'page_count': 1, 'slide_count': None, 'is_beamer': False,
        'extracted_text': 'Local real worker smoke produced a verified artifact.', 'artifact': artifact}
    envelope = {'success': True, 'job_id': job_id, 'result': result, 'error': None}
    geometry = {'schema_version': 1, 'coordinate_system': 'pdf_points_top_left',
        'source_sha256': artifact['source_sha256'], 'pdf_sha256': artifact['pdf_sha256'],
        'document_id': 'guest', 'content_revision': 1, 'branch': 'draft', 'artifact_id': artifact['artifact_id'],
        'pages': [{'page': 1, 'width': 612, 'height': 792, 'rotation': 0}],
        'boxes': [{'node_id': 'literal-node', 'node_revision': 1, 'kind': 'bullet',
            'text': 'Local real worker smoke produced a verified artifact.',
            'source_span': {'start': 0, 'end': 1}, 'page': 1, 'x': 10, 'y': 20, 'width': 100, 'height': 12}],
        'omissions': []}
    return job_id, envelope, pdf, geometry


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

    def test_internal_endpoint_requires_exact_ownership_network_and_private_address(self):
        container = {'id': 'owned-container', 'name': '/owned-api', 'run': 'run', 'running': True,
            'status': 'running', 'ports': {'8030/tcp': None}, 'networks': {'owned-network': {
                'NetworkID': 'network-id', 'EndpointID': 'endpoint-id', 'IPAddress': '172.18.0.2'}}}
        network = {'Id': 'network-id', 'Name': 'owned-network', 'Driver': 'bridge', 'Scope': 'local',
            'Internal': True, 'Labels': {'latexy.ci.run': 'run'}, 'IPAM': {'Config': [
                {'Subnet': '172.18.0.0/16', 'Gateway': '172.18.0.1'}]}, 'Containers': {'owned-container': {
                    'Name': 'owned-api', 'EndpointID': 'endpoint-id', 'IPv4Address': '172.18.0.2/16'}}}
        def validate(c=container, n=network):
            return harness.owned_internal_address(c, n, name='owned-api', network_name='owned-network', run_id='run')
        self.assertEqual(validate(), '172.18.0.2')
        # Docker can serialize no host bindings as either null or an empty map.
        self.assertEqual(validate({**container, 'ports': None}), '172.18.0.2')
        self.assertEqual(validate({**container, 'ports': {}}), '172.18.0.2')
        for updates in ({'run': 'other'}, {'name': '/other'}, {'running': False}, {'status': 'exited'},
                        {'ports': {'8030/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8030'}]}},
                        {'networks': {**container['networks'], 'egress': {}}}, {'id': 'other-container'},
                        {'ports': []}, {'ports': 'not-a-map'}):
            with self.assertRaises(RuntimeError):
                validate({**container, **updates})
        for updates in ({'Internal': False}, {'Name': 'other'}, {'Driver': 'host'}, {'Scope': 'swarm'},
                        {'Labels': {}}, {'Id': 'other-network'}, {'Containers': {}},
                        {'Options': {'com.docker.network.bridge.gateway_mode_ipv4': 'isolated'}},
                        {'IPAM': {'Config': [{'Subnet': '10.0.0.0/8'}]}}):
            with self.assertRaises(RuntimeError):
                validate(n={**network, **updates})
        for address in ('127.0.0.1', '169.254.1.2', '0.0.0.0', '224.0.0.1', '8.8.8.8',
                        '172.18.0.0', '172.18.255.255', '172.18.0.1'):
            bad = copy.deepcopy(container)
            bad['networks']['owned-network']['IPAddress'] = address
            with self.assertRaises(RuntimeError):
                validate(bad)

    def test_relay_forwards_opaque_duplex_bytes_and_half_close_using_only_socketpairs(self):
        client, client_side = socket.socketpair()
        upstream_side, upstream = socket.socketpair()
        sockets = (client, client_side, upstream_side, upstream)
        for connection in sockets:
            connection.settimeout(2)
        stop = threading.Event()
        errors = []
        def forward():
            try:
                harness.relay_streams(client_side, upstream_side, stop, time.monotonic() + 3)
            except (OSError, ValueError, KeyError) as error:
                errors.append(error)
        thread = threading.Thread(target=forward, daemon=True)
        thread.start()
        try:
            request = b'GET /api/ws HTTP/1.1\r\nUpgrade: websocket\r\n\r\n\x00\xff\x80'
            client.sendall(request)
            self.assertEqual(upstream.recv(4096), request)
            response = b'HTTP/1.1 101 Switching Protocols\r\n\r\n\x82\x00\xff'
            upstream.sendall(response)
            self.assertEqual(client.recv(4096), response)
            client.shutdown(socket.SHUT_WR)
            self.assertEqual(upstream.recv(1), b'')
            # A response after one-direction EOF must still reach the client.
            upstream.sendall(b'final\x00bytes')
            self.assertEqual(client.recv(4096), b'final\x00bytes')
            upstream.shutdown(socket.SHUT_WR)
            self.assertEqual(client.recv(1), b'')
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        finally:
            stop.set()
            for connection in sockets:
                connection.close()
            thread.join(timeout=2)

    def test_relay_constructor_has_no_generic_external_destination_or_listener_reuse(self):
        for address, port in (('8.8.8.8', 8030), ('127.0.0.1', 8030), ('169.254.1.2', 5432),
                              ('172.18.0.2', 80), ('172.18.0.2', 9000)):
            with self.assertRaises(RuntimeError):
                harness.FixedTargetRelay(address, port, time.monotonic() + 1)
        self.assertFalse(harness.FixedTargetRelay.allow_reuse_address)
        self.assertIn("super().__init__(('127.0.0.1', 0), Handler)", inspect.getsource(harness.FixedTargetRelay.__init__))
        prepare = inspect.getsource(harness.Harness.prepare)
        self.assertNotIn('--publish', prepare)
        self.assertIn('"--internal"', prepare)
        self.assertNotIn('published_port', prepare)

    def test_relay_streams_stop_at_deadline_or_owned_stop_signal(self):
        client, upstream = MagicMock(), MagicMock()
        stop = threading.Event()
        with patch.object(harness.select, 'select') as select:
            harness.relay_streams(client, upstream, stop, time.monotonic() - 1)
            select.assert_not_called()
            stop.set()
            harness.relay_streams(client, upstream, stop, time.monotonic() + 10)
            select.assert_not_called()

    def test_relay_close_closes_owned_active_sockets_even_after_shutdown_error(self):
        relay = object.__new__(harness.FixedTargetRelay)
        relay.stop_event = threading.Event()
        relay.lock = threading.Lock()
        relay.workers_done = threading.Condition(relay.lock)
        relay.workers = set()
        connection = MagicMock()
        connection.shutdown.side_effect = OSError('already shut down')
        relay.connections = {connection}
        relay.shutdown = MagicMock()
        relay.server_close = MagicMock()
        relay.thread = MagicMock()
        relay.thread.is_alive.return_value = False
        relay.close()
        self.assertTrue(relay.stop_event.is_set())
        connection.close.assert_called_once()
        relay.shutdown.assert_called_once()
        relay.server_close.assert_called_once()
        relay.thread.join.assert_called_once_with(timeout=5)

    def test_relay_creation_refuses_unknown_resources_before_any_inspection(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            instance.names = [instance.prefix + '-api', instance.prefix + '-storage']
            instance.docker = MagicMock()
            for name, port in (('other-api', 8030), (instance.prefix + '-storage', 9000),
                               (instance.prefix + '-api', 5432)):
                with self.assertRaises(RuntimeError):
                    instance.relay_port(name, port)
            instance.docker.assert_not_called()

    def test_relay_creation_inspects_only_own_target_and_registers_exact_bound_socket(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            name = instance.prefix + '-api'
            instance.names = [name]
            instance.docker = MagicMock(side_effect=['{}', '{}'])
            relay = MagicMock(server_address=('127.0.0.1', 12345))
            with (patch.object(harness, 'owned_internal_address', return_value='172.18.0.2') as validate,
                  patch.object(harness, 'FixedTargetRelay', return_value=relay) as create):
                self.assertEqual(instance.relay_port(name, 8030), 12345)
            validate.assert_called_once_with({}, {}, name=name, network_name=instance.network, run_id=instance.run_id)
            create.assert_called_once_with('172.18.0.2', 8030, instance.deadline)
            self.assertEqual(instance.relays, [relay])
            self.assertEqual(instance.docker.call_args_list[0].args,
                             ('inspect', '--format', harness.CONTAINER_STATE_FORMAT, name))
            self.assertEqual(instance.docker.call_args_list[1].args,
                             ('network', 'inspect', '--format', '{{json .}}', instance.network))

    def test_sanitized_diagnostics_keep_errors_without_fixture_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            instance.app_environment = {'MINIO_SECRET_KEY': 'synthetic-secret', 'MINIO_ACCESS_KEY': 'synthetic-user',
                'JWT_SECRET_KEY': 'synthetic-jwt', 'API_KEY_ENCRYPTION_KEY': 'synthetic-fernet'}
            value = ('failure synthetic-secret synthetic-user synthetic-jwt synthetic-fernet '
                'postgresql://fixture:pass@postgres/db Authorization: Bearer token123 '
                'http://api/path?token=querysecret')
            sanitized = instance.sanitize_diagnostic(value)
            for secret in ('synthetic-secret', 'synthetic-user', 'synthetic-jwt', 'synthetic-fernet',
                           'fixture:pass', 'token123', 'querysecret'):
                self.assertNotIn(secret, sanitized)
            self.assertIn('failure', sanitized)
            self.assertEqual(instance.sanitize_diagnostic('12345678', limit=3), '678')
            self.assertNotIn('.Config.Env', harness.CONTAINER_STATE_FORMAT)

    def test_failure_diagnostics_run_before_cleanup_refuse_unowned_and_remain_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            instance = harness.Harness(work, work, work)
            instance.names = [instance.prefix + '-api', 'unrelated-container']
            result = subprocess.CompletedProcess([], 0, json.dumps({'name': '/' + instance.names[0], 'run': 'other'}), '')
            with patch.object(harness.subprocess, 'run', return_value=result) as run:
                instance.collect_failure_diagnostics()
            run.assert_called_once()
            self.assertLessEqual(run.call_args.kwargs['timeout'], 5)
            self.assertEqual(run.call_args.args[0][-1], instance.names[0])
            evidence = json.loads((work / 'owned-container-diagnostics.json').read_text())
            self.assertEqual(len(evidence), 1)
            self.assertIn('logs refused', evidence[0]['diagnostic_error'])
        main = inspect.getsource(harness.main)
        self.assertLess(main.index('harness.collect_failure_diagnostics()'), main.index('harness.cleanup()'))

    def test_failure_diagnostics_capture_only_filtered_own_state_and_redacted_startup_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            instance = harness.Harness(work, work, work)
            name = instance.prefix + '-api'
            instance.names = [name]
            instance.app_environment = {'JWT_SECRET_KEY': 'synthetic-secret'}
            state = {'id': 'fixture', 'name': '/' + name, 'run': instance.run_id, 'status': 'exited',
                'running': False, 'exit_code': 1, 'oom_killed': False, 'networks': {}, 'ports': {},
                'error': 'failure synthetic-secret'}
            results = [subprocess.CompletedProcess([], 0, json.dumps(state), ''),
                       subprocess.CompletedProcess([], 0, 'Startup failure synthetic-secret', '')]
            with patch.object(harness.subprocess, 'run', side_effect=results) as run:
                instance.collect_failure_diagnostics()
            self.assertEqual(run.call_args_list[1].args[0], ['docker', 'logs', '--tail', '60', name])
            evidence = (work / 'owned-container-diagnostics.json').read_text()
            self.assertNotIn('synthetic-secret', evidence)
            self.assertIn('Startup failure', evidence)
            self.assertEqual(json.loads(evidence)[0]['state']['exit_code'], 1)

    def test_cleanup_closes_owned_relays_and_keeps_removing_containers_after_relay_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            instance.names = [instance.prefix + '-api']
            good, failed = MagicMock(), MagicMock()
            failed.close.side_effect = RuntimeError('synthetic')
            instance.relays = [good, failed]
            instance.docker = MagicMock()
            self.assertEqual(instance.cleanup(), ['loopback-relay'])
            good.close.assert_called_once()
            failed.close.assert_called_once()
            instance.docker.assert_called_once_with('rm', '--force', '--volumes', instance.names[0], timeout=30, capture=True)

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

    def test_minio_fixture_uses_pinned_official_source_and_verified_go_builder(self):
        recipe = (HERE / 'Dockerfile.minio-ci').read_text()
        self.assertEqual(harness.MINIO_SOURCE_COMMIT, '9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a')
        self.assertEqual(harness.MINIO_MODULE_VERSION, 'v0.0.0-20251015172955-9e49d5e7a648')
        self.assertIn('FROM golang:1.24.8-bookworm@sha256:4ed690d6649d63c312b99a6120025ec79ce3b542968a37da53d6236c7c61a848 AS build', recipe)
        self.assertIn('GOSUMDB=sum.golang.org', recipe)
        self.assertIn('GOPROXY=https://proxy.golang.org', recipe)
        self.assertIn('GOTOOLCHAIN=local', recipe)
        self.assertIn('CGO_ENABLED=0', recipe)
        self.assertIn('go install -trimpath -p 2 github.com/minio/minio@' + harness.MINIO_MODULE_VERSION, recipe)
        self.assertIn('org.opencontainers.image.revision="' + harness.MINIO_SOURCE_COMMIT + '"', recipe)
        self.assertIn('FROM scratch', recipe)
        self.assertIn('USER 65532:65532', recipe)
        self.assertNotIn('GOSUMDB=off', recipe)
        self.assertNotIn('storage', harness.SERVICE_IMAGES)
        prepare = inspect.getsource(harness.Harness.prepare)
        self.assertLess(prepare.index('self.prepare_storage_image()'), prepare.index('self.image_attempted = True'))
        self.assertLess(prepare.index('self.app_environment.update(MINIO_ACCESS_KEY=access, MINIO_SECRET_KEY=secret)'),
                        prepare.index('storage = self.start('))

    def test_owned_storage_build_context_and_provenance_have_no_application_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            instance = harness.Harness(HERE.parents[1], work, work)
            instance.docker = MagicMock(return_value='sha256:synthetic-storage')
            instance.prepare_storage_image()
            self.assertEqual([path.name for path in (work / 'storage-context').iterdir()], ['Dockerfile'])
            self.assertTrue(instance.storage_image_attempted and instance.storage_image_built)
            self.assertEqual(instance.provenance['storage_source_commit'], harness.MINIO_SOURCE_COMMIT)
            self.assertEqual(instance.provenance['storage_image_id'], 'sha256:synthetic-storage')
            self.assertEqual(len(instance.provenance['storage_recipe_sha256']), 64)
            self.assertEqual(instance.docker.call_args_list[0].kwargs['timeout'], 900)

    def test_cleanup_removes_only_owned_storage_fixture_image_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            instance = harness.Harness(Path(temporary), Path(temporary), Path(temporary))
            instance.storage_image_attempted = instance.storage_image_built = True
            instance.docker = MagicMock()
            self.assertEqual(instance.cleanup(), [])
            instance.docker.assert_called_once_with('image', 'rm', instance.storage_image, timeout=30, capture=True)
            instance.docker = MagicMock(side_effect=subprocess.TimeoutExpired('docker', 30))
            self.assertEqual(instance.cleanup(), ['storage-image'])

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

    def test_compile_result_unwraps_actual_public_envelope_without_runtime_imports(self):
        job_id, envelope, _, _ = compile_fixture()
        self.assertIs(smoke.unwrap_compile_result(envelope, job_id), envelope['result'])
        route = ast.parse((HERE.parents[1] / 'backend/app/api/job_routes.py').read_text())
        model = next(node for node in route.body if isinstance(node, ast.ClassDef) and node.name == 'JobResultResponse')
        fields = {node.target.id for node in model.body if isinstance(node, ast.AnnAssign)}
        self.assertEqual(fields, {'success', 'job_id', 'result', 'error'})

    def test_compile_result_rejects_failure_delivery_failure_and_success_disagreement(self):
        job_id, envelope, _, _ = compile_fixture()
        failed = {'success': False, 'job_id': job_id, 'result': None, 'error': 'synthetic-private-detail'}
        delivery = {**failed, 'result': {**envelope['result'], 'success': False, 'output_unavailable': True}}
        for value in (failed, delivery, {**envelope, 'success': False},
                      {**envelope, 'error': 'synthetic-private-detail'},
                      {**envelope, 'result': {**envelope['result'], 'success': False}},
                      {**envelope, 'result': {**envelope['result'], 'error': 'synthetic-private-detail'}}):
            with self.assertRaises(RuntimeError) as error:
                smoke.unwrap_compile_result(value, job_id)
            self.assertNotIn('synthetic-private-detail', str(error.exception))

    def test_compile_result_rejects_flattened_missing_malformed_and_cross_job_shapes(self):
        job_id, envelope, _, _ = compile_fixture()
        result = envelope['result']
        for value in (None, [], True, 'not an envelope', {}, result,
                      {key: value for key, value in envelope.items() if key != 'error'},
                      {**envelope, 'artifact': result['artifact']},
                      {**envelope, 'result': None}, {**envelope, 'result': []},
                      {**envelope, 'success': 1}, {**envelope, 'job_id': 'other'},
                      {**envelope, 'result': {**result, 'success': 1}},
                      {**envelope, 'result': {**result, 'job_id': 'other'}},
                      {**envelope, 'result': {**result, 'pdf_job_id': 'other'}},
                      {**envelope, 'result': {key: value for key, value in result.items() if key != 'artifact'}},
                      {**envelope, 'result': {**result, 'artifact': None}},
                      {**envelope, 'result': {**result, 'artifact': []}},
                      {**envelope, 'result': {**result, 'artifact': {}}},
                      {**envelope, 'result': {**result, 'artifact': {**result['artifact'], 'job_id': 'other'}}}):
            with self.assertRaises(RuntimeError):
                smoke.unwrap_compile_result(value, job_id)

    def test_artifact_identity_matches_guest_manifest_and_rejects_boolean_or_wrong_metadata(self):
        job_id, envelope, pdf, _ = compile_fixture()
        artifact = envelope['result']['artifact']
        self.assertEqual(smoke.validate_artifact(artifact, job_id, smoke.MINIMAL_SOURCE, 'pdflatex', pdf), 'a' * 64)
        for updates in ({'page_count': True}, {'page_count': 0}, {'content_revision': True},
                        {'document_id': 'other'}, {'branch': 'candidate'}, {'compiler': 'lualatex'},
                        {'source_sha256': 'c' * 64}, {'pdf_sha256': 'c' * 64}, {'pdf_size': len(pdf) + 1}):
            with self.assertRaises(RuntimeError):
                smoke.validate_artifact({**artifact, **updates}, job_id, smoke.MINIMAL_SOURCE, 'pdflatex', pdf)

    def test_smoke_reader_consumes_model_shaped_result_and_real_route_shapes_with_one_identity(self):
        job_id, envelope, pdf, geometry = compile_fixture()
        artifact = envelope['result']['artifact']
        prefix = artifact['preview_url']
        calls = []
        def request(base, path, fingerprint, payload=None):
            self.assertEqual(base, 'http://127.0.0.1:8030')
            calls.append((path, fingerprint))
            if path == '/jobs/submit':
                self.assertEqual(payload, {'job_type': 'latex_compilation', 'latex_content': smoke.MINIMAL_SOURCE,
                    'compiler': 'pdflatex', 'device_fingerprint': fingerprint})
            responses = {
                '/health': ({'status': 'healthy', 'latex_available': True}, 'application/json'),
                '/jobs/submit': ({'success': True, 'job_id': job_id, 'message': 'Started', 'estimated_time': 30}, 'application/json'),
                f'/jobs/{job_id}/result': (envelope, 'application/json'),
                f'/jobs/{job_id}/state': ({'status': 'completed', 'stage': 'done', 'percent': 100,
                    'last_updated': 1.0, 'artifact': artifact}, 'application/json'),
                f'/download/{job_id}': (pdf, 'application/pdf'),
                prefix: (pdf, 'application/pdf'),
                prefix + '/synctex': (b'SyncTeX Version:1\nInput:1:resume.tex\n', 'text/plain'),
                prefix + '/geometry': (geometry, 'application/json'),
            }
            body, media = responses[path]
            return (body if isinstance(body, bytes) else json.dumps(body).encode()), media
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'evidence.json'
            with (patch.object(sys, 'argv', ['local-job-smoke.py', '--base-url', 'http://127.0.0.1:8030', '--output', str(output)]),
                  patch.object(smoke, 'request', side_effect=request), patch('builtins.print'),
                  patch.object(smoke.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'Local real worker smoke', b''))):
                smoke.main()
            report = json.loads(output.read_text())
            self.assertTrue(report['success'])
            self.assertEqual(report['artifact_id'], artifact['artifact_id'])
            self.assertEqual(report['pdf_sha256'], hashlib.sha256(pdf).hexdigest())
            self.assertEqual(report['geometry_boxes'], 1)
            self.assertEqual(len(calls), 8)
            self.assertEqual(len({fingerprint for _, fingerprint in calls}), 1)
            self.assertNotIn(calls[0][1], output.read_text())
            self.assertNotIn(smoke.MINIMAL_SOURCE, output.read_text())

    def test_smoke_reader_refuses_bad_result_before_state_or_artifact_download(self):
        job_id, envelope, _, _ = compile_fixture()
        responses = [{'status': 'healthy', 'latex_available': True},
                     {'success': True, 'job_id': job_id, 'message': 'Started'}, envelope['result']]
        with (patch.object(sys, 'argv', ['local-job-smoke.py']), patch('builtins.print'),
              patch.object(smoke, 'request', side_effect=[(json.dumps(value).encode(), 'application/json') for value in responses]) as request,
              self.assertRaises(RuntimeError)):
            smoke.main()
        self.assertEqual(request.call_count, 3)

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
