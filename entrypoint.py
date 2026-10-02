# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 The Linux Foundation

"""Run the vars_to_env package after refusing interpreters older than 3.9.

Keep this file parseable by every Python, 2.7 included: an old interpreter
has to reach the version check and fail with a clear message, rather than
stop on a SyntaxError in the package.
"""

import sys

# A named constant rather than a literal tuple: linters that assume a newer
# Python would otherwise treat the check as dead code and remove it.
MINIMUM_VERSION = (3, 9)

if sys.version_info < MINIMUM_VERSION:
    _ = sys.stdout.write(
        "::error::vars-to-env-action needs Python 3.9 or newer, but "
        + sys.executable
        + " is Python "
        + sys.version.split()[0]
        + "\n"
    )
    sys.exit(1)
else:
    from vars_to_env.action import main

    sys.exit(main())
