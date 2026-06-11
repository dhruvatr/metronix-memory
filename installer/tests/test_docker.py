from metatron_installer.docker import CommandResult, DockerShell, parse_ps_services


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, env=None):
        self.calls.append(argv)
        return self.results.pop(0)


def test_version_invokes_docker_version():
    runner = FakeRunner([CommandResult(0, "Docker version 27.1.1, build x", "")])
    sh = DockerShell(runner=runner)
    out = sh.version()
    assert runner.calls[0] == ["docker", "version", "--format", "{{.Server.Version}}"]
    assert out.returncode == 0


def test_compose_up_passes_detach_and_profiles_env():
    runner = FakeRunner([CommandResult(0, "", "")])
    sh = DockerShell(runner=runner)
    sh.compose_up(compose_file="install/docker-compose.yml", env={"COMPOSE_PROFILES": "full"})
    argv = runner.calls[0]
    assert argv[:3] == ["docker", "compose", "-f"]
    assert "up" in argv and "-d" in argv


def test_pull_falls_back_to_login_on_auth_failure():
    # First pull fails with 401, login succeeds, retry pull succeeds.
    runner = FakeRunner(
        [
            CommandResult(1, "", "denied: requested access ... 401 Unauthorized"),
            CommandResult(0, "Login Succeeded", ""),
            CommandResult(0, "", ""),
        ]
    )
    sh = DockerShell(runner=runner)
    ok = sh.compose_pull(
        compose_file="install/docker-compose.yml",
        env={},
        registry_login=lambda: sh.login("ghcr.io", "user", "token"),
    )
    assert ok is True
    # docker login was attempted between the two pulls
    assert any(c[:2] == ["docker", "login"] for c in runner.calls)


def test_pull_succeeds_anonymously_without_login():
    runner = FakeRunner([CommandResult(0, "", "")])
    sh = DockerShell(runner=runner)
    ok = sh.compose_pull(compose_file="install/docker-compose.yml", env={}, registry_login=None)
    assert ok is True
    assert all(c[:2] != ["docker", "login"] for c in runner.calls)


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


def test_compose_restart_argv():
    runner = FakeRunner([CommandResult(0, "", "")])
    sh = DockerShell(runner=runner)
    sh.compose_restart("install/docker-compose.yml", env={})
    assert runner.calls[0] == ["docker", "compose", "-f", "install/docker-compose.yml", "restart"]


def test_compose_down_with_and_without_volumes():
    runner = FakeRunner([CommandResult(0, "", ""), CommandResult(0, "", "")])
    sh = DockerShell(runner=runner)
    sh.compose_down("install/docker-compose.yml", env={})
    sh.compose_down("install/docker-compose.yml", env={}, remove_volumes=True)
    assert runner.calls[0] == ["docker", "compose", "-f", "install/docker-compose.yml", "down"]
    assert runner.calls[1][-1] == "--volumes"


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
