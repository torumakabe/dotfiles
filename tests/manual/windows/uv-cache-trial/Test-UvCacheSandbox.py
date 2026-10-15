"""Measure uv cache behavior inside one Copilot PowerShell tool call."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


class ProbeFailure(Exception):
    def __init__(self, stage: str, category: str) -> None:
        super().__init__(category)
        self.stage = stage
        self.category = category


def path_key(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(value)))


def is_under(child: str | Path, parent: str | Path) -> bool:
    try:
        return os.path.commonpath((path_key(child), path_key(parent))) == path_key(parent)
    except ValueError:
        return False


def load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8-sig") as stream:
            return json.load(stream)
    except FileNotFoundError as error:
        raise ProbeFailure("evidence", "required-file-missing") from error
    except PermissionError as error:
        raise ProbeFailure("evidence", "required-file-inaccessible") from error
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        raise ProbeFailure("evidence", "required-file-invalid") from error


def classify_uv_error(stderr: str) -> str:
    lowered = stderr.lower()
    if any(value in lowered for value in ("denied", "permission", "0x80070005")):
        return "permission"
    if any(
        value in lowered
        for value in ("download", "network", "connect", "tls", "certificate", "resolve")
    ):
        return "network-or-resolution"
    if "python" in lowered or "interpreter" in lowered:
        return "python"
    return "uv-command-failed"


def read_uv_cache_dir() -> Path:
    try:
        completed = subprocess.run(
            ["uv", "cache", "dir"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as error:
        raise ProbeFailure("cache-discovery", "uv-not-found") from error
    except PermissionError as error:
        raise ProbeFailure("cache-discovery", "permission") from error
    except OSError as error:
        raise ProbeFailure("cache-discovery", "uv-launch-failed") from error
    if completed.returncode:
        raise ProbeFailure("cache-discovery", classify_uv_error(completed.stderr))
    value = completed.stdout.strip()
    if not value:
        raise ProbeFailure("cache-discovery", "empty-cache-path")
    try:
        return Path(value).resolve()
    except (OSError, ValueError) as error:
        raise ProbeFailure("cache-discovery", "invalid-cache-path") from error


def cache_environment_evidence(
    cache: Path, preflight_cache_environment: str | None
) -> dict:
    payload_cache_environment = os.environ.get("UV_CACHE_DIR")
    return {
        "payloadUvCacheEnvironment": payload_cache_environment,
        "preflightUvCacheEnvironment": preflight_cache_environment,
        "uvCacheEnvironmentMatchesReportedDir": (
            path_key(payload_cache_environment) == path_key(cache)
            if payload_cache_environment
            else False
        ),
    }


def verify_trial(root: Path, mode: str) -> tuple[dict, dict, dict, Path]:
    trial = load_json(root / "trial.json")
    if path_key(trial.get("workspace", "")) != path_key(root):
        raise ProbeFailure("evidence", "workspace-mismatch")

    resolution = load_json(root / "evidence" / mode / "uv-resolution.json")
    host = trial["hostUv"]
    if (
        resolution.get("matched") is not True
        or resolution.get("toolCommandType") != "Application"
        or path_key(resolution.get("toolPath", "")) != path_key(host["path"])
        or resolution.get("toolVersion") != host["version"]
    ):
        raise ProbeFailure("uv-resolution", "host-tool-resolution-mismatch")

    launch = load_json(root / "evidence" / mode / "launch.json")
    if (
        launch.get("mode") != mode
        or launch.get("sandboxSettingsLoaded") is not True
        or launch.get("helperEnabled") != (mode == "control")
    ):
        raise ProbeFailure("evidence", "trial-launch-not-verified")
    return trial, resolution, launch, root / "evidence" / mode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("control", "candidate"))
    parser.add_argument("--step", required=True, type=int, choices=(1, 2))
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    workspace = Path.cwd().resolve()
    evidence = workspace / "evidence" / args.mode
    result_path = evidence / f"step-{args.step}.json"
    result = {
        "schema": 2,
        "mode": args.mode,
        "step": args.step,
        "networkMode": "online" if args.step == 1 else "offline",
        "invocationId": str(uuid.uuid4()),
        "status": "failed",
        "stage": "preconditions",
        "probes": [],
        "runtimeSandboxAttribution": "unverified",
        "removalDecision": "pending-runtime-sandbox-attribution",
    }
    if os.name != "nt":
        raise ProbeFailure("preconditions", "requires-native-windows")
    if result_path.exists():
        raise ProbeFailure("preconditions", "step-evidence-already-exists")

    trial, resolution, launch, evidence = verify_trial(workspace, args.mode)
    result["trialId"] = trial["trialId"]
    result["cliVersion"] = trial["cliVersion"]
    result["uvVersion"] = resolution["toolVersion"]
    result["uvExecutable"] = resolution["toolPath"]
    result["osBuild"] = trial["osBuild"]
    result["runtimeCachePathBasisMatchesCliVersion"] = (
        trial["runtimeCachePathBasisCliVersion"] == "1.0.98-0"
        and re.search(
            r"(?m)^GitHub Copilot CLI 1\.0\.98-0(?:\.|\s|$)",
            trial["cliVersion"],
        )
        is not None
    )
    result["parentUvCacheOverridePresent"] = bool(
        launch.get("parentUvCacheOverridePresent")
    )

    result["stage"] = "cache-discovery"
    cache = read_uv_cache_dir()
    result["cachePath"] = str(cache)
    result["runtimeUvCachePath"] = trial["runtimeUvCachePath"]
    result["runtimeCacheMatchesReportedDir"] = (
        path_key(cache) == path_key(trial["runtimeUvCachePath"])
    )
    result.update(
        cache_environment_evidence(
            cache, resolution.get("preflightUvCacheEnvironment")
        )
    )
    result["controlCacheMatchesLegacyGrant"] = (
        path_key(cache) == path_key(trial["oldCachePath"])
        if args.mode == "control"
        else None
    )
    result["cacheUnderWorkspace"] = is_under(cache, workspace)
    result["cacheUnderLegacyGrant"] = is_under(cache, trial["oldCachePath"])
    result["cacheCoveredByConfiguredWriteGrant"] = any(
        is_under(cache, grant)
        for grant in trial["modes"][args.mode]["readwritePaths"]
    )
    result["cacheUnderTemp"] = is_under(cache, tempfile.gettempdir())

    owned = cache / f".dotfiles-uv-trial-{trial['trialId']}-{args.mode}"
    result["probeOwnedDirectory"] = str(owned)
    marker = owned / "cross-command.txt"
    result["stage"] = "cross-command-marker"
    if args.step == 1:
        try:
            owned.mkdir()
            marker.write_text(f"{trial['trialId']}:{args.mode}", encoding="utf-8")
        except FileExistsError as error:
            raise ProbeFailure(
                "cross-command-marker", "trial-cache-directory-already-exists"
            ) from error
        except PermissionError as error:
            raise ProbeFailure("cross-command-marker", "permission") from error
        except OSError as error:
            raise ProbeFailure(
                "cross-command-marker", "filesystem-write-failed"
            ) from error
        result["crossCommandMarker"] = "created"
    else:
        first = load_json(evidence / "step-1.json")
        if (
            first.get("status") != "technical-success"
            or first.get("trialId") != trial["trialId"]
            or first.get("mode") != args.mode
            or path_key(first.get("cachePath", "")) != path_key(cache)
        ):
            raise ProbeFailure(
                "cross-command-marker", "first-call-cache-state-not-reused"
            )
        try:
            marker_value = marker.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ProbeFailure("cross-command-marker", "marker-missing") from error
        except PermissionError as error:
            raise ProbeFailure("cross-command-marker", "permission") from error
        except (OSError, UnicodeError) as error:
            raise ProbeFailure("cross-command-marker", "marker-read-failed") from error
        if marker_value != f"{trial['trialId']}:{args.mode}":
            raise ProbeFailure("cross-command-marker", "marker-content-mismatch")
        result["previousInvocationId"] = first["invocationId"]
        result["crossCommandMarker"] = "passed"

    source = owned / f"step-{args.step}.before"
    target = owned / f"step-{args.step}.after"
    result["stage"] = "atomic-rename"
    if source.exists() or target.exists():
        raise ProbeFailure("atomic-rename", "rename-probe-file-already-exists")
    try:
        source.write_text("synthetic-rename-payload", encoding="utf-8")
        os.replace(source, target)
        renamed_content = target.read_text(encoding="utf-8")
    except PermissionError as error:
        raise ProbeFailure("atomic-rename", "permission") from error
    except OSError as error:
        raise ProbeFailure("atomic-rename", "filesystem-operation-failed") from error
    if source.exists() or renamed_content != "synthetic-rename-payload":
        raise ProbeFailure("atomic-rename", "rename-content-mismatch")
    result["probes"].append(
        {"name": "same-directory-atomic-rename", "status": "passed", "exitCode": 0}
    )

    result["stage"] = "uv-package-run"
    try:
        import idna
    except ModuleNotFoundError as error:
        raise ProbeFailure("uv-package-run", "idna-not-installed") from error
    package = {
        "package": "idna",
        "version": idna.__version__,
        "pythonVersion": sys.version.split()[0],
        "pythonExecutable": sys.executable,
        "pythonPrefix": sys.prefix,
    }
    if package["version"] != "3.10" or not is_under(package["pythonPrefix"], cache):
        raise ProbeFailure("uv-package-run", "package-environment-outside-cache")
    result["package"] = package
    result["runtimeSandboxAttribution"] = (
        "candidate-private-cache"
        if args.mode == "candidate"
        and result["runtimeCachePathBasisMatchesCliVersion"]
        and result["runtimeCacheMatchesReportedDir"]
        and result["uvCacheEnvironmentMatchesReportedDir"]
        and not result["parentUvCacheOverridePresent"]
        and not result["cacheCoveredByConfiguredWriteGrant"]
        and not result["cacheUnderWorkspace"]
        and not result["cacheUnderLegacyGrant"]
        and not result["cacheUnderTemp"]
        else "unverified"
    )
    result["status"] = "technical-success"
    result["stage"] = "complete"
    result["probes"].append(
        {"name": "uv-run-idna", "status": "passed", "exitCode": 0}
    )
    return result


def write_result(path: Path, result: dict) -> bool:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        return False
    return True


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
    except ProbeFailure as error:
        result = {
            "schema": 2,
            "status": "failed",
            "mode": args.mode,
            "step": args.step,
            "stage": error.stage,
            "error": error.category,
        }
        evidence = Path.cwd() / "evidence" / args.mode
        result_path = evidence / f"step-{args.step}.json"
        if evidence.is_dir() and not result_path.exists() and not write_result(result_path, result):
            result["resultWriteError"] = "evidence-write-failed"
        print(json.dumps(result, ensure_ascii=False))
        return 1

    result_path = (
        Path.cwd()
        / "evidence"
        / args.mode
        / f"step-{args.step}.json"
    )
    if not write_result(result_path, result):
        print(
            json.dumps(
                {
                    "schema": 2,
                    "status": "failed",
                    "mode": args.mode,
                    "step": args.step,
                    "stage": "result-record",
                    "error": "evidence-write-failed",
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
