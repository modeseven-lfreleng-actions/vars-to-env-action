# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Export the keys of a JSON object as environment variables.

A standard-library reimplementation of infovista-opensource/vars-to-env-action
1.0.2, a Node.js action built on @actions/core. It reproduces that action's
observable behaviour, including JavaScript key ordering and value
stringification, apart from the deliberate differences the README lists.

entrypoint.py refuses interpreters older than Python 3.9 before importing this
package, so it may use any syntax that 3.9 accepts.
"""
