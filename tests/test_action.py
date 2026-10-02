# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Behaviour the reference vectors cannot show: new features and host conventions."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import WINDOWS, Result, entry, failure, inputs, read, run_action
from vars_to_env.action import Platform, run


class MaskTest(unittest.TestCase):
    """The mask input."""

    def test_masks_exported_values_before_anything_else(self) -> None:
        """Only exported values are masked, line by line, ahead of every log line."""
        result = run_action(
            {
                **inputs(
                    '{"a":"one\\ntwo","b":"skipped","n":5,"github_token":"t"}',
                    mask="true",
                ),
                "B": "already set",
            }
        )
        self.assertEqual(
            result.stdout,
            [
                "::add-mask::one",
                "::add-mask::two",
                "::add-mask::5",
                "Exported envvar -> A",
                "Skip overwriting secret B",
                "Exported envvar -> N",
                "",
            ],
        )

    def test_only_exactly_true(self) -> None:
        """Anything but "true" leaves masking off."""
        for value in ("True", "yes", "1", ""):
            with self.subTest(value=value):
                result = run_action(inputs('{"a":"x"}', mask=value))
                self.assertEqual(result.stdout, ["Exported envvar -> A", ""])


class OutputsTest(unittest.TestCase):
    """The count and names outputs."""

    def test_distinct_names_in_export_order(self) -> None:
        """A name exported twice under override counts once."""
        result = run_action(
            inputs('{"b":"1","a":"2","B":"3"}', override="true"), outputs=True
        )
        self.assertEqual(
            result.github_output, entry("count", "2") + entry("names", "B,A")
        )
        self.assertEqual(
            result.github_env, entry("B", "1") + entry("A", "2") + entry("B", "3")
        )

    def test_nothing_exported(self) -> None:
        """An empty object still sets both outputs."""
        result = run_action(inputs("{}"), outputs=True)
        self.assertEqual(
            result, Result(0, "", entry("count", "0") + entry("names", ""), [""])
        )

    def test_skipped_without_github_output(self) -> None:
        """Outside a runner that offers outputs, the export still succeeds."""
        self.assertEqual(run_action(inputs('{"a":"1"}')).exit_code, 0)


class PlatformTest(unittest.TestCase):
    """Line endings and name case on Windows."""

    def test_windows_line_endings(self) -> None:
        """Entries end in CRLF; line breaks inside values are left alone."""
        result = run_action(inputs('{"a":"x\\ny"}'), outputs=True, platform=WINDOWS)
        self.assertEqual(result.github_env, entry("A", "x\ny", "\r\n"))
        self.assertEqual(
            result.github_output,
            entry("count", "1", "\r\n") + entry("names", "A", "\r\n"),
        )

    def test_windows_names_ignore_case(self) -> None:
        """Existing variables and earlier exports match whatever their case."""
        result = run_action(
            {**inputs('{"path":"1","a":"2","A":"3"}', convert="none"), "Path": "C:\\"},
            platform=WINDOWS,
        )
        self.assertEqual(result.github_env, entry("a", "2", "\r\n"))
        self.assertEqual(
            result.stdout,
            [
                "Skip overwriting secret path",
                "Exported envvar -> a",
                "Skip overwriting secret A",
                "",
            ],
        )

    def test_current_platform(self) -> None:
        """The line ending comes from os.linesep at the time of the run."""
        with mock.patch.object(os, "linesep", "\r\n"):
            self.assertEqual(Platform.current().eol, "\r\n")
        self.assertEqual(Platform.current(), Platform(os.linesep, os.name == "nt"))


class RunnerFileTest(unittest.TestCase):
    """Runs without usable runner files."""

    def test_github_env_unset(self) -> None:
        """Nothing can be exported without GITHUB_ENV, so the run fails."""
        out = io.StringIO()
        self.assertEqual(run(inputs("{}"), out), 1)
        self.assertEqual(
            out.getvalue(),
            "::error::GITHUB_ENV is not set; this action must run in a GitHub Actions job\n",
        )

    def test_missing_files_write_nothing(self) -> None:
        """A missing file fails the run before the other file is touched."""
        with tempfile.TemporaryDirectory() as scratch:
            present = Path(scratch, "present")
            missing = str(Path(scratch, "missing"))
            present.touch()
            for env_path, output_path in (
                (missing, str(present)),
                (str(present), missing),
            ):
                with self.subTest(
                    missing="GITHUB_ENV" if env_path == missing else "GITHUB_OUTPUT"
                ):
                    environ = {
                        **inputs('{"a":"1"}'),
                        "GITHUB_ENV": env_path,
                        "GITHUB_OUTPUT": output_path,
                    }
                    self.assertEqual(run(environ, io.StringIO()), 1)
                    self.assertEqual(read(present), "")


class ValidationTest(unittest.TestCase):
    """Everything is checked before anything is written."""

    def test_no_partial_export(self) -> None:
        """A bad name late in the object stops the earlier exports too."""
        result = run_action(inputs('{"a":"1","b":"2","c=d":"3"}'), outputs=True)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual((result.github_env, result.github_output), ("", ""))
        self.assertEqual(len(result.stdout), 2)

    def test_values_never_logged(self) -> None:
        """Failure messages name the key, never its value."""
        for secrets in ('{"bad\\nkey":"hunter2"}', '{"ok":"hunter2","":"hunter2"}'):
            with self.subTest(secrets=secrets):
                result = run_action(inputs(secrets, tracelog="true"))
                self.assertEqual(result.exit_code, 1)
                self.assertNotIn("hunter2", "\n".join(result.stdout))

    def test_excluded_keys_are_not_validated(self) -> None:
        """A key that would never be exported cannot fail the run."""
        result = run_action(inputs('{"a=b":"1","c":"2"}', exclude="="))
        self.assertEqual(
            result, Result(0, entry("C", "2"), None, ["Exported envvar -> C", ""])
        )

    def test_secrets_input_absent(self) -> None:
        """No secrets input at all is the same as an empty one."""
        self.assertEqual(
            run_action({}), failure("Input required and not supplied: secrets")
        )

    def test_deep_nesting(self) -> None:
        """JSON nested beyond the recursion limit fails cleanly."""
        depth = 100_000
        result = run_action(inputs('{"a":' + "[" * depth + "]" * depth + "}"))
        self.assertEqual(
            result, failure("The secrets input is nested too deeply to process")
        )

    def test_pattern_classes_are_ascii(self) -> None:
        r"""\w and \d match only ASCII, as in a JavaScript RegExp."""
        result = run_action(
            inputs('{"s\\u00fc\\u00df":"1","x\\u0663":"2","x1":"3"}', include=r"^\w+$")
        )
        self.assertEqual(result.github_env, entry("X1", "3"))


if __name__ == "__main__":
    _ = unittest.main()
