"""Verify the cross-platform Copilot CLI sandbox settings contract.

On POSIX, `sandbox.enabled` defaults to false in Codespaces and this
repository's Dev Container, and to true elsewhere. `/sandbox disable`
persists `sandbox.enabled=false` in `~/.copilot/settings.json`, and that value
must survive every future `chezmoi apply` until `/sandbox enable` restores it. The
``CopilotSandboxEnabledPreservationTests`` below execute the rendered POSIX
and PowerShell scripts against seeded settings files to pin that contract.
"""

import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

from tests._helpers import load_script


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
USER_POLICY_PATH = SOURCE_ROOT / ".chezmoitemplates/copilot-user-settings.json"
REMOVE_PATH = SOURCE_ROOT / ".chezmoiremove"
POSIX_SCRIPT_PATH = SOURCE_ROOT / "run_onchange_after_35-configure-copilot-sandbox.sh.tmpl"
POWERSHELL_SCRIPT_PATH = (
    SOURCE_ROOT / "run_onchange_after_35-configure-copilot-sandbox.ps1.tmpl"
)
ZSHRC_PATH = SOURCE_ROOT / "dot_zshrc.tmpl"
POWERSHELL_PROFILE_PATH = SOURCE_ROOT / "PowerShell_profile.ps1.tmpl"
UV_ENFORCER_PATH = (
    SOURCE_ROOT
    / "private_dot_copilot/hooks/scripts/executable_uv-enforcer.py"
)
uv_enforcer = load_script("sandbox_config_uv_enforcer", UV_ENFORCER_PATH)

FILESYSTEM_PATHS = {
    "readwritePaths": ["/tmp/readwrite"],
    "readonlyPaths": ["/tmp/readonly"],
    "deniedPaths": ["/tmp/denied"],
}
UNKNOWN_SETTINGS = {
    "extraKnownMarketplaces": {
        "existing-marketplace": {
            "source": {
                "source": "github",
                "repo": "example/existing-marketplace",
            }
        }
    },
    "enabledPlugins": {"existing-plugin@existing-marketplace": False},
    "sandbox": {"keep": "sandbox"},
    "userPolicy": {"keep": "policy"},
    "filesystem": {"keep": {"nested": "filesystem"}},
    "network": {"keep": ["network"]},
}
EXPECTED_MARKETPLACE = {
    "source": {
        "source": "github",
        "repo": "torumakabe/copilot-agent-plugins",
    },
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
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _normalized_powershell_error(stderr: str) -> str:
    return " ".join(ANSI_ESCAPE.sub("", stderr).replace("|", " ").split())

# Sentinel distinguishing "no sandbox.enabled key seeded" from any JSON value,
# including `None` (JSON null), which is itself one of the invalid cases.
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
            "chezmoi",
            "--source",
            str(SOURCE_ROOT),
            "execute-template",
            "--override-data",
            json.dumps(
                {
                    "chezmoi": {"os": platform, "arch": "amd64"},
                    "codespaces": codespaces,
                    "devcontainer": devcontainer,
                }
            ),
            "--file",
            str(path),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
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
            "filesystem": {
                **FILESYSTEM_PATHS,
                **UNKNOWN_SETTINGS["filesystem"],
            },
            "network": {
                "allowedHosts": ["api.github.com"],
                "blockedHosts": ["example.invalid"],
                **UNKNOWN_SETTINGS["network"],
            },
        }
    }
    if enabled is not _ENABLED_KEY_ABSENT:
        sandbox["enabled"] = enabled
    settings_path.write_text(
        json.dumps(
            {
                "unrelated": {"keep": True},
                "deepUnknown": DEEP_UNKNOWN,
                "extraKnownMarketplaces": UNKNOWN_SETTINGS[
                    "extraKnownMarketplaces"
                ],
                "enabledPlugins": UNKNOWN_SETTINGS["enabledPlugins"],
                "sandbox": sandbox,
            }
        ),
        encoding="utf-8",
    )
    return settings_path


def _run_posix_script(
    home: pathlib.Path,
    settings_path: pathlib.Path,
    *,
    platform: str = "linux",
    codespaces: bool = False,
    devcontainer: bool = False,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script_path = home / "configure-sandbox.sh"
    script_path.write_text(
        _render(
            POSIX_SCRIPT_PATH,
            platform,
            codespaces=codespaces,
            devcontainer=devcontainer,
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "COPILOT_HOME": str(settings_path.parent),
        "HOME": str(home),
    }
    env.pop("MISE_DATA_DIR", None)
    env.pop("MISE_INSTALLS_DIR", None)
    env.pop("XDG_DATA_HOME", None)
    env.pop("XDG_CACHE_HOME", None)
    env.pop("UV_CACHE_DIR", None)
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(script_path)],
        env=env,
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


def _run_powershell_script(
    home: pathlib.Path,
    settings_path: pathlib.Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script_path = home / "configure-sandbox.ps1"
    script_path.write_text(_render(POWERSHELL_SCRIPT_PATH, "windows"), encoding="utf-8")
    env = {
        **os.environ,
        "COPILOT_HOME": str(settings_path.parent),
        "LOCALAPPDATA": str(home / "AppData/Local"),
    }
    env.pop("MISE_DATA_DIR", None)
    env.pop("MISE_INSTALLS_DIR", None)
    env.pop("XDG_DATA_HOME", None)
    env.pop("UV_CACHE_DIR", None)
    env.update(extra_env or {})
    return subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-File", str(script_path)],
        env=env,
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


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
        self.assertTrue(sandbox["enabled"])
        self.assertTrue(sandbox["allowBypass"])
        self.assertFalse(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertTrue(sandbox["addCurrentWorkingDirectory"])
        self.assertTrue(sandbox["allowDevToolAccess"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})
        self.assertEqual(
            sandbox["userPolicy"]["network"],
            {"allowOutbound": True, "allowLocalNetwork": True},
        )

    def test_plugin_skills_replace_legacy_user_copies(self) -> None:
        skill_names = ("agentfinder", "japanese-technical-writing", "lsp-setup")
        removals = {
            line
            for line in REMOVE_PATH.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        }

        for skill_name in skill_names:
            self.assertIn(f".copilot/skills/{skill_name}", removals)
            self.assertFalse(
                any(
                    path.is_file()
                    for path in (
                        SOURCE_ROOT / "private_dot_copilot" / "skills" / skill_name
                    ).rglob("*")
                )
            )

    def test_guardrails_aliases_keep_allow_all(self) -> None:
        self.assertIn("--allow-all", ZSHRC_PATH.read_text(encoding="utf-8"))
        self.assertIn("--allow-all", POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8"))

    def test_posix_merge_uses_a_private_temporary_directory(self) -> None:
        script = POSIX_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('tmp_dir="$(mktemp -d)"', script)
        self.assertIn('settings_tmp="$(mktemp "${settings_dir}/.settings.json.XXXXXX")"', script)
        self.assertIn('chmod 0600 "${settings_tmp}"', script)

    def test_powershell_merge_replaces_settings_atomically(self) -> None:
        script = POWERSHELL_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("[System.IO.File]::Replace", script)
        self.assertIn(
            "[System.IO.File]::Move($temporaryPath, $settingsPath, $true)",
            script,
        )


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotSandboxMergeTests(unittest.TestCase):
    def _assert_settings(
        self,
        settings: dict,
        expected_mise_readonly_paths: list[pathlib.Path],
        expected_uv_cache_path: pathlib.Path,
        expected_enabled: bool = True,
    ) -> None:
        self.assertEqual(settings["unrelated"], {"keep": True})
        self.assertEqual(settings["deepUnknown"], DEEP_UNKNOWN)
        self.assertTrue(settings["experimental"])
        self.assertEqual(
            settings["extraKnownMarketplaces"],
            {
                **UNKNOWN_SETTINGS["extraKnownMarketplaces"],
                "torumakabe-agent-plugins": EXPECTED_MARKETPLACE,
            },
        )
        self.assertEqual(
            settings["enabledPlugins"],
            {
                **UNKNOWN_SETTINGS["enabledPlugins"],
                **EXPECTED_PLUGINS,
            },
        )

        sandbox = settings["sandbox"]
        self.assertEqual(sandbox["keep"], UNKNOWN_SETTINGS["sandbox"]["keep"])
        self.assertIs(sandbox["enabled"], expected_enabled)
        self.assertTrue(sandbox["allowBypass"])
        self.assertFalse(sandbox["sandboxMcpServers"])
        self.assertFalse(sandbox["sandboxLspServers"])
        self.assertTrue(sandbox["addCurrentWorkingDirectory"])
        self.assertTrue(sandbox["allowDevToolAccess"])
        self.assertEqual(sandbox["auth"], {"git": True, "gh": True})

        policy = sandbox["userPolicy"]
        self.assertEqual(policy["keep"], UNKNOWN_SETTINGS["userPolicy"]["keep"])
        self.assertNotIn("version", policy)
        self.assertEqual(
            policy["filesystem"]["readwritePaths"],
            [
                *FILESYSTEM_PATHS["readwritePaths"],
                str(expected_uv_cache_path),
            ],
        )
        self.assertEqual(
            policy["filesystem"]["readonlyPaths"],
            [
                *FILESYSTEM_PATHS["readonlyPaths"],
                *(str(path) for path in expected_mise_readonly_paths),
            ],
        )
        self.assertEqual(
            policy["filesystem"]["deniedPaths"],
            FILESYSTEM_PATHS["deniedPaths"],
        )
        self.assertEqual(
            policy["filesystem"]["keep"],
            UNKNOWN_SETTINGS["filesystem"]["keep"],
        )
        self.assertFalse(policy["filesystem"]["clearPolicyOnExit"])
        self.assertTrue(policy["network"]["allowOutbound"])
        self.assertTrue(policy["network"]["allowLocalNetwork"])
        self.assertEqual(
            policy["network"]["keep"],
            UNKNOWN_SETTINGS["network"]["keep"],
        )
        self.assertNotIn("allowedHosts", policy["network"])
        self.assertNotIn("blockedHosts", policy["network"])

    def _assert_normalizes_empty_filesystem_paths(
        self,
        run_script,
        expected_mise_readonly_paths,
        expected_uv_cache_path,
    ) -> None:
        for path_name in FILESYSTEM_PATHS:
            for case_name, remove_key in (("missing", True), ("null", False)):
                with self.subTest(path=path_name, case=case_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        home = pathlib.Path(temp_dir)
                        settings_path = _seed_settings(home)
                        settings = json.loads(settings_path.read_text(encoding="utf-8"))
                        filesystem = settings["sandbox"]["userPolicy"]["filesystem"]
                        if remove_key:
                            filesystem.pop(path_name)
                        else:
                            filesystem[path_name] = None
                        settings_path.write_text(json.dumps(settings), encoding="utf-8")

                        result = run_script(home, settings_path)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        merged = json.loads(
                            settings_path.read_text(encoding="utf-8-sig")
                        )
                        expected = (
                            [
                                str(path)
                                for path in expected_mise_readonly_paths(home)
                            ]
                            if path_name == "readonlyPaths"
                            else (
                                [str(expected_uv_cache_path(home))]
                                if path_name == "readwritePaths"
                                else []
                            )
                        )
                        self.assertEqual(
                            merged["sandbox"]["userPolicy"]["filesystem"][path_name],
                            expected,
                        )

    def _assert_rejects_invalid_filesystem_paths(self, run_script) -> None:
        invalid_cases = (
            ("string", "/tmp/not-an-array"),
            ("number", 1),
            ("boolean", True),
            ("object", {"path": "/tmp"}),
        )
        for path_name in FILESYSTEM_PATHS:
            for case_name, invalid_value in invalid_cases:
                with self.subTest(path=path_name, case=case_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        home = pathlib.Path(temp_dir)
                        settings_path = _seed_settings(home)
                        settings = json.loads(settings_path.read_text(encoding="utf-8"))
                        settings["sandbox"]["userPolicy"]["filesystem"][path_name] = (
                            invalid_value
                        )
                        settings_path.write_text(json.dumps(settings), encoding="utf-8")
                        original = settings_path.read_text(encoding="utf-8")

                        result = run_script(home, settings_path)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("non-array", result.stderr)
                        self.assertIn(
                            f"sandbox.userPolicy.filesystem.{path_name}",
                            result.stderr,
                        )
                        self.assertEqual(
                            settings_path.read_text(encoding="utf-8"),
                            original,
                        )

    def _assert_managed_path_conflicts(
        self, run_script, managed_path_for_home
    ) -> None:
        for path_name, expected_success in (
            ("readwritePaths", True),
            ("deniedPaths", False),
        ):
            with self.subTest(path=path_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    managed_path = managed_path_for_home(home)
                    settings_path = _seed_settings(home)
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    filesystem = settings["sandbox"]["userPolicy"]["filesystem"]
                    filesystem[path_name] = [f"{managed_path}{os.sep}"]
                    settings_path.write_text(json.dumps(settings), encoding="utf-8")
                    original = settings_path.read_text(encoding="utf-8")

                    result = run_script(home, settings_path)
                    if expected_success:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        merged = json.loads(
                            settings_path.read_text(encoding="utf-8-sig")
                        )
                        self.assertEqual(
                            merged["sandbox"]["userPolicy"]["filesystem"][
                                "readonlyPaths"
                            ],
                            FILESYSTEM_PATHS["readonlyPaths"],
                        )
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("deniedPaths", result.stderr)
                        self.assertEqual(
                            settings_path.read_text(encoding="utf-8"),
                            original,
                        )
                        self.assertFalse(managed_path.exists())

    def _assert_uv_cache_permission_conflicts(
        self, run_script, uv_cache_path_for_home
    ) -> None:
        for path_name, expected_success in (
            ("readwritePaths", True),
            ("readonlyPaths", False),
            ("deniedPaths", False),
        ):
            with self.subTest(path=path_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    uv_cache_path = uv_cache_path_for_home(home)
                    settings_path = _seed_settings(home)
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    filesystem = settings["sandbox"]["userPolicy"]["filesystem"]
                    filesystem[path_name] = [f"{uv_cache_path}{os.sep}"]
                    settings_path.write_text(json.dumps(settings), encoding="utf-8")
                    original = settings_path.read_text(encoding="utf-8")

                    result = run_script(home, settings_path)
                    if expected_success:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        merged = json.loads(
                            settings_path.read_text(encoding="utf-8-sig")
                        )
                        self.assertEqual(
                            merged["sandbox"]["userPolicy"]["filesystem"][
                                "readwritePaths"
                            ],
                            [f"{uv_cache_path}{os.sep}"],
                        )
                        self.assertTrue(uv_cache_path.is_dir())
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        error = _normalized_powershell_error(result.stderr)
                        self.assertIn(path_name, error)
                        self.assertIn("managed Copilot uv cache path", error)
                        self.assertEqual(
                            settings_path.read_text(encoding="utf-8"),
                            original,
                        )
                        self.assertFalse(uv_cache_path.exists())

    def _assert_uv_cache_parent_permission_conflicts(
        self, run_script, uv_cache_path_for_home
    ) -> None:
        for path_name in ("readonlyPaths", "deniedPaths"):
            with self.subTest(path=path_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    uv_cache_path = uv_cache_path_for_home(home)
                    settings_path = _seed_settings(home)
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    filesystem = settings["sandbox"]["userPolicy"]["filesystem"]
                    filesystem[path_name] = [
                        str(uv_cache_path.parent / "nested" / "..")
                    ]
                    settings_path.write_text(json.dumps(settings), encoding="utf-8")
                    original = settings_path.read_text(encoding="utf-8")

                    result = run_script(home, settings_path)
                    self.assertNotEqual(result.returncode, 0)
                    error = _normalized_powershell_error(result.stderr)
                    self.assertIn(path_name, error)
                    self.assertIn("managed Copilot uv cache path", error)
                    self.assertEqual(
                        settings_path.read_text(encoding="utf-8"),
                        original,
                    )
                    self.assertFalse(uv_cache_path.exists())

    def _assert_uv_cache_rejects_links(
        self, run_script, uv_cache_path_for_home, expected_error: str
    ) -> None:
        for link_name in ("parent", "target"):
            with self.subTest(link=link_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    uv_cache_path = uv_cache_path_for_home(home)
                    settings_path = _seed_settings(home)
                    original = settings_path.read_text(encoding="utf-8")
                    redirect = home / "redirect"
                    redirect.mkdir()
                    try:
                        if link_name == "parent":
                            uv_cache_path.parent.parent.mkdir(parents=True)
                            uv_cache_path.parent.symlink_to(
                                redirect,
                                target_is_directory=True,
                            )
                        else:
                            uv_cache_path.parent.mkdir(parents=True)
                            uv_cache_path.symlink_to(
                                redirect,
                                target_is_directory=True,
                            )
                    except OSError as error:
                        self.skipTest(f"directory symlink unavailable: {error}")

                    result = run_script(home, settings_path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected_error, result.stderr)
                    self.assertEqual(
                        settings_path.read_text(encoding="utf-8"),
                        original,
                    )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            for _ in range(2):
                result = _run_posix_script(home, settings_path)
                self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8")),
                [home / ".local/share/mise"],
                home / ".cache/github-copilot/uv",
            )
            self.assertTrue((home / ".local/share/mise/installs").is_dir())
            self.assertTrue((home / ".cache/github-copilot/uv").is_dir())

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_uses_configured_mise_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            mise_data_dir = home / "custom-mise"
            mise_installs_dir = home / "custom-installs"
            result = _run_posix_script(
                home,
                settings_path,
                extra_env={
                    "MISE_DATA_DIR": str(mise_data_dir),
                    "MISE_INSTALLS_DIR": str(mise_installs_dir),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8")),
                [mise_data_dir, mise_installs_dir],
                home / ".cache/github-copilot/uv",
            )
            self.assertTrue(mise_data_dir.is_dir())
            self.assertTrue(mise_installs_dir.is_dir())

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_uses_xdg_data_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            xdg_data_home = home / "xdg-data"
            result = _run_posix_script(
                home,
                settings_path,
                extra_env={"XDG_DATA_HOME": str(xdg_data_home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8")),
                [xdg_data_home / "mise"],
                home / ".cache/github-copilot/uv",
            )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_uses_xdg_cache_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            xdg_cache_home = home / "xdg-cache"
            result = _run_posix_script(
                home,
                settings_path,
                extra_env={"XDG_CACHE_HOME": str(xdg_cache_home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            expected_cache = pathlib.Path(
                uv_enforcer.copilot_uv_cache_dir(
                    "linux",
                    {"XDG_CACHE_HOME": str(xdg_cache_home)},
                    str(home),
                )
            )
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8")),
                [home / ".local/share/mise"],
                expected_cache,
            )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_darwin_uv_cache_path_matches_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            result = _run_posix_script(
                home,
                settings_path,
                platform="darwin",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            expected_cache = pathlib.Path(
                uv_enforcer.copilot_uv_cache_dir(
                    "darwin",
                    {},
                    str(home),
                )
            )
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8")),
                [home / ".local/share/mise"],
                expected_cache,
            )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_merge_preserves_paths_and_removes_stale_network_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            for _ in range(2):
                result = _run_powershell_script(home, settings_path)
                self.assertEqual(result.returncode, 0, result.stderr)
            expected_cache = pathlib.Path(
                uv_enforcer.copilot_uv_cache_dir(
                    "win32",
                    {"LOCALAPPDATA": str(home / "AppData/Local")},
                    str(home),
                ).replace("\\", "/")
            )
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8-sig")),
                [home / "AppData/Local/mise"],
                expected_cache,
            )
            self.assertTrue((home / "AppData/Local/mise/installs").is_dir())
            self.assertTrue((home / "AppData/Local/GitHubCopilot/uv").is_dir())

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_uses_configured_mise_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            mise_data_dir = home / "custom-mise"
            mise_installs_dir = home / "custom-installs"
            result = _run_powershell_script(
                home,
                settings_path,
                extra_env={
                    "MISE_DATA_DIR": str(mise_data_dir),
                    "MISE_INSTALLS_DIR": str(mise_installs_dir),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8-sig")),
                [mise_data_dir, mise_installs_dir],
                home / "AppData/Local/GitHubCopilot/uv",
            )
            self.assertTrue(mise_data_dir.is_dir())
            self.assertTrue(mise_installs_dir.is_dir())

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_uses_xdg_data_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            xdg_data_home = home / "xdg-data"
            result = _run_powershell_script(
                home,
                settings_path,
                extra_env={"XDG_DATA_HOME": str(xdg_data_home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_settings(
                json.loads(settings_path.read_text(encoding="utf-8-sig")),
                [xdg_data_home / "mise"],
                home / "AppData/Local/GitHubCopilot/uv",
            )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_normalizes_missing_or_null_filesystem_paths(self) -> None:
        self._assert_normalizes_empty_filesystem_paths(
            _run_posix_script,
            lambda home: [home / ".local/share/mise"],
            lambda home: home / ".cache/github-copilot/uv",
        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_normalizes_missing_or_null_filesystem_paths(self) -> None:
        self._assert_normalizes_empty_filesystem_paths(
            _run_powershell_script,
            lambda home: [home / "AppData/Local/mise"],
            lambda home: home / "AppData/Local/GitHubCopilot/uv",
        )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_rejects_non_array_filesystem_paths(self) -> None:
        self._assert_rejects_invalid_filesystem_paths(_run_posix_script)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_non_array_filesystem_paths(self) -> None:
        self._assert_rejects_invalid_filesystem_paths(_run_powershell_script)

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_handles_managed_path_permission_conflicts(self) -> None:
        self._assert_managed_path_conflicts(
            _run_posix_script,
            lambda home: home / ".local/share/mise",
        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_handles_managed_path_permission_conflicts(self) -> None:
        self._assert_managed_path_conflicts(
            _run_powershell_script,
            lambda home: home / "AppData/Local/mise",
        )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_handles_uv_cache_permission_conflicts(self) -> None:
        self._assert_uv_cache_permission_conflicts(
            _run_posix_script,
            lambda home: home / ".cache/github-copilot/uv",
        )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_rejects_uv_cache_parent_permission_conflicts(self) -> None:
        self._assert_uv_cache_parent_permission_conflicts(
            _run_posix_script,
            lambda home: home / ".cache/github-copilot/uv",
        )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_relative_dot_policy_path_is_not_a_parent_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = pathlib.Path(temp_dir)
            settings_path = _seed_settings(home)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["sandbox"]["userPolicy"]["filesystem"]["deniedPaths"] = ["."]
            settings_path.write_text(json.dumps(settings), encoding="utf-8")

            result = _run_posix_script(home, settings_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            self.assertIn(
                str(home / ".cache/github-copilot/uv"),
                merged["sandbox"]["userPolicy"]["filesystem"]["readwritePaths"],
            )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_expands_tilde_for_uv_cache_permission_conflicts(self) -> None:
        for path_name, expected_success in (
            ("readwritePaths", True),
            ("readonlyPaths", False),
            ("deniedPaths", False),
        ):
            with self.subTest(path=path_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    uv_cache_path = home / ".cache/github-copilot/uv"
                    settings_path = _seed_settings(home)
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    filesystem = settings["sandbox"]["userPolicy"]["filesystem"]
                    filesystem[path_name] = ["~/.cache/github-copilot/uv/"]
                    settings_path.write_text(json.dumps(settings), encoding="utf-8")
                    original = settings_path.read_text(encoding="utf-8")

                    result = _run_posix_script(home, settings_path)
                    if expected_success:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        merged = json.loads(
                            settings_path.read_text(encoding="utf-8-sig")
                        )
                        self.assertEqual(
                            merged["sandbox"]["userPolicy"]["filesystem"][
                                "readwritePaths"
                            ],
                            ["~/.cache/github-copilot/uv/"],
                        )
                        self.assertTrue(uv_cache_path.is_dir())
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(path_name, result.stderr)
                        self.assertIn("managed Copilot uv cache path", result.stderr)
                        self.assertEqual(
                            settings_path.read_text(encoding="utf-8"),
                            original,
                        )
                        self.assertFalse(uv_cache_path.exists())

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_handles_uv_cache_permission_conflicts(self) -> None:
        self._assert_uv_cache_permission_conflicts(
            _run_powershell_script,
            lambda home: home / "AppData/Local/GitHubCopilot/uv",
        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_uv_cache_parent_permission_conflicts(self) -> None:
        self._assert_uv_cache_parent_permission_conflicts(
            _run_powershell_script,
            lambda home: home / "AppData/Local/GitHubCopilot/uv",
        )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_rejects_linked_uv_cache_paths(self) -> None:
        self._assert_uv_cache_rejects_links(
            _run_posix_script,
            lambda home: home / ".cache/github-copilot/uv",
            "symbolic link",
        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_linked_uv_cache_paths(self) -> None:
        self._assert_uv_cache_rejects_links(
            _run_powershell_script,
            lambda home: home / "AppData/Local/GitHubCopilot/uv",
            "reparse point",
        )


# (case name, seeded value, expected merged value). ``_ENABLED_KEY_ABSENT``
# seeds an existing settings file without a `sandbox.enabled` key.
VALID_ENABLED_CASES = (
    ("missing", _ENABLED_KEY_ABSENT, True),
    ("true", True, True),
    ("false", False, False),
)

# (case name, seeded value). Each must make the script fail loudly instead of
# silently coercing the value to a boolean.
INVALID_ENABLED_CASES = (
    ("null", None),
    ("string", "disabled"),
    ("number", 1),
    ("array", [True]),
)

# (case name, Codespaces, Dev Container, first-apply default)
POSIX_ENVIRONMENT_CASES = (
    ("ordinary-linux", False, False, True),
    ("codespaces", True, False, False),
    ("devcontainer", False, True, False),
)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class CopilotSandboxEnabledPreservationTests(unittest.TestCase):
    """Pin the environment defaults and user override contract in ADR-026."""

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_defaults_enabled_when_settings_file_is_absent(self) -> None:
        for environment, codespaces, devcontainer, expected in POSIX_ENVIRONMENT_CASES:
            with self.subTest(environment=environment):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    settings_path = home / ".copilot/settings.json"
                    result = _run_posix_script(
                        home,
                        settings_path,
                        codespaces=codespaces,
                        devcontainer=devcontainer,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    self.assertIs(settings["sandbox"]["enabled"], expected)
                    self.assertEqual(
                        stat.S_IMODE(settings_path.stat().st_mode),
                        0o600,
                    )

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_preserves_or_defaults_enabled(self) -> None:
        for environment, codespaces, devcontainer, default in POSIX_ENVIRONMENT_CASES:
            for case_name, seeded, ordinary_expected in VALID_ENABLED_CASES:
                expected = default if seeded is _ENABLED_KEY_ABSENT else ordinary_expected
                with self.subTest(environment=environment, case=case_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        home = pathlib.Path(temp_dir)
                        settings_path = _seed_settings(home, enabled=seeded)
                        result = _run_posix_script(
                            home,
                            settings_path,
                            codespaces=codespaces,
                            devcontainer=devcontainer,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        settings = json.loads(settings_path.read_text(encoding="utf-8"))
                        self.assertIs(settings["sandbox"]["enabled"], expected)
                        self.assertEqual(
                            stat.S_IMODE(settings_path.stat().st_mode),
                            0o600,
                        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_preserves_or_defaults_enabled(self) -> None:
        for case_name, seeded, expected in VALID_ENABLED_CASES:
            with self.subTest(case=case_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    settings_path = _seed_settings(home, enabled=seeded)
                    result = _run_powershell_script(home, settings_path)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    settings = json.loads(
                        settings_path.read_text(encoding="utf-8-sig")
                    )
                    self.assertIs(settings["sandbox"]["enabled"], expected)

    @unittest.skipIf(os.name == "nt", "POSIX script executes in Linux/macOS CI")
    @unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "bash and jq are required")
    def test_posix_rejects_non_boolean_enabled(self) -> None:
        for environment, codespaces, devcontainer, _ in POSIX_ENVIRONMENT_CASES:
            for case_name, seeded in INVALID_ENABLED_CASES:
                with self.subTest(environment=environment, case=case_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        home = pathlib.Path(temp_dir)
                        settings_path = _seed_settings(home, enabled=seeded)
                        original = settings_path.read_text(encoding="utf-8")
                        result = _run_posix_script(
                            home,
                            settings_path,
                            codespaces=codespaces,
                            devcontainer=devcontainer,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("non-boolean", result.stderr)
                        self.assertIn("sandbox.enabled", result.stderr)
                        self.assertEqual(
                            settings_path.read_text(encoding="utf-8"), original
                        )

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_rejects_non_boolean_enabled(self) -> None:
        for case_name, seeded in INVALID_ENABLED_CASES:
            with self.subTest(case=case_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    home = pathlib.Path(temp_dir)
                    settings_path = _seed_settings(home, enabled=seeded)
                    original = settings_path.read_text(encoding="utf-8")
                    result = _run_powershell_script(home, settings_path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("non-boolean", result.stderr)
                    self.assertIn("sandbox.enabled", result.stderr)
                    self.assertEqual(
                        settings_path.read_text(encoding="utf-8"), original
                    )


if __name__ == "__main__":
    unittest.main()
