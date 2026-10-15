"""Read Docker inspect JSON from stdin; never start containers or read secrets."""

import json
import posixpath
import sys

DEFAULTS = {
    "PERFORMANCE_KRW_SNAPSHOT_ENABLED": "false",
    "PERFORMANCE_REPORT_ENABLED": "false",
    "PERFORMANCE_REPORT_DATA_SOURCE": "legacy_usd",
    "PERFORMANCE_REPORT_OUTPUT_DIR": "outputs/performance",
    "PERFORMANCE_REPORT_BENCHMARKS": "SPY,IWM",
    "PERFORMANCE_REPORT_PUBLISH_LATEST": "true",
    "PERFORMANCE_REPORT_HISTORY": "false",
    "PERFORMANCE_REPORT_TELEGRAM_ENABLED": "false",
}
# State/input/output trees only; never extend this from report configuration.
# logs/log.json is the output of logging_config/logging_config.json.
STATE_DIRECTORIES = ("/py_app/data", "/py_app/outputs", "/py_app/portfolio", "/py_app/logs")


def normalize_path(path: str) -> str:
    """Normalize Linux container paths without consulting the host filesystem."""
    if not path.startswith("/"):
        raise ValueError("Expected absolute container path")
    return posixpath.normpath("/" + path.lstrip("/"))


def within_directory(path: str, directory: str) -> bool:
    """Compare exact paths or descendants, respecting directory boundaries."""
    path, directory = normalize_path(path), normalize_path(directory)
    return path == directory or path.startswith(directory.rstrip("/") + "/")


def covering_mount(path: str, mounts: list[dict]) -> dict | None:
    """Use the deepest mount, including mounts shadowing a persistent parent."""
    matches = [mount for mount in mounts if within_directory(path, mount["Destination"])]
    return max(matches, key=lambda item: len(normalize_path(item["Destination"])), default=None)


def review_container(container: dict) -> tuple[dict, list[str]]:
    """Return only non-secret rollout facts and fail-closed persistence checks."""
    errors = []
    config = container["Config"]
    env = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
    flags = {name: env.get(name, default) for name, default in DEFAULTS.items()}
    mounts = container.get("Mounts", [])
    working_dir = config.get("WorkingDir", "")
    if working_dir != "/py_app":
        errors.append("Expected WorkingDir=/py_app; relative data/report paths need review.")
    state = container["State"]
    if state["Status"] not in {"created", "exited"} or state.get("Running", False):
        errors.append("Wait for the scheduled one-shot run to finish before recreation.")
    if state["Status"] == "exited" and state["ExitCode"] != 0:
        errors.append("Previous one-shot exit was nonzero; inspect private logs before rollout.")
    if container.get("HostConfig", {}).get("RestartPolicy", {}).get("Name", "no") not in {"", "no"}:
        errors.append("Expected restart policy no for the scheduled one-shot container.")
    if flags["PERFORMANCE_REPORT_DATA_SOURCE"] not in {"legacy_usd", "broker_krw"}:
        errors.append("Unsupported performance data source.")
    for name, value in flags.items():
        if name.endswith(("_ENABLED", "_HISTORY", "_PUBLISH_LATEST")):
            accepted = {"true", "false"} if name == "PERFORMANCE_REPORT_TELEGRAM_ENABLED" else {
                "1", "true", "yes", "on", "0", "false", "no", "off",
            }
            if value.strip().lower() not in accepted:
                errors.append(f"Unrecognized boolean configuration: {name}")
    output = normalize_path(posixpath.join("/py_app", flags["PERFORMANCE_REPORT_OUTPUT_DIR"]))
    if within_directory(output, "/py_app/data"):
        errors.append("Report output must be separate from live input data.")
    paths = ["/py_app/data", "/py_app/data/live/broker_equity_snapshots.csv",
             "/py_app/data/live/krw_external_flows.csv", output]
    persistence = {}
    for path in paths:
        mount = covering_mount(path, mounts)
        persistent = bool(mount and mount.get("Type") in {"bind", "volume"} and mount.get("RW"))
        persistence[path] = {"persistent_writable": persistent,
                             "destination": mount["Destination"] if mount else None,
                             "source": (mount.get("Name") or mount.get("Source")) if mount else None}
        if not persistent:
            errors.append(f"Missing writable bind/named-volume persistence: {path}")
    for mount in mounts:
        destination = mount["Destination"]
        if (within_directory(destination, "/py_app") or within_directory("/py_app", destination)) and not any(
                within_directory(destination, directory) for directory in STATE_DIRECTORIES):
            errors.append("Runtime mount hides image code: destination is outside reviewed state directories.")
    portfolio = covering_mount("/py_app/portfolio/portfolio.csv", mounts)
    if not portfolio or portfolio.get("Type") not in {"bind", "volume"}:
        errors.append("Candidate input requires the existing portfolio mount; it is excluded from the image.")
    return {
        "state": state["Status"], "exit_code": state["ExitCode"],
        "image_id": container["Image"], "flags": flags, "persistence": persistence,
    }, errors


def main() -> int:
    """Consume `docker inspect stock` without exposing its credential fields."""
    try:
        containers = json.load(sys.stdin)
        if not isinstance(containers, list) or len(containers) != 1:
            raise ValueError("Expected one container")
        facts, errors = review_container(containers[0])
    except (KeyError, TypeError, ValueError):
        print("Invalid Docker inspect input", file=sys.stderr)
        return 1
    print(json.dumps({**facts, "errors": errors}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
