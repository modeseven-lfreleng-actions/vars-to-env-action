# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Replay the golden vectors recorded from the Node.js action.

Every case must reproduce the reference exactly, except the cases listed in
DEVIATIONS: each names a deliberate difference the README documents, and
states the result this action produces instead.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tests.support import PLACEHOLDER, Result, entry, failure, run_action
from vars_to_env.action import Platform

if TYPE_CHECKING:
    from typing import TypedDict

    class ReferenceData(TypedDict):
        """Where the vectors came from."""

        commit: str
        describe: str
        node: str
        eol: str
        fold_case: bool

    class VectorData(TypedDict):
        """One recorded run of the reference action."""

        name: str
        environ: dict[str, str]
        exit_code: int
        github_env: str
        github_output: str | None
        stdout: list[str]

    class VectorsFile(TypedDict):
        """The layout of vectors.json."""

        reference: ReferenceData
        regenerate: str
        cases: list[VectorData]


VECTORS = Path(__file__).resolve().parent / "reference" / "vectors.json"


@dataclass(frozen=True)
class Deviation:
    """A deliberate difference from the reference, and the result instead."""

    name: str
    expected: Result
    # The error line ends in Python's own description of a bad pattern, which
    # differs between versions, so only the text up to it is compared.
    error_prefix_only: bool = False


def _unsafe_name(key: str, name: str, problem: str) -> Deviation:
    return Deviation(
        "unsafe-name-rejected",
        failure(f"Cannot export key {key} as {name}: the variable name {problem}"),
    )


def _invalid_pattern(source: str, input_name: str) -> Deviation:
    return Deviation(
        "invalid-pattern-fails-first",
        failure(f'Invalid regular expression "{source}" in {input_name}: '),
        error_prefix_only=True,
    )


def _not_an_object(description: str) -> Deviation:
    return Deviation(
        "object-required",
        failure(f"The secrets input must be a JSON object, but it is {description}"),
    )


DEVIATIONS = {
    "whitespace-input": Deviation(
        "required-after-trim", failure("Input required and not supplied: secrets")
    ),
    "top-level-null": _not_an_object("null"),
    "top-level-array": _not_an_object("an array"),
    "top-level-string": _not_an_object("a string"),
    "top-level-number": _not_an_object("a number"),
    "top-level-boolean": _not_an_object("a boolean"),
    "invalid-regex-empty-object": _invalid_pattern("(", "include"),
    "invalid-regex": _invalid_pattern("[", "exclude"),
    "invalid-regex-partial": _invalid_pattern("(", "include"),
    "removeprefix-whole-key": _unsafe_name('"only"', '""', "is empty"),
    "key-empty": _unsafe_name('""', '""', "is empty"),
    "key-line-feed": _unsafe_name('"a\\nb"', '"A\\nB"', "contains a line feed"),
    "key-carriage-return": _unsafe_name(
        '"a\\rb"', '"A\\rB"', "contains a carriage return"
    ),
    "key-equals": _unsafe_name('"a=b"', '"A=B"', 'contains "="'),
    "key-heredoc": _unsafe_name('"a<<b"', '"A<<B"', 'contains "<<"'),
    "key-nul": _unsafe_name('"a\\u0000b"', '"A\\u0000B"', "contains a NUL character"),
    "include-trailing-comma": Deviation(
        "empty-pattern-entries",
        Result(0, entry("A", "1"), None, ["Exported envvar -> A", ""]),
    ),
    "exclude-trailing-comma": Deviation(
        "empty-pattern-entries",
        Result(0, entry("B", "2"), None, ["Exported envvar -> B", ""]),
    ),
    "convert-unknown": Deviation(
        "unknown-convert-warns",
        Result(
            0,
            entry("MIXED_CASE", "1"),
            None,
            [
                '::warning::Unrecognised convert value "Title"; converting names'
                + " to upper case. Accepted values: upper, lower, none",
                "Exported envvar -> MIXED_CASE",
                "",
            ],
        ),
    ),
    "convert-none": Deviation(
        "convert-none",
        Result(
            0, entry("Mixed_Case", "1"), None, ["Exported envvar -> Mixed_Case", ""]
        ),
    ),
    "inherited-names-lower": Deviation(
        "inherited-names",
        Result(
            0,
            "".join(
                entry(name, value)
                for name, value in (
                    ("constructor", "1"),
                    ("__proto__", "2"),
                    ("tostring", "3"),
                    ("valueof", "4"),
                )
            ),
            None,
            [
                "Exported envvar -> constructor",
                "Exported envvar -> __proto__",
                "Exported envvar -> tostring",
                "Exported envvar -> valueof",
                "",
            ],
        ),
    ),
    "mask-requested": Deviation(
        "mask",
        Result(
            0,
            entry("A", "one\ntwo"),
            None,
            ["::add-mask::one", "::add-mask::two", "Exported envvar -> A", ""],
        ),
    ),
    "outputs": Deviation(
        "outputs",
        Result(
            0,
            entry("A", "1") + entry("B", "2"),
            entry("count", "2") + entry("names", "A,B"),
            ["Exported envvar -> A", "Exported envvar -> B", ""],
        ),
    ),
}


def load_vectors() -> VectorsFile:
    """Read the recorded vectors."""
    with VECTORS.open(encoding="utf-8") as handle:
        return cast("VectorsFile", json.load(handle))


def recorded(case: VectorData) -> Result:
    """Return the reference action's result for a case."""
    return Result(
        case["exit_code"], case["github_env"], case["github_output"], case["stdout"]
    )


class ReplayTest(unittest.TestCase):
    """The Python implementation against the Node.js reference."""

    def assert_deviation(self, actual: Result, deviation: Deviation) -> None:
        """Assert a run produced the result a deviation states."""
        expected = deviation.expected
        if not deviation.error_prefix_only:
            self.assertEqual(actual, expected)
            return
        self.assertEqual(
            (actual.exit_code, actual.github_env, actual.github_output),
            (expected.exit_code, expected.github_env, expected.github_output),
        )
        self.assertEqual(len(actual.stdout), len(expected.stdout))
        self.assertTrue(actual.stdout[0].startswith(expected.stdout[0]), actual.stdout)
        self.assertEqual(actual.stdout[1:], expected.stdout[1:])

    def test_every_vector(self) -> None:
        """Each case matches the reference, or the deviation it is listed under."""
        vectors = load_vectors()
        reference = vectors["reference"]
        platform = Platform(eol=reference["eol"], fold_case=reference["fold_case"])
        for case in vectors["cases"]:
            with self.subTest(case=case["name"]):
                actual = run_action(
                    case["environ"],
                    outputs=case["github_output"] is not None,
                    platform=platform,
                )
                deviation = DEVIATIONS.get(case["name"])
                if deviation is None:
                    self.assertEqual(actual, recorded(case))
                else:
                    self.assert_deviation(actual, deviation)

    def test_deviations_name_recorded_cases(self) -> None:
        """No deviation outlives the case it describes."""
        names = [case["name"] for case in load_vectors()["cases"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(DEVIATIONS) - set(names), set())

    def test_deviations_still_differ(self) -> None:
        """Each deviation describes a result the reference did not produce."""
        for case in load_vectors()["cases"]:
            deviation = DEVIATIONS.get(case["name"])
            if deviation is not None:
                with self.subTest(case=case["name"]):
                    self.assertNotEqual(recorded(case), deviation.expected)

    def test_vectors_cover_both_outcomes(self) -> None:
        """The vectors exercise success and failure, with real delimiters."""
        cases = load_vectors()["cases"]
        self.assertGreaterEqual(len(cases), 50)
        self.assertEqual({case["exit_code"] for case in cases}, {0, 1})
        self.assertTrue(any(PLACEHOLDER in case["github_env"] for case in cases))


if __name__ == "__main__":
    _ = unittest.main()
