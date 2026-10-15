"""Execute the workflow's staging shell with a fake Docker CLI, never production."""

import os
import re
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest


def remote_script():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/docker-build-push.yml").read_text()
    script = dedent(workflow.split("<<'REMOTE_SCRIPT'\n", 1)[1].split("          REMOTE_SCRIPT", 1)[0])
    replacements = {"github.actor": "test-actor", "env.REGISTRY": "ghcr.io",
                    "secrets.GITHUB_TOKEN": "synthetic-token"}
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda match: replacements[match[1]], script)


def test_staging_pulls_digest_without_strategy_execution_or_removal(tmp_path):
    (tmp_path / "compose.yml").write_text("services: {}\n")
    executable = tmp_path / "docker"
    executable.write_text('#!/bin/bash\nset -eu\nprintf "%s\\n" "$*" >> "$DOCKER_CALLS"\n'
                          'if [ "$1" = login ]; then cat >/dev/null; fi\n')
    executable.chmod(0o755)
    image = "ghcr.io/k11tos/usa_stock_finder@sha256:synthetic-digest"
    calls = tmp_path / "calls"
    result = subprocess.run(["bash", "-se"], input=remote_script(), text=True, check=False,
                            capture_output=True, env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin",
                                                      "TARGET_DIR": str(tmp_path), "IMAGE_REF": image,
                                                      "DOCKER_CALLS": str(calls)})
    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == [
        "--version", "compose version", "login -u test-actor --password-stdin ghcr.io",
        f"pull {image}", f"image inspect --format {{{{.Os}}}}/{{{{.Architecture}}}} {{{{.Id}}}} {image}",
        "ps -a --filter name=^/stock$ --format {{.Names}} {{.Status}} {{.Image}}", "logout ghcr.io",
    ]
    assert "synthetic-token" not in result.stdout + result.stderr


@pytest.mark.parametrize("target_exists", [True, False])
def test_staging_fails_before_docker_when_target_or_compose_missing(tmp_path, target_exists):
    target = tmp_path if target_exists else tmp_path / "missing"
    result = subprocess.run(["bash", "-se"], input=remote_script(), text=True, check=False,
                            capture_output=True, env={**os.environ, "TARGET_DIR": str(target)})
    assert result.returncode == 1
    assert "ERROR:" in result.stdout
