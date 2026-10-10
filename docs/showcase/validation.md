# Public-demo delivery evidence

Date: 2026-10-11, Asia/Seoul. Publication checks are updated after deployment.

## Local checks

- PASS: Python sdist/wheel build with .venv/bin/python -m build --sdist --wheel --no-isolation.
- PASS: Docker image build with test/shop/Dockerfile.
- PASS: service-report regression 14/14; English presentation preserves verbatim captured evidence and escaping.
- PASS: fault-report regression 14/14.
- PASS: actual newcomer script with the new image, three scenarios and eight processes each.
- PASS: the script's local report server responds on 127.0.0.1:18872.
- PASS: Pages package verifies 29 file hashes and local HTML links.
- PASS: browser video decode/playback, duration 42 seconds.
- PASS: mobile width 390 without page overflow; English/Korean navigation, keyboard node selection and light theme.
- PASS: new native C capture has SIGSEGV, collector.ok=true, snapshot stable=true and trace.complete=false; matching-source report verifies a crash location.

The initial analyzer-container experiment failed because its loopback was isolated
from the host-published gateway. Host networking was added for this local-engine
profile, then actual runs passed. The failed output/log is retained locally.

Local generated evidence lives under build/showcase-* and output/growth/.
It is not uploaded as unrelated raw workspace output.
The curated public synthetic evidence is explicitly packaged under site/downloads/.

## Public checks

The tested implementation revision is
4ab393f3588034e3e85d3faa13cd5cddca10330c. Later validation-document and
publisher guard/artifact-path changes are separate from these executed results.

| Gate | Result | Evidence |
| --- | --- | --- |
| General GitHub CI | PASS | [38075216287](https://github.com/lsh235/FalutDebugMCP/actions/runs/38075216287) |
| Pages deployment | PASS | [38075216591](https://github.com/lsh235/FalutDebugMCP/actions/runs/38075216591) |
| Hosted prebuilt image/newcomer script | PASS, three scenarios | [38075238008](https://github.com/lsh235/FalutDebugMCP/actions/runs/38075238008) |
| Public files | PASS | Nine live HTML/video/evidence-download files matched committed SHA-256 |
| Public browser path | PASS | Landing → service report → native crash; Build ID verified and limited evidence visible |
| Anonymous image download | PASS | Actual script download, SHA256SUMS validation, Docker load and local fixture execution |
| Loaded public image | PASS | Source revision label matches 4ab393f; 24 stable captures, 23 complete; intentional crash stays incomplete |
| Local report server after download | PASS | http://127.0.0.1:18873/index.html |

[Published demo snapshot](https://github.com/lsh235/FalutDebugMCP/releases/tag/demo-2026-10-11)
is a prerelease, explicitly separate from native stable acceptance.
Its Docker image archive is 292,547,825 bytes. Loaded image ID:
sha256:e377381c3e2cf0480e4f7e5194696f3689c63cf774105706cbdcb87afab484bc.

One initial public native-report navigation received GitHub's HTTP 503 page.
Subsequent requests returned 200; byte hashes and real browser navigation were
rechecked. This was not recorded as a successful initial navigation.

Local delivery evidence: build/showcase-public-hash-check.json,
build/showcase-anonymous-summary.json and screenshots under build/showcase-*.

## Community and publication scope

- Repository Homepage and description point to the public demo.
- Five actionable newcomer/help-wanted issues exist:
  [translations](https://github.com/lsh235/FalutDebugMCP/issues/1),
  [Make walkthrough](https://github.com/lsh235/FalutDebugMCP/issues/2),
  [Docker diagnostics](https://github.com/lsh235/FalutDebugMCP/issues/3),
  [print layout](https://github.com/lsh235/FalutDebugMCP/issues/4),
  [MCP transcript](https://github.com/lsh235/FalutDebugMCP/issues/5).
- Four README languages link to the demo and explain the prebuilt execution path.
- Announcement drafts and Trendshift submission fields are in ../launch-kit.md.
- External announcements and Trendshift submission have not been sent.
- Baseline stars: 0. This work does not claim that publication produced adoption
  or guarantee a star target.
- GHCR is not used for this delivery: the existing local token lacks package
  scopes, and public package visibility would need account configuration.
  A checksummed public release download provides the login-free prebuilt path.

Native stable-release acceptance, N=32 and Kubernetes remain outside this
showcase delivery. No AI-generated scene stands in for actual debugging evidence.
Graph/index coverage was unavailable; source reads were used for the touched viewer.
