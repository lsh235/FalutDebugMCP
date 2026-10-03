---
name: faultdebug-analysis
description: Inspect faultdebug artifacts using captured runtime records, build provenance, and the independent static index.
---

Use this skill when answering questions about a faultdebug run. Load artifacts only from an explicitly allowlisted root. Validate the ABI header, bounds, publication markers, checksum/provenance, and target/collector status before interpreting records.

Separate runtime evidence from static index facts. A static edge does not prove execution, and a missing or overwritten event must remain unresolved. Report unknown prefixes, gaps, overflow, unbalanced exits, `longjmp`, and exception limitations explicitly. Resolve addresses against the saved binary/symbol/source bundle and Build ID; never use the current worktree as a substitute.
