"""Operational guards use synthetic inspect records; no Docker or account I/O."""

import json
from copy import deepcopy

import pytest

from tools.verify_rollout import main, review_container


def container():
    return {
        "Config": {"WorkingDir": "/py_app", "Env": ["ki_app_key=private", "TELEGRAM_BOT_TOKEN=private"]},
        "State": {"Status": "exited", "ExitCode": 0, "Running": False}, "Image": "sha256:test",
        "HostConfig": {"RestartPolicy": {"Name": "no"}},
        "Mounts": [{"Destination": path, "Type": "bind", "RW": True}
                   for path in ["/py_app/data", "/py_app/outputs", "/py_app/portfolio"]],
    }


def test_stopped_container_defaults_and_no_credentials():
    facts, errors = review_container(container())
    assert not errors
    assert facts["flags"]["PERFORMANCE_KRW_SNAPSHOT_ENABLED"] == "false"
    assert facts["flags"]["PERFORMANCE_REPORT_ENABLED"] == "false"
    assert facts["flags"]["PERFORMANCE_REPORT_DATA_SOURCE"] == "legacy_usd"
    assert "private" not in json.dumps(facts)


@pytest.mark.parametrize("mount", [None, {"Type": "tmpfs", "RW": True}, {"Type": "bind", "RW": False}])
def test_unpersisted_or_shadowed_snapshot_fails(mount):
    value = container()
    if mount is None:
        value["Mounts"] = []
    else:
        value["Mounts"].append({"Destination": "/py_app/data/live", **mount})
    assert review_container(value)[1]


@pytest.mark.parametrize("status,exit_code,running", [("running", 0, True), ("exited", 1, False),
                                                       ("restarting", 0, True)])
def test_active_or_failed_container_fails(status, exit_code, running):
    value = container()
    value["State"] = {"Status": status, "ExitCode": exit_code, "Running": running}
    assert review_container(value)[1]


def test_named_volume_and_created_container_supported():
    value = container()
    value["State"]["Status"] = "created"
    for mount in value["Mounts"]:
        mount["Type"] = "volume"
    assert not review_container(value)[1]


@pytest.mark.parametrize("env", ["PERFORMANCE_REPORT_OUTPUT_DIR=/other",
                                "PERFORMANCE_REPORT_OUTPUT_DIR=data/live",
                                "PERFORMANCE_REPORT_DATA_SOURCE=unknown",
                                "PERFORMANCE_REPORT_ENABLED=typo"])
def test_invalid_report_config_fails(env):
    value = container()
    value["Config"]["Env"].append(env)
    assert review_container(value)[1]


def test_image_code_shadow_and_restart_policy_fail():
    value = container()
    value["Mounts"].append({"Destination": "/py_app/tools", "Type": "bind", "RW": True})
    value["HostConfig"]["RestartPolicy"]["Name"] = "always"
    assert len(review_container(value)[1]) >= 2


def test_missing_candidate_mount_fails():
    value = container()
    value["Mounts"] = value["Mounts"][:2]
    assert review_container(value)[1]


def test_cli_read_only_and_sanitized(monkeypatch, capsys):
    import io

    value = container()
    original = deepcopy(value)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([value])))
    assert main() == 0
    assert value == original
    assert "private" not in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO('{"private": "bad input"}'))
    assert main() == 1
    assert "private" not in capsys.readouterr().err
