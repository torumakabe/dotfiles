"""Verify user-facing shell features remain classified across platforms."""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ZSHRC_PATH = REPO_ROOT / "home/dot_zshrc.tmpl"
POWERSHELL_PROFILE_PATH = REPO_ROOT / "home/PowerShell_profile.ps1.tmpl"
INSTALL_SH_PATH = REPO_ROOT / "home/run_once_after_30-install-tools.sh.tmpl"
INSTALL_PS1_PATH = REPO_ROOT / "home/run_once_after_30-install-tools.ps1.tmpl"
MISE_CONFIG_PATH = REPO_ROOT / "home/dot_config/mise/config.toml.tmpl"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/test-copilot-hooks.yml"
POSIX_RC_TEMPLATE_PATHS = tuple(
    REPO_ROOT / "home" / name
    for name in (
        "dot_profile.tmpl",
        "dot_zprofile.tmpl",
        "dot_zshenv.tmpl",
        "dot_bash_profile.tmpl",
        "dot_bashrc.tmpl",
        "dot_zshrc.tmpl",
    )
)

PLATFORMS = frozenset(
    {
        "windows-powershell",
        "macos-zsh",
        "linux-zsh",
        "wsl-zsh",
    }
)
ZSH_PLATFORMS = PLATFORMS - {"windows-powershell"}
GH_STACK_COMPONENT_PATHS = {
    "skill:gh-stack": {
        **{
            platform: REPO_ROOT / "home/run_after_31-install-gh-stack.sh.tmpl"
            for platform in ZSH_PLATFORMS
        },
        "windows-powershell": REPO_ROOT
        / "home/run_after_31-install-gh-stack.ps1.tmpl",
    },
    "tool:gh-stack-extension": {
        **{
            platform: REPO_ROOT
            / "home/run_after_31-install-gh-stack.sh.tmpl"
            for platform in ZSH_PLATFORMS
        },
        "windows-powershell": REPO_ROOT
        / "home/run_after_31-install-gh-stack.ps1.tmpl",
    },
}


def _implemented_everywhere() -> dict[str, str]:
    return {platform: "implemented" for platform in PLATFORMS}


def _windows_only(reason: str) -> dict[str, str]:
    return {
        platform: "implemented" if platform == "windows-powershell" else reason
        for platform in PLATFORMS
    }


def _zsh_only(reason: str) -> dict[str, str]:
    return {
        platform: "implemented" if platform in ZSH_PLATFORMS else reason
        for platform in PLATFORMS
    }


def _linux_only(reason: str) -> dict[str, str]:
    return {
        platform: (
            "implemented" if platform in {"linux-zsh", "wsl-zsh"} else reason
        )
        for platform in PLATFORMS
    }


PLATFORM_CONTRACT = {
    "shell:edit-shortcut": _windows_only(
        "exception: docs/architecture.md platform exception rationale"
    ),
    "shell:ghcd": _implemented_everywhere(),
    "shell:git-hooks-audit": _implemented_everywhere(),
    "shell:mise-self-upgrade": _windows_only(
        "exception: docs/operations.md platform exception rationale"
    ),
    "shell:mise-upgrade": _implemented_everywhere(),
    "shell:kubectl-shortcut": _implemented_everywhere(),
    "shell:ll": _implemented_everywhere(),
    "shell:copilot-guardrails": _implemented_everywhere(),
    "shell:zoxide": _implemented_everywhere(),
    "feature:copilot-local-sandbox": _implemented_everywhere(),
    "skill:gh-stack": _implemented_everywhere(),
    "completion:azure-cli": _implemented_everywhere(),
    "completion:kubectl": _implemented_everywhere(),
    "completion:helm": _implemented_everywhere(),
    "completion:gh": _implemented_everywhere(),
    "completion:azd": _implemented_everywhere(),
    "completion:trivy": _implemented_everywhere(),
    "completion:terraform": _zsh_only(
        "exception: docs/architecture.md platform exception rationale"
    ),
    "completion:rad": _zsh_only(
        "exception: docs/architecture.md platform exception rationale"
    ),
    "tool:fieldalignment": _implemented_everywhere(),
    "tool:fast": _implemented_everywhere(),
    "tool:gh-stack-extension": _implemented_everywhere(),
    "tool:lefthook": _implemented_everywhere(),
    "tool:bubblewrap": _linux_only(
        "exception: docs/architecture.md platform exception rationale"
    ),
    "tool:ty": _implemented_everywhere(),
}

ZSH_INTERNAL_FUNCTIONS = {
    "_cached_source",
    "_completion_cache_clear",
    "_mise_normalize_log_line",
    "_mise_is_allowed_warning",
    "_mise_check_warnings",
    "_mise_restore_lockfile",
}
POWERSHELL_INTERNAL_FUNCTIONS = {
    "Get-CachedSourcePath",
    "Clear-CompletionCache",
}

ZSH_PUBLIC_SYMBOLS = {
    ("function", "ghcd"): "shell:ghcd",
    ("function", "git-hooks-audit"): "shell:git-hooks-audit",
    ("function", "mise-upgrade"): "shell:mise-upgrade",
    ("alias", "k"): "shell:kubectl-shortcut",
    ("alias", "ll"): "shell:ll",
    ("alias", "copilot-guardrails"): "shell:copilot-guardrails",
    ("alias", "z"): "shell:zoxide",
    ("alias", "zi"): "shell:zoxide",
}
POWERSHELL_PUBLIC_SYMBOLS = {
    ("function", "Open-EditInNewConsole"): "shell:edit-shortcut",
    ("function", "zi"): "shell:zoxide",
    ("function", "ghcd"): "shell:ghcd",
    ("function", "ll"): "shell:ll",
    ("function", "Invoke-MiseSelfUpgrade"): "shell:mise-self-upgrade",
    ("function", "Invoke-MiseUpgrade"): "shell:mise-upgrade",
    ("function", "Invoke-GitHooksAudit"): "shell:git-hooks-audit",
    ("function", "Invoke-CopilotGuardrails"): "shell:copilot-guardrails",
    ("alias", "e"): "shell:edit-shortcut",
    ("alias", "k"): "shell:kubectl-shortcut",
    ("alias", "mise-self-upgrade"): "shell:mise-self-upgrade",
    ("alias", "mise-upgrade"): "shell:mise-upgrade",
    ("alias", "git-hooks-audit"): "shell:git-hooks-audit",
    ("alias", "copilot-guardrails"): "shell:copilot-guardrails",
    ("alias", "z"): "shell:zoxide",
}

SHELL_ANCHORS = {
    "shell:edit-shortcut": {"powershell": "function Open-EditInNewConsole {"},
    "shell:ghcd": {"zsh": "function ghcd() {", "powershell": "function ghcd {"},
    "shell:git-hooks-audit": {
        "zsh": "git-hooks-audit() {",
        "powershell": "function Invoke-GitHooksAudit {",
    },
    "shell:mise-self-upgrade": {"powershell": "function Invoke-MiseSelfUpgrade {"},
    "shell:mise-upgrade": {
        "zsh": "mise-upgrade() {",
        "powershell": "function Invoke-MiseUpgrade {",
    },
    "shell:kubectl-shortcut": {
        "zsh": "alias k=kubectl",
        "powershell": "Set-Alias -Name k -Value kubectl",
    },
    "shell:ll": {"zsh": "alias ll=", "powershell": "function ll {"},
    "shell:copilot-guardrails": {
        "zsh": "alias copilot-guardrails=",
        "powershell": "Set-Alias -Name copilot-guardrails",
    },
    "shell:zoxide": {
        "zsh": "_cached_source zoxide",
        "powershell": "zoxide init powershell --cmd cd",
    },
    "completion:azure-cli": {
        "zsh": "bash_completion.d/azure-cli",
        "powershell": "Register-ArgumentCompleter -Native -CommandName az",
    },
    "completion:kubectl": {
        "zsh": "_cached_source kubectl",
        "powershell": "Get-CachedSourcePath -Name kubectl",
    },
    "completion:helm": {
        "zsh": "_cached_source helm",
        "powershell": "Get-CachedSourcePath -Name helm",
    },
    "completion:gh": {
        "zsh": "_cached_source gh",
        "powershell": "Get-CachedSourcePath -Name gh",
    },
    "completion:azd": {
        "zsh": "_cached_source azd",
        "powershell": "Get-CachedSourcePath -Name azd",
    },
    "completion:trivy": {
        "zsh": "_cached_source trivy",
        "powershell": "Get-CachedSourcePath -Name trivy",
    },
    "completion:terraform": {"zsh": "complete -o nospace -C"},
    "completion:rad": {"zsh": "_cached_source rad"},
}

TOOL_ANCHORS = {
    "tool:fieldalignment": "golang.org/x/tools/go/analysis/passes/fieldalignment/cmd/fieldalignment@latest",
    "tool:fast": "github.com/ddo/fast@latest",
    "tool:ty": "uv tool install --quiet ty",
}

SOURCE_INITIALIZERS = {
    "zoxide": "shell:zoxide",
    "kubectl": "completion:kubectl",
    "helm": "completion:helm",
    "rad": "completion:rad",
    "gh": "completion:gh",
    "azd": "completion:azd",
    "trivy": "completion:trivy",
}

EXCEPTION_DOCUMENT_IDENTIFIERS = {
    "shell:edit-shortcut": ("Microsoft Edit",),
    "shell:mise-self-upgrade": ("mise-self-upgrade",),
    "completion:terraform": ("Terraform", "PowerShell completion"),
    "completion:rad": ("Radicle", "Windows"),
    "tool:bubblewrap": ("bubblewrap", "Seatbelt", "ProcessContainer"),
}


def _zsh_symbols(source: str) -> set[tuple[str, str]]:
    functions = set(
        re.findall(
            r"(?m)^(?:function\s+)?([A-Za-z_][A-Za-z0-9_-]*)\(\)\s*\{",
            source,
        )
    )
    aliases = set(re.findall(r"(?m)^alias\s+([A-Za-z0-9_-]+)=", source))
    return {("function", name) for name in functions - ZSH_INTERNAL_FUNCTIONS} | {
        ("alias", name) for name in aliases
    }


def _powershell_symbols(source: str) -> set[tuple[str, str]]:
    functions = set(
        re.findall(r"(?m)^function\s+([A-Za-z][A-Za-z0-9-]*)\b", source)
    )
    aliases = set(
        re.findall(r"(?m)^Set-Alias\s+-Name\s+([A-Za-z0-9-]+)\b", source)
    )
    return {
        ("function", name) for name in functions - POWERSHELL_INTERNAL_FUNCTIONS
    } | {("alias", name) for name in aliases}


def _cached_source_names(source: str) -> set[str]:
    return set(re.findall(r"(?m)^\s*_cached_source\s+([A-Za-z0-9_-]+)\b", source))


def _powershell_cached_source_names(source: str) -> set[str]:
    return set(
        re.findall(
            r"(?m)^\s*\$\w+\s*=\s*Get-CachedSourcePath\s+-Name\s+([A-Za-z0-9_-]+)\b",
            source,
        )
    )


def _installed_tools(source: str) -> set[str]:
    go_tools = re.findall(
        r"(?m)^\s*(?:if\s+!\s+)?go install\s+(\S+@latest)\b",
        source,
    )
    uv_tools = re.findall(
        r"(?m)^\s*(?:if\s+!\s+)?uv tool install --quiet\s+(\S+)\b",
        source,
    )
    return set(go_tools) | {f"uv tool install --quiet {tool}" for tool in uv_tools}


def _powershell_completion_section(profile: str) -> str:
    start = profile.index("function Get-CachedSourcePath {")
    last_call = (
        "$zoxideCompletionPath = Get-CachedSourcePath -Name zoxide "
        "-Command zoxide -Generator { zoxide init powershell --cmd cd }"
    )
    end = profile.index(last_call, start) + len(last_call)
    dot_source = "if ($zoxideCompletionPath) { . $zoxideCompletionPath }"
    end = profile.index(dot_source, end) + len(dot_source)
    return profile[start:end]


class PlatformParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.zshrc = ZSHRC_PATH.read_text(encoding="utf-8")
        cls.powershell = POWERSHELL_PROFILE_PATH.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_every_feature_accounts_for_every_platform(self) -> None:
        for feature, coverage in PLATFORM_CONTRACT.items():
            with self.subTest(feature=feature):
                self.assertEqual(set(coverage), PLATFORMS)
                for status in coverage.values():
                    self.assertTrue(
                        status == "implemented" or status.startswith("exception: docs/"),
                        status,
                    )

    def test_gh_stack_contract_components_exist_for_each_platform(self) -> None:
        for feature, paths in GH_STACK_COMPONENT_PATHS.items():
            self.assertEqual(set(paths), PLATFORMS)
            for platform, path in paths.items():
                with self.subTest(feature=feature, platform=platform):
                    self.assertEqual(
                        PLATFORM_CONTRACT[feature][platform],
                        "implemented",
                    )
                    self.assertTrue(path.is_file(), path)

                    source = path.read_text(encoding="utf-8")
                    if feature == "skill:gh-stack":
                        self.assertIn(
                            "--agent github-copilot --scope user",
                            source,
                        )
                    else:
                        self.assertIn(
                            "gh extension install github/gh-stack",
                            source,
                        )

    def test_exceptions_reference_relevant_existing_documentation(self) -> None:
        checked_features = set()
        for feature, coverage in PLATFORM_CONTRACT.items():
            for platform, status in coverage.items():
                if status == "implemented":
                    continue
                with self.subTest(feature=feature, platform=platform):
                    match = re.fullmatch(r"exception:\s+(docs/\S+)\s+(.+)", status)
                    self.assertIsNotNone(match, status)
                    document_path, reason = match.groups()
                    self.assertTrue(reason.strip(), status)
                    document = REPO_ROOT / document_path
                    self.assertTrue(document.is_file(), document_path)
                    for identifier in EXCEPTION_DOCUMENT_IDENTIFIERS.get(feature, ()):
                        self.assertIn(
                            identifier,
                            document.read_text(encoding="utf-8"),
                            f"{feature}: {document_path} lacks {identifier!r}",
                        )
                checked_features.add(feature)
        self.assertEqual(checked_features, set(EXCEPTION_DOCUMENT_IDENTIFIERS))

    def test_all_public_shell_symbols_are_classified(self) -> None:
        self.assertEqual(_zsh_symbols(self.zshrc), set(ZSH_PUBLIC_SYMBOLS))
        self.assertEqual(
            _powershell_symbols(self.powershell),
            set(POWERSHELL_PUBLIC_SYMBOLS),
        )
        for feature in set(ZSH_PUBLIC_SYMBOLS.values()) | set(
            POWERSHELL_PUBLIC_SYMBOLS.values()
        ):
            self.assertIn(feature, PLATFORM_CONTRACT)

    def test_declared_shell_implementations_exist(self) -> None:
        for feature, anchors in SHELL_ANCHORS.items():
            coverage = PLATFORM_CONTRACT[feature]
            if any(coverage[platform] == "implemented" for platform in ZSH_PLATFORMS):
                with self.subTest(feature=feature, shell="zsh"):
                    self.assertIn(anchors["zsh"], self.zshrc)
            if coverage["windows-powershell"] == "implemented":
                with self.subTest(feature=feature, shell="powershell"):
                    self.assertIn(anchors["powershell"], self.powershell)

    def test_cached_source_initializers_are_fully_classified(self) -> None:
        expected_zsh_names = {
            name
            for name, feature in SOURCE_INITIALIZERS.items()
            if any(
                PLATFORM_CONTRACT[feature][platform] == "implemented"
                for platform in ZSH_PLATFORMS
            )
        }
        expected_powershell_names = {
            name
            for name, feature in SOURCE_INITIALIZERS.items()
            if PLATFORM_CONTRACT[feature]["windows-powershell"] == "implemented"
        }
        zsh_names = _cached_source_names(self.zshrc)
        powershell_names = _powershell_cached_source_names(self.powershell)

        self.assertEqual(zsh_names, expected_zsh_names)
        self.assertEqual(powershell_names, expected_powershell_names)
        for name, feature in SOURCE_INITIALIZERS.items():
            with self.subTest(name=name, feature=feature):
                self.assertIn(feature, PLATFORM_CONTRACT)
                if feature.startswith("completion:"):
                    self.assertEqual(feature, f"completion:{name}")
                else:
                    self.assertEqual((name, feature), ("zoxide", "shell:zoxide"))

    def test_cross_platform_tools_are_installed_by_both_scripts(self) -> None:
        shell_installer = INSTALL_SH_PATH.read_text(encoding="utf-8")
        powershell_installer = INSTALL_PS1_PATH.read_text(encoding="utf-8")
        expected_tools = set(TOOL_ANCHORS.values())

        self.assertEqual(_installed_tools(shell_installer), expected_tools)
        self.assertEqual(_installed_tools(powershell_installer), expected_tools)
        self.assertEqual(
            _installed_tools(shell_installer),
            _installed_tools(powershell_installer),
        )
        for feature in TOOL_ANCHORS:
            with self.subTest(feature=feature):
                self.assertIn(feature, PLATFORM_CONTRACT)

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
    def test_lefthook_is_managed_by_mise_on_every_platform(self) -> None:
        platform_data = {
            "windows-powershell": {"os": "windows", "arch": "amd64"},
            "macos-zsh": {"os": "darwin", "arch": "arm64"},
            "linux-zsh": {"os": "linux", "arch": "amd64"},
            "wsl-zsh": {"os": "linux", "arch": "amd64"},
        }

        for platform, chezmoi_data in platform_data.items():
            with self.subTest(platform=platform):
                result = subprocess.run(
                    [
                        "chezmoi",
                        "execute-template",
                        "--override-data",
                        json.dumps({"chezmoi": chezmoi_data}),
                        "--file",
                        str(MISE_CONFIG_PATH),
                    ],
                    check=False,
                    capture_output=True,
                    encoding="utf-8",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                config = tomllib.loads(result.stdout)
                self.assertEqual(config["tools"]["lefthook"], "latest")

    def test_powershell_completion_cache_executes_generated_sources(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is required for PowerShell completion tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            test_root = pathlib.Path(temp_dir)
            bin_dir = test_root / "bin"
            bin_dir.mkdir()
            powershell_initializers = {
                name
                for name, feature in SOURCE_INITIALIZERS.items()
                if PLATFORM_CONTRACT[feature]["windows-powershell"] == "implemented"
            }
            for name in powershell_initializers:
                statements = [f"$global:TEST_SOURCED += '{name}'"]
                if name == "kubectl":
                    statements[:0] = [
                        "Register-ArgumentCompleter -Native -CommandName kubectl "
                        "-ScriptBlock {}",
                        "$global:__kubectlCompleterBlock = {}",
                    ]
                if os.name == "nt":
                    stub = bin_dir / f"{name}.cmd"
                    stub.write_text(
                        "@echo off\n"
                        + "\n".join(f"@echo {statement}" for statement in statements)
                        + "\n",
                        encoding="utf-8",
                    )
                else:
                    stub = bin_dir / name
                    stub.write_text(
                        "#!/bin/sh\n"
                        "cat <<'POWERSHELL_COMPLETION_EOF'\n"
                        + "\n".join(statements)
                        + "\nPOWERSHELL_COMPLETION_EOF\n",
                        encoding="utf-8",
                    )
                    stub.chmod(0o755)

            script_file = test_root / "test-completions.ps1"
            script_file.write_text(
                f"""
$global:TEST_SOURCED = @()
$global:TEST_REGISTERED = @()
function Register-ArgumentCompleter {{
    param(
        [switch]$Native,
        [string[]]$CommandName,
        [scriptblock]$ScriptBlock
    )
    $global:TEST_REGISTERED += $CommandName
}}

{_powershell_completion_section(self.powershell)}

$result = @{{
    sourced = @($global:TEST_SOURCED)
    registered = @($global:TEST_REGISTERED)
}}
"RESULT_JSON=$($result | ConvertTo-Json -Compress)"
""",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "HOME": temp_dir,
                    "USERPROFILE": temp_dir,
                    "LOCALAPPDATA": str(test_root / "local-app-data"),
                    "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
                    "TEMP": temp_dir,
                    "TMP": temp_dir,
                }
            )
            result = subprocess.run(
                [pwsh, "-NoProfile", "-NonInteractive", "-File", str(script_file)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
            )
            match = re.search(r"(?m)^RESULT_JSON=(.+)$", result.stdout)
            self.assertIsNotNone(
                match,
                f"PowerShell result marker missing\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
            state = json.loads(match.group(1))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(set(state["sourced"]), powershell_initializers)
            self.assertEqual(set(state["registered"]), {"kubectl", "k"})

    def test_closed_azure_warning_workaround_is_removed(self) -> None:
        self.assertNotRegex(self.zshrc, r"(?m)^az\(\)\s*\{")

    def test_copilot_app_cli_path_override_is_removed(self) -> None:
        self.assertNotIn("COPILOT_CLI_PATH", self.zshrc)

    def test_ci_runs_for_home_changes_on_pull_requests_and_main_pushes(self) -> None:
        pull_request = self.workflow.split("  push:", maxsplit=1)[0]
        push = self.workflow.split("  push:", maxsplit=1)[1].split(
            "  schedule:", maxsplit=1
        )[0]
        self.assertIn("- 'home/**'", pull_request)
        self.assertIn("- 'home/**'", push)

    def test_ci_installs_and_requires_both_shells_before_unittest(self) -> None:
        install = "sudo apt-get install --yes zsh"
        zsh_check = "command -v zsh"
        pwsh_check = "command -v pwsh"
        unittest_discover = "uv run -m unittest discover -s tests -v"
        for command in (install, zsh_check, pwsh_check, unittest_discover):
            with self.subTest(command=command):
                self.assertIn(command, self.workflow)
        unittest_position = self.workflow.index(unittest_discover)
        for prerequisite in (install, zsh_check, pwsh_check):
            with self.subTest(prerequisite=prerequisite):
                self.assertLess(self.workflow.index(prerequisite), unittest_position)

    def test_ci_installs_chezmoi_before_unittest(self) -> None:
        """Without chezmoi the tests that render templates skip instead of failing."""
        install = "CHEZMOI_INSTALL_ONLY=1 ./install.sh"
        check = "chezmoi --version"
        unittest_discover = "uv run -m unittest discover -s tests -v"
        unittest_position = self.workflow.index(unittest_discover)
        for prerequisite in (install, check):
            with self.subTest(prerequisite=prerequisite):
                self.assertIn(prerequisite, self.workflow)
                self.assertLess(self.workflow.index(prerequisite), unittest_position)


class WrapperGateParityTests(unittest.TestCase):
    """ADR-012 の wrapper は参照側と配布側で同じ条件を使う必要がある。

    条件が食い違うと ``gpg.ssh.program`` が存在しないファイルを指し、署名が
    失敗する。条件は ``home/.chezmoi.toml.tmpl`` の data に置けないため
    （``chezmoi init`` 時にしか評価されず環境の変化へ追従しない）、2 つの
    テンプレートへ重複して書いている。その重複が崩れていないことを検査する。
    """

    PREDICATE = (
        'and .isWSL (stat "/proc/sys/fs/binfmt_misc/WSLInterop") '
        '(ne .windowsUser "")'
    )

    def setUp(self) -> None:
        self.gitconfig = (REPO_ROOT / "home/dot_gitconfig-linux.tmpl").read_text(
            encoding="utf-8"
        )
        self.ignore = (REPO_ROOT / "home/.chezmoiignore").read_text(encoding="utf-8")
        self.wrapper = (
            REPO_ROOT / "home/dot_local/bin/executable_op-ssh-sign-wrapper.sh.tmpl"
        ).read_text(encoding="utf-8")

    def test_gitconfig_selects_wrapper_with_the_shared_predicate(self) -> None:
        self.assertIn("{{- if " + self.PREDICATE + " -}}", self.gitconfig)

    def test_chezmoiignore_excludes_wrapper_with_the_negated_predicate(self) -> None:
        self.assertIn("{{ if not (" + self.PREDICATE + ") -}}", self.ignore)
        self.assertIn(".local/bin/op-ssh-sign-wrapper.sh", self.ignore)

    def test_wrapper_depends_on_windows_user(self) -> None:
        self.assertIn("{{ .windowsUser }}", self.wrapper)


class WindowsPosixRcManagementTests(unittest.TestCase):
    WINDOWS_IGNORED_RCS = {
        ".profile",
        ".zprofile",
        ".zshenv",
        ".bash_profile",
        ".bashrc",
    }

    def test_windows_ignores_every_posix_rc_except_zshrc(self) -> None:
        ignore = (REPO_ROOT / "home/.chezmoiignore").read_text(encoding="utf-8")
        start = ignore.index('{{ if eq .chezmoi.os "windows" -}}')
        block = ignore[start:].split("{{ end -}}", maxsplit=1)[0]
        ignored = {
            line
            for line in block.splitlines()
            if line.startswith(".") and not line.startswith("..")
        }

        self.assertEqual(ignored, self.WINDOWS_IGNORED_RCS)
        self.assertNotIn(".zshrc", ignored)

    def test_posix_rc_templates_keep_content_inside_windows_guard(self) -> None:
        guard = '{{ if ne .chezmoi.os "windows" -}}'
        for path in POSIX_RC_TEMPLATE_PATHS:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                source_without_template_comments = re.sub(
                    r"{{-?\s*/\*.*?\*/\s*-?}}",
                    "",
                    source,
                    flags=re.DOTALL,
                ).strip()
                self.assertTrue(source_without_template_comments.startswith(guard))
                self.assertTrue(source_without_template_comments.endswith("{{ end -}}"))

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
    def test_posix_rc_templates_render_empty_on_windows(self) -> None:
        override = json.dumps({"chezmoi": {"os": "windows"}})
        for path in POSIX_RC_TEMPLATE_PATHS:
            with self.subTest(path=path.name):
                result = subprocess.run(
                    [
                        "chezmoi",
                        "execute-template",
                        "--override-data",
                        override,
                        "--file",
                        str(path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
