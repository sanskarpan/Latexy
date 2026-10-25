"""No Docker/services: prove isolation, exact cleanup and browser CI selection."""
import importlib.util
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, call, patch

spec = importlib.util.spec_from_file_location('sharing_ci', Path(__file__).with_name('sharing-full-stack-smoke.py'))
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class SharingCITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='latexy-sharing-guards-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.browser_cache = self.directory / 'installed-browsers'
        self.browser_cache.mkdir()

    def services(self):
        return dict(DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/latexy_test',
            REDIS_URL='redis://localhost:6379/0', REDIS_CACHE_URL='redis://localhost:6379/1',
            CELERY_BROKER_URL='redis://localhost:6379/0', CELERY_RESULT_BACKEND='redis://localhost:6379/0',
            PLAYWRIGHT_BROWSERS_PATH=str(self.browser_cache))

    def test_shared_installed_browser_cache_survives_home_replacement(self):
        environment = harness.test_environment(self.services(), self.directory / 'fresh-home')
        self.assertEqual(environment['PLAYWRIGHT_BROWSERS_PATH'], str(self.browser_cache))
        self.assertNotEqual(environment['HOME'], str(self.browser_cache.parent))
        for invalid in ('', '0', 'relative-cache', str(self.directory / 'missing-cache')):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                harness.test_environment(dict(self.services(), PLAYWRIGHT_BROWSERS_PATH=invalid), self.directory)

    def test_runtime_dotenv_variants_are_rejected_without_reading_or_printing_contents(self):
        for directory in (self.directory, self.directory / 'backend', self.directory / 'frontend'):
            directory.mkdir(exist_ok=True)
        synthetic = 'synthetic-do-not-read-or-print'
        for location in ('', 'backend', 'frontend'):
            for name in ('.env', '.env.local', '.env.test', '.env.development', '.env.development.local',
                         '.env.production', '.env.production.local', '.env.staging'):
                path = self.directory / location / name
                path.write_text(synthetic)
                output = io.StringIO()
                with self.subTest(location=location, name=name), \
                        patch.object(Path, 'read_text') as read, \
                        patch.object(harness.subprocess, 'run') as run, \
                        patch.object(harness.subprocess, 'Popen') as launch, \
                        redirect_stdout(output), redirect_stderr(output):
                    with self.assertRaisesRegex(RuntimeError, 'runtime dotenv files'):
                        harness.reject_runtime_env_files(self.directory)
                    read.assert_not_called()
                    run.assert_not_called()
                    launch.assert_not_called()
                self.assertEqual(output.getvalue(), '')
                path.unlink()
        for location, name in (('', '.env.production.example'), ('backend', '.env.example'),
                               ('frontend', '.env.example'), ('frontend', '.env.production.example')):
            (self.directory / location / name).write_text(synthetic)
        harness.reject_runtime_env_files(self.directory)

    def test_main_dotenv_preflight_precedes_any_subprocess_or_storage_setup(self):
        with patch.object(harness.sys, 'argv', ['sharing-full-stack-smoke.py', '--confirm-isolated-sharing-run']), \
                patch.object(harness.os, 'name', 'posix'), \
                patch.object(harness, 'reject_runtime_env_files', side_effect=RuntimeError('runtime dotenv files')), \
                patch.object(harness.subprocess, 'run') as run, \
                patch.object(harness.subprocess, 'Popen') as launch, \
                patch.object(harness, 'SharingStorage') as storage:
            with self.assertRaisesRegex(RuntimeError, 'runtime dotenv files'):
                harness.main()
        run.assert_not_called()
        launch.assert_not_called()
        storage.assert_not_called()

    def test_remote_or_non_test_services_fail_before_any_subprocess(self):
        for key, bad in [('DATABASE_URL', 'postgresql://postgres@remote.example:5432/latexy_test'),
                         ('DATABASE_URL', 'postgresql://postgres@localhost:5432/latexy'),
                         ('DATABASE_URL', 'postgresql://postgres@localhost:5432/latexy_test?service=live'),
                         ('REDIS_URL', 'redis://remote.example:6379/0'),
                         ('CELERY_RESULT_BACKEND', 'rediss://localhost:6379/0')]:
            with self.subTest(key=key, bad=bad), patch.object(harness.subprocess, 'run') as run:
                source = self.services()
                source[key] = bad
                with self.assertRaises(RuntimeError):
                    harness.test_environment(source, Path('synthetic-home'))
                run.assert_not_called()

    def test_environment_discards_inherited_storage_and_provider_secrets(self):
        source = dict(self.services(), OPENAI_API_KEY='synthetic-provider', AWS_SECRET_ACCESS_KEY='synthetic-key',
                      MINIO_ENDPOINT='https://remote.example', MINIO_BUCKET='production',
                      DOCKER_HOST='tcp://remote.example:2375', DOCKER_CONFIG='operator-config',
                      BETTER_AUTH_SECRET='persistent-synthetic', PATH='runtime-path')
        environment = harness.test_environment(source, Path('synthetic-home'))
        self.assertEqual(environment['OPENAI_API_KEY'], '')
        self.assertEqual(environment['PATH'], 'runtime-path')
        self.assertEqual(environment['ENVIRONMENT'], 'test')
        self.assertEqual(environment['DEPLOY_TARGET'], 'local')
        for key in ('AWS_SECRET_ACCESS_KEY', 'MINIO_ENDPOINT', 'MINIO_BUCKET', 'DOCKER_HOST', 'BETTER_AUTH_SECRET'):
            self.assertNotIn(key, environment)
        self.assertNotEqual(environment['DOCKER_CONFIG'], source['DOCKER_CONFIG'])

    def storage(self):
        storage = harness.SharingStorage({})
        state = {'id': 'owned-container', 'name': '/' + storage.name, 'run': storage.run_id,
                 'running': True, 'status': 'running', 'ports': {'9000/tcp': None},
                 'networks': {storage.network: {'NetworkID': 'network-id', 'EndpointID': 'endpoint-id',
                                               'IPAddress': '172.18.0.2'}}}
        network = {'Id': 'network-id', 'Name': storage.network, 'Driver': 'bridge', 'Scope': 'local',
                   'Internal': True, 'Labels': {'latexy.ci.run': storage.run_id},
                   'IPAM': {'Config': [{'Subnet': '172.18.0.0/16', 'Gateway': '172.18.0.1'}]},
                   'Containers': {'owned-container': {'Name': storage.name, 'EndpointID': 'endpoint-id',
                                                     'IPv4Address': '172.18.0.2/16'}}}
        def docker(*args, **kwargs):
            if args[0] == 'inspect':
                return json.dumps(state)
            if args[:2] == ('network', 'inspect'):
                return json.dumps(network)
            return ''
        storage.docker = MagicMock(side_effect=docker)
        relay = patch.object(harness, 'StorageRelay')
        mocked = relay.start()
        self.addCleanup(relay.stop)
        mocked.return_value.server_address = ('127.0.0.1', 19200)
        return storage, state, network, mocked

    def test_only_owned_ephemeral_loopback_storage_is_selected(self):
        storage, _, _, relay = self.storage()
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(harness, 'urlopen', return_value=response):
            self.assertEqual(storage.start(), 'http://127.0.0.1:19200')
        environment = storage.environment
        self.assertRegex(environment['MINIO_BUCKET'], r'^latexy-sharing-[a-f0-9]{32}$')
        self.assertEqual(environment['MINIO_ENDPOINT'], environment['SHARING_ACCEPTANCE_STORAGE_ENDPOINT'])
        self.assertEqual(environment['MINIO_ENDPOINT'], environment['SHARING_ACCEPTANCE_PUBLIC_STORAGE_ENDPOINT'])
        self.assertEqual(environment['SHARING_ACCEPTANCE_STORAGE_MODE'], 'host')
        self.assertEqual(environment['SHARING_ACCEPTANCE_DISPOSABLE'], '1')
        calls = storage.docker.call_args_list
        self.assertIn('--internal', calls[1].args)
        self.assertNotIn('--publish', calls[2].args)
        self.assertIn('MINIO_API_CORS_ALLOW_ORIGIN=http://localhost:5180', calls[2].args)
        self.assertEqual(environment['SHARING_ACCEPTANCE_CORS_ORIGIN'], 'http://localhost:5180')
        self.assertEqual(relay.call_args.args[:2], ('172.18.0.2', 9000))
        self.assertIn('/data:rw,nosuid,size=512m,uid=65532,gid=65532,mode=0700', calls[2].args)

    def test_unowned_or_non_internal_storage_fails_before_relay_or_probe(self):
        for mutation in ('public', 'wrong-owner', 'wrong-network', 'extra-port',
                         'egress', 'wrong-ip', 'wrong-member', 'not-running'):
            with self.subTest(mutation=mutation):
                storage, state, network, relay = self.storage()
                if mutation == 'public':
                    state['ports']['9000/tcp'] = [{'HostIp': '0.0.0.0', 'HostPort': '19200'}]
                elif mutation == 'wrong-owner':
                    state['run'] = 'other'
                elif mutation == 'wrong-network':
                    state['networks']['unowned-network'] = {}
                elif mutation == 'extra-port':
                    state['ports']['9001/tcp'] = [{'HostIp': '127.0.0.1', 'HostPort': '19201'}]
                elif mutation == 'egress':
                    network['Internal'] = False
                elif mutation == 'wrong-ip':
                    state['networks'][storage.network]['IPAddress'] = '8.8.8.8'
                elif mutation == 'wrong-member':
                    network['Containers']['owned-container']['Name'] = 'unowned'
                else:
                    state['running'] = False
                with patch.object(harness, 'urlopen') as probe, self.assertRaises(RuntimeError):
                    storage.start()
                relay.assert_not_called()
                probe.assert_not_called()
                self.assertNotIn('MINIO_ENDPOINT', storage.environment)

    def test_cancellation_during_relay_creation_records_then_closes_listener(self):
        storage, _, _, factory = self.storage()
        relay = factory.return_value
        def construct(*args):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return relay
        factory.side_effect = construct
        with patch.object(harness, 'urlopen') as probe:
            with self.assertRaises(harness.SharingCancelled):
                with harness.cancellation_guard() as cleanup:
                    try:
                        storage.start(cleanup=cleanup)
                    finally:
                        with cleanup():
                            storage.cleanup()
        relay.close.assert_called_once()
        probe.assert_not_called()
        self.assertEqual(storage.docker.call_args_list[-3].args, ('rm', '--force', storage.name))

    def test_invalid_storage_metadata_is_not_disclosed(self):
        storage, state, network, relay = self.storage()
        state['run'] = 'synthetic-do-not-log'
        state['error'] = 'synthetic-do-not-log'
        network['Labels']['unrelated'] = 'synthetic-do-not-log'
        with patch.object(harness, 'urlopen') as probe, self.assertRaises(RuntimeError) as failure:
            storage.start()
        self.assertEqual(str(failure.exception),
                         'Relay target was not an exact-owned running private endpoint')
        relay.assert_not_called()
        probe.assert_not_called()
        self.assertNotIn('MINIO_ENDPOINT', storage.environment)

    def test_storage_relay_rejects_non_storage_ports_and_external_targets(self):
        for address, port in (('8.8.8.8', 9000), ('127.0.0.1', 9000), ('172.18.0.2', 8030),
                              ('172.18.0.2', 5432), ('172.18.0.2', 80)):
            with self.assertRaises(RuntimeError):
                harness.StorageRelay(address, port, time.monotonic() + 1)
        self.assertEqual(harness.StorageRelay.allowed_ports, (9000,))
        self.assertFalse(harness.StorageRelay.allow_reuse_address)

    def test_storage_relay_cleanup_precedes_docker_and_does_not_block_other_cleanup(self):
        storage = harness.SharingStorage({})
        storage.relay = MagicMock()
        storage.relay.close.side_effect = RuntimeError('synthetic failure')
        storage.container_attempted = storage.network_attempted = storage.image_attempted = True
        storage.docker = MagicMock()
        ordered = MagicMock()
        ordered.attach_mock(storage.relay.close, 'relay_close')
        ordered.attach_mock(storage.docker, 'docker')
        with self.assertRaisesRegex(RuntimeError, 'cleanup incomplete'):
            storage.cleanup()
        self.assertEqual(ordered.mock_calls, [
            call.relay_close(), call.docker('rm', '--force', storage.name),
            call.docker('network', 'rm', storage.network), call.docker('image', 'rm', storage.image)])

    def test_cleanup_attempts_every_exact_owned_name_even_after_one_failure(self):
        storage = harness.SharingStorage({})
        storage.image_attempted = storage.network_attempted = storage.container_attempted = True
        storage.docker = MagicMock(side_effect=[RuntimeError('synthetic cleanup failure'), '', ''])
        with self.assertRaisesRegex(RuntimeError, 'cleanup incomplete'):
            storage.cleanup()
        self.assertEqual([call.args for call in storage.docker.call_args_list], [
            ('rm', '--force', storage.name), ('network', 'rm', storage.network), ('image', 'rm', storage.image)])

    def test_opt_in_is_required_before_any_docker_call(self):
        with patch.object(harness.sys, 'argv', ['sharing-full-stack-smoke.py']), \
                patch.object(harness.subprocess, 'run') as run:
            with self.assertRaises(SystemExit):
                harness.main()
        run.assert_not_called()

    def test_timeout_gives_only_the_owned_group_graceful_bash_cleanup(self):
        process = MagicMock(pid=31415)
        process.wait.side_effect = [subprocess.TimeoutExpired('synthetic-owned-bash', 1), 0]
        with patch.object(harness.subprocess, 'Popen', return_value=process) as launch, \
                patch.object(harness.os, 'killpg', side_effect=[None, ProcessLookupError()], create=True) as killpg, \
                self.assertRaises(subprocess.TimeoutExpired):
            harness.run_smoke({'PATH': 'synthetic'}, timeout=1)
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertEqual(launch.call_args.kwargs['env'], {'PATH': 'synthetic'})
        self.assertEqual([call.args for call in killpg.call_args_list], [(31415, harness.signal.SIGTERM), (31415, 0)])
        self.assertEqual(process.wait.call_args_list[-1].kwargs, {'timeout': 5})

    def test_unresponsive_owned_descendants_are_killed_after_grace_period(self):
        process = MagicMock(pid=31415)
        with patch.object(harness.os, 'killpg', create=True) as killpg, \
                patch.object(harness.signal, 'SIGKILL', 9, create=True), \
                patch.object(harness.time, 'monotonic', side_effect=[0, 16]):
            harness.stop_owned_process_group(process)
        self.assertEqual([call.args for call in killpg.call_args_list], [(31415, harness.signal.SIGTERM), (31415, 0), (31415, 9)])
        process.wait.assert_called_once_with(timeout=5)

    def test_sigterm_raises_into_finally_and_ignores_repeated_cancellation_during_cleanup(self):
        previous = object()
        with patch.object(harness.signal, 'getsignal', return_value=previous), \
                patch.object(harness.signal, 'signal') as install:
            with self.assertRaises(harness.SharingCancelled):
                with harness.cancellation_guard():
                    handler = install.call_args.args[1]
                    handler(harness.signal.SIGTERM, None)
        self.assertEqual(install.call_args_list[1].args, (harness.signal.SIGTERM, harness.signal.SIG_IGN))
        self.assertEqual(install.call_args_list[-1].args, (harness.signal.SIGTERM, previous))

    def test_sigterm_during_normal_cleanup_is_deferred_until_that_cleanup_finishes(self):
        completed = []
        with patch.object(harness.signal, 'signal') as install, self.assertRaises(harness.SharingCancelled):
            with harness.cancellation_guard() as cleanup:
                handler = install.call_args.args[1]
                with cleanup():
                    handler(harness.signal.SIGTERM, None)
                    completed.append('cleanup finished')
        self.assertEqual(completed, ['cleanup finished'])

    @unittest.skipUnless(os.name == 'posix' and Path('/proc').is_dir(), 'Requires native Linux process groups')
    def test_real_sigterm_stops_owned_group_runs_both_cleanups_and_preserves_unrelated_process(self):
        root = self.directory / 'synthetic-checkout'
        (root / 'scripts/ci').mkdir(parents=True)
        (root / 'backend').mkdir()
        (root / 'frontend').mkdir()
        group_file, child_file = self.directory / 'group', self.directory / 'child'
        bash_exit, storage_exit = self.directory / 'bash-exit', self.directory / 'storage-exit'
        script = root / 'scripts/ci/full-stack-smoke.sh'
        script.write_text('trap ' + shlex.quote('printf done > ' + shlex.quote(str(bash_exit))) + ' EXIT\n'
            'sleep 120 &\n'
            'printf "%s" "$!" > ' + shlex.quote(str(child_file)) + '\n'
            'printf "%s" "$$" > ' + shlex.quote(str(group_file)) + '\nwait\n')
        program = '''import importlib.util, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('synthetic_sharing',sys.argv[1])
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
h.ROOT=Path(sys.argv[2]);marker=Path(sys.argv[3])
class FakeStorage:
    def __init__(self,environment): pass
    def start(self, **kwargs): pass
    def cleanup(self): marker.write_text('done')
h.SharingStorage=FakeStorage
sys.argv=['sharing-full-stack-smoke.py','--confirm-isolated-sharing-run']
raise SystemExit(h.cli())
'''
        environment = dict(self.services(), PATH=os.environ['PATH'])
        wrapper = subprocess.Popen([sys.executable, '-c', program, str(Path(harness.__file__).resolve()),
            str(root), str(storage_exit)], env=environment, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(120)'], start_new_session=True)
        group = None
        try:
            deadline = time.monotonic() + 10
            while not group_file.exists() or not child_file.exists():
                if wrapper.poll() is not None or time.monotonic() > deadline:
                    self.fail('Synthetic wrapper did not reach its owned-process readiness marker')
                time.sleep(0.02)
            group, child = int(group_file.read_text()), int(child_file.read_text())
            wrapper.send_signal(signal.SIGTERM)
            output, error = wrapper.communicate(timeout=25)
            self.assertEqual(wrapper.returncode, 128 + signal.SIGTERM, error)
            self.assertEqual(output, '')
            self.assertTrue(bash_exit.exists(), 'Bash EXIT trap must run')
            self.assertTrue(storage_exit.exists(), 'Storage finally cleanup must run')
            for pid in (group, child):
                status = Path('/proc') / str(pid) / 'stat'
                self.assertFalse(status.exists() and status.read_text().split()[2] != 'Z', 'Owned process remains live')
            self.assertIsNone(unrelated.poll(), 'Cancellation must not stop an unrelated process group')
        finally:
            for owned_group in (group, wrapper.pid):
                if owned_group is not None:
                    try:
                        os.killpg(owned_group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            wrapper.communicate(timeout=5)
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_ci_selects_stronger_case_and_retains_existing_suites(self):
        script = (harness.ROOT / 'scripts/ci/full-stack-smoke.sh').read_text()
        workflow = (harness.ROOT / '.github/workflows/ci.yml').read_text()
        for case in ('full-stack-smoke', 'landing-capability-fullstack', 'capability-fullstack',
                     'core-capabilities-fullstack', 'e03-interview-simulation-fullstack',
                     'b07-json-export-fullstack',
                     'sharing-controls-fullstack', 'sharing-capability-fullstack',
                     'collaborator-launch-fullstack', 'collaborator-initial-sync-fullstack'):
            self.assertIn('e2e/' + case + '.spec.ts', script)
        self.assertIn('"${sharing_specs[@]}"', script)
        self.assertIn('python scripts/ci/sharing-full-stack-smoke.py --confirm-isolated-sharing-run', workflow)
        self.assertIn('python scripts/ci/sharing-storage-fixture.test.py -v', workflow)
        self.assertIn('python scripts/ci/sharing-full-stack-smoke.test.py -v', workflow)
        full_stack = workflow.split('  full-stack-smoke:', 1)[1].split('  real-compile-preview:', 1)[0]
        job_configuration, steps = full_stack.split('    steps:', 1)
        self.assertNotIn('runner.temp', job_configuration)
        for step_name in ('Install Playwright browser', 'Run full-stack smoke'):
            step = steps.split('      - name: ' + step_name + '\n', 1)[1].split('      - ', 1)[0]
            self.assertIn('        env:\n          PLAYWRIGHT_BROWSERS_PATH: ${{ runner.temp }}/latexy-sharing-browsers', step)
        self.assertIn('pnpm exec playwright install --with-deps chromium', full_stack)


if __name__ == '__main__':
    unittest.main()
