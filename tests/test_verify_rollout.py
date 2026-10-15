"""Operational guards use synthetic inspect records; no Docker or account I/O."""

import json
from copy import deepcopy

import pytest

from tools.verify_rollout import covering_mount, main, review_container


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


@pytest.mark.parametrize("path", ["config.py", "stock_analysis.py", "sell_signals.py"])
@pytest.mark.parametrize("kind,writable", [("bind", True), ("bind", False),
                                          ("volume", True), ("volume", False), ("tmpfs", True)])
def test_unlisted_runtime_file_mount_rejected(path, kind, writable):
    value = container()
    value["Mounts"].append({"Destination": "/py_app/" + path, "Type": kind, "RW": writable})
    assert any("Runtime mount hides image code" in error for error in review_container(value)[1])


@pytest.mark.parametrize("destination", [
    "/", "/py_app", "/py_app/", "/py_app///", "//py_app//", "/py_app/outputs/..",
    "/py_app/tools", "/py_app/tools/", "/py_app/logging_config", "/py_app/__pycache__",
    "/py_app/new_runtime_package", "/py_app/data/../config.py", "/py_app/token.dat",
    "/py_app/data-old", "/py_app/outputs-old/report", "/py_app/portfolio.csv", "/py_app/logs-old",
])
def test_unapproved_mounts_rejected_even_with_valid_state_mounts(destination):
    value = container()
    value["Mounts"].append({"Destination": destination, "Type": "bind", "RW": True})
    assert any("Runtime mount hides image code" in error for error in review_container(value)[1])


@pytest.mark.parametrize("kind", ["bind", "volume"])
@pytest.mark.parametrize("suffix", ["", "/", "///"])
def test_reviewed_state_mounts_accepted(kind, suffix):
    value = container()
    value["Mounts"].append({"Destination": "/py_app/logs", "Type": kind, "RW": True})
    for mount in value["Mounts"]:
        mount.update(Type=kind, Destination=mount["Destination"] + suffix)
    assert not review_container(value)[1]


@pytest.mark.parametrize("kind,writable", [("bind", True), ("volume", True),
                                          ("bind", False), ("volume", False), ("tmpfs", True)])
def test_nested_snapshot_mount_keeps_deepest_persistence_check(kind, writable):
    value = container()
    # A parent's trailing separators must not outrank a deeper destination.
    value["Mounts"][0]["Destination"] += "/" * 60
    value["Mounts"].append({"Destination": "/py_app/data/live/", "Type": kind, "RW": writable})
    facts, errors = review_container(value)
    persistent = kind in {"bind", "volume"} and writable
    assert facts["persistence"]["/py_app/data"]["persistent_writable"]
    for filename in ("broker_equity_snapshots.csv", "krw_external_flows.csv"):
        assert facts["persistence"]["/py_app/data/live/" + filename]["persistent_writable"] is persistent
    assert bool(errors) is not persistent


def test_nested_readonly_candidate_file_mount_accepted():
    value = container()
    value["Mounts"][-1] = {"Destination": "/py_app/portfolio/portfolio.csv", "Type": "bind", "RW": False}
    assert not review_container(value)[1]


@pytest.mark.parametrize("output,destination", [
    ("outputs/custom/performance", None),
    ("/py_app/outputs/custom/performance/", "/py_app/outputs/custom/"),
    ("/reports/performance", "/reports/"),
    ("../reports/performance", "/reports"),
    ("/py_app-backup/reports", "/py_app-backup"),
])
def test_safe_custom_output_supported(output, destination):
    value = container()
    value["Config"]["Env"].append("PERFORMANCE_REPORT_OUTPUT_DIR=" + output)
    if destination:
        value["Mounts"].append({"Destination": destination, "Type": "volume", "RW": True})
    assert not review_container(value)[1]


@pytest.mark.parametrize("output", [
    "/py_app/config.py", "/py_app/tools", "/py_app/reports", "/py_app/outputs-old",
    "/py_app/outputs/../stock_analysis.py", "/py_app", "/",
])
def test_custom_output_cannot_exempt_unapproved_mount(output):
    value = container()
    value["Config"]["Env"].append("PERFORMANCE_REPORT_OUTPUT_DIR=" + output)
    value["Mounts"].append({"Destination": output, "Type": "volume", "RW": True})
    assert any("Runtime mount hides image code" in error for error in review_container(value)[1])


@pytest.mark.parametrize("path,destination,covered", [
    ("/py_app/data/live/file.csv", "/py_app/data/", True),
    ("/py_app/data", "/py_app/data///", True),
    ("/py_app/data/live/file.csv", "//py_app//data/./live/", True),
    ("/py_app/config.py", "/", True),
    ("/py_app/data", "/py_app/dat", False),
    ("/py_app/data-old/file.csv", "/py_app/data", False),
    ("/py_app/outputs-old/report", "/py_app/outputs", False),
    ("/py_app/portfolio/portfolio.csv", "/py_app/portfolio/portfolio.csv-old", False),
    ("/py_app/data", "/py_app/data/live", False),
])
def test_covering_mount_path_boundaries(path, destination, covered):
    mount = {"Destination": destination}
    assert covering_mount(path, [mount]) == (mount if covered else None)


@pytest.mark.parametrize("path,index", [("data", 0), ("outputs", 1), ("portfolio", 2)])
def test_similarly_named_mount_cannot_supply_required_persistence(path, index):
    value = container()
    value["Mounts"][index]["Destination"] = "/py_app/" + path + "-old"
    errors = review_container(value)[1]
    assert any("Missing writable" in error or "Candidate input requires" in error for error in errors)


@pytest.mark.parametrize("destination", ["/py_app/config.py", "/py_app/", "/py_app/reports"])
def test_rejected_mount_cli_is_read_only_and_sanitized(destination, monkeypatch, capsys):
    import io

    value = container()
    value["Config"]["Env"] += ["ki_app_secret_key=private", "account_number=private",
                               "PERFORMANCE_REPORT_URL=https://private.invalid"]
    value["Mounts"].append({"Destination": destination, "Type": "bind", "RW": False})
    original = deepcopy(value)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([value])))
    assert main() == 1
    assert value == original
    captured = capsys.readouterr()
    assert "private" not in captured.out + captured.err
    assert json.loads(captured.out)["errors"]


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
