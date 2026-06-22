from metatron_installer.preflight import (
    PUBLISHED_PORTS,
    ComposeInfo,
    DockerInfo,
    PortConflict,
    check_compose,
    find_port_conflicts,
    parse_docker_version,
    summarize,
)


def test_summarize_docker_missing_is_not_ok():
    ok, messages = summarize(DockerInfo(present=False), [])
    assert ok is False
    assert any("Docker not available" in m for m in messages)


def test_summarize_docker_present_no_conflicts_is_ok():
    ok, messages = summarize(DockerInfo(present=True, major=27, minor=1), [])
    assert ok is True
    assert any("27.1" in m for m in messages)


def test_summarize_port_conflicts_are_warnings_not_blocking():
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [PortConflict(port=8000, service="metatron-api")],
    )
    assert ok is True  # conflicts warn but don't block
    assert any("8000" in m for m in messages)


def test_parse_docker_version_ok():
    info = parse_docker_version("Docker version 27.1.1, build 6312585")
    assert info == DockerInfo(present=True, major=27, minor=1)


def test_parse_docker_version_missing():
    info = parse_docker_version("")
    assert info.present is False


def test_find_port_conflicts_reports_busy_ports():
    busy = {8000, 5433}
    conflicts = find_port_conflicts(checker=lambda p: p in busy)
    ports = {c.port for c in conflicts}
    assert ports == {8000, 5433}


def test_find_port_conflicts_none_when_all_free():
    assert find_port_conflicts(checker=lambda p: False) == []


def test_published_ports_cover_known_services():
    assert 8000 in PUBLISHED_PORTS  # api
    assert 5433 in PUBLISHED_PORTS  # postgres (full-stack offset)
    assert 7688 in PUBLISHED_PORTS  # neo4j bolt


def test_detect_os_returns_known_value():
    from metatron_installer.preflight import detect_os

    assert detect_os() in {"linux", "darwin", "windows"}


# ── Compose detection tests ──

def test_composeinfo_available_plugin():
    info = ComposeInfo(available=True, variant="plugin")
    assert info.available is True
    assert info.variant == "plugin"


def test_composeinfo_available_standalone():
    info = ComposeInfo(available=True, variant="standalone")
    assert info.available is True
    assert info.variant == "standalone"


def test_composeinfo_unavailable():
    info = ComposeInfo(available=False)
    assert info.available is False
    assert info.variant == ""


def test_check_compose_prefers_v2_plugin(monkeypatch):
    """When `docker compose version` succeeds, returns plugin variant."""
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append(argv)
        from subprocess import CompletedProcess
        return CompletedProcess(argv, 0, stdout="Docker Compose version v2.29.0\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = check_compose()
    assert result.available is True
    assert result.variant == "plugin"
    assert calls[0][:3] == ["docker", "compose", "version"]


def test_check_compose_falls_back_to_v1_standalone(monkeypatch):
    """When `docker compose` fails but `docker-compose` succeeds, returns standalone."""
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append(argv)
        from subprocess import CompletedProcess
        if argv[0] == "docker" and "compose" in argv:
            return CompletedProcess(argv, 1, stdout="", stderr="docker: 'compose' is not a docker command")
        if argv[0] == "docker-compose":
            return CompletedProcess(argv, 0, stdout="docker-compose version 1.29.2\n", stderr="")
        return CompletedProcess(argv, 1, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = check_compose()
    assert result.available is True
    assert result.variant == "standalone"
    assert calls[1][:2] == ["docker-compose", "--version"]


def test_check_compose_none_available(monkeypatch):
    """When neither variant works, returns unavailable."""
    def _fake_run(argv, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(argv, 1, stdout="", stderr="not found")

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = check_compose()
    assert result.available is False
    assert result.variant == ""


# ── summarize() with compose= ──

def test_summarize_compose_plugin_ok():
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [],
        compose=ComposeInfo(available=True, variant="plugin"),
    )
    assert ok is True
    assert any("Docker Compose plugin (v2) detected" in m for m in messages)


def test_summarize_compose_standalone_ok():
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [],
        compose=ComposeInfo(available=True, variant="standalone"),
    )
    assert ok is True
    assert any("Docker Compose standalone (v1) detected" in m for m in messages)


def test_summarize_compose_missing_hard_stop():
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [],
        compose=ComposeInfo(available=False),
    )
    assert ok is False
    assert any("Docker Compose not found" in m for m in messages)


def test_summarize_compose_missing_macos_hint(monkeypatch):
    """On macOS, the error message includes a Homebrew hint."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [],
        compose=ComposeInfo(available=False),
    )
    assert ok is False
    assert any("brew install docker-compose" in m for m in messages)


def test_summarize_compose_missing_linux_hint(monkeypatch):
    """On Linux, the error message includes an apt hint."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [],
        compose=ComposeInfo(available=False),
    )
    assert ok is False
    assert any("apt-get install docker-compose-plugin" in m for m in messages)


def test_summarize_backward_compat_no_compose_arg():
    """Without compose= kwarg, no compose messages (backward compat)."""
    ok, messages = summarize(DockerInfo(present=True, major=27, minor=1), [])
    assert ok is True
    assert not any("Compose" in m for m in messages)
