# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""JavaScript semantics: trimming, key order, numbers and JSON text.

Expected values were taken from Node.js, not derived from the code under test.
"""

from __future__ import annotations

import math
import unittest
from typing import TYPE_CHECKING

from vars_to_env.javascript import (
    js_keys,
    js_number,
    js_quote,
    js_stringify,
    js_trim,
    json_parse,
)

if TYPE_CHECKING:
    from vars_to_env.javascript import JSONValue

# (value, String(value) in Node.js)
NUMBERS = (
    (1.0, "1"),
    (-0.0, "0"),
    (0.5, "0.5"),
    (-1.5, "-1.5"),
    (100.0, "100"),
    (1e20, "100000000000000000000"),
    (1e21, "1e+21"),
    (999999999999999999999.0, "1e+21"),
    (1.25e25, "1.25e+25"),
    (1e100, "1e+100"),
    (1.5e300, "1.5e+300"),
    (1.7976931348623157e308, "1.7976931348623157e+308"),
    (12345678901234567890.0, "12345678901234567000"),
    (2.0**53, "9007199254740992"),
    (123456789.123, "123456789.123"),
    (0.1 + 0.2, "0.30000000000000004"),
    (0.000001, "0.000001"),
    (1.2345e-6, "0.0000012345"),
    (1e-7, "1e-7"),
    (-1e-7, "-1e-7"),
    (1.5e-7, "1.5e-7"),
    (123e-20, "1.23e-18"),
    (5e-324, "5e-324"),
)


class TrimTest(unittest.TestCase):
    """String.prototype.trim()."""

    def test_strips_ecmascript_whitespace(self) -> None:
        """Byte order marks and Unicode spaces are trimmed."""
        self.assertEqual(js_trim("\ufeff\u00a0\u2028 \t\r\nvalue\u3000\v\f"), "value")

    def test_keeps_what_str_strip_would_remove(self) -> None:
        """U+001C to U+001F and U+0085 are not ECMAScript whitespace."""
        for char in "\x1c\x1d\x1e\x1f\x85":
            with self.subTest(char=hex(ord(char))):
                self.assertEqual(js_trim(f"{char}x{char}"), f"{char}x{char}")

    def test_keeps_inner_whitespace(self) -> None:
        """Only the ends are trimmed."""
        self.assertEqual(js_trim("  a b  "), "a b")


class KeysTest(unittest.TestCase):
    """Object.keys() order."""

    def test_array_indices_first_in_numeric_order(self) -> None:
        """Canonical integers below 2**32 - 1 come first; the rest keep their order."""
        keys = ["b", "10", "a", "2", "01", "-1", "1.5", "4294967295", "4294967294", "0"]
        self.assertEqual(
            js_keys(dict.fromkeys(keys)),
            ["0", "2", "10", "4294967294", "b", "a", "01", "-1", "1.5", "4294967295"],
        )

    def test_rejects_non_ascii_digits(self) -> None:
        """Other scripts' digits are names, not indices."""
        self.assertEqual(
            js_keys(dict.fromkeys(["b", "\u0663", "1"])), ["1", "b", "\u0663"]
        )

    def test_empty(self) -> None:
        """An empty object has no keys."""
        self.assertEqual(js_keys({}), [])


class NumberTest(unittest.TestCase):
    """Number::toString()."""

    def test_matches_node(self) -> None:
        """Each value formats as Node.js formats it."""
        for value, expected in NUMBERS:
            with self.subTest(value=repr(value)):
                self.assertEqual(js_number(value), expected)


class QuoteTest(unittest.TestCase):
    """String quoting in JSON.stringify()."""

    def test_escapes(self) -> None:
        """Short escapes where JSON has them, lowercase hex elsewhere."""
        self.assertEqual(
            js_quote('\x00\x1f\b\t\n\f\r"\\/'),
            '"\\u0000\\u001f\\b\\t\\n\\f\\r\\"\\\\/"',
        )

    def test_lone_surrogates_escaped_pairs_kept(self) -> None:
        """Only unpaired surrogates are escaped."""
        self.assertEqual(
            js_quote("\U0001f600\udfff\ud800"), '"\U0001f600\\udfff\\ud800"'
        )

    def test_leaves_other_characters(self) -> None:
        """DEL, line separators and non-ASCII text pass through."""
        self.assertEqual(js_quote("\x7f\u2028\u00e9"), '"\x7f\u2028\u00e9"')


class StringifyTest(unittest.TestCase):
    """JSON.stringify() of parsed values."""

    def test_nested(self) -> None:
        """Nested objects use Object.keys() order; numbers use Number::toString()."""
        value = json_parse(
            '{"b":[1e21,-0,null,true,"\\u2028\\u0007\\ud800"],"1":{"z":1,"0":2},"a":{}}'
        )
        self.assertEqual(
            js_stringify(value),
            '{"1":{"0":2,"z":1},"b":[1e+21,0,null,true,"\u2028\\u0007\\ud800"],"a":{}}',
        )

    def test_scalars(self) -> None:
        """Each JSON type on its own."""
        cases: list[tuple[JSONValue, str]] = [
            (None, "null"),
            (True, "true"),
            (False, "false"),
            (2.0, "2"),
            ("x", '"x"'),
            ([], "[]"),
            ({}, "{}"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(js_stringify(value), expected)

    def test_infinity_is_null(self) -> None:
        """Numbers too large for a double stringify as null."""
        self.assertEqual(js_stringify(json_parse("[1e400,-1e400]")), "[null,null]")


class ParseTest(unittest.TestCase):
    """JSON.parse()."""

    def test_integers_are_doubles(self) -> None:
        """Integers lose precision exactly as they do in JavaScript."""
        self.assertEqual(json_parse("12345678901234567890"), 12345678901234567890.0)
        self.assertIsInstance(json_parse("1"), float)

    def test_overflow_is_infinite(self) -> None:
        """Out-of-range numbers parse, as they do in JavaScript."""
        self.assertEqual(json_parse("[1e400,-1e400]"), [math.inf, -math.inf])

    def test_rejects_non_json_constants(self) -> None:
        """NaN and Infinity are Python extensions that JSON.parse() refuses."""
        for text in ("NaN", "Infinity", "-Infinity", "[NaN]"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                _ = json_parse(text)

    def test_rejects_malformed_text(self) -> None:
        """Trailing commas, single quotes and raw control characters fail."""
        for text in ('{"a":1,}', "{'a':1}", '"\n"', "", "{} {}", "\ufeff{}"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                _ = json_parse(text)

    def test_duplicate_keys(self) -> None:
        """The last value wins, in the position of the first."""
        self.assertEqual(
            js_stringify(json_parse('{"a":1,"b":2,"a":3}')), '{"a":3,"b":2}'
        )

    def test_escaped_surrogates(self) -> None:
        """Escaped pairs join; lone escapes survive as lone surrogates."""
        self.assertEqual(json_parse('"\\ud83d\\ude00\\ud800"'), "\U0001f600\ud800")


if __name__ == "__main__":
    _ = unittest.main()
