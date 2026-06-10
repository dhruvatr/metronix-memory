import subprocess
import sys


def test_module_reports_version():
    out = subprocess.run(
        [sys.executable, "-m", "metatron_installer", "--version"],
        capture_output=True,
        text=True,
        cwd="src",
    )
    assert out.returncode == 0
    assert "0.1.0" in out.stdout
