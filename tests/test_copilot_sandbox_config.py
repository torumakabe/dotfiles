"""Verify sandbox defaults, preservation, and the dedicated POSIX uv cache."""

import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from tests._helpers import load_script


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
USER_POLICY_PATH = SOURCE_ROOT / ".chezmoitemplates/copilot-user-settings.json"
REMOVE_PATH = SOURCE_ROOT / ".chezmoiremove"
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

FILESYSTEM_PATHS = {
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


def _seed_settings(home: pathlib.Path, enabled: object = _ENABLED_KEY_ABSENT) -> pathlib.Path:
    settings_path = home / ".copilot/settings.json"
    settings_path.parent.mkdir(parents=True)
    sandbox: dict = {
        "keep": UNKNOWN_SETTINGS["sandbox"]["keep"],
        "userPolicy": {
            "version": 1,
            "keep": UNKNOWN_SETTINGS["userPolicy"]["keep"],
            "filesystem": {**FILESYSTEM_PATHS, **UNKNOWN_SETTINGS["filesystem"]},
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
    codespaces: bool = False,
    devcontainer: bool = False,
    platform: str = "linux",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
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


def _run_powershell_script(home: pathlib.Path, settings_path: pathlib.Path):
    script_path = home / "configure-sandbox.ps1"
    script_path.write_text(_render(POWERSHELL_SCRIPT_PATH, "windows"), encoding="utf-8")
    return subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-File", str(script_path)],
        env={**os.environ, "COPILOT_HOME": str(settings_path.parent)},
        check=False, capture_output=True, encoding="utf-8",
    )


def _filesystem(settings_path: pathlib.Path) -> dict:
    return json.loads(settings_path.read_text())["sandbox"]["userPolicy"]["filesystem"]


class CopilotSandboxPolicyTests(unittest.TestCase):
    def test_platform_scripts_share_policy_version(self) -> None:
        marker = "# Copilot sandbox policy version: "
        versions = []
        for script_path in (POSIX_SCRIPT_PATH, POWERSHELL_SCRIPT_PATH):
            matches = [
                line.removeprefix(marker)
                for line in script_path.read_text().splitlines()
                if line.startswith(marker)
            ]
            self.assertEqual(len(matches), 1, script_path)
            versions.append(matches[0])
        self.assertEqual(versions[0], versions[1])

    def test_user_policy_has_the_cross_platform_defaults(self) -> None:
        policy = json.loads(USER_POLICY_PATH.read_text())
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

    def test_plugin_skills_replace_legacy_user_copies(self) -> None:
        removals = {
            line for line in REMOVE_PATH.read_text().splitlines()
            if line and not line.startswith("#")
        }
        for skill_name in ("agentfinder", "japanese-technical-writing", "lsp-setup"):
            self.assertIn(f".copilot/skills/{skill_name}", removals)
            self.assertFalse(any(
                path.is_file()
                for path in (SOURCE_ROOT / "private_dot_copilot/skills" / skill_name).rglob("*")
            ))

    def test_guardrails_aliases_keep_allow_all(self) -> None:
        self.assertIn("--allow-all", ZSHRC_PATH.read_text())
        self.assertIn("--allow-all", POWERSHELL_PROFILE_PATH.read_text())

    def test_posix_merge_uses_private_atomic_staging(self) -> None:
        script = POSIX_SCRIPT_PATH.read_text()
        self.assertIn('settings_tmp="${settings_dir}/.settings.json.$$"', script)
        self.assertIn("set -o noclobber", script)
        self.assertIn('chmod 0600 "${settings_tmp}"', script)
        self.assertIn('mv -f "${settings_tmp}" "${settings_path}"', script)

    def test_powershell_merge_replaces_settings_atomically(self) -> None:
        script = POWERSHELL_SCRIPT_PATH.read_text()
        self.assertIn("[System.IO.File]::Replace", script)
        self.assertIn("[System.IO.File]::Move($temporaryPath, $settingsPath, $true)", script)

    def test_posix_rechecks_environment_on_every_apply(self) -> None:
        self.assertTrue(POSIX_SCRIPT_PATH.name.startswith("run_after_"))
        self.assertFalse((SOURCE_ROOT / "run_onchange_after_35-configure-copilot-sandbox.sh.tmpl").exists())
        self.assertFalse((SOURCE_ROOT / "dot_config/uv/modify_private_uv.toml").exists())
        self.assertNotIn("UV_CACHE_DIR", POWERSHELL_SCRIPT_PATH.read_text())
        self.assertNotIn("github-copilot/uv", POWERSHELL_SCRIPT_PATH.read_text())


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotSandboxMergeTests(unittest.TestCase):
    def _assert_settings(self, settings: dict, expected_enabled=True, cache=None) -> None:
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
        expected = {**FILESYSTEM_PATHS}
        if cache:
            expected["readwritePaths"] = [*expected["readwritePaths"], str(cache)]
        self.assertEqual(
            {name: policy["filesystem"][name] for name in FILESYSTEM_PATHS}, expected,
        )
        self.assertEqual(policy["filesystem"]["keep"], UNKNOWN_SETTINGS["filesystem"]["keep"])
        self.assertFalse(policy["filesystem"]["clearPolicyOnExit"])
        self.assertTrue(policy["network"]["allowOutbound"])
        self.assertTrue(policy["network"]["allowLocalNetwork"])
        self.assertEqual(policy["network"]["keep"], UNKNOWN_SETTINGS["network"]["keep"])
        self.assertNotIn("allowedHosts", policy["network"])
        self.assertNotIn("blockedHosts", policy["network"])

    def _assert_normalizes_empty_filesystem_paths(self, run_script) -> None:
        for path_name in FILESYSTEM_PATHS:
            for remove_key in (True, False):
                with self.subTest(path=path_name, remove=remove_key), tempfile.TemporaryDirectory() as root:
                    home = pathlib.Path(root)
                    settings_path = _seed_settings(home)
                    settings = json.loads(settings_path.read_text())
                    fs = settings["sandbox"]["userPolicy"]["filesystem"]
                    if remove_key:
                        fs.pop(path_name)
                    else:
                        fs[path_name] = None
                    settings_path.write_text(json.dumps(settings))
                    result = run_script(home, settings_path)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    merged = json.loads(settings_path.read_text(encoding="utf-8-sig"))
                    expected = []
                    if run_script is _run_posix_script and path_name == "readwritePaths":
                        expected = [str(home.resolve() / ".cache/github-copilot/uv")]
                    self.assertEqual(merged["sandbox"]["userPolicy"]["filesystem"][path_name], expected)

    def _assert_rejects_invalid_filesystem_paths(self, run_script) -> None:
        for path_name in FILESYSTEM_PATHS:
            for value in ("/tmp/not-an-array", 1, True, {"path": "/tmp"}):
                with self.subTest(path=path_name, value=value), tempfile.TemporaryDirectory() as root:
                    home = pathlib.Path(root)
                    settings_path = _seed_settings(home)
                    settings = json.loads(settings_path.read_text())
                    settings["sandbox"]["userPolicy"]["filesystem"][path_name] = value
                    settings_path.write_text(json.dumps(settings))
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
            settings_path = _seed_settings(home)
            result = _run_posix_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(json.loads(settings_path.read_text()), cache=home.resolve() / ".cache/github-copilot/uv")

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root)
            settings_path = _seed_settings(home)
            result = _run_powershell_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(json.loads(settings_path.read_text(encoding="utf-8-sig")))

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq required")
    def test_posix_normalizes_missing_or_null_filesystem_paths(self) -> None:
        self._assert_normalizes_empty_filesystem_paths(_run_posix_script)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_normalizes_missing_or_null_filesystem_paths(self) -> None:
        self._assert_normalizes_empty_filesystem_paths(_run_powershell_script)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq required")
    def test_posix_rejects_non_array_filesystem_paths(self) -> None:
        self._assert_rejects_invalid_filesystem_paths(_run_posix_script)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_non_array_filesystem_paths(self) -> None:
        self._assert_rejects_invalid_filesystem_paths(_run_powershell_script)


VALID_ENABLED_CASES = (
    ("missing", _ENABLED_KEY_ABSENT, True), ("true", True, True), ("false", False, False),
)
INVALID_ENABLED_CASES = (
    ("null", None), ("string", "disabled"), ("number", 1), ("array", [True]),
)
POSIX_ENVIRONMENT_CASES = (
    ("ordinary-linux", False, False, True),
    ("codespaces", True, False, False),
    ("devcontainer", False, True, False),
)


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
                result = _run_posix_script(home, settings_path, codespaces=codespaces, devcontainer=devcontainer)
                self.assertEqual(result.returncode, 0, result.stderr)
                settings = json.loads(settings_path.read_text())
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
                    result = _run_posix_script(home, settings_path, codespaces=codespaces, devcontainer=devcontainer)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIs(json.loads(settings_path.read_text())["sandbox"]["enabled"], expected)
                    self.assertEqual(stat.S_IMODE(settings_path.stat().st_mode), 0o600)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_preserves_or_defaults_enabled(self) -> None:
        for case_name, seeded, expected in VALID_ENABLED_CASES:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as root:
                home = pathlib.Path(root)
                settings_path = _seed_settings(home, enabled=seeded)
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
                    result = _run_posix_script(home, settings_path, codespaces=codespaces, devcontainer=devcontainer)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("non-boolean", result.stderr)
                    self.assertIn("sandbox.enabled", result.stderr)
                    self.assertEqual(settings_path.read_bytes(), original)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_non_boolean_enabled(self) -> None:
        for case_name, seeded in INVALID_ENABLED_CASES:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as root:
                home = pathlib.Path(root)
                settings_path = _seed_settings(home, enabled=seeded)
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
class DedicatedUvCacheTests(unittest.TestCase):
    def _hook_path(self, home, settings, platform, env):
        with mock.patch.dict(os.environ, _posix_env(home, settings, env), clear=True), mock.patch.object(UVE.sys, "platform", platform):
            return UVE.copilot_uv_cache_dir()

    def test_sync_and_hook_agree_and_reapply_is_idempotent(self) -> None:
        for platform in ("linux", "darwin"):
            for xdg in (None, "", "external", "punctuation"):
                with self.subTest(platform=platform, xdg=xdg), tempfile.TemporaryDirectory() as root:
                    home = pathlib.Path(root).resolve()
                    settings = _seed_settings(home)
                    base = home / ("cache with 'quote; dollar$" if xdg == "punctuation" else "cache")
                    env = {} if xdg is None else {"XDG_CACHE_HOME": "" if xdg == "" else str(base)}
                    if xdg == "external":
                        base = home.parent / f"{home.name}-cache"
                        env["XDG_CACHE_HOME"] = str(base)
                        self.addCleanup(shutil.rmtree, base, True)
                    expected = home / "Library/Caches" if platform == "darwin" else (base if xdg else home / ".cache")
                    expected /= "github-copilot/uv"
                    for _ in range(2):
                        result = _run_posix_script(home, settings, platform=platform, extra_env=env)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(_filesystem(settings)["readwritePaths"], [*FILESYSTEM_PATHS["readwritePaths"], str(expected)])
                        self.assertEqual(self._hook_path(home, settings, platform, env), str(expected))
                    self.assertTrue(expected.is_dir())
                    self.assertFalse((home / ".config/uv").exists())
                    self.assertEqual(sorted(p.name for p in settings.parent.iterdir()), ["settings.json"])
                    self.assertEqual(_filesystem(settings)["readonlyPaths"], FILESYSTEM_PATHS["readonlyPaths"])

    def test_existing_ancestor_or_alias_grants_are_preserved(self) -> None:
        for rule in ("~/.cache", "~/.cache/github-copilot/uv", "alias"):
            with self.subTest(rule=rule), tempfile.TemporaryDirectory() as root:
                home = pathlib.Path(root).resolve()
                cache = home / ".cache/github-copilot/uv"
                cache.mkdir(parents=True)
                alias = home / "alias"
                alias.symlink_to(cache)
                settings = _seed_settings(home)
                value = str(alias) if rule == "alias" else rule
                document = json.loads(settings.read_text())
                paths = document["sandbox"]["userPolicy"]["filesystem"]["readwritePaths"]
                paths.append(value)
                settings.write_text(json.dumps(document))
                result = _run_posix_script(home, settings)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(_filesystem(settings)["readwritePaths"], paths)

    def test_xdg_change_keeps_old_grant_without_ownership_inference(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root).resolve()
            settings = _seed_settings(home)
            for base in (home / ".cache", home / "other-cache"):
                result = _run_posix_script(home, settings, extra_env={"XDG_CACHE_HOME": str(base)})
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(_filesystem(settings)["readwritePaths"], [
                *FILESYSTEM_PATHS["readwritePaths"],
                str(home / ".cache/github-copilot/uv"),
                str(home / "other-cache/github-copilot/uv"),
            ])

    def test_restrictive_rules_fail_without_settings_or_cache_writes(self) -> None:
        for category in ("readonlyPaths", "deniedPaths"):
            for rule in ("~", "~/.cache", "~/.cache/github-copilot/uv", "~/.cache/github-copilot/uv/subdir", "/"):
                with self.subTest(category=category, rule=rule), tempfile.TemporaryDirectory() as root:
                    home = pathlib.Path(root).resolve()
                    settings = _seed_settings(home)
                    document = json.loads(settings.read_text())
                    document["sandbox"]["userPolicy"]["filesystem"][category].append(rule)
                    settings.write_text(json.dumps(document))
                    original = settings.read_bytes()
                    result = _run_posix_script(home, settings)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(category, result.stderr)
                    self.assertEqual(settings.read_bytes(), original)
                    self.assertFalse((home / ".cache").exists())

    def test_invalid_environment_is_rejected_by_sync_and_hook(self) -> None:
        for value in ("relative", "/", "//", "/some/../cache", "/cache\nbad", "/cache\rbad"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as root:
                home = pathlib.Path(root).resolve()
                settings = _seed_settings(home)
                original = settings.read_bytes()
                env = {"XDG_CACHE_HOME": value}
                result = _run_posix_script(home, settings, extra_env=env)
                self.assertNotEqual(result.returncode, 0)
                with self.assertRaises(ValueError):
                    self._hook_path(home, settings, "linux", env)
                self.assertEqual(settings.read_bytes(), original)

    def test_cache_home_normalization_agrees_without_broad_grants(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root).resolve()
            settings = _seed_settings(home)
            for value in (str(home), str(home) + "/", str(home) + "//./cache///"):
                with self.subTest(value=value):
                    env = {"XDG_CACHE_HOME": value}
                    expected = self._hook_path(home, settings, "linux", env)
                    result = _run_posix_script(home, settings, extra_env=env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    paths = _filesystem(settings)["readwritePaths"]
                    self.assertIn(expected, paths)
                    self.assertNotIn(str(home), paths)
                    self.assertNotIn(str(pathlib.Path(value)), paths)

    def test_invalid_home_is_rejected_by_sync_and_hook(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root).resolve()
            settings = _seed_settings(home)
            for value in ("/", "relative", str(home) + "/.", str(home) + "//", str(home) + "\n"):
                with self.subTest(value=value):
                    env = {"HOME": value}
                    result = _run_posix_script(home, settings, extra_env=env)
                    self.assertNotEqual(result.returncode, 0)
                    with self.assertRaises(ValueError):
                        self._hook_path(home, settings, "linux", env)

    def test_launch_override_is_rejected_even_when_empty_or_matching(self) -> None:
        for platform in ("linux", "darwin"):
            for value in ("", "/explicit-cache", "matching"):
                with self.subTest(platform=platform, value=value), tempfile.TemporaryDirectory() as root:
                    home = pathlib.Path(root).resolve()
                    settings = _seed_settings(home)
                    if value == "matching":
                        value = self._hook_path(home, settings, platform, {})
                    env = {"UV_CACHE_DIR": value}
                    result = _run_posix_script(home, settings, platform=platform, extra_env=env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("launch-environment UV_CACHE_DIR", result.stderr)
                    with self.assertRaisesRegex(ValueError, "launch-environment UV_CACHE_DIR"):
                        self._hook_path(home, settings, platform, env)

    def test_redirected_cache_components_are_rejected_without_target_writes(self) -> None:
        for suffix in (".cache", ".cache/github-copilot", ".cache/github-copilot/uv"):
            for dangling in (False, True):
                with self.subTest(suffix=suffix, dangling=dangling), tempfile.TemporaryDirectory() as root:
                    home = pathlib.Path(root).resolve()
                    target = home / "redirect"
                    if not dangling:
                        target.mkdir()
                    link = home / suffix
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(target)
                    settings = _seed_settings(home)
                    original = settings.read_bytes()
                    result = _run_posix_script(home, settings)
                    self.assertNotEqual(result.returncode, 0)
                    with self.assertRaisesRegex(ValueError, "symlinks"):
                        self._hook_path(home, settings, "linux", {})
                    self.assertEqual(settings.read_bytes(), original)
                    self.assertEqual(list(target.iterdir()) if target.exists() else [], [])

    def test_home_alias_is_canonicalized_but_cache_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = pathlib.Path(root).resolve()
            home = base / "real"
            home.mkdir()
            alias = base / "alias"
            alias.symlink_to(home)
            settings = _seed_settings(home)
            for value in (str(alias / ".cache"), f"/{alias}//./.cache", str(alias)):
                env = {"XDG_CACHE_HOME": value}
                result = _run_posix_script(alias, settings, extra_env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = home / ("github-copilot/uv" if value == str(alias) else ".cache/github-copilot/uv")
                self.assertEqual(self._hook_path(alias, settings, "linux", env), str(expected))
        with tempfile.TemporaryDirectory() as root:
            home = pathlib.Path(root).resolve()
            (home / ".cache").write_text("not a directory")
            settings = _seed_settings(home)
            result = _run_posix_script(home, settings)
            self.assertNotEqual(result.returncode, 0)
            with self.assertRaisesRegex(ValueError, "non-directories"):
                self._hook_path(home, settings, "linux", {})


if __name__ == "__main__":
    unittest.main()
