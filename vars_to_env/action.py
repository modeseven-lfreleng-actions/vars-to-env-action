# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Read the inputs, plan every export, then write the plan out.

Nothing is written until every input has been validated and every variable
name worked out, so a failing run never leaves a partial set of exports.
"""

from __future__ import annotations

import io
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TextIO

from .javascript import js_keys, js_quote, js_trim, json_parse
from .workflow import (
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
    from typing import TypeAlias

    from .javascript import JSONValue
    from .workflow import Level

    JSONObject: TypeAlias = dict[str, JSONValue]

ALWAYS_EXCLUDED = "github_token"
CONVERT_VALUES = ("upper", "lower", "none")

# Identical to the Node.js action's message, trailing newline included, so
# that anything matching on the failure text keeps working.
PARSE_ERROR = (
    "Cannot parse JSON secrets.\n"
    "Make sure you add the following to this action:\n"
    "\n"
    "with:\n"
    "      secrets: ${{ toJSON(secrets) }}\n"
    "or:\n"
    "      secrets: ${{ toJSON(vars) }}\n"
)

JSON_TYPE_NAMES: dict[type[object], str] = {
    type(None): "null",
    bool: "a boolean",
    float: "a number",
    str: "a string",
    list: "an array",
}

# Character sequences that let a name break out of its GITHUB_ENV entry, or
# that the runner rejects or misreads.
NAME_PROBLEMS = (
    ("=", 'contains "="'),
    ("<<", 'contains "<<"'),
    ("\r", "contains a carriage return"),
    ("\n", "contains a line feed"),
    ("\0", "contains a NUL character"),
)


@dataclass(frozen=True)
class Platform:
    """The host conventions the Node.js action inherited from its platform."""

    eol: str
    fold_case: bool

    @classmethod
    def current(cls) -> Platform:
        """Describe the platform this process runs on."""
        return cls(eol=os.linesep, fold_case=os.name == "nt")


@dataclass(frozen=True)
class Options:
    """The action inputs other than secrets, parsed and validated."""

    prefix: str
    remove_prefix: str
    include: list[re.Pattern[str]]
    exclude: list[re.Pattern[str]]
    convert: str
    override: bool
    trace: bool
    mask: bool


@dataclass(frozen=True)
class Export:
    """A variable for the GITHUB_ENV file."""

    name: str
    value: str


@dataclass
class Plan:
    """Every export and log line, worked out before anything is written."""

    messages: list[Message] = field(default_factory=list)
    exports: list[Export] = field(default_factory=list)

    def log(self, level: Level, text: str) -> None:
        """Queue a log line."""
        self.messages.append(Message(level, text))


class ProcessEnvironment:
    """The variables the Node.js action saw as already set, in process.env.

    A variable is set when it holds a non-empty value, JavaScript's truthiness
    test. process.env stores names and values as UTF-8 C strings, so a lone
    surrogate reads as U+FFFD and a value ends at its first NUL character. On
    Windows it also ignores the case of names.
    """

    def __init__(self, environ: Mapping[str, str], *, fold_case: bool) -> None:
        self._fold_case: bool = fold_case
        self._values: dict[str, str] = {}
        for name, value in environ.items():
            self.assign(name, value)

    def _key(self, name: str) -> str:
        name = well_formed(name)
        return name.upper() if self._fold_case else name

    def is_set(self, name: str) -> bool:
        """Report whether the variable holds a non-empty value."""
        return bool(self._values.get(self._key(name)))

    def assign(self, name: str, value: str) -> None:
        """Record a value, as an assignment to process.env would."""
        self._values[self._key(name)] = value.partition("\0")[0]


def parse_secrets(text: str) -> JSONObject:
    """Parse the secrets input, requiring a JSON object."""
    try:
        document = json_parse(text)
    except ValueError:
        raise ActionError(PARSE_ERROR) from None
    if isinstance(document, dict):
        return document
    raise ActionError(
        "The secrets input must be a JSON object, but it is "
        + JSON_TYPE_NAMES[type(document)]
    )


def compile_patterns(text: str, input_name: str) -> list[re.Pattern[str]]:
    """Compile a comma-separated list of regular expressions, skipping empty entries.

    re.ASCII limits \\d, \\w and \\b to ASCII, as in a JavaScript RegExp.
    """
    patterns: list[re.Pattern[str]] = []
    for entry in text.split(","):
        source = js_trim(entry)
        if not source:
            continue
        try:
            patterns.append(re.compile(source, re.ASCII))
        except (re.error, OverflowError) as error:
            raise ActionError(
                f"Invalid regular expression {js_quote(source)} in {input_name}: {error}"
            ) from None
    return patterns


def read_options(environ: Mapping[str, str]) -> Options:
    """Read and validate every input except secrets."""
    return Options(
        prefix=get_input(environ, "prefix"),
        remove_prefix=get_input(environ, "removeprefix"),
        include=compile_patterns(get_input(environ, "include"), "include"),
        exclude=[
            re.compile(ALWAYS_EXCLUDED, re.ASCII),
            *compile_patterns(get_input(environ, "exclude"), "exclude"),
        ],
        convert=get_input(environ, "convert") or "upper",
        override=get_input(environ, "override") == "true",
        trace=get_input(environ, "tracelog") == "true",
        mask=get_input(environ, "mask") == "true",
    )


def _settings(options: Options) -> list[tuple[str, str]]:
    def sources(patterns: list[re.Pattern[str]]) -> str:
        return ", ".join(pattern.pattern for pattern in patterns)

    return [
        ("Using include list", sources(options.include) or "undefined"),
        ("Using exclude list", sources(options.exclude)),
        ("Adding prefix", options.prefix),
        ("Removing prefix", options.remove_prefix),
        ("Override", "true" if options.override else "false"),
        ("Convert", options.convert),
    ]


def _log_options(result: Plan, options: Options) -> None:
    if options.convert not in CONVERT_VALUES:
        result.log(
            "warning",
            f"Unrecognised convert value {js_quote(options.convert)};"
            + " converting names to upper case."
            + f" Accepted values: {', '.join(CONVERT_VALUES)}",
        )
    if options.trace:
        for label, value in _settings(options):
            result.log("debug", f"{label}: {value}")


def name_problem(name: str) -> str | None:
    """Describe why a variable name cannot be exported, or return None."""
    if not name:
        return "is empty"
    return next((problem for chars, problem in NAME_PROBLEMS if chars in name), None)


def _selected(key: str, options: Options, result: Plan) -> bool:
    if options.include and not any(pattern.search(key) for pattern in options.include):
        if options.trace:
            result.log("info", f"excluding {key} as not in includelist")
        return False
    if any(pattern.search(key) for pattern in options.exclude):
        if options.trace:
            result.log("debug", f"excluding {key} as in excludelist")
        return False
    return True


def _variable_name(key: str, options: Options, result: Plan) -> str:
    name = key
    if options.remove_prefix and key.startswith(options.remove_prefix):
        name = key[len(options.remove_prefix) :]
        if options.trace:
            result.log("debug", f"removing prefix from {key}")
            result.log("debug", f"prefix removal {key} -> {name}")
    elif options.prefix:
        name = options.prefix + key
        if options.trace:
            result.log("debug", f"adding prefix to {key}")
            result.log("debug", f"prefix add {key} -> {name}")
    if options.convert == "lower":
        name = name.lower()
    elif options.convert != "none":
        name = name.upper()
    problem = name_problem(name)
    if problem:
        # js_quote() escapes control characters, so the key cannot break the log line.
        raise ActionError(
            f"Cannot export key {js_quote(key)} as {js_quote(name)}:"
            + f" the variable name {problem}"
        )
    return name


def plan(
    document: JSONObject,
    options: Options,
    environ: Mapping[str, str],
    *,
    fold_case: bool,
) -> Plan:
    """Work out every export and log line without writing anything.

    Each export updates the view of process.env as Node.js would, so when two
    keys map to the same name the first wins, unless override is on, in which
    case the last wins with a warning.
    """
    result = Plan()
    _log_options(result, options)
    known = ProcessEnvironment(environ, fold_case=fold_case)
    for key in js_keys(document):
        if not _selected(key, options, result):
            continue
        name = _variable_name(key, options, result)
        if known.is_set(name):
            if not options.override:
                result.log("info", f"Skip overwriting secret {name}")
                continue
            result.log("warning", f'Will re-write "{name}" environment variable.')
        value = command_value(document[key])
        known.assign(name, value)
        result.exports.append(Export(name, value))
        result.log("info", f"Exported envvar -> {name}")
    return result


def execute(
    result: Plan,
    options: Options,
    environ: Mapping[str, str],
    out: TextIO,
    eol: str,
) -> None:
    """Carry out a plan: mask values, export them, set outputs, then log."""
    env_path = command_file(environ, "GITHUB_ENV", required=True)
    output_path = command_file(environ, "GITHUB_OUTPUT", required=False)
    env_text = "".join(
        key_value_block(export.name, export.value, eol) for export in result.exports
    )
    names = list(dict.fromkeys(export.name for export in result.exports))
    output_text = key_value_block("count", str(len(names)), eol) + key_value_block(
        "names", ",".join(names), eol
    )
    if options.mask:
        for command in mask_commands(export.value for export in result.exports):
            write_line(out, command)
    if env_path and env_text:
        append_file(env_path, "GITHUB_ENV", env_text)
    if output_path:
        append_file(output_path, "GITHUB_OUTPUT", output_text)
    for message in result.messages:
        write_line(out, message.render())


def run(
    environ: Mapping[str, str], out: TextIO, platform: Platform | None = None
) -> int:
    """Run the action and return its exit status."""
    host = platform or Platform.current()
    try:
        secrets = get_input(environ, "secrets")
        if not secrets:
            raise ActionError("Input required and not supplied: secrets")
        document = parse_secrets(secrets)
        options = read_options(environ)
        result = plan(document, options, environ, fold_case=host.fold_case)
        execute(result, options, environ, out, host.eol)
    except ActionError as error:
        write_line(out, "::error::" + escape_data(str(error)))
        return 1
    except RecursionError:
        write_line(out, "::error::The secrets input is nested too deeply to process")
        return 1
    return 0


def main() -> int:
    """Run the action against the process environment."""
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    return run(os.environ, sys.stdout)
