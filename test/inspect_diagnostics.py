#!/usr/bin/env python3
"""Unit checks for stable CLI inspection diagnostics."""
from faultdebug.inspect import diagnose

def main() -> int:
    missing = diagnose({"header": {"status": 0}}, [{"address": 1, "resolved": False, "reason": "missing_symbol"}])
    assert missing[0]["code"] == "FD-MISSING-SYMBOL"
    mismatch = diagnose({"header": {"status": 0}}, [{"address": 1, "resolved": False, "reason": "build_id_mismatch"}])
    assert mismatch[0]["code"] == "FD-PROVENANCE-MISMATCH"
    incomplete = diagnose({"header": {"status": 1 << 9}, "threads": [{"tid": 7, "events": [{"sequence": 2, "type": 1}], "dropped_count": 0}]})
    assert any(item["code"] == "FD-INCOMPLETE-TRACE" for item in incomplete)
    print("diagnostics-ok")
    return 0

if __name__ == "__main__": raise SystemExit(main())
