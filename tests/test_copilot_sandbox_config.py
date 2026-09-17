"""Verify sandbox defaults, preservation, and the dedicated uv cache."""

import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests._helpers import load_script, scoped_environ


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
USER_POLICY_PATH = SOURCE_ROOT / ".chezmoitemplates/copilot-user-settings.json"
POSIX_SCRIPT_PATH = SOURCE_ROOT / "run_after_35-configure-copilot-sandbox.sh.tmpl"
POWERSHELL_SCRIPT_PATH = (
    SOURCE_ROOT / "run_onchange_after_35-configure-copilot-sandbox.ps1.tmpl"
)
ZSHRC_PATH = SOURCE_ROOT / "dot_zshrc.tmpl"
POWERSHELL_PROFILE_PATH = SOURCE_ROOT / "PowerShell_profile.ps1.tmpl"
UVE = load_script(
    "sandbox_uv_enforcer",
    SOURCE_ROOT / "private_dot_copilot/hooks/scripts/executable_uv-enforcer.py",
)

POSIX_FILESYSTEM_PATHS = {
    "readwritePaths": ["/tmp/readwrite"],
    "readonlyPaths": ["/tmp/readonly"],
    "deniedPaths": ["/tmp/denied"],
}
UNKNOWN_SETTINGS = {
    "extraKnownMarketplaces": {
        "existing-marketplace": {
            "source": {"source": "github", "repo": "example/existing-marketplace"}
        }
    },
    "enabledPlugins": {"existing-plugin@existing-marketplace": False},
    "sandbox": {"keep": "sandbox"},
    "userPolicy": {"keep": "policy"},
    "filesystem": {"keep": {"nested": "filesystem"}},
    "network": {"keep": ["network"]},
}
EXPECTED_MARKETPLACE = {
    "source": {"source": "github", "repo": "torumakabe/copilot-agent-plugins"},
    "autoUpdate": True,
}
EXPECTED_PLUGINS = {
    "personal-skills@torumakabe-agent-plugins": True,
    "skill-creator@torumakabe-agent-plugins": True,
}


def _nested_unknown(depth: int) -> object:
    value: object = "deep-value"
    for level in reversed(range(depth)):
        value = {f"level{level}": value}
    return value


DEEP_UNKNOWN = _nested_unknown(25)
_ENABLED_KEY_ABSENT = object()


def _windows_test_home(root: pathlib.Path) -> pathlib.Path:
    return root / "Users" / "TestUser"


def _windows_test_local_app_data(home: pathlib.Path) -> pathlib.Path:
    return home / "AppData" / "Local"


def _windows_path(path: pathlib.Path, root: pathlib.Path) -> str:
    relative = path.resolve().relative_to(root.resolve())
    return str(pathlib.PureWindowsPath("C:/") / relative.as_posix())


def _windows_filesystem_paths(home: pathlib.Path, root: pathlib.Path) -> dict[str, list[str]]:
    policy_root = home / "policy-fixtures"
    for name in ("readwrite", "readonly", "denied"):
        (policy_root / name).mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        return {
            "readwritePaths": [str((policy_root / "readwrite").resolve())],
            "readonlyPaths": [str((policy_root / "readonly").resolve())],
            "deniedPaths": [str((policy_root / "denied").resolve())],
        }
    return {
        "readwritePaths": [_windows_path(policy_root / "readwrite", root)],
        "readonlyPaths": [_windows_path(policy_root / "readonly", root)],
        "deniedPaths": [_windows_path(policy_root / "denied", root)],
    }


def _expected_windows_cache(home: pathlib.Path, root: pathlib.Path) -> str:
    cache = _windows_test_local_app_data(home) / "github-copilot" / "uv"
    if os.name == "nt":
        return str(cache.resolve())
    return _windows_path(cache, root)


def _render(
    path: pathlib.Path,
    platform: str,
    *,
    codespaces: bool = False,
    devcontainer: bool = False,
) -> str:
    result = subprocess.run(
        [
            "chezmoi", "--source", str(SOURCE_ROOT), "execute-template",
            "--override-data",
            json.dumps({
                "chezmoi": {"os": platform, "arch": "amd64"},
                "codespaces": codespaces,
                "devcontainer": devcontainer,
            }),
            "--file", str(path),
        ],
        check=False, capture_output=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout


def _seed_settings(
    home: pathlib.Path,
    *,
    filesystem_paths: dict[str, list[str]] | None = None,
    enabled: object = _ENABLED_KEY_ABSENT,
) -> pathlib.Path:
    settings_path = home / ".copilot/settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    filesystem_paths = filesystem_paths or POSIX_FILESYSTEM_PATHS
    sandbox: dict = {
        "keep": UNKNOWN_SETTINGS["sandbox"]["keep"],
        "userPolicy": {
            "version": 1,
            "keep": UNKNOWN_SETTINGS["userPolicy"]["keep"],
            "filesystem": {**filesystem_paths, **UNKNOWN_SETTINGS["filesystem"]},
            "network": {
                "allowedHosts": ["api.github.com"],
                "blockedHosts": ["example.invalid"],
                **UNKNOWN_SETTINGS["network"],
            },
        },
    }
    if enabled is not _ENABLED_KEY_ABSENT:
        sandbox["enabled"] = enabled
    settings_path.write_text(json.dumps({
        "unrelated": {"keep": True},
        "deepUnknown": DEEP_UNKNOWN,
        "extraKnownMarketplaces": UNKNOWN_SETTINGS["extraKnownMarketplaces"],
        "enabledPlugins": UNKNOWN_SETTINGS["enabledPlugins"],
        "sandbox": sandbox,
    }), encoding="utf-8")
    return settings_path


def _posix_env(home: pathlib.Path, settings_path: pathlib.Path, extra_env=None) -> dict:
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("UV_", "XDG_"))
    }
    env.update(HOME=str(home), COPILOT_HOME=str(settings_path.parent))
    env.update(extra_env or {})
    return env


def _run_posix_script(
    home: pathlib.Path,
    settings_path: pathlib.Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    platform = "darwin" if sys.platform == "darwin" else "linux"
    codespaces = bool(os.environ.get("CODESPACES"))
    devcontainer = bool(os.environ.get("REMOTE_CONTAINERS"))
    env = _posix_env(home, settings_path, extra_env)
    script_path = home / "configure-sandbox.sh"
    script_path.write_text(_render(
        POSIX_SCRIPT_PATH, platform, codespaces=codespaces,
        devcontainer=devcontainer,
    ), encoding="utf-8")
    return subprocess.run(
        ["bash", str(script_path)], env=env, check=False,
        capture_output=True, encoding="utf-8",
    )


def _run_powershell_script(
    home: pathlib.Path,
    settings_path: pathlib.Path,
    *,
    local_app_data: pathlib.Path | None = None,
    extra_env: dict[str, str] | None = None,
    create_local_app_data: bool = True,
) -> subprocess.CompletedProcess[str]:
    if os.name != "nt":
        raise unittest.SkipTest("Windows PowerShell sandbox tests run only on Windows")

    script_path = home / "configure-sandbox.ps1"
    script_path.write_text(_render(POWERSHELL_SCRIPT_PATH, "windows"), encoding="utf-8")
    local_app_data = local_app_data or _windows_test_local_app_data(home)
    if create_local_app_data:
        local_app_data.mkdir(parents=True, exist_ok=True)
    extra_env = extra_env or {}
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(local_app_data),
        "COPILOT_HOME": str(settings_path.parent),
        **extra_env,
    }
    return subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-File", str(script_path)],
        env=env,
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


def _filesystem(settings_path: pathlib.Path) -> dict:
    return json.loads(settings_path.read_text(encoding="utf-8-sig"))["sandbox"]["userPolicy"]["filesystem"]


class CopilotSandboxPolicyTests(unittest.TestCase):
    def test_platform_scripts_share_policy_version(self) -> None:
        marker = "# Copilot sandbox policy version: "
        versions = []
        for script_path in (POSIX_SCRIPT_PATH, POWERSHELL_SCRIPT_PATH):
            matches = [
                line.removeprefix(marker)
                for line in script_path.read_text(encoding="utf-8").splitlines()
                if line.startswith(marker)
            ]
            self.assertEqual(len(matches), 1, script_path)
            versions.append(matches[0])
        self.assertEqual(versions[0], versions[1])

    def test_user_policy_has_the_cross_platform_defaults(self) -> None:
        policy = json.loads(USER_POLICY_PATH.read_text(encoding="utf-8"))
        self.assertTrue(policy["experimental"])
        self.assertEqual(
            policy["extraKnownMarketplaces"]["torumakabe-agent-plugins"],
            EXPECTED_MARKETPLACE,
        )
        self.assertEqual(policy["enabledPlugins"], EXPECTED_PLUGINS)
        sandbox = policy["sandbox"]
        for name in ("enabled", "allowBypass", "addCurrentWorkingDirectory", "allowDevToolAccess"):
            self.assertTrue(sandbox[name])
        self.assertFalse(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})
        self.assertEqual(sandbox["userPolicy"]["network"], {
            "allowOutbound": True, "allowLocalNetwork": True,
        })

    def test_guardrails_aliases_keep_allow_all(self) -> None:
        self.assertIn("--allow-all", ZSHRC_PATH.read_text(encoding="utf-8"))
        self.assertIn("--allow-all", POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8"))

    def test_posix_merge_uses_private_atomic_staging(self) -> None:
        script = POSIX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('settings_tmp="${settings_dir}/.settings.json.$$"', script)
        self.assertIn("set -o noclobber", script)
        self.assertIn('chmod 0600 "${settings_tmp}"', script)
        self.assertIn('mv -f "${settings_tmp}" "${settings_path}"', script)

    def test_powershell_merge_replaces_settings_atomically(self) -> None:
        script = POWERSHELL_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("[System.IO.File]::Replace", script)
        self.assertIn("[System.IO.File]::Move($temporaryPath, $settingsPath, $true)", script)

@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotSandboxMergeTests(unittest.TestCase):
    def _assert_settings(
        self,
        settings: dict,
        *,
        filesystem_paths: dict[str, list[str]],
        expected_enabled=True,
        cache=None,
    ) -> None:
        self.assertEqual(settings["unrelated"], {"keep": True})
        self.assertEqual(settings["deepUnknown"], DEEP_UNKNOWN)
        self.assertTrue(settings["experimental"])
        self.assertEqual(settings["extraKnownMarketplaces"], {
            **UNKNOWN_SETTINGS["extraKnownMarketplaces"],
            "torumakabe-agent-plugins": EXPECTED_MARKETPLACE,
        })
        self.assertEqual(settings["enabledPlugins"], {
            **UNKNOWN_SETTINGS["enabledPlugins"], **EXPECTED_PLUGINS,
        })
        sandbox = settings["sandbox"]
        self.assertEqual(sandbox["keep"], UNKNOWN_SETTINGS["sandbox"]["keep"])
        self.assertIs(sandbox["enabled"], expected_enabled)
        for name in ("allowBypass", "addCurrentWorkingDirectory", "allowDevToolAccess"):
            self.assertTrue(sandbox[name])
        self.assertFalse(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})
        policy = sandbox["userPolicy"]
        self.assertEqual(policy["keep"], UNKNOWN_SETTINGS["userPolicy"]["keep"])
        self.assertNotIn("version", policy)
        expected = {**filesystem_paths}
        if cache:
            expected["readwritePaths"] = [*expected["readwritePaths"], str(cache)]
        self.assertEqual(
            {name: policy["filesystem"][name] for name in filesystem_paths}, expected,
        )
        self.assertEqual(policy["filesystem"]["keep"], UNKNOWN_SETTINGS["filesystem"]["keep"])
        self.assertFalse(policy["filesystem"]["clearPolicyOnExit"])
        self.assertTrue(policy["network"]["allowOutbound"])
        self.assertTrue(policy["network"]["allowLocalNetwork"])
        self.assertEqual(policy["network"]["keep"], UNKNOWN_SETTINGS["network"]["keep"])
        self.assertNotIn("allowedHosts", policy["network"])
        self.assertNotIn("blockedHosts", policy["network"])

    def _assert_normalizes_empty_filesystem_paths(
        self,
        run_script,
        *,
        home: pathlib.Path,
        filesystem_paths: dict[str, list[str]],
        cache: str,
    ) -> None:
        for path_name in filesystem_paths:
            for remove_key in (True, False):
                with self.subTest(path=path_name, remove=remove_key):
                    settings_path = _seed_settings(home, filesystem_paths=filesystem_paths)
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    fs = settings["sandbox"]["userPolicy"]["filesystem"]
                    if remove_key:
                        fs.pop(path_name)
                    else:
                        fs[path_name] = None
                    settings_path.write_text(json.dumps(settings), encoding="utf-8")
                    result = run_script(home, settings_path)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    merged = json.loads(settings_path.read_text(encoding="utf-8-sig"))
                    expected = []
                    if path_name == "readwritePaths":
                        expected = [cache]
                    self.assertEqual(merged["sandbox"]["userPolicy"]["filesystem"][path_name], expected)

    def _assert_rejects_invalid_filesystem_paths(
        self,
        run_script,
        *,
        home: pathlib.Path,
        filesystem_paths: dict[str, list[str]],
    ) -> None:
        for path_name in filesystem_paths:
            for value in ("/tmp/not-an-array", 1, True, {"path": "/tmp"}):
                with self.subTest(path=path_name, value=value):
                    settings_path = _seed_settings(home, filesystem_paths=filesystem_paths)
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    settings["sandbox"]["userPolicy"]["filesystem"][path_name] = value
                    settings_path.write_text(json.dumps(settings), encoding="utf-8")
                    original = settings_path.read_bytes()
                    result = run_script(home, settings_path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("non-array", result.stderr)
                    self.assertIn(f"sandbox.userPolicy.filesystem.{path_name}", result.stderr)
                    self.assertEqual(settings_path.read_bytes(), original)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq required")
    def test_posix_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root)
            settings_path = _seed_settings(home, filesystem_paths=POSIX_FILESYSTEM_PATHS)
            result = _run_posix_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8")),
                filesystem_paths=POSIX_FILESYSTEM_PATHS,
                cache=home.resolve() / ".cache/github-copilot/uv",
            )

    @unittest.skipUnless(os.name == "nt", "Windows only")
    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = pathlib.Path(root)
            home = _windows_test_home(root_path)
            filesystem_paths = _windows_filesystem_paths(home, root_path)
            settings_path = _seed_settings(home, filesystem_paths=filesystem_paths)
            result = _run_powershell_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8-sig")),
                filesystem_paths=filesystem_paths,
                cache=_expected_windows_cache(home, root_path),
            )

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq required")
    def test_posix_normalizes_missing_or_null_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root)
            self._assert_normalizes_empty_filesystem_paths(
                _run_posix_script,
                home=home,
                filesystem_paths=POSIX_FILESYSTEM_PATHS,
                cache=str(home.resolve() / ".cache/github-copilot/uv"),
            )

    @unittest.skipUnless(os.name == "nt", "Windows only")
    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_normalizes_missing_or_null_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = pathlib.Path(root)
            home = _windows_test_home(root_path)
            filesystem_paths = _windows_filesystem_paths(home, root_path)
            self._assert_normalizes_empty_filesystem_paths(
                _run_powershell_script,
                home=home,
                filesystem_paths=filesystem_paths,
                cache=_expected_windows_cache(home, root_path),
            )

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq required")
    def test_posix_rejects_non_array_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root)
            self._assert_rejects_invalid_filesystem_paths(
                _run_posix_script,
                home=home,
                filesystem_paths=POSIX_FILESYSTEM_PATHS,
            )

    @unittest.skipUnless(os.name == "nt", "Windows only")
    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_non_array_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = pathlib.Path(root)
            home = _windows_test_home(root_path)
            filesystem_paths = _windows_filesystem_paths(home, root_path)
            self._assert_rejects_invalid_filesystem_paths(
                _run_powershell_script,
                home=home,
                filesystem_paths=filesystem_paths,
            )


VALID_ENABLED_CASES = (
    ("missing", _ENABLED_KEY_ABSENT, True), ("true", True, True), ("false", False, False),
)
INVALID_ENABLED_CASES = (
    ("null", None), ("string", "disabled"), ("number", 1), ("array", [True]),
)


def _current_posix_environment_case() -> tuple[str, bool, bool, bool]:
    if os.environ.get("CODESPACES"):
        return ("codespaces", True, False, False)
    if os.environ.get("REMOTE_CONTAINERS"):
        return ("devcontainer", False, True, False)
    return ("ordinary", False, False, True)


POSIX_ENVIRONMENT_CASES = (_current_posix_environment_case(),)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotSandboxEnabledPreservationTests(unittest.TestCase):
    """Pin the environment defaults and user override contract in ADR-026."""

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq required")
    def test_posix_defaults_enabled_when_settings_file_is_absent(self) -> None:
        for environment, codespaces, devcontainer, expected in POSIX_ENVIRONMENT_CASES:
            with self.subTest(environment=environment), tempfile.TemporaryDirectory() as root:
                home = pathlib.Path(root)
                settings_path = home / ".copilot/settings.json"
                result = _run_posix_script(home, settings_path)
                self.assertEqual(result.returncode, 0, result.stderr)
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertIs(settings["sandbox"]["enabled"], expected)
                self.assertEqual(stat.S_IMODE(settings_path.stat().st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq required")
    def test_posix_preserves_or_defaults_enabled(self) -> None:
        for environment, codespaces, devcontainer, default in POSIX_ENVIRONMENT_CASES:
            for case_name, seeded, ordinary_expected in VALID_ENABLED_CASES:
                expected = default if seeded is _ENABLED_KEY_ABSENT else ordinary_expected
                with self.subTest(environment=environment, case=case_name), tempfile.TemporaryDirectory() as root:
                    home = pathlib.Path(root)
                    settings_path = _seed_settings(home, enabled=seeded)
                    result = _run_posix_script(home, settings_path)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIs(json.loads(settings_path.read_text(encoding="utf-8"))["sandbox"]["enabled"], expected)
                    self.assertEqual(stat.S_IMODE(settings_path.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "nt", "Windows only")
    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_preserves_or_defaults_enabled(self) -> None:
        for case_name, seeded, expected in VALID_ENABLED_CASES:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as root:
                root_path = pathlib.Path(root)
                home = _windows_test_home(root_path)
                settings_path = _seed_settings(
                    home,
                    filesystem_paths=_windows_filesystem_paths(home, root_path),
                    enabled=seeded,
                )
                result = _run_powershell_script(home, settings_path)
                self.assertEqual(result.returncode, 0, result.stderr)
                settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
                self.assertIs(settings["sandbox"]["enabled"], expected)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq required")
    def test_posix_rejects_non_boolean_enabled(self) -> None:
        for environment, codespaces, devcontainer, _ in POSIX_ENVIRONMENT_CASES:
            for case_name, seeded in INVALID_ENABLED_CASES:
                with self.subTest(environment=environment, case=case_name), tempfile.TemporaryDirectory() as root:
                    home = pathlib.Path(root)
                    settings_path = _seed_settings(home, enabled=seeded)
                    original = settings_path.read_bytes()
                    result = _run_posix_script(home, settings_path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("non-boolean", result.stderr)
                    self.assertIn("sandbox.enabled", result.stderr)
                    self.assertEqual(settings_path.read_bytes(), original)

    @unittest.skipUnless(os.name == "nt", "Windows only")
    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_non_boolean_enabled(self) -> None:
        for case_name, seeded in INVALID_ENABLED_CASES:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as root:
                root_path = pathlib.Path(root)
                home = _windows_test_home(root_path)
                settings_path = _seed_settings(
                    home,
                    filesystem_paths=_windows_filesystem_paths(home, root_path),
                    enabled=seeded,
                )
                original = settings_path.read_bytes()
                result = _run_powershell_script(home, settings_path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("non-boolean", result.stderr)
                self.assertIn("sandbox.enabled", result.stderr)
                self.assertEqual(settings_path.read_bytes(), original)


@unittest.skipIf(os.name == "nt", "POSIX only")
@unittest.skipUnless(
    shutil.which("chezmoi") and shutil.which("bash") and shutil.which("jq"),
    "chezmoi, bash and jq required",
)
class PosixDedicatedUvCacheTests(unittest.TestCase):
    def _hook_path(self, home, settings, platform, env):
        with mock.patch.dict(os.environ, _posix_env(home, settings, env), clear=True), mock.patch.object(UVE.sys, "platform", platform):
            return UVE.copilot_uv_cache_dir()

    def test_sync_and_hook_use_the_same_idempotent_cache_grant(self) -> None:
        platform = "darwin" if sys.platform == "darwin" else "linux"
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root).resolve()
            settings = _seed_settings(home, filesystem_paths=POSIX_FILESYSTEM_PATHS)
            expected = (
                home / "Library/Caches/github-copilot/uv"
                if platform == "darwin"
                else home / ".cache/github-copilot/uv"
            )
            for _ in range(2):
                result = _run_posix_script(home, settings)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    _filesystem(settings)["readwritePaths"],
                    [*POSIX_FILESYSTEM_PATHS["readwritePaths"], str(expected)],
                )
                self.assertEqual(
                    self._hook_path(home, settings, platform, {}),
                    str(expected),
                )
            self.assertTrue(expected.is_dir())

    def test_restrictive_rules_are_not_overridden(self) -> None:
        for category in ("readonlyPaths", "deniedPaths"):
            with self.subTest(category=category), tempfile.TemporaryDirectory() as root:
                home = pathlib.Path(root).resolve()
                settings = _seed_settings(home, filesystem_paths=POSIX_FILESYSTEM_PATHS)
                document = json.loads(settings.read_text(encoding="utf-8"))
                document["sandbox"]["userPolicy"]["filesystem"][category].append(
                    "~/.cache"
                )
                settings.write_text(json.dumps(document), encoding="utf-8")
                original = settings.read_bytes()
                result = _run_posix_script(home, settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(settings.read_bytes(), original)

    def test_sync_and_hook_reject_unsafe_environment(self) -> None:
        cases = (
            ("HOME", "relative"),
            ("XDG_CACHE_HOME", "relative"),
            ("UV_CACHE_DIR", "/explicit-cache"),
        )
        for name, value in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                home = pathlib.Path(root).resolve()
                settings = _seed_settings(home, filesystem_paths=POSIX_FILESYSTEM_PATHS)
                original = settings.read_bytes()
                env = {name: value}

                result = _run_posix_script(home, settings, extra_env=env)

                self.assertNotEqual(result.returncode, 0)
                with self.assertRaises((ValueError, OSError)):
                    self._hook_path(home, settings, "linux", env)
                self.assertEqual(settings.read_bytes(), original)

    def test_sync_and_hook_reject_redirected_cache(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root).resolve()
            target = home / "redirect"
            target.mkdir()
            (home / ".cache").symlink_to(target)
            settings = _seed_settings(home, filesystem_paths=POSIX_FILESYSTEM_PATHS)
            original = settings.read_bytes()

            result = _run_posix_script(home, settings)

            self.assertNotEqual(result.returncode, 0)
            with self.assertRaises((ValueError, OSError)):
                self._hook_path(home, settings, "linux", {})
            self.assertEqual(settings.read_bytes(), original)
            self.assertEqual(list(target.iterdir()), [])


@unittest.skipIf(os.name != "nt", "Windows only")
@unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
class WindowsDedicatedUvCacheTests(unittest.TestCase):
    def _hook_path(self, local_app_data: pathlib.Path) -> str:
        env = {
            "LOCALAPPDATA": str(local_app_data),
            "USERPROFILE": str(local_app_data.parent.parent),
        }
        with scoped_environ(env, unset=("UV_CACHE_DIR",)), mock.patch.object(
            UVE.sys, "platform", "win32"
        ):
            return UVE.copilot_uv_cache_dir_windows()

    def _create_junction(self, path: pathlib.Path, target: pathlib.Path) -> None:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(path), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(result.stderr or result.stdout or "failed to create junction")

    def test_sync_and_hook_use_the_same_idempotent_cache_grant(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = pathlib.Path(root)
            home = _windows_test_home(root_path)
            filesystem_paths = _windows_filesystem_paths(home, root_path)
            settings = _seed_settings(home, filesystem_paths=filesystem_paths)
            local_app_data = _windows_test_local_app_data(home)
            expected = local_app_data / "github-copilot" / "uv"
            for _ in range(2):
                result = _run_powershell_script(home, settings, local_app_data=local_app_data)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    _filesystem(settings)["readwritePaths"],
                    [*filesystem_paths["readwritePaths"], str(expected)],
                )
                self.assertEqual(self._hook_path(local_app_data), str(expected))
            self.assertTrue(expected.is_dir())

    def test_restrictive_rules_are_not_overridden(self) -> None:
        for category in ("readonlyPaths", "deniedPaths"):
            with self.subTest(category=category), tempfile.TemporaryDirectory() as root:
                root_path = pathlib.Path(root)
                home = _windows_test_home(root_path)
                settings = _seed_settings(
                    home,
                    filesystem_paths=_windows_filesystem_paths(home, root_path),
                )
                local_app_data = _windows_test_local_app_data(home)
                document = json.loads(settings.read_text(encoding="utf-8"))
                document["sandbox"]["userPolicy"]["filesystem"][category].append(
                    str(local_app_data)
                )
                settings.write_text(json.dumps(document), encoding="utf-8")
                original = settings.read_bytes()

                result = _run_powershell_script(
                    home, settings, local_app_data=local_app_data
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(settings.read_bytes(), original)

    def test_sync_and_hook_reject_unsafe_environment(self) -> None:
        cases = (
            ("LOCALAPPDATA", "relative"),
            ("LOCALAPPDATA", r"C:\temp\..\cache"),
            ("LOCALAPPDATA", r"\\server\share\cache"),
            ("UV_CACHE_DIR", r"C:\explicit-cache"),
        )
        for name, value in cases:
            with self.subTest(name=name, value=value), tempfile.TemporaryDirectory() as root:
                root_path = pathlib.Path(root)
                home = _windows_test_home(root_path)
                settings = _seed_settings(
                    home,
                    filesystem_paths=_windows_filesystem_paths(home, root_path),
                )
                local_app_data = _windows_test_local_app_data(home)
                original = settings.read_bytes()
                result = _run_powershell_script(
                    home,
                    settings,
                    local_app_data=local_app_data,
                    extra_env={name: value},
                )

                self.assertNotEqual(result.returncode, 0)
                env = {
                    "LOCALAPPDATA": str(local_app_data),
                    "USERPROFILE": str(home),
                }
                unset = ("UV_CACHE_DIR",)
                if name == "UV_CACHE_DIR":
                    env["UV_CACHE_DIR"] = value
                    unset = ()
                else:
                    env["LOCALAPPDATA"] = value
                with scoped_environ(env, unset=unset), mock.patch.object(
                    UVE.sys, "platform", "win32"
                ):
                    with self.assertRaises((ValueError, OSError)):
                        UVE.copilot_uv_cache_dir_windows()
                self.assertEqual(settings.read_bytes(), original)

    def test_sync_and_hook_reject_redirected_cache(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = pathlib.Path(root)
            home = _windows_test_home(root_path)
            target = home / "redirect-target"
            target.mkdir(parents=True)
            local_app_parent = _windows_test_local_app_data(home).parent
            local_app_parent.mkdir(parents=True, exist_ok=True)
            self._create_junction(local_app_parent / "Local", target)
            settings = _seed_settings(
                home,
                filesystem_paths=_windows_filesystem_paths(home, root_path),
            )
            original = settings.read_bytes()
            redirected_local_app_data = local_app_parent / "Local"

            result = _run_powershell_script(
                home, settings, local_app_data=redirected_local_app_data
            )

            self.assertNotEqual(result.returncode, 0)
            with self.assertRaises((ValueError, OSError)):
                self._hook_path(redirected_local_app_data)
            self.assertEqual(settings.read_bytes(), original)
            self.assertFalse((target / "github-copilot").exists())


if __name__ == "__main__":
    unittest.main()
