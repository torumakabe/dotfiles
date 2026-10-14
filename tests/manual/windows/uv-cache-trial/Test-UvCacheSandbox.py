"""Measure uv cache behavior when invoked directly by the Copilot powershell tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import idna


class ProbeFailure(Exception):
    def __init__(self, stage: str, category: str) -> None:
        super().__init__(category)
        self.stage = stage
        self.category = category


def path_key(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.expandvars(str(value))))


def is_under(child: str | Path, parent: str | Path) -> bool:
    child_key = path_key(child)
    parent_key = path_key(parent)
    try:
        return os.path.commonpath((child_key, parent_key)) == parent_key
    except ValueError:
        return False


def load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8-sig") as stream:
            return json.load(stream)
    except FileNotFoundError as error:
        raise ProbeFailure("trial-evidence", "required-file-missing") from error
    except PermissionError as error:
        raise ProbeFailure("trial-evidence", "required-file-inaccessible") from error
    except OSError as error:
        raise ProbeFailure("trial-evidence", "required-file-read-failed") from error
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ProbeFailure("trial-evidence", "invalid-json") from error


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError as error:
        raise ProbeFailure("hook-integrity", "support-file-missing") from error
    except PermissionError as error:
        raise ProbeFailure("hook-integrity", "support-file-inaccessible") from error
    except OSError as error:
        raise ProbeFailure("hook-integrity", "support-file-read-failed") from error
    return digest.hexdigest().upper()


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


def verify_trial_files(root: Path, mode: str) -> tuple[dict, dict, dict, Path]:
    manifest = load_json(root / "manifest.json")
    if path_key(manifest.get("root", "")) != path_key(root):
        raise ProbeFailure("trial-evidence", "root-mismatch")
    workspace = Path(manifest["workspace"])
    if path_key(Path.cwd()) != path_key(workspace):
        raise ProbeFailure("trial-evidence", "workspace-mismatch")
    evidence = workspace / "evidence" / mode
    launch = load_json(evidence / "launch.json")
    if (
        launch.get("mode") != mode
        or launch.get("parentCacheOverridePresent") is not False
        or (mode == "candidate" and launch.get("parentHelperPresent") is not False)
    ):
        raise ProbeFailure("trial-evidence", "launch-condition-mismatch")

    configured = load_json(evidence / "cli-configured-sandbox.json")
    expected = manifest["modes"][mode]["configuredSandbox"]
    for name in (
        "enabled",
        "allowBypass",
        "allowDevToolAccess",
        "addCurrentWorkingDirectory",
        "sandboxMcpServers",
        "sandboxLspServers",
    ):
        if configured.get(name) != expected.get(name):
            raise ProbeFailure("trial-evidence", "sandbox-snapshot-mismatch")
    for name in ("readwritePaths", "readonlyPaths", "deniedPaths"):
        actual_paths = sorted(configured["userPolicy"]["filesystem"].get(name, []))
        expected_paths = sorted(expected["userPolicy"]["filesystem"].get(name, []))
        if actual_paths != expected_paths:
            raise ProbeFailure("trial-evidence", "sandbox-path-snapshot-mismatch")

    mode_info = manifest["modes"][mode]
    hooks = Path(mode_info["home"]) / "hooks"
    for name, expected_hash in mode_info["supportHashes"].items():
        if hash_file(hooks / name) != expected_hash.upper():
            raise ProbeFailure("hook-integrity", "support-file-changed")
    for name, expected_hash in mode_info["hookHashes"].items():
        if hash_file(hooks / "scripts" / name) != expected_hash.upper():
            raise ProbeFailure("hook-integrity", "hook-script-changed")
    if mode_info.get("directPythonAndPipDenied") is not True:
        raise ProbeFailure("hook-integrity", "python-policy-not-verified")
    return manifest, mode_info, launch, evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--mode", required=True, choices=("control", "candidate"))
    parser.add_argument("--step", required=True, type=int, choices=(1, 2))
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    root = Path(args.root).resolve()
    evidence = root / "workspace" / "evidence" / args.mode
    result_path = evidence / f"step-{args.step}.json"
    result = {
        "schema": 1,
        "trialId": None,
        "mode": args.mode,
        "step": args.step,
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

    manifest, mode_info, launch, evidence = verify_trial_files(root, args.mode)
    result["trialId"] = manifest["trialId"]
    result["cliVersion"] = launch["cliVersion"]
    result["uvVersion"] = manifest["uvVersion"]
    result["osBuild"] = manifest["osBuild"]
    result["cliSandboxSettingsLoaded"] = True
    result["stage"] = "cache-discovery"
    cache = read_uv_cache_dir()
    result["cachePath"] = str(cache)
    environment_cache = os.environ.get("UV_CACHE_DIR")
    result["uvCacheEnvironmentPresent"] = bool(environment_cache)
    result["uvCacheEnvironmentMatchesReportedDir"] = (
        path_key(environment_cache) == path_key(cache) if environment_cache else None
    )
    result["copilotHelperVariablePresent"] = bool(
        os.environ.get("COPILOT_DOTFILES_UV_CACHE_DIR")
    )
    result["controlCacheMatchesLegacyGrant"] = (
        path_key(cache) == path_key(manifest["oldCachePath"])
        if args.mode == "control"
        else None
    )
    if args.mode == "candidate":
        result["cacheUnderWorkspace"] = is_under(cache, manifest["workspace"])
        result["cacheUnderLegacyGrant"] = is_under(cache, manifest["oldCachePath"])
        result["cacheCoveredByConfiguredWriteGrant"] = any(
            is_under(cache, grant)
            for grant in mode_info["configuredSandbox"]["userPolicy"]["filesystem"].get(
                "readwritePaths", []
            )
        )
        result["cacheUnderTemp"] = is_under(cache, tempfile.gettempdir())

    owned = cache / f".dotfiles-uv-trial-{manifest['trialId']}-{args.mode}"
    result["probeOwnedDirectory"] = str(owned)
    marker = owned / "cross-command.txt"
    result["stage"] = "cross-command-marker"
    if args.step == 1:
        try:
            owned.mkdir()
            marker.write_text(f"{manifest['trialId']}:{args.mode}", encoding="utf-8")
        except FileExistsError as error:
            raise ProbeFailure("cross-command-marker", "trial-cache-directory-already-exists") from error
        except PermissionError as error:
            raise ProbeFailure("cross-command-marker", "permission") from error
        except OSError as error:
            raise ProbeFailure("cross-command-marker", "filesystem-write-failed") from error
    else:
        first = load_json(evidence / "step-1.json")
        if (
            first.get("status") != "technical-success"
            or first.get("trialId") != manifest["trialId"]
            or first.get("mode") != args.mode
            or path_key(first.get("cachePath", "")) != path_key(cache)
        ):
            raise ProbeFailure("cross-command-marker", "first-call-cache-state-not-reused")
        try:
            marker_value = marker.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ProbeFailure("cross-command-marker", "marker-missing") from error
        except PermissionError as error:
            raise ProbeFailure("cross-command-marker", "permission") from error
        except UnicodeError as error:
            raise ProbeFailure("cross-command-marker", "invalid-marker") from error
        except OSError as error:
            raise ProbeFailure("cross-command-marker", "marker-read-failed") from error
        if marker_value != f"{manifest['trialId']}:{args.mode}":
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
    package = {
        "package": "idna",
        "version": idna.__version__,
        "pythonVersion": sys.version.split()[0],
        "pythonExecutable": sys.executable,
        "pythonPrefix": sys.prefix,
        "uvCacheDir": str(cache),
    }
    if package["version"] != "3.10" or not is_under(package["pythonPrefix"], cache):
        raise ProbeFailure("uv-package-run", "package-environment-outside-cache")
    result["package"] = package
    result["status"] = "technical-success"
    result["stage"] = "complete"
    result["probes"].append(
        {"name": "uv-run-idna", "status": "passed", "exitCode": 0}
    )
    return result


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
    except ProbeFailure as error:
        result = {
            "schema": 1,
            "status": "failed",
            "mode": args.mode,
            "step": args.step,
            "stage": error.stage,
            "error": error.category,
        }
        evidence = Path(args.root).resolve() / "workspace" / "evidence" / args.mode
        result_path = evidence / f"step-{args.step}.json"
        if evidence.is_dir() and not result_path.exists() and not write_result(result_path, result):
            result["resultWriteError"] = "evidence-write-failed"
        print(json.dumps(result, ensure_ascii=False))
        return 1
    result_path = (
        Path(args.root).resolve()
        / "workspace"
        / "evidence"
        / args.mode
        / f"step-{args.step}.json"
    )
    if not write_result(result_path, result):
        print(
            json.dumps(
                {
                    "schema": 1,
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


def write_result(path: Path, result: dict) -> bool:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
