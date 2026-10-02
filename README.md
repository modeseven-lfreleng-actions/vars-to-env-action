<!--
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 The Linux Foundation
-->

# 📤 Vars to Env

<!-- prettier-ignore-start -->
<!-- markdownlint-disable-next-line MD013 -->
[![Linux Foundation](https://img.shields.io/badge/Linux-Foundation-blue)](https://linuxfoundation.org/) [![Source Code](https://img.shields.io/badge/GitHub-100000?logo=github&logoColor=white&color=blue)](https://github.com/lfreleng-actions/vars-to-env-action) [![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) [![pre-commit.ci status badge]][pre-commit.ci results page] [![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lfreleng-actions/vars-to-env-action/badge)](https://scorecard.dev/viewer/?uri=github.com/lfreleng-actions/vars-to-env-action)
<!-- prettier-ignore-end -->

Exports the keys of a JSON object, such as `toJSON(vars)` or
`toJSON(secrets)`, as environment variables for the later steps of a job.

## vars-to-env-action

A drop-in replacement for [infovista-opensource/vars-to-env-action], written
in Python using the standard library alone. It keeps the inputs, defaults and
behaviour of release 1.0.2, so callers migrate by changing `uses:` and
nothing else. A short list of deliberate differences follows below; most of
them add validation.

The action needs `bash` and Python 3.9 or newer, as `python3` or `python` on
`PATH`. GitHub-hosted Linux (x64 and arm64), macOS and Windows runners
provide both, so it runs there with no setup step, no network access and no
packages to install. Self-hosted runners need Python 3.9 or newer; on Windows,
`bash` comes from Git for Windows.

## Usage Example

<!-- markdownlint-disable MD046 -->

```yaml
steps:
  - name: "Export repository variables"
    uses: lfreleng-actions/vars-to-env-action@main
    with:
      secrets: ${{ toJSON(vars) }}

  - name: "Export the deployment secrets, without their prefix"
    id: deploy
    uses: lfreleng-actions/vars-to-env-action@main
    with:
      secrets: ${{ toJSON(secrets) }}
      include: "^DEPLOY_"
      removeprefix: "DEPLOY_"

  - name: "Use them"
    shell: bash
    env:
      EXPORTED: ${{ steps.deploy.outputs.names }}
    run: |
      echo "Exported: $EXPORTED"
      ./deploy.sh --host "$HOST"
```

<!-- markdownlint-enable MD046 -->

Pin the action to a full commit SHA in production workflows.

## Migrating

### From infovista-opensource/vars-to-env-action

Change `uses:` to this action. The inputs, defaults, variable names, log
lines and exit status stay the same, apart from the
[deliberate differences](#differences-from-the-nodejs-action).

### From oNaiPs/secrets-to-env-action

infovista-opensource/vars-to-env-action forked [oNaiPs/secrets-to-env-action]
and diverged from it. Map its inputs as follows:

<!-- markdownlint-disable MD013 -->

| oNaiPs input     | This action    | Notes                                                                        |
| ---------------- | -------------- | ---------------------------------------------------------------------------- |
| `secrets`        | `secrets`      | Same                                                                         |
| `vars`           | (none)         | Call the action twice, see below                                             |
| `prefix`         | `prefix`       | Here, keys that `removeprefix` shortens do not receive the prefix            |
| `remove_prefix`  | `removeprefix` | Literal and case-sensitive here; a case-insensitive regular expression there |
| `include`        | `include`      | Same comma-separated regular expressions                                     |
| `exclude`        | `exclude`      | Same; both always exclude `github_token`                                     |
| `convert`        | `convert`      | Default `upper` here, no conversion there; accepts `upper`, `lower`, `none`  |
| `convert_prefix` | (none)         | Conversion always covers the prefix                                          |
| `override`       | `override`     | Default `false` here, `true` there                                           |
| `on_collision`   | (none)         | Call the action twice, see below                                             |

<!-- markdownlint-enable MD013 -->

In practice:

- Add `override: true` to keep the oNaiPs default of replacing variables that
  already hold a value.
- Add `convert: none` to keep names as given; the default here converts them
  to upper case.
- Write `removeprefix` as the literal text, in the case the keys use.
- This action offers no `camel`, `constant`, `pascal` or `snake` conversion.
- To export both secrets and variables, call the action once with
  `toJSON(secrets)` and then once with `toJSON(vars)`. The second call skips
  names the first one set, which matches the oNaiPs default of
  `on_collision: prefer-secrets`; add `override: true` to the second call to
  prefer variables instead.

## Inputs

<!-- markdownlint-disable MD013 -->

| Name           | Required | Default | Description                                                                        |
| -------------- | -------- | ------- | ---------------------------------------------------------------------------------- |
| `secrets`      | True     |         | JSON object to export, such as `${{ toJSON(vars) }}` or `${{ toJSON(secrets) }}`   |
| `prefix`       | False    | `""`    | Text added to the start of each name, except for keys that `removeprefix` shortens |
| `include`      | False    | `""`    | Comma-separated regular expressions; when set, a key must match one to export      |
| `exclude`      | False    | `""`    | Comma-separated regular expressions; skip keys that match one                      |
| `convert`      | False    | `upper` | Case of the names: `upper`, `lower` or `none`                                      |
| `override`     | False    | `false` | `true` replaces variables that already hold a non-empty value                      |
| `removeprefix` | False    | `""`    | Literal text removed from the start of keys that begin with it                     |
| `tracelog`     | False    | `false` | `true` logs the settings in use and each filtering and renaming decision           |
| `mask`         | False    | `false` | `true` masks every exported value in the rest of the job's log                     |

<!-- markdownlint-enable MD013 -->

The action trims surrounding whitespace from every input. The `override`,
`tracelog` and `mask` inputs take effect for the exact value `true` alone;
`True` or `yes` leave them off.

## Outputs

<!-- markdownlint-disable MD013 -->

| Name    | Description                                                                  |
| ------- | ---------------------------------------------------------------------------- |
| `count` | Number of distinct variable names the action exported                        |
| `names` | Comma-separated names of the exported variables, in the order of exporting   |

<!-- markdownlint-enable MD013 -->

## Implementation Details

### Processing

The action reads each input from its `INPUT_<NAME>` variable, as
`@actions/core` does. It parses `secrets`, which must hold a JSON object; an
empty object exports nothing and succeeds. It compiles the `include` and
`exclude` patterns, then visits the keys in JavaScript property order: keys
that are array indexes, such as `0` or `42`, first in ascending numeric
order, then the rest in document order. For each key it:

1. Skips the key when `include` holds patterns and none matches it.
2. Skips the key when any `exclude` pattern matches it. The action always
   adds `github_token` to that list, unanchored and case-sensitive, so it
   skips `my_github_token_old` too but not `GITHUB_TOKEN`.
3. Removes `removeprefix` from the start of the key when the key begins with
   it. Otherwise, it adds `prefix` to the start.
4. Converts the whole name, prefix included, to upper or lower case using the
   full Unicode case mapping, so `ß` becomes `SS`. An unrecognised `convert`
   value means upper case, with a warning.
5. Checks the name: see [Failures](#failures).
6. Skips the variable, logging `Skip overwriting secret <NAME>`, when it
   already holds a non-empty value, whether from the job or from an earlier
   key in the same run. With `override: true` it logs the warning
   `Will re-write "<NAME>" environment variable.` and exports it anyway. When
   two keys produce one name, the first wins, or the last with
   `override: true`. Windows compares names without regard to case.

The action works all this out before writing anything. It then registers the
masks, appends the variables to `GITHUB_ENV`, sets the outputs and logs
`Exported envvar -> <NAME>` for each export.

### Values

<!-- markdownlint-disable MD013 -->

| JSON value         | Exported text                                                                        |
| ------------------ | ------------------------------------------------------------------------------------ |
| String             | Unchanged, line breaks included                                                      |
| `null`             | Empty                                                                                |
| `true` and `false` | `true` and `false`                                                                   |
| Number             | As JavaScript prints it: `1.0` gives `1`, `1e21` gives `1e+21`, `-0` gives `0`       |
| Array or object    | Compact JSON as JavaScript's `JSON.stringify` writes it, non-ASCII text left as is   |

<!-- markdownlint-enable MD013 -->

The action writes each variable to `GITHUB_ENV` in the heredoc form, with a
random delimiter and the platform's line ending, so multi-line values arrive
intact.

### Logging

The action never logs values; names do appear. Plain lines go to standard
output, warnings and debug lines use workflow commands, and `tracelog: true`
adds debug lines for the settings and a line for each key that `include`,
`exclude`, `prefix` or `removeprefix` affects.

### Failures

The action reports an `::error::` annotation, exits with status 1 and exports
nothing when:

- `secrets` is empty or holds whitespace alone:
  `Input required and not supplied: secrets`.
- `secrets` holds invalid JSON: the same message as the Node.js action.
- The JSON is an array, string, number, boolean or `null`.
- An `include` or `exclude` pattern fails to compile.
- A final name is empty or contains `=`, `<<`, a carriage return, a line feed
  or a NUL character. The message quotes the key, never the value.
- `GITHUB_ENV` is unset or names a missing file, or `GITHUB_OUTPUT` names a
  missing file.
- The JSON nests too deeply to process.

### Regular expressions

Patterns use Python's `re` module, not JavaScript's `RegExp`. Both search for
a match anywhere in the key and respect case, and the common subset behaves
the same: literals, `^`, `.`, character classes, alternation, groups and
quantifiers. The differences:

- The action compiles patterns with `re.ASCII`, so `\d`, `\w` and `\b` match
  ASCII characters alone, as in JavaScript. `\s` matches ASCII whitespace
  alone, where JavaScript also matches Unicode spaces such as U+00A0.
- In Python, `$` also matches before a trailing line feed, where JavaScript
  matches at the end of the key alone. In Python, `\Z` gives the JavaScript
  meaning.
- Python spells named groups `(?P<name>...)`; the JavaScript form
  `(?<name>...)` fails to compile. Lookbehind needs a fixed width.
- Python accepts inline flags: `(?i)^deploy_` matches without regard to case.

### Differences from the Node.js action

Compared with infovista-opensource/vars-to-env-action 1.0.2 (commit 28db16e),
the action differs on purpose in these cases. The replay test names each one.

<!-- markdownlint-disable MD013 -->

| Case                                                                 | Node.js action 1.0.2                                                                                       | This action                                       |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `secrets` holding whitespace alone                                   | Reports the JSON parse error                                                                               | `Input required and not supplied: secrets`        |
| JSON other than an object                                            | Exports array indexes or string characters as `0`, `1`…; nothing for numbers and booleans; fails on `null` | Fails, naming the type                            |
| Invalid `include` or `exclude` pattern                               | Fails on reaching it, after exporting earlier keys; succeeds for `{}`                                      | Fails before exporting anything, even for `{}`    |
| Name empty or containing `=`, `<<`, CR, LF or NUL                    | Writes it to `GITHUB_ENV`, where the runner rejects or misreads it                                         | Fails before exporting anything                   |
| Empty `include` or `exclude` entry, as from a trailing comma         | Matches every key: `include` lets all through, `exclude` blocks all                                        | Ignored                                           |
| Unrecognised `convert` value                                         | Upper case, no warning                                                                                     | Upper case, with a warning naming accepted values |
| `convert: none`                                                      | Upper case                                                                                                 | Names kept as given                               |
| Keys that become `constructor` or `__proto__` under `convert: lower` | Treated as already set and skipped                                                                         | Exported                                          |
| `mask` input                                                         | Not available                                                                                              | Masks exported values                             |
| `count` and `names` outputs                                          | Not available                                                                                              | Set                                               |

<!-- markdownlint-enable MD013 -->

## Security

- The action never logs values.
- GitHub masks values from the `secrets` context in logs, but not
  configuration variables: a later step that prints a value from
  `toJSON(vars)` shows it in clear text. `mask: true` registers each exported
  value as a mask, line by line for multi-line values. A mask hides its text
  everywhere in the rest of the job's log, so masking a short or common value
  such as `1` or `true` blanks out every occurrence of it.
- Every later step in the job sees the exported variables, third-party
  actions included. `toJSON(secrets)` hands over every secret the job can
  read; use `include` to export the ones later steps need.
- The action rejects names that could break out of their `GITHUB_ENV` entry
  and smuggle in further variables. It does not block names that change how
  later steps run, such as `LD_PRELOAD` or `BASH_ENV`: pass JSON whose keys
  you trust, or allow-list them with `include`.
- The action runs Python with `-E -s`, so `PYTHONPATH` and similar variables
  left by earlier steps cannot change the code it loads.

## Testing

The unit tests use the standard library alone and run on Python 3.9 or newer,
on Linux, macOS and Windows:

```bash
python3 -m unittest discover -s tests -v
```

`tests/reference/vectors.json` holds results recorded from the Node.js action
at commit 28db16e. The replay test runs each case against this action and
expects the same exit status, `GITHUB_ENV` content and log lines, apart from
the differences listed above, where it expects the new behaviour. To record
the vectors again, on Linux or macOS with Node.js installed:

```bash
git clone https://github.com/infovista-opensource/vars-to-env-action /tmp/vte
git -C /tmp/vte checkout 28db16e
python3 tests/reference/generate.py /tmp/vte/dist/index.js
```

The testing workflow runs the unit tests and calls the action itself on
Linux x64 and arm64, macOS and Windows runners.

## Notes

The behaviour derives from [infovista-opensource/vars-to-env-action] and
[oNaiPs/secrets-to-env-action]; this repository contains none of their code.

[infovista-opensource/vars-to-env-action]: https://github.com/infovista-opensource/vars-to-env-action
[oNaiPs/secrets-to-env-action]: https://github.com/oNaiPs/secrets-to-env-action
[pre-commit.ci results page]: https://results.pre-commit.ci/latest/github/lfreleng-actions/vars-to-env-action/main
[pre-commit.ci status badge]: https://results.pre-commit.ci/badge/github/lfreleng-actions/vars-to-env-action/main.svg
