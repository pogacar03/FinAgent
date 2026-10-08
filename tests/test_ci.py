"""Offline CI guard tests. Mocked Docker commands do not verify containers."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def smoke_module():
    spec = importlib.util.spec_from_file_location('compose_smoke', ROOT/'scripts/ci/compose_smoke.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_poll_fails_immediately_on_failed_worker():
    module = smoke_module()
    with pytest.raises(RuntimeError, match='FAILED'):
        module.wait_job(lambda: {'status': 'FAILED', 'error': 'VALIDATION_FAILED'}, timeout=.1)


def test_poll_timeout_is_non_success():
    module = smoke_module()
    with pytest.raises(TimeoutError):
        module.wait_job(lambda: {'status': 'QUEUED'}, timeout=.01, interval=.001)


@pytest.mark.parametrize('payload', [
    '[{"Service":"worker","State":"running"}]',
    '{"Service":"worker","State":"running"}\n',
])
def test_worker_state_accepts_supported_compose_json_formats(payload):
    smoke_module().check_worker_state(payload)


@pytest.mark.parametrize('payload', ['[]', '{"Service":"worker","State":"exited"}',
                                     '{"Service":"api","State":"running"}'])
def test_worker_missing_or_dead_fails(payload):
    with pytest.raises(RuntimeError):
        smoke_module().check_worker_state(payload)


def test_database_checks_reject_injection_before_running_docker():
    with pytest.raises(ValueError):
        smoke_module().database_evidence("' OR 1=1 --", 'not-a-uuid')


@pytest.mark.parametrize('failed_stage,code', [('build', 17), ('up', 18), ('smoke', 19), ('down', 20)])
def test_shell_failure_logs_cleanup_and_nonzero(tmp_path, failed_stage, code):
    docker = tmp_path/'docker'
    call_log = tmp_path/'calls.log'
    # Exercise the actual trap and shell exit code, without a Docker installation.
    docker.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALL_LOG"
if [[ "$*" == *" logs "* ]]; then echo 'FAKE_CONTAINER_FAILURE_LOG'; fi
if [[ "$FAIL_STAGE" == build && "$*" == *" build "* ]]; then exit "$FAIL_CODE"; fi
if [[ "$FAIL_STAGE" == up && "$*" == *" up "* ]]; then exit "$FAIL_CODE"; fi
if [[ "$FAIL_STAGE" == down && "$*" == *" down "* ]]; then exit "$FAIL_CODE"; fi
exit 0
''')
    docker.chmod(0o755)
    python = tmp_path/'python3'
    python.write_text('#!/bin/bash\nexit "$FAIL_CODE"\n' if failed_stage == 'smoke' else '#!/bin/bash\nexit 0\n')
    python.chmod(0o755)
    import os
    env = dict(os.environ, PATH=str(tmp_path)+os.pathsep+os.environ['PATH'],
               CALL_LOG=str(call_log), FAIL_STAGE=failed_stage, FAIL_CODE=str(code),
               CI_ARTIFACT_DIR=str(tmp_path/'artifacts'))
    result = subprocess.run(['bash', str(ROOT/'scripts/ci/docker_check.sh')], cwd=ROOT,
                            env=env, capture_output=True, text=True)
    assert result.returncode == code, result.stderr
    assert 'FAKE_CONTAINER_FAILURE_LOG' in result.stdout
    calls = call_log.read_text()
    assert 'logs --no-color --timestamps' in calls
    assert 'down --volumes --remove-orphans' in calls
    assert 'compose.log' in {p.name for p in (tmp_path/'artifacts').iterdir()}
    assert not (tmp_path/'artifacts'/'verified.json').exists()


@pytest.mark.parametrize('docker_result,expected', [('success', 0), ('failure', 1), ('skipped', 1)])
def test_actual_workflow_verdict_never_verifies_failure_or_skip(tmp_path, docker_result, expected):
    import os
    import yaml
    workflow = yaml.load((ROOT/'.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    step = workflow['jobs']['ci-verdict']['steps'][0]
    results = {'python-tests': {'result': 'success'}, 'frontend-build': {'result': 'success'},
               'docker-integration': {'result': docker_result}}
    summary = tmp_path/'summary.md'
    result = subprocess.run(['bash', '-c', step['run']], capture_output=True, text=True,
        env=dict(os.environ, JOB_RESULTS=json.dumps(results), GITHUB_STEP_SUMMARY=str(summary),
                 GITHUB_SHA='offline-test-only'))
    assert result.returncode == expected, result.stderr
    assert ('**VERIFIED (Linux CI)**' if expected == 0 else '**UNVERIFIED**') in summary.read_text()
