from metatron_installer.docker import CommandResult, DockerShell


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
