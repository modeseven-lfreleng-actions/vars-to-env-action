#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Record golden vectors from the Node.js action this one replaces.

Usage, from any directory, on Linux or macOS:

    python3 tests/reference/generate.py <checkout>/dist/index.js [node]

<checkout> is a git checkout of infovista-opensource/vars-to-env-action at the
release being matched, and node defaults to the first one on PATH. Every case
runs in a fresh process whose environment holds only the case's inputs, the
variables the case sets, and an empty GITHUB_ENV file, so nothing from the
host leaks in. The script rewrites vectors.json beside it; the unit tests
replay each case against the Python implementation.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

VECTORS = Path(__file__).resolve().with_name("vectors.json")
DELIMITER = re.compile(r"ghadelimiter_[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
PLACEHOLDER = "ghadelimiter_<uuid>"
TIMEOUT_SECONDS = 60

TYPES = (
    '{"string":"text","true":true,"false":false,"null":null,"zero":0,'
    '"neg_zero":-0,"one":1,"one_point_zero":1.0,"big":1e21,"e20":1e20,'
    '"small":1.5e-7,"micro":0.000001,"long":12345678901234567890,"neg":-2.5,'
    '"fraction":0.1,"max":1.7976931348623157e308,"min":5e-324,"overflow":1e400,'
    '"hundred":100,"exp":123e-20,"list":[1,"two",null,false,1.0e2]}'
)
NESTED = (
    '{"config":{"b":1,"a":[true,null,{"2":"x","1":"y","z":{}}]},'
    '"empty_list":[],"empty_object":{},"text":"{\\"not\\":\\"parsed\\"}"}'
)
INTEGER_KEYS = (
    '{"b":"1","10":"2","a":"3","2":"4","01":"5","-1":"6","1.5":"7",'
    '"4294967295":"8","4294967294":"9","0":"10"}'
)
UNICODE_NAMES = (
    '{"straße":"1","ſ":"2","ﬁle":"3","İstanbul":"4","naïve":"5","\\u00e9t\\u00e9":"6"}'
)
UNICODE_VALUES = (
    '{"emoji":"😀","escaped":"\\u00e9\\ud83d\\ude00","nested":{"k":"é😀"},'
    '"lone":"\\ud800","lone_nested":["\\udc00"],"bidi":"\\u202e"}'
)
FILTERED = '{"db_host":"h","db_port":"5432","api_token":"t","other":"o"}'
OVERRIDDEN = '{"existing":"new","empty":"filled","fresh":"x"}'
PRESET = {"EXISTING": "old", "EMPTY": ""}
INHERITED = '{"constructor":"1","__proto__":"2","toString":"3","valueOf":"4"}'


@dataclass(frozen=True)
class Case:
    """One run of the reference action."""

    name: str
    secrets: str
    inputs: dict[str, str] = field(default_factory=dict)
    environ: dict[str, str] = field(default_factory=dict)
    outputs: bool = False


CASES = (
    Case("basic", '{"alpha":"one","beta":"two"}'),
    Case("empty-object", "{}"),
    Case("empty-input", ""),
    Case("whitespace-input", "  \n\t "),
    Case("invalid-json", '{"a":'),
    Case("top-level-null", "null"),
    Case("top-level-array", '["x","y"]'),
    Case("top-level-string", '"ab"'),
    Case("top-level-number", "42"),
    Case("top-level-boolean", "true"),
    Case(
        "trimmed-input", '\ufeff {"a":"1"} \n', {"prefix": "  P_ ", "include": " ^a "}
    ),
    Case("nested-objects", NESTED),
    Case("value-types", TYPES),
    Case("null-values", '{"a":null,"b":"","c":"x"}'),
    Case(
        "multi-line-values",
        '{"lf":"one\\ntwo","crlf":"one\\r\\ntwo","cr":"one\\rtwo","trailing":"x\\n","blank":"\\n\\n"}',
    ),
    Case(
        "quotes-and-equals",
        '{"conn":"host=db;pass=\\"p=1\\"","path":"C:\\\\dir\\\\file"}',
    ),
    Case("unicode-names-upper", UNICODE_NAMES),
    Case("unicode-names-lower", UNICODE_NAMES, {"convert": "lower"}),
    Case("unicode-values", UNICODE_VALUES),
    Case("lone-surrogate-names", '{"\\ud800":"a","\\udc00":"b"}'),
    Case("integer-keys", INTEGER_KEYS),
    Case("duplicate-keys", '{"a":"1","b":"2","a":"3"}'),
    Case("prefix", '{"one":"1","Two":"2"}', {"prefix": "PRE_"}),
    Case(
        "removeprefix-match", '{"app_one":"1","app_two":"2"}', {"removeprefix": "app_"}
    ),
    Case(
        "removeprefix-no-match", '{"app_one":"1","other":"2"}', {"removeprefix": "APP_"}
    ),
    Case(
        "prefix-and-removeprefix",
        '{"old_a":"1","b":"2","xold_c":"3"}',
        {"prefix": "NEW_", "removeprefix": "old_"},
    ),
    Case(
        "removeprefix-whole-key", '{"only":"1","other":"2"}', {"removeprefix": "only"}
    ),
    Case("include", FILTERED, {"include": "^db_, token$"}),
    Case("exclude", FILTERED, {"exclude": "port, ^other$"}),
    Case("include-and-exclude", FILTERED, {"include": "^db_", "exclude": "port"}),
    Case("include-trailing-comma", '{"a":"1","b":"2"}', {"include": "^a,"}),
    Case("exclude-trailing-comma", '{"a":"1","b":"2"}', {"exclude": "^a,"}),
    Case(
        "regex-ascii-classes",
        '{"süß":"1","plain":"2","٣":"3","12":"4"}',
        {"include": "^\\w+$,^\\d+$"},
    ),
    Case("invalid-regex-empty-object", "{}", {"include": "("}),
    Case("invalid-regex", '{"a":"1","b":"2"}', {"exclude": "["}),
    Case("invalid-regex-partial", '{"a":"1","b":"2"}', {"include": "^a$,("}),
    Case(
        "github-token",
        '{"github_token":"1","GITHUB_TOKEN":"2","my_github_token_old":"3","Github_Token":"4"}',
    ),
    Case("override-false-existing", OVERRIDDEN, environ=PRESET),
    Case("override-true-existing", OVERRIDDEN, {"override": "true"}, PRESET),
    Case("override-not-exactly-true", '{"a":"1"}', {"override": "TRUE"}, {"A": "x"}),
    Case("collision-override-false", '{"a":"lower","A":"upper"}'),
    Case("collision-override-true", '{"a":"lower","A":"upper"}', {"override": "true"}),
    Case("nul-in-values", '{"a":"\\u0000x","A":"y","b":"x\\u0000y"}'),
    Case(
        "tracelog",
        '{"keep_x1":"1","keep_2":"2","keep_skip":"3","drop":"4"}',
        {
            "include": "^keep",
            "exclude": "skip",
            "prefix": "P_",
            "removeprefix": "keep_x",
            "tracelog": "true",
        },
    ),
    Case("tracelog-defaults", '{"a":"1"}', {"tracelog": "true"}),
    Case("tracelog-not-exactly-true", '{"a":"1"}', {"tracelog": "True"}),
    Case("convert-lower", '{"Mixed_Case":"1","UPPER":"2"}', {"convert": "lower"}),
    Case("convert-upper", '{"Mixed_Case":"1","lower":"2"}', {"convert": "upper"}),
    Case("convert-unknown", '{"Mixed_Case":"1"}', {"convert": "Title"}),
    Case("convert-none", '{"Mixed_Case":"1"}', {"convert": "none"}),
    Case("inherited-names-lower", INHERITED, {"convert": "lower"}),
    Case("inherited-names-upper", INHERITED),
    Case("key-line-feed", '{"a\\nb":"1","c":"2"}'),
    Case("key-carriage-return", '{"c":"2","a\\rb":"1"}'),
    Case("key-equals", '{"c":"2","a=b":"1"}'),
    Case("key-heredoc", '{"c":"2","a<<b":"1"}'),
    Case("key-empty", '{"c":"2","":"1"}'),
    Case("key-nul", '{"c":"2","a\\u0000b":"1"}'),
    Case("mask-requested", '{"a":"one\\ntwo"}', {"mask": "true"}),
    Case("outputs", '{"a":"1","b":"2"}', outputs=True),
)


def normalise(text: str) -> str:
    """Replace each random file-command delimiter with a fixed placeholder."""
    return DELIMITER.sub(PLACEHOLDER, text)


def git(checkout: Path, *args: str) -> str:
    """Return the output of a git command run in the reference checkout."""
    completed = subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def record(node: str, script: Path, case: Case) -> dict[str, object]:
    """Run one case against the reference action and describe the result."""
    environ = {"INPUT_SECRETS": case.secrets}
    environ.update(
        {"INPUT_" + name.upper(): value for name, value in case.inputs.items()}
    )
    environ.update(case.environ)
    with tempfile.TemporaryDirectory() as scratch:
        env_file = Path(scratch, "github_env")
        output_file = Path(scratch, "github_output")
        env_file.touch()
        process_env = {**environ, "GITHUB_ENV": str(env_file)}
        if case.outputs:
            output_file.touch()
            process_env["GITHUB_OUTPUT"] = str(output_file)
        completed = subprocess.run(
            [node, str(script)],
            env=process_env,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        if completed.stderr:
            raise SystemExit(f"{case.name}: unexpected stderr: {completed.stderr!r}")
        # Decoded from bytes, as read_text() would translate CR and CRLF to LF.
        github_env = env_file.read_bytes().decode("utf-8")
        github_output = (
            output_file.read_bytes().decode("utf-8") if case.outputs else None
        )
    return {
        "name": case.name,
        "environ": environ,
        "exit_code": completed.returncode,
        "github_env": normalise(github_env),
        "github_output": None if github_output is None else normalise(github_output),
        "stdout": normalise(completed.stdout.decode("utf-8")).split("\n"),
    }


def main(argv: list[str]) -> int:
    """Regenerate vectors.json from the reference action."""
    if len(argv) not in (2, 3):
        _ = sys.stderr.write(__doc__ or "")
        return 64
    script = Path(argv[1]).resolve()
    node = argv[2] if len(argv) == 3 else shutil.which("node")
    if not node:
        _ = sys.stderr.write(
            "node is not on PATH; pass its path as the second argument\n"
        )
        return 64
    checkout = script.parent.parent
    vectors = {
        "reference": {
            "commit": git(checkout, "rev-parse", "HEAD"),
            "describe": git(checkout, "describe", "--tags", "--always"),
            "node": subprocess.run(
                [node, "--version"], capture_output=True, text=True, check=True
            ).stdout.strip(),
            "eol": "\r\n" if sys.platform == "win32" else "\n",
            "fold_case": sys.platform == "win32",
        },
        "regenerate": "python3 tests/reference/generate.py <checkout>/dist/index.js [node]",
        "cases": [record(node, script, case) for case in CASES],
    }
    _ = VECTORS.write_text(json.dumps(vectors, indent=2) + "\n", encoding="utf-8")
    _ = sys.stdout.write(f"Wrote {len(CASES)} cases to {VECTORS}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
