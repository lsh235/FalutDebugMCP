#!/usr/bin/env python3
"""Independent oracle for the complex IPC/thread fixture marker."""
import re, sys
def main():
    text=sys.stdin.read(); m=re.search(r"complex marker threads=(\d+) ipc=(\d+) child=(-?\d+)",text)
    if not m or tuple(map(int,m.groups())) != (8,8,0):
        print("complex oracle FAIL", file=sys.stderr); return 1
    print("complex oracle PASS"); return 0
if __name__ == "__main__": raise SystemExit(main())
