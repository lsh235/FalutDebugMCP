# FaultDebugMCP agent instructions

<!-- codebase-memory-mcp:start -->
For structural codebase exploration, use the installed `codebase-memory` skill.
<!-- codebase-memory-mcp:end -->

## Escalating an implementation or diagnosis failure

Start with the current model. For a reproducible failure, inspect the error and
make one focused correction when the cause is clear. Escalate to a sub-agent when:

- The same implementation, build, or runtime failure remains after that correction.
- A reproducible failure has no supported diagnosis after inspecting the relevant
  source and logs, so another edit would be speculative.
- Conflicting evidence prevents a safe decision about capture integrity, source
  matching, or the meaning of a reported fault.

Use `gpt-6.1-sol` as the preferred higher-capability sub-agent model when the
tool exposes it. Use high reasoning, or xhigh for an unresolved multi-component
diagnosis. Pass a concise, self-contained task with `fork_turns="none"` when
setting a model override. If the coordinator already uses that model or a more
capable one, a second opinion may help, but do not describe it as a model upgrade.

The handoff must include:

- The intended behavior and a bounded acceptance condition.
- The exact failing command, working directory, relevant environment details,
  exit status, and a minimal reproduction or artifact path.
- Relevant log excerpts with secrets removed, observed versus expected results,
  and the correction already attempted.
- Explicit ownership of files or a read-only diagnostic scope; identify concurrent
  work and instruct the agent to preserve other changes.
- Relevant source evidence and any codebase-memory coverage limitations.

Create at most one escalation agent per unresolved problem. The escalation agent
must return a diagnosis, scoped changes if authorized, and verification evidence;
it must not spawn further agents. Reuse it for a focused follow-up if needed.
Do not delegate routine successful work under this rule, repeatedly retry the
same failed action, or escalate missing credentials, permissions, or unavailable
services as though a different model could supply them.

The coordinator reviews the returned changes and verifies the original failing
case with an appropriate build or runtime check before reporting success. Keep
unverified conclusions explicit. If the model or sub-agent tool is unavailable,
state that limitation accurately and continue with a bounded local diagnosis
where possible; never claim an escalation occurred when it did not. If both
attempts remain blocked, report the remaining evidence and the specific external
input needed, rather than starting an unbounded escalation chain.
