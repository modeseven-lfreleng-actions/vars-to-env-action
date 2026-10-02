# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Workflow commands, inputs and runner files."""

from __future__ import annotations

import io
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from vars_to_env.workflow import (
    ActionError,
    Message,
    append_file,
    command_file,
    command_value,
    escape_data,
    get_input,
    key_value_block,
    mask_commands,
    well_formed,
    write_line,
)

if TYPE_CHECKING:
    from vars_to_env.javascript import JSONValue

FIXED_UUID = uuid.UUID("12345678-1234-4234-8234-123456789abc")
FIXED_DELIMITER = f"ghadelimiter_{FIXED_UUID}"


class InputTest(unittest.TestCase):
    """@actions/core getInput()."""

    def test_name_mapping_and_trimming(self) -> None:
        """Spaces become underscores, the name is upper-cased, the value trimmed."""
        environ = {"INPUT_REMOVE_PREFIX": " \ufeffx \n", "INPUT_PREFIX": "p"}
        self.assertEqual(get_input(environ, "remove prefix"), "x")
        self.assertEqual(get_input(environ, "prefix"), "p")

    def test_missing_is_empty(self) -> None:
        """An unset input reads as an empty string."""
        self.assertEqual(get_input({}, "include"), "")


class CommandValueTest(unittest.TestCase):
    """@actions/core toCommandValue()."""

    def test_values(self) -> None:
        """Strings verbatim, null empty, everything else JSON."""
        cases: list[tuple[JSONValue, str]] = [
            ("a\nb", "a\nb"),
            ("", ""),
            (None, ""),
            (True, "true"),
            (1.0, "1"),
            ([1.0, None], "[1,null]"),
            ({"k": "v"}, '{"k":"v"}'),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(command_value(value), expected)


class EscapeTest(unittest.TestCase):
    """@actions/core escapeData() and text written to the log."""

    def test_escape_data(self) -> None:
        """Percent signs first, then line breaks."""
        self.assertEqual(escape_data("100%\r\n%0A"), "100%25%0D%0A%250A")

    def test_message_rendering(self) -> None:
        """Info is verbatim; debug and warning are escaped commands."""
        self.assertEqual(Message("info", "a\nb%").render(), "a\nb%")
        self.assertEqual(Message("debug", "a\nb%").render(), "::debug::a%0Ab%25")
        self.assertEqual(Message("warning", "w").render(), "::warning::w")

    def test_lone_surrogates_become_replacement_characters(self) -> None:
        """Text written out is well-formed, as Node.js writes it."""
        self.assertEqual(
            well_formed("a\ud800b\U0001f600\udfff"), "a\ufffdb\U0001f600\ufffd"
        )
        out = io.StringIO()
        write_line(out, "x\udc00")
        self.assertEqual(out.getvalue(), "x\ufffd\n")


class KeyValueBlockTest(unittest.TestCase):
    """File-command entries."""

    def test_layout(self) -> None:
        """Name, heredoc delimiter, value and delimiter, each ending in the EOL."""
        with mock.patch.object(uuid, "uuid4", return_value=FIXED_UUID):
            block = key_value_block("NAME", "a\nb", "\r\n")
        d = FIXED_DELIMITER
        self.assertEqual(block, f"NAME<<{d}\r\na\nb\r\n{d}\r\n")

    def test_fresh_delimiter_each_time(self) -> None:
        """Each entry gets its own random delimiter."""
        first = key_value_block("A", "", "\n").split("\n", 1)[0]
        second = key_value_block("A", "", "\n").split("\n", 1)[0]
        self.assertNotEqual(first, second)

    def test_rejects_delimiter_in_name_or_value(self) -> None:
        """A name or value containing the delimiter cannot be written safely."""
        for name, value, part in (
            (FIXED_DELIMITER, "v", "name"),
            ("N", f"x{FIXED_DELIMITER}x", "value"),
        ):
            with self.subTest(part=part):
                with mock.patch.object(uuid, "uuid4", return_value=FIXED_UUID):
                    with self.assertRaises(ActionError) as caught:
                        _ = key_value_block(name, value, "\n")
                self.assertEqual(
                    str(caught.exception),
                    f'Unexpected input: {part} should not contain the delimiter "{FIXED_DELIMITER}"',
                )


class MaskTest(unittest.TestCase):
    """::add-mask:: commands."""

    def test_each_line_masked_once(self) -> None:
        """Lines split on any line break; blank lines and repeats are skipped."""
        self.assertEqual(
            mask_commands(["one\r\ntwo\rthree\n\n  \n", "two", "", "100%"]),
            [
                "::add-mask::one",
                "::add-mask::two",
                "::add-mask::three",
                "::add-mask::100%25",
            ],
        )

    def test_nothing_to_mask(self) -> None:
        """Empty values produce no commands."""
        self.assertEqual(mask_commands(["", "\n"]), [])


class RunnerFileTest(unittest.TestCase):
    """GITHUB_ENV and GITHUB_OUTPUT checks and writes."""

    def test_unset(self) -> None:
        """A required file must be named; an optional one may be absent."""
        with self.assertRaises(ActionError) as caught:
            _ = command_file({}, "GITHUB_ENV", required=True)
        self.assertEqual(
            str(caught.exception),
            "GITHUB_ENV is not set; this action must run in a GitHub Actions job",
        )
        self.assertIsNone(
            command_file({"GITHUB_ENV": ""}, "GITHUB_OUTPUT", required=False)
        )

    def test_missing_or_not_a_file(self) -> None:
        """A named path must be an existing file, whether required or not."""
        with tempfile.TemporaryDirectory() as scratch:
            missing = str(Path(scratch, "missing"))
            for path in (missing, scratch):
                for required in (True, False):
                    with self.subTest(path=path, required=required):
                        with self.assertRaises(ActionError) as caught:
                            _ = command_file(
                                {"GITHUB_OUTPUT": path},
                                "GITHUB_OUTPUT",
                                required=required,
                            )
                        self.assertEqual(
                            str(caught.exception),
                            f"The GITHUB_OUTPUT file does not exist: {path}",
                        )

    def test_append_keeps_line_endings(self) -> None:
        """Text is appended as UTF-8 with its line endings untouched."""
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch, "env")
            _ = path.write_bytes(b"existing\n")
            append_file(str(path), "GITHUB_ENV", "a\r\nb\rc\n\u00df\ud800")
            self.assertEqual(
                path.read_bytes(), "existing\na\r\nb\rc\n\u00df\ufffd".encode()
            )

    def test_append_failure(self) -> None:
        """A write error is reported as an action failure naming the file."""
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(ActionError) as caught:
                append_file(scratch, "GITHUB_ENV", "x")
            self.assertTrue(
                str(caught.exception).startswith(
                    f"Cannot write to the GITHUB_ENV file {scratch}: "
                )
            )


if __name__ == "__main__":
    _ = unittest.main()
