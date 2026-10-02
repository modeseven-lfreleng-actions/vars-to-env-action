# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""The entry point, and the composite step in action.yaml that starts it."""

from __future__ import annotations

import io
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.support import entry, normalise, read

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / "entrypoint.py"
ACTION = (ROOT / "action.yaml").read_text(encoding="utf-8")
TIMEOUT_SECONDS = 60
BASH = shutil.which("bash")


def runnable_environment(**variables: str) -> dict[str, str]:
    """Return a minimal environment, plus what Python needs to start on Windows."""
    environ = {name: os.environ[name] for name in ("SYSTEMROOT",) if name in os.environ}
    environ.update(variables)
    return environ


def step_script() -> str:
    """Return the run: block of the composite step."""
    match = re.search(r"^      run: \|\n((?:        .*\n|\n)+)", ACTION, re.MULTILINE)
    if match is None:
        raise AssertionError("action.yaml has no run: block")
    return textwrap.dedent(match.group(1))


class VersionGuardTest(unittest.TestCase):
    """Refusing interpreters older than Python 3.9."""

    def test_old_interpreter_refused(self) -> None:
        """An old version fails with an error command, before importing the package."""
        out = io.StringIO()
        with mock.patch.object(sys, "version_info", (3, 8, 18)), redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                _ = runpy.run_path(str(ENTRYPOINT), run_name="__main__")
        self.assertEqual(caught.exception.code, 1)
        self.assertTrue(
            out.getvalue().startswith(
                f"::error::vars-to-env-action needs Python 3.9 or newer, but {sys.executable} is Python "
            ),
            out.getvalue(),
        )


class EntryPointTest(unittest.TestCase):
    """A real run in a child process, as the composite step starts it."""

    def test_exports_with_native_line_endings_and_utf8_log(self) -> None:
        """GITHUB_ENV uses os.linesep and the log is UTF-8 whatever the console."""
        with tempfile.TemporaryDirectory() as scratch:
            env_file = Path(scratch, "github_env")
            env_file.touch()
            completed = subprocess.run(
                [sys.executable, "-B", "-E", "-s", str(ENTRYPOINT)],
                env=runnable_environment(
                    INPUT_SECRETS='{"\\u0133":"\\u00e9"}', GITHUB_ENV=str(env_file)
                ),
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
            github_env = normalise(read(env_file))
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(
            completed.stdout.decode("utf-8").splitlines(), ["Exported envvar -> \u0132"]
        )
        self.assertEqual(github_env, entry("\u0132", "\u00e9", os.linesep))


@unittest.skipIf(BASH is None or os.name == "nt", "needs bash and POSIX executables")
class InterpreterSelectionTest(unittest.TestCase):
    """The step tries python3, then python, running each to prove it works."""

    def run_step(self, python3: str | None, python: str | None) -> tuple[int, str, str]:
        """Run the step with fake interpreters; return its status, log and choice."""
        with tempfile.TemporaryDirectory() as scratch:
            bin_dir = Path(scratch, "bin")
            bin_dir.mkdir()
            for name, body in (("python3", python3), ("python", python)):
                if body is not None:
                    fake = bin_dir / name
                    _ = fake.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
                    fake.chmod(0o755)
            env_file = Path(scratch, "github_env")
            env_file.touch()
            script = Path(scratch, "step.sh")
            _ = script.write_text(step_script(), encoding="utf-8")
            completed = subprocess.run(
                [str(BASH), "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                env=runnable_environment(
                    PATH=str(bin_dir),
                    GITHUB_ACTION_PATH=str(ROOT),
                    GITHUB_ENV=str(env_file),
                    INPUT_SECRETS='{"a":"1"}',
                ),
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
            chosen = completed.stderr.splitlines()[-1:] or [""]
            return completed.returncode, completed.stdout, chosen[0]

    def real(self, name: str) -> str:
        """Return a fake interpreter body that names itself, then runs Python."""
        return f'echo {name} >&2\nexec "{sys.executable}" "$@"'

    def test_prefers_python3(self) -> None:
        """python3 is used when it runs."""
        status, log, chosen = self.run_step(self.real("python3"), self.real("python"))
        self.assertEqual(
            (status, log, chosen), (0, "Exported envvar -> A\n", "python3")
        )

    def test_skips_a_python3_that_does_not_run(self) -> None:
        """A python3 that fails, like the Windows Store alias, is passed over."""
        status, log, chosen = self.run_step("exit 9", self.real("python"))
        self.assertEqual((status, log, chosen), (0, "Exported envvar -> A\n", "python"))

    def test_falls_back_when_python3_absent(self) -> None:
        """python is used when there is no python3 at all."""
        status, _, chosen = self.run_step(None, self.real("python"))
        self.assertEqual((status, chosen), (0, "python"))

    def test_fails_clearly_without_python(self) -> None:
        """With no working interpreter the step fails with an error command."""
        status, log, _ = self.run_step("exit 9", None)
        self.assertEqual(status, 1)
        self.assertEqual(
            log,
            "::error::vars-to-env-action needs Python 3.9 or newer, but neither python3 nor python runs\n",
        )


class ActionMetadataTest(unittest.TestCase):
    """action.yaml passes every input to the step."""

    def test_every_input_reaches_the_step(self) -> None:
        """Each input appears as INPUT_<NAME>, the variable getInput() reads."""
        block = ACTION.split("\ninputs:\n", 1)[1].split("\noutputs:\n", 1)[0]
        declared = [
            line.strip().rstrip(":")
            for line in block.splitlines()
            if re.fullmatch(r"  [a-z]+:", line)
        ]
        passed = [
            line for line in ACTION.splitlines() if line.lstrip().startswith("INPUT_")
        ]
        self.assertGreater(len(declared), 0)
        self.assertEqual(
            passed,
            [
                f"        INPUT_{name.upper()}: ${{{{ inputs.{name} }}}}"
                for name in declared
            ],
        )


if __name__ == "__main__":
    _ = unittest.main()
