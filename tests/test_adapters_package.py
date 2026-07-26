"""The adapter package must not pull unused runtimes into deployments."""

import subprocess
import sys


def test_workers_import_does_not_load_asgi_adapter():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import hayate.adapters.workers; "
                "assert 'hayate.adapters.asgi' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_public_asgi_adapter_export_remains_available():
    from hayate.adapters import ASGIAdapter
    from hayate.adapters.asgi import ASGIAdapter as DirectASGIAdapter

    assert ASGIAdapter is DirectASGIAdapter
