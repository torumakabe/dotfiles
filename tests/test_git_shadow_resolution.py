"""Exercise the git un-shadowing step from the Linux package bootstrap.

Codespaces / Dev Container base images build git from source into /usr/local
(devcontainers git feature, version=latest, ppa=false, prefix=/usr/local).
/usr/local/bin precedes /usr/bin in PATH, so installing a newer git through
ppa:git-core/ppa leaves the older source build as the binary that actually
runs. When that build predates git 2.54, the ADR-020 config-based gitleaks
hook stays inactive even though the PPA step reported success.

The bootstrap relinks the shadowing binaries to their /usr/bin counterparts,
and the post-apply check reports what to do while the hook stays inactive.
Both touch paths the base image owns, so these tests drive the real code
against fakes rather than matching its source text: the relink step is a shell
function that takes the two directories as arguments, and the check script is
rendered and run against a fake git on PATH.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOTSTRAP_PATH = REPO_ROOT / "home/run_once_before_10-install-packages.sh.tmpl"
CHECK_SCRIPT_PATH = REPO_ROOT / "home/run_after_40-check-git-hooks.sh.tmpl"
BLOCK_START = "# >>> git-unshadow"
BLOCK_END = "# <<< git-unshadow"
CONTAINER_GUARD = "{{ if or .codespaces .devcontainer -}}"

# The block only relinks when it decides the config-based hook is at stake, so
# the fixtures below name the versions on either side of that threshold.
BEFORE_CONFIG_HOOKS = "2.53.0"
AFTER_CONFIG_HOOKS = "2.54.0"


def extract_unshadow_block() -> str:
    """Return the bootstrap's relink function, which carries no template syntax."""
    lines = BOOTSTRAP_PATH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(BLOCK_START))
    end = next(i for i, line in enumerate(lines) if line.startswith(BLOCK_END))
    block = lines[start + 1 : end]
    if any("{{" in line for line in block):
        raise AssertionError("the extracted block must not contain template actions")
    return "\n".join(block)


@unittest.skipUnless(shutil.which("bash"), "bash is required")
@unittest.skipUnless(shutil.which("dpkg"), "dpkg --compare-versions is required")
class GitUnshadowBehaviourTests(unittest.TestCase):
    """Run the real block against fake bin directories."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.block = extract_unshadow_block()

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.source_bin = self.root / "local"
        self.target_bin = self.root / "usr"
        self.source_bin.mkdir()
        self.target_bin.mkdir()
        # The block calls sudo; the stub keeps the test unprivileged.
        self.stub_bin = self.root / "stub"
        self.stub_bin.mkdir()
        self._write_executable(self.stub_bin / "sudo", '#!/bin/sh\nexec "$@"\n')

    def _write_executable(self, path: pathlib.Path, body: str) -> None:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def _fake_git(self, path: pathlib.Path, version: str) -> None:
        self._write_executable(path, f'#!/bin/sh\necho "git version {version}"\n')

    def run_block(self) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PATH"] = f"{self.stub_bin}{os.pathsep}{env['PATH']}"
        # The directories are arguments, not environment variables: nothing in
        # the runtime environment may redirect what the step rewrites.
        script = f'{self.block}\ngit_unshadow "{self.source_bin}" "{self.target_bin}"\n'
        # -euo pipefail matches how chezmoi runs the bootstrap, so a non-zero
        # exit here is an exit that would abort the whole apply.
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def assert_block_succeeded(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_relinks_when_the_shadowing_git_predates_config_hooks(self) -> None:
        self._fake_git(self.source_bin / "git", BEFORE_CONFIG_HOOKS)
        self._fake_git(self.target_bin / "git", AFTER_CONFIG_HOOKS)

        result = self.run_block()

        self.assert_block_succeeded(result)
        self.assertTrue((self.source_bin / "git").is_symlink())
        self.assertEqual(
            os.readlink(self.source_bin / "git"), str(self.target_bin / "git")
        )

    def test_leaves_a_shadowing_git_that_already_supports_config_hooks(self) -> None:
        # Relinking here would swap one working git for another, which is not
        # what ADR-020 asks for.
        self._fake_git(self.source_bin / "git", AFTER_CONFIG_HOOKS)
        self._fake_git(self.target_bin / "git", "2.55.0")

        result = self.run_block()

        self.assert_block_succeeded(result)
        self.assertFalse((self.source_bin / "git").is_symlink())

    def test_leaves_both_sides_alone_when_apt_cannot_supply_config_hooks(self) -> None:
        # Without the PPA the distro git is older still; relinking would downgrade.
        self._fake_git(self.source_bin / "git", BEFORE_CONFIG_HOOKS)
        self._fake_git(self.target_bin / "git", "2.43.0")

        result = self.run_block()

        self.assert_block_succeeded(result)
        self.assertFalse((self.source_bin / "git").is_symlink())

    def test_keeps_binaries_that_have_no_counterpart(self) -> None:
        # git-lfs shares the directory but ships separately from git itself.
        self._fake_git(self.source_bin / "git", BEFORE_CONFIG_HOOKS)
        self._fake_git(self.target_bin / "git", AFTER_CONFIG_HOOKS)
        self._write_executable(self.source_bin / "git-lfs", "#!/bin/sh\nexit 0\n")
        self._write_executable(self.source_bin / "gitk", "#!/bin/sh\nexit 0\n")
        self._write_executable(self.source_bin / "git-upload-pack", "#!/bin/sh\n")
        self._write_executable(self.target_bin / "git-upload-pack", "#!/bin/sh\n")

        result = self.run_block()

        self.assert_block_succeeded(result)
        self.assertFalse((self.source_bin / "git-lfs").is_symlink())
        self.assertFalse((self.source_bin / "gitk").is_symlink())
        self.assertTrue((self.source_bin / "git-upload-pack").is_symlink())

    def test_leaves_an_existing_symlink_alone(self) -> None:
        # A symlink is somebody's explicit choice, so the step defers to it.
        self._fake_git(self.target_bin / "git", AFTER_CONFIG_HOOKS)
        elsewhere = self.root / "chosen-git"
        self._fake_git(elsewhere, BEFORE_CONFIG_HOOKS)
        (self.source_bin / "git").symlink_to(elsewhere)

        result = self.run_block()

        self.assert_block_succeeded(result)
        self.assertEqual(os.readlink(self.source_bin / "git"), str(elsewhere))

    def test_survives_a_shadowing_git_that_cannot_report_its_version(self) -> None:
        # An unreadable version must not abort the apply under `set -e`.
        self._write_executable(self.source_bin / "git", "#!/bin/sh\nexit 127\n")
        self._fake_git(self.target_bin / "git", AFTER_CONFIG_HOOKS)

        result = self.run_block()

        self.assert_block_succeeded(result)
        self.assertFalse((self.source_bin / "git").is_symlink())

    def test_is_a_no_op_when_nothing_shadows(self) -> None:
        self._fake_git(self.target_bin / "git", AFTER_CONFIG_HOOKS)

        result = self.run_block()

        self.assert_block_succeeded(result)
        self.assertFalse((self.source_bin / "git").exists())

    def test_second_run_changes_nothing(self) -> None:
        self._fake_git(self.source_bin / "git", BEFORE_CONFIG_HOOKS)
        self._fake_git(self.target_bin / "git", AFTER_CONFIG_HOOKS)

        self.assert_block_succeeded(self.run_block())
        first = os.readlink(self.source_bin / "git")
        second_result = self.run_block()

        self.assert_block_succeeded(second_result)
        self.assertEqual(os.readlink(self.source_bin / "git"), first)
        self.assertEqual(second_result.stdout, "")


class GitUnshadowScopeTests(unittest.TestCase):
    """Pin the decisions the behaviour tests cannot reach."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.check_script = CHECK_SCRIPT_PATH.read_text(encoding="utf-8")

    def test_relink_runs_only_in_container_images(self) -> None:
        # Elsewhere a git under /usr/local is the machine owner's own build.
        block_start = self.bootstrap.index(BLOCK_START)
        guard = self.bootstrap.rindex(CONTAINER_GUARD, 0, block_start)
        self.assertNotIn(
            "{{ end",
            self.bootstrap[guard:block_start],
            msg="the guard closes before the relink block starts",
        )
        after_block = self.bootstrap[self.bootstrap.index(BLOCK_END) :]
        self.assertLess(
            after_block.index("{{ end -}}"),
            after_block.index("{{ if"),
            msg="the guard does not close before the next template branch",
        )

    def test_ppa_is_still_added(self) -> None:
        # Relinking only helps because apt holds a git the image predates.
        self.assertIn("add-apt-repository -y ppa:git-core/ppa", self.bootstrap)

    def test_warning_offers_a_relink_only_for_the_known_image_build(self) -> None:
        # /usr/local/bin/git cannot be faked without root, so this one branch is
        # pinned by source. The behaviour tests below cover the other branches.
        self.assertIn("sudo ln -sfn /usr/bin/git /usr/local/bin/git", self.check_script)
        self.assertIn("[ ! -L /usr/local/bin/git ]", self.check_script)
        self.assertNotIn("sudo ln -sfn /usr/bin/git ${resolved_git}", self.check_script)


@unittest.skipUnless(shutil.which("bash"), "bash is required")
@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi renders the check script")
class GitHookWarningBehaviourTests(unittest.TestCase):
    """Run the rendered check script against a fake git.

    The check script is the safety net for every case the bootstrap declines to
    touch, so what it tells the reader has to be right for the cause at hand.
    """

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()

    def _render(self, *, container: bool) -> str:
        env = dict(os.environ)
        env.pop("CODESPACES", None)
        env.pop("REMOTE_CONTAINERS", None)
        if container:
            env["CODESPACES"] = "true"
        config = self.root / f"config-{container}.toml"
        config.write_text(
            subprocess.run(
                ["chezmoi", "execute-template", "--init"],
                input=(REPO_ROOT / "home/.chezmoi.toml.tmpl").read_text(
                    encoding="utf-8"
                ),
                capture_output=True,
                text=True,
                env=env,
                check=True,
            ).stdout,
            encoding="utf-8",
        )
        return subprocess.run(
            ["chezmoi", "--config", str(config), "execute-template"],
            input=CHECK_SCRIPT_PATH.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            env=env,
            check=True,
        ).stdout

    def _fake_git(self, version: str) -> None:
        # `git hook list` reports nothing, which is the state that triggers the
        # warning; `git --version` decides which cause the script reports.
        (self.fake_bin / "git").write_text(
            f'#!/bin/sh\ncase "$1" in\n'
            f'  --version) echo "git version {version}" ;;\n'
            f"  *) exit 1 ;;\nesac\n",
            encoding="utf-8",
        )
        (self.fake_bin / "git").chmod(0o755)

    def _run(self, script: str) -> str:
        env = dict(os.environ)
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env['PATH']}"
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result.stderr

    def test_points_at_the_config_when_git_already_supports_hooks(self) -> None:
        # Reinstalling git cannot fix a gitconfig that never arrived, so the
        # warning has to name the config instead of the package.
        self._fake_git(AFTER_CONFIG_HOOKS)

        warning = self._run(self._render(container=True))

        self.assertIn("chezmoi apply ~/.gitconfig", warning)
        self.assertIn("hook\\.dotfiles-gitleaks\\.", warning)
        self.assertNotIn("add-apt-repository", warning)
        self.assertNotIn("ln -sfn", warning)

    @unittest.skipUnless(
        pathlib.Path("/usr/bin/git").exists(), "the apt git decides the branch"
    )
    def test_reports_the_shadowing_path_without_prescribing_a_relink(self) -> None:
        # A git this script cannot attribute to the base image may belong to a
        # tool manager, so the warning describes the situation and stops there.
        self._fake_git(BEFORE_CONFIG_HOOKS)

        warning = self._run(self._render(container=True))

        apt_version = subprocess.run(
            ["/usr/bin/git", "--version"], capture_output=True, text=True, check=False
        ).stdout.split()
        apt_supports_hooks = len(apt_version) > 2 and apt_version[2] >= "2.54"
        if apt_supports_hooks:
            self.assertIn(f"PATH resolves git to {self.fake_bin}/git", warning)
            self.assertNotIn("ln -sfn", warning)
        else:
            # Without a newer git in /usr/bin there is nothing to un-shadow.
            self.assertIn("add-apt-repository", warning)
            self.assertNotIn("ln -sfn", warning)

    def test_never_prescribes_a_relink_outside_container_images(self) -> None:
        # Elsewhere a git under /usr/local is the machine owner's own build.
        self.assertNotIn("ln -sfn", self._render(container=False))


if __name__ == "__main__":
    unittest.main()
