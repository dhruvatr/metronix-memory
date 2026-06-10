from metatron_installer.docker import CommandResult, DockerShell
from metatron_installer.runner import launch_stack


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, env=None):
        self.calls.append((argv, env))
        return self.results.pop(0)


def test_launch_stack_pulls_then_ups_with_profiles():
    runner = FakeRunner([CommandResult(0, "", ""), CommandResult(0, "", "")])
    sh = DockerShell(runner=runner)
    ok = launch_stack(
        sh,
        compose_file="install/docker-compose.yml",
        compose_profiles="full",
        registry_login=None,
    )
    assert ok is True
    # env carried COMPOSE_PROFILES to both pull and up
    assert runner.calls[0][1]["COMPOSE_PROFILES"] == "full"
    assert runner.calls[1][1]["COMPOSE_PROFILES"] == "full"
