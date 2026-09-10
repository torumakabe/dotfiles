"""Exercise rendered profiles without loading the user's tools or configuration."""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OPERATIONS_PATH = REPO_ROOT / "docs/operations.md"
SHELLS = tuple(shell for shell in ("sh", "dash", "bash", "zsh") if shutil.which(shell))


@unittest.skipIf(os.name == "nt", "POSIX profiles are not deployed on Windows")
@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class ShellEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profiles = {}
        for platform in ("linux", "darwin"):
            for name in ("profile", "zprofile", "zshenv", "bash_profile"):
                result = subprocess.run(
                    [
                        "chezmoi", "execute-template", "--override-data",
                        json.dumps({"chezmoi": {"os": platform}}),
                        "--file", str(REPO_ROOT / f"home/dot_{name}.tmpl"),
                    ],
                    capture_output=True, text=True, check=True,
                )
                cls.profiles[platform, name] = result.stdout

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.home = self.root / "home with spaces"
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.tools = self.root / "selected tools"
        self.tools.mkdir()
        self.log = self.root / "mise-calls"
        self.write_executable(self.tools / "fixture-tool", '#!/bin/sh\nprintf "selected\\n"\n')
        self.write_executable(self.bin / "fixture-tool", '#!/bin/sh\nexit 99\n')
        self.write_executable(
            self.bin / "mise",
            '#!/bin/sh\n'
            'printf "%s\\n" "$*" >> "$FIXTURE_LOG"\n'
            '[ "$*" = "env --shell bash" ] || exit 64\n'
            'if [ "${FIXTURE_FAIL:-0}" != 0 ]; then\n'
            '  printf "fixture env failed\\n" >&2; exit 17\n'
            'fi\n'
            'printf \'export PATH="%s:$PATH"\\nexport DOTNET_ROOT="%s"\\n\' '
            '"$FIXTURE_TOOLS" "$FIXTURE_TOOLS/sdk"\n',
        )
        self.env = {
            "HOME": str(self.home), "ZDOTDIR": str(self.home),
            "PATH": "/usr/bin:/bin", "FIXTURE_TOOLS": str(self.tools),
            "FIXTURE_LOG": str(self.log),
        }
        self.deploy("linux")

    def write_executable(self, path: pathlib.Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def deploy(self, platform: str) -> None:
        for name in ("profile", "zprofile", "zshenv", "bash_profile"):
            (self.home / f".{name}").write_text(
                self.profiles[platform, name], encoding="utf-8"
            )

    def run_shell(
        self, shell: str, script: str, *, login: bool = False, **env: str
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [shutil.which(shell), *(["-l"] if login else []), "-c", script],
            cwd=self.home,
            env=self.env | env, capture_output=True, text=True, check=False,
        )

    def assert_success(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_profiles_export_real_paths_to_no_profile_children(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell(
                    shell,
                    '. "$HOME/.profile" && /bin/sh -c '
                    '\'fixture-tool; printf "%s\\n" "$DOTNET_ROOT" "$GOPATH"\'',
                )
                self.assert_success(result)
                self.assertEqual(result.stdout.splitlines(), [
                    "selected", str(self.tools / "sdk"), str(self.home / "go"),
                ])

    def test_unchanged_path_skips_mise_on_reentry_and_in_children(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.log.unlink(missing_ok=True)
                result = self.run_shell(
                    shell,
                    '. "$HOME/.profile"; . "$HOME/.profile"; '
                    '/bin/sh -c \'. "$HOME/.profile"; fixture-tool\'',
                )
                self.assert_success(result)
                self.assertEqual(self.log.read_text().splitlines(), ["env --shell bash"])
                self.assertEqual(result.stdout, "selected\n")

    def test_changed_path_refreshes_mise_despite_inherited_bootstrap_guard(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell(
                    shell, '. "$HOME/.profile" && fixture-tool',
                    __DOTFILES_PROFILE_LOADED="1",
                    __DOTFILES_MISE_PATH="/old/path",
                    PATH=f"{self.bin}:/usr/bin:/bin",
                )
                self.assert_success(result)
                self.assertEqual(result.stdout, "selected\n")

    def test_failed_generation_is_reported_and_retried(self) -> None:
        # zsh automatically reads .zshenv; use sh to isolate explicit source calls.
        result = self.run_shell(
            "sh",
            'FIXTURE_FAIL=1; export FIXTURE_FAIL; '
            '. "$HOME/.profile"; result=$?; '
            '[ "$result" -ne 0 ] || exit 90; '
            '[ -z "${__DOTFILES_MISE_PATH:-}" ] || exit 91; '
            'FIXTURE_FAIL=0; . "$HOME/.profile" && fixture-tool',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fixture env failed", result.stderr)
        self.assertIn("mise environment", result.stderr)
        self.assertEqual(result.stdout, "selected\n")
        self.assertEqual(len(self.log.read_text().splitlines()), 2)

    def test_missing_mise_is_not_marked_initialized(self) -> None:
        (self.bin / "mise").unlink()
        result = self.run_shell("sh", '. "$HOME/.profile"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mise", result.stderr)

    @unittest.skipUnless(shutil.which("zsh"), "zsh is required")
    def test_path_helper_reordering_is_corrected_without_repeating_homebrew(self) -> None:
        self.deploy("darwin")
        # Keep the macOS path order, but never invoke the host's Homebrew.
        brew = self.bin / "brew"
        brew_log = self.root / "brew-calls"
        self.write_executable(
            brew,
            '#!/bin/sh\nprintf "brew\\n" >> "$FIXTURE_BREW_LOG"\n'
            'printf \'export HOMEBREW_PREFIX="%s"\\n\' "$HOME/brew"\n',
        )
        profile = (self.home / ".profile").read_text()
        profile = profile.replace(
            "/opt/homebrew/bin/brew /usr/local/bin/brew", '"$HOME/.local/bin/brew"'
        )
        (self.home / ".profile").write_text(profile)
        result = self.run_shell(
            "zsh",
            # Reproduce /etc/zprofile between .zshenv and .zprofile, even on Linux.
            'PATH="$HOME/.local/bin:/usr/bin:/bin:$FIXTURE_TOOLS"; export PATH; '
            '. "$HOME/.zprofile"; fixture-tool; '
            '/bin/sh -c \'. "$HOME/.profile"; fixture-tool\'',
            FIXTURE_BREW_LOG=str(brew_log),
        )
        self.assert_success(result)
        self.assertEqual(result.stdout.splitlines(), ["selected", "selected"])
        self.assertEqual(brew_log.read_text().splitlines(), ["brew"])
        self.assertEqual(len(self.log.read_text().splitlines()), 2)

        if sys.platform == "darwin":
            self.log.unlink()
            brew_log.unlink()
            result = self.run_shell(
                "zsh",
                'fixture-tool; /bin/sh -c \'. "$HOME/.profile"; fixture-tool\'',
                login=True, FIXTURE_BREW_LOG=str(brew_log),
            )
            self.assert_success(result)
            self.assertEqual(result.stdout.splitlines(), ["selected", "selected"])
            self.assertEqual(brew_log.read_text().splitlines(), ["brew"])
            self.assertEqual(len(self.log.read_text().splitlines()), 2)

    @unittest.skipUnless(shutil.which("mise"), "mise is required for generated syntax")
    def test_real_mise_output_is_compatible_with_each_shell(self) -> None:
        # Exercise real quoting and PATH generation without installs or network.
        mise = pathlib.Path(shutil.which("mise")).resolve()
        (self.bin / "mise").unlink()
        (self.bin / "mise").symlink_to(mise)
        config = self.root / "mise.toml"
        node_bin = self.tools / "bin"
        node_bin.mkdir()
        self.write_executable(node_bin / "node", "#!/bin/sh\nexit 0\n")
        config.write_text(
            '[env]\n_.path = [' + json.dumps(str(node_bin)) + ']\n'
            'FIXTURE_QUOTED = "spaces and \'quotes\'"\n',
            encoding="utf-8",
        )
        isolated_env = {
            "MISE_CONFIG_DIR": str(self.root / "config"),
            "MISE_DATA_DIR": str(self.root / "data"),
            "MISE_CACHE_DIR": str(self.root / "cache"),
            "MISE_STATE_DIR": str(self.root / "state"),
            "MISE_GLOBAL_CONFIG_FILE": str(config),
            "MISE_TRUSTED_CONFIG_PATHS": str(self.root),
            "MISE_AUTO_INSTALL": "0",
        }
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell(
                    shell,
                    '. "$HOME/.profile" && command -v node && '
                    'printf "%s\\n" "$FIXTURE_QUOTED"; '
                    'PATH="/usr/bin:/bin:$PATH"; export PATH; '
                    '. "$HOME/.profile" && command -v node',
                    **isolated_env,
                )
                self.assert_success(result)
                self.assertEqual(result.stdout.splitlines(), [
                    str(node_bin / "node"), "spaces and 'quotes'", str(node_bin / "node"),
                ])

    @unittest.skipUnless(
        shutil.which("mise") and shutil.which("zsh"),
        "mise and zsh are required for activation behavior",
    )
    def test_real_mise_activation_honors_activate_shims(self) -> None:
        mise = pathlib.Path(shutil.which("mise")).resolve()
        data = self.root / "data"
        shims = data / "shims"
        install_bin = data / "installs/node/1.2.3/bin"
        install_bin.mkdir(parents=True)
        shims.mkdir()
        self.write_executable(install_bin / "node", "#!/bin/sh\nexit 0\n")
        self.write_executable(shims / "node", "#!/bin/sh\nexit 99\n")
        env = self.env | {
            "PATH": f"{self.bin}:{shims}:/usr/bin:/bin",
            "MISE_CONFIG_DIR": str(self.root / "config"),
            "MISE_DATA_DIR": str(data),
            "MISE_CACHE_DIR": str(self.root / "cache"),
            "MISE_STATE_DIR": str(self.root / "state"),
            "MISE_TRUSTED_CONFIG_PATHS": str(self.root),
            "MISE_AUTO_INSTALL": "1",
        }
        config = self.root / "mise.toml"

        for activate_shims, expected_count in ((True, "1"), (False, "0")):
            with self.subTest(activate_shims=activate_shims):
                config.write_text(
                    '[tools]\nnode = "1.2.3"\n'
                    f"[settings]\nactivate_shims = {str(activate_shims).lower()}\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        shutil.which("zsh"),
                        "-dfc",
                        f'eval "$({mise} activate zsh)"; '
                        'command -v node; '
                        'printf "%s\\n" "$MISE_SHELL"; '
                        'print -r -- "$PATH" | tr : "\\n" | '
                        'grep -c "$MISE_DATA_DIR/shims" || true',
                    ],
                    cwd=self.root,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assert_success(result)
                self.assertEqual(result.stdout.splitlines(), [
                    str(install_bin / "node"), "zsh", expected_count,
                ])


class ShimResolutionCheckTests(unittest.TestCase):
    """Run the documented acceptance check so the published command stays usable."""

    @staticmethod
    def documented_block(
        language: str, marker: str = "outside mise bin paths:"
    ) -> str:
        text = OPERATIONS_PATH.read_text(encoding="utf-8")
        blocks = [
            block
            for block in re.findall(rf"```{language}\n(.*?)```", text, re.DOTALL)
            if marker in block
        ]
        assert len(blocks) == 1, f"expected one {language} block for {marker!r}"
        return blocks[0]

    def test_posix_listing_takes_names_from_declared_bin_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            tools, fake = root / "tools", root / "fake"
            for directory in (tools, fake, tools / "subdir"):
                directory.mkdir(parents=True)
            for name in ("alpha", "beta"):
                (tools / name).write_text("#!/bin/sh\n", encoding="utf-8")
                (tools / name).chmod(0o755)
            (tools / "notexec").write_text("", encoding="utf-8")
            (fake / "mise").write_text(f"#!/bin/sh\nprintf '%s\\n' '{tools}'\n", encoding="utf-8")
            (fake / "mise").chmod(0o755)

            result = subprocess.run(
                ["sh", "-c", self.documented_block("sh", "mise bin-paths")],
                capture_output=True, text=True, check=False,
                env={"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(root)},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (root / "mise-tool-paths.tsv").read_text(encoding="utf-8"),
                f"alpha\t{tools / 'alpha'}\nbeta\t{tools / 'beta'}\n",
            )

    def test_posix_check_reports_non_mise_and_shim_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            expected, shims, other = root / "expected", root / "shims", root / "other"
            for directory in (expected, shims, other):
                directory.mkdir()
            for path in (
                expected / "alpha",
                expected / "beta",
                expected / "delta",
                shims / "beta",
                other / "delta",
            ):
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(0o755)
            (root / "mise-tool-paths.tsv").write_text(
                f"alpha\t{expected / 'alpha'}\n"
                f"beta\t{expected / 'beta'}\n"
                f"gamma\t{expected / 'gamma'}\n"
                f"delta\t{expected / 'delta'}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["sh", "-c", self.documented_block("sh")],
                capture_output=True, text=True, check=False,
                env={
                    "PATH": f"{shims}:{other}:{expected}:/usr/bin:/bin",
                    "HOME": str(root),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [
                f"via shim: beta -> {shims}/beta (expected {expected}/beta)",
                "unresolved: gamma",
                f"outside mise bin paths: delta -> {other}/delta "
                f"(expected {expected}/delta)",
            ])

    def test_checks_report_an_empty_entry_list_as_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            (pathlib.Path(temp) / "mise-tool-paths.tsv").write_text("", encoding="utf-8")

            result = subprocess.run(
                ["sh", "-c", self.documented_block("sh")],
                capture_output=True, text=True, check=False,
                env={"PATH": "/usr/bin:/bin", "HOME": temp},
            )

            self.assertEqual(
                result.stdout.splitlines(), ["no entries: the host list is empty"]
            )
        self.assertIn("no entries", self.documented_block("powershell"))

    def test_powershell_listing_strips_only_executable_extensions(self) -> None:
        block = self.documented_block("powershell", "mise bin-paths")

        self.assertIn("PATHEXT", block)
        self.assertNotIn("BaseName", block)

    def test_listings_take_names_from_declared_bin_paths(self) -> None:
        for language in ("sh", "powershell"):
            with self.subTest(language=language):
                listing = self.documented_block(language, "mise bin-paths")
                self.assertNotIn("shims", listing)
                self.assertIn("mise-tool-paths.tsv", listing)

    def test_checks_reject_shims_and_other_executable_paths(self) -> None:
        self.assertIn("*/shims/*", self.documented_block("sh"))
        self.assertIn('"$expected"', self.documented_block("sh"))
        self.assertIn(r"'*\shims\*'", self.documented_block("powershell"))
        self.assertIn("[IO.Path]::GetFullPath($expected)", self.documented_block("powershell"))

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
    def test_powershell_check_parses(self) -> None:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command",
             "$errors=$null; $null=[Management.Automation.Language.Parser]::ParseInput("
             "[Console]::In.ReadToEnd(),[ref]$null,[ref]$errors); "
             "if ($errors.Count) { $errors | Out-String; exit 1 }"],
            input=self.documented_block("powershell"),
            capture_output=True, text=True, check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()