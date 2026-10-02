# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Run the action in-process against temporary runner files."""

from __future__ import annotations

import io
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from vars_to_env.action import Platform, run

DELIMITER = re.compile(r"ghadelimiter_[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
PLACEHOLDER = "ghadelimiter_<uuid>"
POSIX = Platform(eol="\n", fold_case=False)
WINDOWS = Platform(eol="\r\n", fold_case=True)


@dataclass(frozen=True)
class Result:
    """What one run left behind, with file-command delimiters normalised."""

    exit_code: int
    github_env: str
    github_output: str | None
    stdout: list[str]


def normalise(text: str) -> str:
    """Replace each random file-command delimiter with a fixed placeholder."""
    return DELIMITER.sub(PLACEHOLDER, text)


def entry(name: str, value: str, eol: str = "\n") -> str:
    """Return the file-command entry the action writes for one variable."""
    return f"{name}<<{PLACEHOLDER}{eol}{value}{eol}{PLACEHOLDER}{eol}"


def failure(message: str) -> Result:
    """Return the result of a run that fails before writing anything."""
    return Result(1, "", None, ["::error::" + message, ""])


def inputs(secrets: str, **others: str) -> dict[str, str]:
    """Return the environment the composite step gives the entry point."""
    environ = {"INPUT_SECRETS": secrets}
    environ.update({"INPUT_" + name.upper(): value for name, value in others.items()})
    return environ


def read(path: Path) -> str:
    """Read a runner file without translating its line endings."""
    return path.read_bytes().decode("utf-8")


def run_action(
    environ: Mapping[str, str],
    *,
    outputs: bool = False,
    platform: Platform = POSIX,
) -> Result:
    """Run the action with fresh GITHUB_ENV and, optionally, GITHUB_OUTPUT files."""
    with tempfile.TemporaryDirectory() as scratch:
        env_file = Path(scratch, "github_env")
        output_file = Path(scratch, "github_output")
        env_file.touch()
        full = {**environ, "GITHUB_ENV": str(env_file)}
        if outputs:
            output_file.touch()
            full["GITHUB_OUTPUT"] = str(output_file)
        out = io.StringIO()
        exit_code = run(full, out, platform)
        return Result(
            exit_code,
            normalise(read(env_file)),
            normalise(read(output_file)) if outputs else None,
            normalise(out.getvalue()).split("\n"),
        )
