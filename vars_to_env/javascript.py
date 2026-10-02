# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""The JavaScript semantics the Node.js action relied on.

JSON.parse(), Object.keys(), String.prototype.trim(), Number::toString() and
JSON.stringify() each differ from their nearest Python equivalent in ways that
change which variables are exported, in what order, and with what text.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, NoReturn, cast

if TYPE_CHECKING:
    from typing import TypeAlias

    # Postponed annotations keep this alias out of the runtime, where the
    # union syntax would need Python 3.10.
    JSONValue: TypeAlias = (
        None | bool | float | str | list["JSONValue"] | dict[str, "JSONValue"]
    )

# String.prototype.trim() strips ECMAScript WhiteSpace and LineTerminator code
# points. str.strip() uses a different set: it also strips U+001C-U+001F and
# U+0085, but not U+FEFF.
JS_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)

# An object key is an array index when it is the canonical decimal form of an
# integer below 2**32 - 1; JavaScript lists such keys first, in numeric order.
ARRAY_INDEX = re.compile(r"0|[1-9][0-9]{0,9}")
MAX_ARRAY_INDEX = 2**32 - 2

JSON_ESCAPE = re.compile(r'["\\\x00-\x1f\ud800-\udfff]')
SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def js_trim(text: str) -> str:
    """Trim text as String.prototype.trim() does."""
    return text.strip(JS_WHITESPACE)


def js_keys(obj: Mapping[str, object]) -> list[str]:
    """Return the keys of an object in Object.keys() order."""
    indices: list[tuple[int, str]] = []
    names: list[str] = []
    for key in obj:
        if ARRAY_INDEX.fullmatch(key) and int(key) <= MAX_ARRAY_INDEX:
            indices.append((int(key), key))
        else:
            names.append(key)
    return [key for _, key in sorted(indices)] + names


def js_number(value: float) -> str:
    """Format a finite number as Number::toString() does.

    repr() already produces the shortest digit string that round-trips, which
    is the digit string the ECMAScript algorithm specifies; only the position
    of the decimal point and the switch to exponent notation differ.
    """
    if value == 0:
        return "0"
    if value < 0:
        return "-" + js_number(-value)
    mantissa, _, exponent = repr(value).partition("e")
    whole, _, fraction = mantissa.partition(".")
    padded = whole + fraction
    significant = padded.lstrip("0")
    # The value is 0.<digits> * 10**point, as in the ECMAScript algorithm.
    point = len(whole) + int(exponent or "0") - (len(padded) - len(significant))
    digits = significant.rstrip("0")
    count = len(digits)
    if count <= point <= 21:
        return digits + "0" * (point - count)
    if 0 < point <= 21:
        return digits[:point] + "." + digits[point:]
    if -6 < point <= 0:
        return "0." + "0" * -point + digits
    sign = "+" if point > 0 else "-"
    lead = digits[0] if count == 1 else digits[0] + "." + digits[1:]
    return f"{lead}e{sign}{abs(point - 1)}"


def _escape_json_char(match: re.Match[str]) -> str:
    char = match.group()
    return SHORT_ESCAPES.get(char, f"\\u{ord(char):04x}")


def js_quote(text: str) -> str:
    """Quote a string as JSON.stringify() does, escaping lone surrogates.

    Python's json module joins escaped surrogate pairs while decoding, so any
    surrogate left in a parsed string is unpaired.
    """
    return '"' + JSON_ESCAPE.sub(_escape_json_char, text) + '"'


def _stringify_null(_value: None) -> str:
    return "null"


def _stringify_boolean(value: bool) -> str:
    return "true" if value else "false"


def _stringify_number(value: float) -> str:
    # JSON.parse() reads 1e400 as Infinity, which JSON.stringify() writes as null.
    return js_number(value) if math.isfinite(value) else "null"


def _stringify_array(value: list[JSONValue]) -> str:
    return "[" + ",".join(map(js_stringify, value)) + "]"


def _stringify_object(value: dict[str, JSONValue]) -> str:
    members = (js_quote(key) + ":" + js_stringify(value[key]) for key in js_keys(value))
    return "{" + ",".join(members) + "}"


# Keyed on the exact type: json_parse() produces these six and no subclasses.
STRINGIFIERS: dict[type[object], Callable[..., str]] = {
    type(None): _stringify_null,
    bool: _stringify_boolean,
    float: _stringify_number,
    str: js_quote,
    list: _stringify_array,
    dict: _stringify_object,
}


def js_stringify(value: JSONValue) -> str:
    """Serialise a value from json_parse() as JSON.stringify() does."""
    return STRINGIFIERS[type(value)](value)


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(f"{name} is not valid JSON")


def json_parse(text: str) -> JSONValue:
    """Parse text as JSON.parse() does, raising ValueError where it would throw.

    Integers are read as floats because JavaScript holds every number as a
    double. NaN and Infinity are rejected because JSON.parse() rejects them.
    """
    return cast(
        "JSONValue",
        json.loads(text, parse_int=float, parse_constant=_reject_constant),
    )
