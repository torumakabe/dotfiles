"""Windows P1 ランタイムの導入と PATH 契約を検証する。

PowerShell テンプレートだけをレンダリングし、動的検証では一時 HOME 配下の
モックだけを使う。SDK のダウンロードや実行は行わない。
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from tests.chezmoi_test_helpers import execute_template


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "home"
USER_PATH_PS1 = SOURCE_ROOT / "run_once_after_05-setup-user-path.ps1.tmpl"
INSTALL_TOOLS_PS1 = SOURCE_ROOT / "run_once_after_30-install-tools.ps1.tmpl"

GO_PS1 = SOURCE_ROOT / "run_after_15-install-go.ps1.tmpl"
NODE_PS1 = SOURCE_ROOT / "run_after_16-install-node.ps1.tmpl"
DOTNET_PS1 = SOURCE_ROOT / "run_after_17-install-dotnet.ps1.tmpl"
BUN_PS1 = SOURCE_ROOT / "run_after_18-install-bun.ps1.tmpl"
PNPM_PS1 = SOURCE_ROOT / "run_after_19-install-pnpm.ps1.tmpl"
TS_CLI_PS1 = SOURCE_ROOT / "run_after_21-install-typescript-cli.ps1.tmpl"
TS_LSP_PS1 = SOURCE_ROOT / "run_after_22-install-typescript-lsp.ps1.tmpl"
TSLS_PS1 = SOURCE_ROOT / "run_after_23-install-typescript-language-server.ps1.tmpl"

WINDOWS_RUNTIME_SCRIPTS = (
    GO_PS1,
    NODE_PS1,
    DOTNET_PS1,
    BUN_PS1,
    PNPM_PS1,
    TS_CLI_PS1,
    TS_LSP_PS1,
    TSLS_PS1,
)
LOCK_GUARD_SCRIPTS = (
    GO_PS1,
    NODE_PS1,
    DOTNET_PS1,
    BUN_PS1,
    PNPM_PS1,
    TS_CLI_PS1,
    TS_LSP_PS1,
    TSLS_PS1,
)
EXPECTED_PATH_VARIABLES = (
    "$localBinDir",
    "$goBinDir",
    "$nodeRootDir",
    "$dotnetRootDir",
    "$pnpmRootDir",
    "$typescriptCliBinDir",
    "$typescriptLspBinDir",
    "$typescriptLanguageServerBinDir",
    "$shimsDir",
)


def _render(path: pathlib.Path) -> str:
    override = {
        "chezmoi": {"os": "windows", "arch": "amd64"},
        "codespaces": False,
        "devcontainer": False,
        "isWSL": False,
        "windowsUser": "",
        "corpUser": "",
    }
    result = execute_template(path, override, SOURCE_ROOT)
    if result.returncode != 0:
        raise AssertionError(f"{path.name} failed to render: {result.stderr}")
    return result.stdout


def _extract_marked_block(source: str, marker: str) -> str:
    start = f"# >>> {marker}:"
    end = f"# <<< {marker}"
    return source[source.index(start) : source.index(end) + len(end)]


def _extract_function(source: str, name: str) -> str:
    match = re.search(rf"(?m)^function {re.escape(name)}\s*\{{", source)
    if match is None:
        raise AssertionError(f"function {name} not found")

    depth = 0
    for index in range(match.start(), len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"function {name} is not balanced")


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class WindowsRuntimeStaticContractTests(unittest.TestCase):
    def test_user_and_process_path_use_all_fixed_roots_in_order(self) -> None:
        source = USER_PATH_PS1.read_text(encoding="utf-8")
        leading = re.search(
            r"(?ms)^\$leadingEntries = @\(\n(?P<body>.*?)^\)",
            source,
        )
        self.assertIsNotNone(leading)
        variables = tuple(
            line.strip().rstrip(",")
            for line in leading.group("body").splitlines()
            if line.strip()
        )

        self.assertEqual(variables, EXPECTED_PATH_VARIABLES)
        self.assertIn(
            "[Environment]::SetEnvironmentVariable('Path', $newPath, 'User')",
            source,
        )
        self.assertIn(
            "$env:Path = (Get-OrderedPathEntries "
            "-Leading $leadingEntries -Existing $processEntries) -join ';'",
            source,
        )

    def test_path_comparison_normalizes_slashes_case_and_trailing_separator(
        self,
    ) -> None:
        source = USER_PATH_PS1.read_text(encoding="utf-8")

        self.assertIn("$Path.Replace('\\', '/')", source)
        self.assertIn(".TrimEnd('/').ToLowerInvariant()", source)
        self.assertIn("HashSet[string]", source)
        self.assertIn("foreach ($entry in @($Leading) + @($Existing))", source)

    def test_payload_roots_are_kept_intact_without_generated_proxies(self) -> None:
        expected_roots = {
            GO_PS1: "'go'",
            NODE_PS1: "'node'",
            DOTNET_PS1: "'dotnet'",
            PNPM_PS1: "'pnpm'",
            TS_CLI_PS1: "'typescript-cli'",
            TS_LSP_PS1: "'typescript-lsp'",
            TSLS_PS1: "'typescript-language-server'",
        }
        forbidden = (
            "shimPath",
            "wrapperPath",
            "proxyPath",
            "PATH fragment",
            "mise which",
            "mise.exe",
        )
        for path, root_literal in expected_roots.items():
            with self.subTest(installer=path.name):
                source = _render(path)
                self.assertIn(
                    "$shareDir = Join-Path $HOME "
                    "'.local\\share\\chezmoi-dotfiles'",
                    source,
                )
                self.assertIn(f"$finalRoot = Join-Path $shareDir {root_literal}", source)
                for token in forbidden:
                    self.assertNotIn(token, source)

        bun_source = _render(BUN_PS1)
        self.assertIn("$binDir = Join-Path $HOME '.local\\bin'", bun_source)
        self.assertIn("$targetBun = Join-Path $binDir 'bun.exe'", bun_source)
        self.assertIn("$targetBunx = Join-Path $binDir 'bunx.exe'", bun_source)

    def test_node_consumers_use_absolute_direct_install_prerequisites(self) -> None:
        for path in (TS_CLI_PS1, TS_LSP_PS1, TSLS_PS1):
            with self.subTest(installer=path.name):
                source = _render(path)
                self.assertIn("$nodeExe = Join-Path $nodeRoot 'node.exe'", source)
                self.assertIn("$npmCmd = Join-Path $nodeRoot 'npm.cmd'", source)
                self.assertIn("& $npmCmd install --prefix", source)
                self.assertNotIn("Get-Command node", source)
                self.assertNotIn("Get-Command npm", source)

    def test_go_version_probe_cannot_switch_or_download_toolchains(self) -> None:
        source = _render(GO_PS1)
        function = _extract_function(source, "Get-InstalledGoVersion")

        self.assertIn("$env:GOTOOLCHAIN = 'local'", function)
        self.assertIn("$env:GOWORK = 'off'", function)
        self.assertIn("Set-Location -LiteralPath $probeDir", function)
        self.assertIn("$env:GOTOOLCHAIN = $previousGoToolchain", function)
        self.assertIn("$env:GOWORK = $previousGoWork", function)
        self.assertIn("Set-Location -LiteralPath $previousLocation", function)
        self.assertIn(
            "Remove-Item -LiteralPath $probeDir -Recurse -Force "
            "-ErrorAction SilentlyContinue",
            function,
        )
        self.assertNotIn("[Environment]::SetEnvironmentVariable", function)
        self.assertIn(
            "Get-InstalledGoVersion -Path $entrypoint",
            source,
        )
        self.assertIn(
            "Get-InstalledGoVersion -Path $stagedEntrypoint",
            source,
        )

    def test_pnpm_version_probe_cannot_switch_or_download_project_pnpm(self) -> None:
        source = _render(PNPM_PS1)
        function = _extract_function(source, "Get-InstalledPnpmVersion")

        self.assertIn("$env:PNPM_CONFIG_PM_ON_FAIL = 'ignore'", function)
        self.assertIn("Set-Location -LiteralPath $probeDir", function)
        self.assertIn(
            "$env:PNPM_CONFIG_PM_ON_FAIL = $previousPmOnFail",
            function,
        )
        self.assertIn("Set-Location -LiteralPath $previousLocation", function)
        self.assertIn(
            "Remove-Item -LiteralPath $probeDir -Recurse -Force "
            "-ErrorAction SilentlyContinue",
            function,
        )
        self.assertNotIn("managePackageManagerVersions", function)
        self.assertNotIn("[Environment]::SetEnvironmentVariable", function)
        self.assertIn("Get-InstalledPnpmVersion -Path $entrypoint", source)
        self.assertIn("Get-InstalledPnpmVersion -Path $stagedEntrypoint", source)

    def test_dotnet_preserves_the_vendor_dnx_entrypoint(self) -> None:
        source = _render(DOTNET_PS1)

        self.assertIn("$dnx = Join-Path $Root 'dnx.cmd'", source)
        self.assertIn("(Test-Path -LiteralPath $dnx -PathType Leaf)", source)
        self.assertIn("Test-DotnetSdkPresent -Root $finalRoot", source)
        self.assertIn("Test-DotnetSdkPresent -Root $extractedRoot", source)
        self.assertIn("Assert-BinaryReplaceable -Path $dnxEntrypoint", source)

    def test_payload_completeness_requires_files_not_same_named_directories(
        self,
    ) -> None:
        for path in WINDOWS_RUNTIME_SCRIPTS:
            with self.subTest(installer=path.name):
                source = _render(path)
                for line in source.splitlines():
                    if "Test-Path -LiteralPath" not in line:
                        continue
                    if any(
                        name in line
                        for name in (
                            "$gofmt",
                            "$compile",
                            "$npmCmd",
                            "$npxCmd",
                            "$npmCli",
                            "$npxCli",
                            "$npmPkg",
                            "$BunPath",
                            "$BunxPath",
                            "pnpm.mjs",
                            "worker.js",
                            "$binPath",
                            "$stagedBinPath",
                            "$stagedTsserverPath",
                        )
                    ):
                        self.assertIn("-PathType Leaf", line, line)

    def test_dedicated_typescript_runtime_exposes_and_validates_tsserver(self) -> None:
        source = _render(TS_LSP_PS1)

        self.assertIn(
            "$binPath = Join-Path $finalRoot "
            "'node_modules\\.bin\\tsserver.cmd'",
            source,
        )
        self.assertIn(
            "(Test-Path -LiteralPath $binPath -PathType Leaf)",
            source,
        )
        self.assertIn(
            "$stagedBinPath = Join-Path $stagedRoot "
            "'node_modules\\.bin\\tsserver.cmd'",
            source,
        )
        self.assertIn(
            "-not (Test-Path -LiteralPath $stagedBinPath -PathType Leaf)",
            source,
        )
        self.assertIn("Assert-BinaryReplaceable -Path $binPath", source)

    def test_typescript_cli_and_language_server_probe_vendor_launchers(self) -> None:
        cases = (
            (
                TS_CLI_PS1,
                "Get-TypeScriptCliVersion",
                "$binPath",
                "$stagedBinPath",
            ),
            (
                TSLS_PS1,
                "Get-TslsLauncherVersion",
                "$binPath",
                "$stagedBinPath",
            ),
        )
        for path, function_name, installed_path, staged_path in cases:
            with self.subTest(installer=path.name):
                source = _render(path)
                function = _extract_function(source, function_name)
                self.assertIn("& $LauncherPath --version", function)
                self.assertIn(
                    '$env:Path = if ($previousPath) { "$nodeRoot;$previousPath" }',
                    function,
                )
                self.assertIn("$env:Path = $previousPath", function)
                self.assertIn(
                    f"{function_name} -LauncherPath {installed_path}",
                    source,
                )
                self.assertIn(
                    f"{function_name} -LauncherPath {staged_path}",
                    source,
                )

    def test_failure_paths_preserve_or_restore_existing_roots(self) -> None:
        for path in LOCK_GUARD_SCRIPTS:
            with self.subTest(installer=path.name):
                source = _render(path)
                self.assertIn("function Assert-BinaryReplaceable", source)
                self.assertIn("Assert-BinaryReplaceable -Path", source)

        for path in LOCK_GUARD_SCRIPTS:
            if path == BUN_PS1:
                continue
            with self.subTest(rollback=path.name):
                source = _render(path)
                self.assertRegex(source, r"previous-[a-z-]+")
                self.assertIn("Move-Item -LiteralPath $backupRoot", source)
                self.assertIn("$cleanupStageDir = $false", source)

        bun_source = _render(BUN_PS1)
        self.assertIn("$backupBun", bun_source)
        self.assertIn("$backupBunx", bun_source)
        self.assertIn("Move-Item -LiteralPath $backupBun", bun_source)
        self.assertIn("Move-Item -LiteralPath $backupBunx", bun_source)

    def test_followup_tool_installer_uses_absolute_go_and_uv_paths(self) -> None:
        source = INSTALL_TOOLS_PS1.read_text(encoding="utf-8")

        self.assertIn(
            "$goExe = Join-Path $HOME "
            "'.local\\share\\chezmoi-dotfiles\\go\\bin\\go.exe'",
            source,
        )
        self.assertIn("$uvExe = Join-Path $localBinDir 'uv.exe'", source)
        self.assertIn("& $goExe install", source)
        self.assertIn("& $uvExe tool install", source)
        self.assertNotIn("Get-Command go", source)
        self.assertNotIn("Get-Command uv", source)


@unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class WindowsRuntimePowerShellTests(unittest.TestCase):
    def _run_pwsh(
        self, script: str, home: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        script_path = home / "contract-test.ps1"
        script_path.write_text(script, encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "LOCALAPPDATA": str(home / "AppData/Local"),
                "TEMP": str(home / "Temp"),
                "TMP": str(home / "Temp"),
            }
        )
        (home / "Temp").mkdir()
        return subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_rendered_windows_scripts_parse_without_profiles(self) -> None:
        for path in (*WINDOWS_RUNTIME_SCRIPTS, USER_PATH_PS1, INSTALL_TOOLS_PS1):
            with self.subTest(installer=path.name), tempfile.TemporaryDirectory() as temp:
                home = pathlib.Path(temp)
                rendered_path = home / path.name.removesuffix(".tmpl")
                rendered_path.write_text(_render(path), encoding="utf-8")
                command = (
                    "$tokens=$null; $errors=$null; "
                    "[System.Management.Automation.Language.Parser]::ParseFile("
                    "$args[0], [ref]$tokens, [ref]$errors) | Out-Null; "
                    "if ($errors.Count -ne 0) { "
                    "$errors | ForEach-Object { [Console]::Error.WriteLine($_) }; exit 1 }"
                )
                result = subprocess.run(
                    [
                        "pwsh",
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        command,
                        str(rendered_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_path_order_is_identical_for_user_and_process_inputs(self) -> None:
        block = _extract_marked_block(_render(USER_PATH_PS1), "user-path-normalization")
        expected = [
            r"C:\Users\x\.local\bin",
            r"C:\Users\x\.local\share\chezmoi-dotfiles\go\bin",
            r"C:\Users\x\.local\share\chezmoi-dotfiles\node",
            r"C:\Users\x\.local\share\chezmoi-dotfiles\dotnet",
            r"C:\Users\x\.local\share\chezmoi-dotfiles\pnpm",
            r"C:\Users\x\.local\share\chezmoi-dotfiles\typescript-cli\node_modules\.bin",
            r"C:\Users\x\.local\share\chezmoi-dotfiles\typescript-lsp\node_modules\.bin",
            r"C:\Users\x\.local\share\chezmoi-dotfiles\typescript-language-server\node_modules\.bin",
            r"C:\Users\x\AppData\Local\mise\shims",
            r"C:\Users\x\AppData\Local\mise\installs\node\old",
            r"C:\Windows\System32",
            r"C:\Tools",
        ]
        leading = ",\n".join(f"    '{entry}'" for entry in expected[:9])
        existing = (
            "'c:/users/x/.LOCAL/bin/', "
            "'C:/Users/x/.local/share/chezmoi-dotfiles/GO/bin/', "
            "'C:\\Users\\x\\AppData\\Local\\mise\\installs\\node\\old', "
            "'C:\\Windows\\System32', "
            "'c:/users/x/appdata/local/MISE/shims/', "
            "'C:\\Windows\\System32\\', "
            "'C:\\Tools'"
        )
        script = (
            f"{block}\n"
            f"$leading = @(\n{leading}\n)\n"
            f"$existing = @({existing})\n"
            "$userResult = @(Get-OrderedPathEntries -Leading $leading -Existing $existing)\n"
            "$processResult = @(Get-OrderedPathEntries -Leading $leading -Existing $existing)\n"
            "@{ user = $userResult; process = $processResult } | ConvertTo-Json -Compress\n"
        )
        with tempfile.TemporaryDirectory() as temp:
            result = self._run_pwsh(script, pathlib.Path(temp))

        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout.strip())
        self.assertEqual(state["user"], expected)
        self.assertEqual(state["process"], expected)

    def test_go_version_probe_uses_local_toolchain_and_restores_process_state(
        self,
    ) -> None:
        function = _extract_function(_render(GO_PS1), "Get-InstalledGoVersion")
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp)
            mock_go = home / "mock-go.ps1"
            mock_go.write_text(
                "param([string]$Verb)\n"
                "if ($Verb -ne 'version') { exit 2 }\n"
                "$state = @{\n"
                "    toolchain = $env:GOTOOLCHAIN\n"
                "    gowork = $env:GOWORK\n"
                "    cwd = (Get-Location).Path\n"
                "}\n"
                "$state | ConvertTo-Json -Compress | "
                "Set-Content -LiteralPath (Join-Path $env:HOME 'go-probe-state.json')\n"
                "Write-Output 'go version go1.27.1 windows/amd64'\n",
                encoding="utf-8",
            )
            script = (
                f"{function}\n"
                "$env:GOTOOLCHAIN = 'auto'\n"
                "$env:GOWORK = 'C:\\existing\\go.work'\n"
                "$initialLocation = (Get-Location).Path\n"
                f"$version = Get-InstalledGoVersion -Path '{mock_go}'\n"
                "$probe = Get-Content -LiteralPath "
                "(Join-Path $env:HOME 'go-probe-state.json') -Raw | ConvertFrom-Json\n"
                "$result = @{\n"
                "    version = $version\n"
                "    probeToolchain = $probe.toolchain\n"
                "    probeGoWork = $probe.gowork\n"
                "    probeCwd = $probe.cwd\n"
                "    restoredToolchain = $env:GOTOOLCHAIN\n"
                "    restoredGoWork = $env:GOWORK\n"
                "    restoredCwd = (Get-Location).Path\n"
                "    initialCwd = $initialLocation\n"
                "}\n"
                "$result | ConvertTo-Json -Compress\n"
            )
            result = self._run_pwsh(script, home)

            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(result.stdout.strip())
            self.assertEqual(state["version"], "1.27.1")
            self.assertEqual(state["probeToolchain"], "local")
            self.assertEqual(state["probeGoWork"], "off")
            self.assertNotEqual(state["probeCwd"], state["initialCwd"])
            self.assertEqual(state["restoredToolchain"], "auto")
            self.assertEqual(state["restoredGoWork"], r"C:\existing\go.work")
            self.assertEqual(state["restoredCwd"], state["initialCwd"])

    def test_typescript_launcher_probes_use_private_node_and_restore_path(
        self,
    ) -> None:
        cases = (
            (TS_CLI_PS1, "Get-TypeScriptCliVersion", "Version 7.0.2", "7.0.2"),
            (
                TSLS_PS1,
                "Get-TslsLauncherVersion",
                "6.0.0",
                "6.0.0",
            ),
        )
        for path, function_name, output, expected in cases:
            with self.subTest(installer=path.name), tempfile.TemporaryDirectory() as temp:
                home = pathlib.Path(temp)
                node_root = home / "private-node"
                node_root.mkdir()
                launcher = home / "mock-launcher.ps1"
                launcher.write_text(
                    "param([string]$Argument)\n"
                    "if ($Argument -ne '--version') { exit 2 }\n"
                    "$firstPath = ($env:Path -split ';')[0]\n"
                    "if ($firstPath -ne $env:EXPECTED_NODE_ROOT) { exit 3 }\n"
                    f"Write-Output '{output}'\n",
                    encoding="utf-8",
                )
                function = _extract_function(_render(path), function_name)
                script = (
                    f"{function}\n"
                    f"$nodeRoot = '{node_root}'\n"
                    "$env:EXPECTED_NODE_ROOT = $nodeRoot\n"
                    "$env:Path = 'C:\\original\\bin'\n"
                    f"$version = {function_name} -LauncherPath '{launcher}'\n"
                    "$result = @{ version = $version; restoredPath = $env:Path }\n"
                    "$result | ConvertTo-Json -Compress\n"
                )
                result = self._run_pwsh(script, home)

                self.assertEqual(result.returncode, 0, result.stderr)
                state = json.loads(result.stdout.strip())
                self.assertEqual(state["version"], expected)
                self.assertEqual(state["restoredPath"], r"C:\original\bin")

    def test_pnpm_version_probe_uses_opt_out_and_restores_process_state(
        self,
    ) -> None:
        function = _extract_function(_render(PNPM_PS1), "Get-InstalledPnpmVersion")
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp)
            mock_pnpm = home / "mock-pnpm.ps1"
            mock_pnpm.write_text(
                "param([string]$Argument)\n"
                "if ($Argument -ne '--version') { exit 2 }\n"
                "$state = @{\n"
                "    pmOnFail = $env:PNPM_CONFIG_PM_ON_FAIL\n"
                "    cwd = (Get-Location).Path\n"
                "}\n"
                "$state | ConvertTo-Json -Compress | "
                "Set-Content -LiteralPath (Join-Path $env:HOME 'pnpm-probe-state.json')\n"
                "Write-Output '11.25.0'\n",
                encoding="utf-8",
            )
            script = (
                f"{function}\n"
                "$env:PNPM_CONFIG_PM_ON_FAIL = 'original'\n"
                "$initialLocation = (Get-Location).Path\n"
                f"$version = Get-InstalledPnpmVersion -Path '{mock_pnpm}'\n"
                "$probe = Get-Content -LiteralPath "
                "(Join-Path $env:HOME 'pnpm-probe-state.json') -Raw | ConvertFrom-Json\n"
                "$result = @{\n"
                "    version = $version\n"
                "    probePmOnFail = $probe.pmOnFail\n"
                "    probeCwd = $probe.cwd\n"
                "    restoredPmOnFail = $env:PNPM_CONFIG_PM_ON_FAIL\n"
                "    restoredCwd = (Get-Location).Path\n"
                "    initialCwd = $initialLocation\n"
                "}\n"
                "$result | ConvertTo-Json -Compress\n"
            )
            result = self._run_pwsh(script, home)

            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(result.stdout.strip())
            self.assertEqual(state["version"], "11.25.0")
            self.assertEqual(state["probePmOnFail"], "ignore")
            self.assertNotEqual(state["probeCwd"], state["initialCwd"])
            self.assertEqual(state["restoredPmOnFail"], "original")
            self.assertEqual(state["restoredCwd"], state["initialCwd"])

    @unittest.skipUnless(os.name == "nt", "Windows is required for lock semantics")
    def test_locked_entrypoints_fail_in_the_lock_guard_before_replacement(self) -> None:
        for path in LOCK_GUARD_SCRIPTS:
            with self.subTest(installer=path.name), tempfile.TemporaryDirectory() as temp:
                home = pathlib.Path(temp)
                function = _extract_function(
                    _render(path), "Assert-BinaryReplaceable"
                )
                script = (
                    f"{function}\n"
                    "$locked = Join-Path $HOME 'locked-entrypoint.exe'\n"
                    "[System.IO.File]::WriteAllText($locked, 'existing')\n"
                    "$held = [System.IO.File]::Open("
                    "$locked, [System.IO.FileMode]::Open, "
                    "[System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)\n"
                    "try {\n"
                    "    try {\n"
                    "        Assert-BinaryReplaceable -Path $locked\n"
                    "        throw 'LOCK_GUARD_DID_NOT_FAIL'\n"
                    "    }\n"
                    "    catch {\n"
                    "        if ($_.Exception.Message -eq 'LOCK_GUARD_DID_NOT_FAIL') { throw }\n"
                    f"        Write-Output 'EXPECTED_LOCK_FAILURE={path.name}'\n"
                    "    }\n"
                    "}\n"
                    "finally { $held.Dispose() }\n"
                    "if ([System.IO.File]::ReadAllText($locked) -ne 'existing') {\n"
                    "    throw 'LOCKED_FILE_CHANGED'\n"
                    "}\n"
                )
                result = self._run_pwsh(script, home)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("ParserError", result.stderr)
                self.assertIn(
                    f"EXPECTED_LOCK_FAILURE={path.name}",
                    result.stdout,
                )


if __name__ == "__main__":
    unittest.main()
