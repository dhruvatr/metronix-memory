from types import SimpleNamespace
from unittest.mock import patch

from metatron_installer.docker import CommandResult, DockerShell, parse_ps_services


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, env=None):
        self.calls.append(argv)
        return self.results.pop(0)


def _mock_subprocess_run(returncode=0, stdout="", stderr=""):
    """Create a mock for subprocess.run that captures calls."""

    calls = []

    def _run_mock(argv, *, env=None, stdout=None, stderr=None, text=None, **kwargs):
        calls.append({"argv": argv, "env": env})
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return calls, _run_mock


# ── tests that use FakeRunner (methods calling self._run) ──

def test_version_invokes_docker_version():
    runner = FakeRunner([CommandResult(0, "Docker version 27.1.1, build x", "")])
    sh = DockerShell(runner=runner)
    out = sh.version()
    assert runner.calls[0] == ["docker", "version", "--format", "{{.Server.Version}}"]
    assert out.returncode == 0


def test_parse_ps_services_ndjson():
    out = (
        '{"Service": "postgres", "Status": "running"}\n'
        '{"Service": "neo4j", "Status": "starting"}\n'
    )
    assert parse_ps_services(out) == [("postgres", "running"), ("neo4j", "starting")]


def test_parse_ps_services_json_array():
    out = '[{"Name": "metatron-full-api", "State": "running"}]'
    assert parse_ps_services(out) == [("metatron-full-api", "running")]


def test_parse_ps_services_empty_and_malformed():
    assert parse_ps_services("") == []
    assert parse_ps_services("not json\n{bad}") == []


def test_running_container_names_parses_lines():
    runner = FakeRunner([CommandResult(0, "metatron-full-api\nmetatron-full-postgres\n", "")])
    sh = DockerShell(runner=runner)
    names = sh.running_container_names()
    assert names == ["metatron-full-api", "metatron-full-postgres"]
    assert runner.calls[0] == ["docker", "ps", "--format", "{{.Names}}"]


def test_running_container_names_empty_on_failure():
    runner = FakeRunner([CommandResult(1, "", "cannot connect to docker daemon")])
    sh = DockerShell(runner=runner)
    assert sh.running_container_names() == []


# ── compose detection tests ──

def test_detect_compose_prefers_v2_plugin(monkeypatch):
    """When `docker compose version` succeeds, _detect_compose returns v2 prefix."""
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append(argv)
        from subprocess import CompletedProcess
        return CompletedProcess(argv, 0, stdout="Docker Compose version v2.29.0\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    sh = DockerShell()
    prefix = sh._detect_compose()
    assert prefix == ["docker", "compose"]
    assert calls[0][:3] == ["docker", "compose", "version"]


def test_detect_compose_falls_back_to_v1_standalone(monkeypatch):
    """When v2 fails but v1 works, _detect_compose returns v1 prefix."""
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append(argv)
        from subprocess import CompletedProcess
        if argv[0] == "docker" and "compose" in argv:
            return CompletedProcess(argv, 1, stdout="", stderr="not a docker command")
        if argv[0] == "docker-compose":
            return CompletedProcess(argv, 0, stdout="docker-compose version 1.29.2\n", stderr="")
        return CompletedProcess(argv, 1, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    sh = DockerShell()
    prefix = sh._detect_compose()
    assert prefix == ["docker-compose"]
    assert calls[1][:2] == ["docker-compose", "--version"]


def test_detect_compose_defaults_to_v2_when_neither_found(monkeypatch):
    """When neither variant works, defaults to `docker compose` (clear error msg)."""
    def _fake_run(argv, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(argv, 1, stdout="", stderr="not found")

    monkeypatch.setattr("subprocess.run", _fake_run)
    sh = DockerShell()
    prefix = sh._detect_compose()
    assert prefix == ["docker", "compose"]


def test_detect_compose_caches_result(monkeypatch):
    """Detection runs only once; subsequent calls return cached result."""
    call_count = [0]

    def _fake_run(argv, **kwargs):
        call_count[0] += 1
        from subprocess import CompletedProcess
        return CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    sh = DockerShell()
    sh._detect_compose()
    sh._detect_compose()
    sh._detect_compose()
    assert call_count[0] == 1  # Only the first call triggers detection


def test_compose_argv_with_v2_plugin(monkeypatch):
    """_compose_argv uses the detected v2 prefix."""
    def _fake_run(argv, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(argv, 0, stdout="Docker Compose version v2.29.0\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    sh = DockerShell()
    argv = sh._compose_argv("/path/to/compose.yml", "up", "-d")
    assert argv == ["docker", "compose", "-f", "/path/to/compose.yml", "up", "-d"]


def test_compose_argv_with_v1_standalone(monkeypatch):
    """_compose_argv uses the detected v1 prefix."""
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append(argv)
        from subprocess import CompletedProcess
        # v2 fails, v1 succeeds
        if argv[0] == "docker" and "compose" in argv:
            return CompletedProcess(argv, 1, stdout="", stderr="")
        return CompletedProcess(argv, 0, stdout="docker-compose version 1.29.2\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    sh = DockerShell()
    argv = sh._compose_argv("/path/to/compose.yml", "ps", "--format", "json")
    assert argv == ["docker-compose", "-f", "/path/to/compose.yml", "ps", "--format", "json"]


# ── tests that mock subprocess.run (compose_pull / compose_up / restart / down) ──

def test_compose_up_passes_detach_and_profiles_env(monkeypatch):
    """compose_up uses detected compose variant and passes -d flag."""
    # Pre-seed with v2 plugin detection
    def _fake_run(argv, **kwargs):
        from subprocess import CompletedProcess
        if "version" in argv:
            return CompletedProcess(argv, 0, stdout="v2.29.0", stderr="")
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    sh = DockerShell()
    # Clear cache so detection runs fresh
    sh._compose_prefix = None
    res = sh.compose_up("install/docker-compose.yml", env={"COMPOSE_PROFILES": "full"})
    assert res.returncode == 0


def test_pull_falls_back_to_login_on_auth_failure(monkeypatch):
    """First pull fails with 401 → login succeeds → retry pull succeeds."""
    call_count = [0]

    def _mock_pull(argv, env):
        call_count[0] += 1
        if call_count[0] == 1:
            return 1, "denied: 401 Unauthorized"
        return 0, ""

    runner = FakeRunner([CommandResult(0, "Login Succeeded", "")])
    sh = DockerShell(runner=runner)

    # Pre-seed compose detection so it uses v2
    sh._compose_prefix = ["docker", "compose"]

    with patch("metatron_installer.docker._pull_with_progress", _mock_pull):
        ok = sh.compose_pull(
            "install/docker-compose.yml",
            env={},
            registry_login=lambda: sh.login("ghcr.io", "user", "token"),
        )
    assert ok is True
    assert any(c[:2] == ["docker", "login"] for c in runner.calls)


def test_pull_succeeds_anonymously_without_login(monkeypatch):
    sh = DockerShell()
    sh._compose_prefix = ["docker", "compose"]
    with patch(
        "metatron_installer.docker._pull_with_progress",
        return_value=(0, ""),
    ):
        ok = sh.compose_pull(
            "install/docker-compose.yml", env={}, registry_login=None,
        )
    assert ok is True


def test_compose_restart_argv(tmp_path, monkeypatch):
    """compose_restart uses subprocess.run directly; test argv + tmp .env handling."""
    compose_file = str(tmp_path / "install" / "docker-compose.yml")
    (tmp_path / "install").mkdir()

    sh = DockerShell()
    all_calls = []

    def _run_capture(argv, *, env=None, stdout=None, stderr=None, text=None, **kwargs):
        all_calls.append(argv)
        if "version" in argv or "--version" in argv:
            return type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("subprocess.run", _run_capture)
    sh.compose_restart(compose_file, env={})

    # Find the restart call (skip compose detection calls)
    restart_args = [a for a in all_calls if "restart" in a]
    assert len(restart_args) == 1
    assert restart_args[0] == [
        "docker", "compose", "-f", compose_file, "restart",
    ]


def test_compose_down_with_and_without_volumes(tmp_path, monkeypatch):
    """compose_down uses subprocess.run directly; test argv variations."""
    compose_file = str(tmp_path / "install" / "docker-compose.yml")
    (tmp_path / "install").mkdir()

    sh = DockerShell()
    all_calls = []

    def _run_capture(argv, *, env=None, stdout=None, stderr=None, text=None, **kwargs):
        all_calls.append(argv)
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("subprocess.run", _run_capture)
    sh.compose_down(compose_file, env={})
    sh.compose_down(compose_file, env={}, remove_volumes=True)

    # Find the down calls (skip compose detection calls)
    down_args = [a for a in all_calls if "down" in a and "version" not in a and "--version" not in a]
    assert len(down_args) == 2
    assert down_args[0] == ["docker", "compose", "-f", compose_file, "down"]
    assert down_args[1][-1] == "--volumes"
