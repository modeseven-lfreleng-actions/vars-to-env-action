# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Workflow commands and file commands, as @actions/core issues them."""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TextIO

from .javascript import js_stringify, js_trim

if TYPE_CHECKING:
    from typing import TypeAlias

    from .javascript import JSONValue

    Level: TypeAlias = Literal["info", "debug", "warning"]

# Python's json module joins escaped surrogate pairs, so any surrogate left in
# a decoded string is unpaired.
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")
LINE_BREAK = re.compile(r"\r\n|\r|\n")


class ActionError(Exception):
    """A failure to report through an ::error:: workflow command."""


@dataclass(frozen=True)
class Message:
    """A log line for stdout."""

    level: Level
    text: str

    def render(self) -> str:
        """Render the line as @actions/core info(), debug() or warning() would."""
        if self.level == "info":
            return self.text
        return f"::{self.level}::{escape_data(self.text)}"


def get_input(environ: Mapping[str, str], name: str) -> str:
    """Read an action input as @actions/core getInput() does."""
    return js_trim(environ.get("INPUT_" + name.replace(" ", "_").upper(), ""))


def command_value(value: JSONValue) -> str:
    """Convert a value to text as @actions/core toCommandValue() does."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return js_stringify(value)


def escape_data(text: str) -> str:
    """Escape a workflow command message as @actions/core escapeData() does."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def well_formed(text: str) -> str:
    """Replace lone surrogates with U+FFFD, as Node.js does when writing UTF-8."""
    return LONE_SURROGATE.sub("\ufffd", text)


def key_value_block(name: str, value: str, eol: str) -> str:
    """Format one entry for a file command, as @actions/core does."""
    delimiter = f"ghadelimiter_{uuid.uuid4()}"
    if delimiter in name:
        raise ActionError(
            f'Unexpected input: name should not contain the delimiter "{delimiter}"'
        )
    if delimiter in value:
        raise ActionError(
            f'Unexpected input: value should not contain the delimiter "{delimiter}"'
        )
    return f"{name}<<{delimiter}{eol}{value}{eol}{delimiter}{eol}"


def mask_commands(values: Iterable[str]) -> list[str]:
    """Return ::add-mask:: commands covering every non-blank line of each value.

    The runner masks log output line by line, so a multi-line value is only
    hidden if each of its lines is registered separately.
    """
    fragments: dict[str, None] = {}
    for value in values:
        for fragment in LINE_BREAK.split(value):
            if fragment.strip():
                fragments[fragment] = None
    return ["::add-mask::" + escape_data(fragment) for fragment in fragments]


def command_file(
    environ: Mapping[str, str], variable: str, *, required: bool
) -> str | None:
    """Return the path of a runner file command, checking that it exists."""
    path = environ.get(variable, "")
    if not path:
        if required:
            raise ActionError(
                f"{variable} is not set; this action must run in a GitHub Actions job"
            )
        return None
    if not os.path.isfile(path):
        raise ActionError(f"The {variable} file does not exist: {path}")
    return path


def append_file(path: str, variable: str, text: str) -> None:
    """Append text to a runner file command, writing line endings unchanged."""
    try:
        with open(path, "a", encoding="utf-8", newline="") as handle:
            _ = handle.write(well_formed(text))
    except OSError as error:
        raise ActionError(
            f"Cannot write to the {variable} file {path}: {error.strerror or error}"
        ) from None


def write_line(out: TextIO, line: str) -> None:
    """Write one line to the log."""
    _ = out.write(well_formed(line) + "\n")
