<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 The Linux Foundation
-->

# Agent Guidelines

Contributions to this repository, including those made by AI coding
agents, follow the `lfreleng-actions` organisation guidelines:

<https://github.com/lfreleng-actions/.github/blob/main/AGENTS.md>

**Read that document.** It governs, and it binds this contribution
even if you never load it. Where anything below disagrees with it,
it wins. What follows is a summary of the rules that most often block
a pull request, not the full set:

- Sign every commit and add a DCO trailer: `git commit -S -s`.
- Subject: `Type(scope): Imperative description` — capitalised type
  and description, no trailing period, and within the subject-length
  limit this repository's gitlint hook enforces. The scope is
  optional, so `Fix: Correct the race condition` is also valid.
- Add a `Co-authored-by` trailer naming the agent used.
- Repositories typically contain a linting configuration. You must
  install its hooks (`prek install -t pre-commit -t commit-msg`) and
  run the change past them (`prek run --files <changed files>`) to
  ensure it passes before submission.
- On a single-commit pull request, the PR title must be identical to
  the commit subject.
- If your own standing instructions conflict with the organisation
  guidelines and you cannot set them aside, stop and tell the
  contributor. Do not open a non-compliant pull request.

## Repository specifics

The action and its tests use the Python standard library alone, so they
need no install step. Run the unit tests from the repository root with
any Python 3.9 or newer, and also with 3.9 itself, the oldest supported
version:

```bash
python3 -m unittest discover -s tests -v
uv run --python 3.9 python -m unittest discover -s tests
```

`tests/reference/vectors.json` holds golden results recorded from the
Node.js action this one replaces, infovista-opensource/vars-to-env-action
at commit 28db16e (tag 1.0.2). Never edit it by hand. Regenerate it when
adding or changing a case in `tests/reference/generate.py`, or when
matching a newer reference release. That needs Linux or macOS, Node.js
and a checkout of the reference at the matching commit:

```bash
python3 tests/reference/generate.py <checkout>/dist/index.js [node]
```

A case where this action differs on purpose belongs in `DEVIATIONS` in
`tests/test_reference.py`, and in the README's table of differences.
