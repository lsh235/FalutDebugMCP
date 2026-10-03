#!/usr/bin/env python3
"""Keep standalone validation gate exit codes distinct by report status."""
from __future__ import annotations

from run_tests import status_exit_code as smoke_exit_code
from v09_validation import status_exit_code as v09_exit_code
from v10_validation import status_exit_code as v10_exit_code


def main() -> int:
    for status, expected in (("PASS", 0), ("FAIL", 1), ("NOT RUN", 2)):
        assert smoke_exit_code(status) == expected
        assert v09_exit_code(status) == expected
        assert v10_exit_code(status) == expected
    print("validation-status-contract-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
