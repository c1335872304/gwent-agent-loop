# Pilot 004: Live Product → Test/Verification

> 记录属性：历史现场证据；当前状态以 [`CURRENT_STATE.md`](../../CURRENT_STATE.md) 为准。

## Result

`GW-REAL-PRODUCT-001` completed one real Product Owner task followed by one
independent Test/Verification task through the local Codex CLI bridge. The
TestReport passed. The RunManifest remains `human_required` only because the
final human review/integration gate was not auto-approved.

## Scope

- Base snapshot: `db697d147b48fb6cf3171df6843f4d18e9174160`
- Final snapshot: `35aa7b1dda5d9d8dc0582f100be09b4e5b2852d9`
- Owner: `product`, attempt `owner-004`
- Verifier: `test-verification`, attempt `verifier-004`
- Changed path: `apps/web/frontend/index.html` only
- Product change: one `theme-color` meta element with content `#0f172a`
- Verification: dependency-free Python static HTML contract check, exit code 0
- Docker: not used; this task did not require services and the host has no Node runtime

## Evidence

The live artifacts are retained under the ignored local runtime directory:

- `.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/owner-004.json`
- `.agent-loop/host-artifacts/GW-REAL-PRODUCT-001/verifier-004.json`
- `.agent-loop/tasks/GW-REAL-PRODUCT-001/run-manifest.json`
- `.agent-loop/tasks/GW-REAL-PRODUCT-001/run-manifest.handoff.json`

The Verifier TestReport has `tester: test-verification`,
`tested_snapshot` equal to the final snapshot, `overall: PASS`, no failures,
no changed test paths, and a clean scope/contract manual check.

## Findings during the live trial

The first live attempts exposed and fixed three control-plane issues: Git
common-directory permissions for isolated worktrees, high-frequency wait
events exhausting the lifecycle record limit, and the HostTransport preserving
a deleted temporary report path instead of the stable artifact path. A later
attempt also exposed that the Verifier prompt needed the exact TestReport
schema and command-string requirements. These were fixed and covered by
regression tests before the final successful attempt.

## Boundary

This proves the single-domain live Owner → independent Test/Verification
transport and evidence chain. It does not prove Docker/service integration,
automatic human approval, worktree merge into the parent checkout, recovery
after a real lost task, or multi-domain scheduling.
