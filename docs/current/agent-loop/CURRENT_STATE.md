# Agent Loop Current State

> **Canonical current-state document**
> **Last verified:** 2026-09-15
> **Status:** Stage 3 本地 Codex CLI Host-backed 多角色串行 canary 已通过；直接父工作树集成仍保持人工 gate
> **Three-stage roadmap:** [`IDEAL_LOOP_3_STAGE_PLAN.md`](IDEAL_LOOP_3_STAGE_PLAN.md)

This is the only document that describes the current Agent Loop status. Phase
status files and pilot reports are historical records and must not be used to
infer the latest implementation state.

## One-line status

The context contracts, deterministic control plane, evidence gates, Docker
canonical test entry point, bounded recovery policy, Codex project-task request
builder, concrete Codex CLI Host Bridge, bounded multi-role orchestration,
recovery journaling, contract handoff and IntegrationManifest gate are
implemented and verified. The latest live canary is recorded in
[`PILOT_018_REPORT.md`](PILOT_018_REPORT.md): a real Product Owner was created,
rebound from a new Scheduler process, handed to an independent Teacher review,
verified by two independent Docker Test runs, integrated in an isolated
branch/worktree, rolled back in isolation, and closed with a completed
RunManifest. Direct mutations outside an explicitly approved path remain
`HUMAN_REQUIRED`; after explicit approval, the verified candidate is now in the
external `main` at `eec999c`; only the two historical ZIP changes remain untouched.

Earlier Product, Docker, recovery, Scheduler and privacy-finding pilots explain
how this operating profile was reached, but they are not part of the default
context. Follow the historical-evidence map below only for audit, regression
triage or a cited decision; Pilot 018 supersedes the earlier blocked field
condition.

## Verified evidence

- Architecture gate: 105 deterministic Agent Loop tests passed;
- Docker canonical pytest: 145 tests passed, with 2 existing warnings;
- Documentation links: 166 local links passed;
- Pilot 018 budget: input `973,240 / 1,000,000`, output `17,654 / 64,000`,
  elapsed `364.257s`, 4 model turns; budget gate passed;
- Python syntax gate: 115 files passed;
- Live phase-two Product pilot: Owner recovered once after an injected loss;
  candidate integration and post-integration independent Test/Verification
  passed in the Codex worktree; the disjoint candidate was also applied to
  isolated branch `agent-loop/GW-REAL-PRODUCT-001/integration-2` at snapshot
  `227d71ed978aca33e37ee1ddee270fec11391fa8`; the explicitly authorized
  path-scoped external-main commit is
  `481f3b1937895826bd2e8eaf4290babcf0dad11b`;
- Service-backed Product verification: Core/BFF/Web healthy, Product HTTP smoke
  passed, missing-Core injection produced BFF `unhealthy` with classified
  `DOCKER_FAILURE`, and isolated containers/network cleanup completed;
  `archive/pilots/PILOT_008_REPORT.md` and the service TestReport contain the evidence;
- Phase 3 P0 serial Scheduler canary: two owner-routed tasks passed FIFO
  pause/resume and completion with `max_concurrency=1`; 8 scheduler events and
  bounded usage evidence are recorded in `archive/pilots/PILOT_009_REPORT.md`;
- Phase 3 multi-role control-plane canary: Product → Core role routing, process
  restart snapshot/rebind without duplicate start, serial completion, and
  cross-domain `product-http:v1` handoff passed in `archive/pilots/PILOT_010_REPORT.md`; model
  calls `0`, Docker `not_run`;
- Host rebind regression: a second bridge process looked up the original
  `runner_ref`, attached to the original PID/worktree, and returned `running`
  without invoking create; covered by `test_codex_cli_bridge.py`;
- Pilot 011 live Host evidence: Product created from candidate
  `53fabec954b549f1cdce46720c3461470230ed6e`, rebind succeeded across the
  Scheduler process boundary, Product final snapshot was
  `e1d7d6793ca1f651eedf5e2e34828a4e885c5d5`, Teacher used `512,884` input /
  `10,581` output tokens and stopped on the privacy finding; see
  `archive/pilots/PILOT_011_REPORT.md` and the ignored RunManifest path recorded there;
- Pilot 018 live Host evidence: revision-5 Product/Teacher/Test chain completed;
  Product candidate `c95584faff0747027b9521188a3dcaa4a8c45384`, isolated applied
  snapshot `207fe91f58f545f8614716905230b3db7b0cb35e`, same-runner process rebind,
  two Docker TestReport PASS results, and isolated rollback PASS; see
  `PILOT_018_REPORT.md` and the ignored RunManifest/IntegrationManifest directory
  recorded there;
- Model scope: temporary model input is frozen; no local model or Torch load is
  required by the architecture gate.

## Capability matrix

| Capability | State | Authoritative evidence |
|---|---|---|
| Main and four domain Owners | implemented | `AGENTS.md`, `.codex/agents/` |
| Context / Integration role | implemented as a mode, not a Manager | `AGENTS.md`, `profiles/context-integration.yaml` |
| Windows write preflight | enforced by repo instructions and architecture markers | `AGENTS.md`, `AGENT_LOOP_NAVIGATION.md`, `scripts/agent_loop/check.py` |
| Test / Verification role | profile and policy implemented | `TEST_AGENT.md`, `profiles/test-verification.yaml` |
| TaskPacket / ContextBrief / Profile validation | implemented | `validate_packet.py`, `launch.py` |
| ContextIndex and lessons navigation | implemented, freshness is still partly manual | `CONTEXT_INDEX.yaml`, `LESSONS_LEARNED.md` |
| State, budget, lock, snapshot and persistence | implemented deterministically | `state_machine.py`, `budget.py`, `locks.py`, `persistence.py` |
| Runner lifecycle and execution journal | implemented as model-free contracts | `runner.py`, `execution.py` |
| Owner to Test handoff and verification plan | implemented as validators | `handoff.py`, `verification.py` |
| TestReport evidence gate | implemented | `report_validation.py`, `TEST_REPORT_TEMPLATE.yaml` |
| Docker canonical pytest | implemented for the declared Python test suite | `python3 scripts/check.py docker-test` |
| Bounded recovery / circuit breaker | implemented deterministically | `recovery.py`, `RECOVERY_POLICY.md` |
| Recovery decision journaling and bounded resume hook | live controlled loss/resume passed once; bounded | `execution.py`, `archive/pilots/PILOT_005_REPORT.md` |
| Codex project-task request | builder implemented | `codex_bridge.py`, `CODEX_TRANSPORT.md` |
| Host lifecycle mapping | implemented with injected bridge | `codex_host_transport.py` |
| Real Codex create / wait / resume / close | implemented via Codex CLI bridge | `codex_cli_bridge.py` |
| Single-domain Owner -> Test orchestration | implemented with bounded waits and evidence gates | `bounded_loop.py` |
| Main scheduler calling the real platform | real Product create, separate-process rebind, Teacher review, two independent Docker Test runs, isolated integration and rollback passed; direct parent mutation remains human-owned | `scheduler_backend.py`, `codex_cli_bridge.py`, `PILOT_018_REPORT.md` |
| Worktree integration planning, conflict/scope detection and rollback rehearsal | implemented; disjoint isolated auto-integration and isolated rollback passed, direct parent mutation remains human-owned | `integration.py`, `INTEGRATION_MANIFEST_TEMPLATE.yaml`, `archive/pilots/PILOT_006_REPORT.md`, `archive/pilots/PILOT_007_REPORT.md` |
| Real Owner and independent Test child tasks | revision-5 Product, Teacher, Test 1 and Test 2 all closed and passed in Pilot 018; Test runs were Docker-backed and independent | `PILOT_018_REPORT.md`, local RunManifest |
| Cross-domain parallel orchestration | intentionally outside the serial operating profile | `IDEAL_LOOP_3_STAGE_PLAN.md` |

## Actual execution boundary

```text
validated TaskPacket + ContextBrief
        -> deterministic LaunchSpec
        -> Codex project-task request builder
        -> Codex CLI child task           [connected]
        -> Test child task                [connected by bounded loop]
        -> bounded recovery decision       [live same-runner resume proven]
        -> bounded integration             [approved paths applied; arbitrary parent mutations remain human-gated]
        -> serial multi-role Scheduler    [role factories + durable Host restore/rebind connected]
        -> cross-domain contract handoff  [validated product -> core envelope]
```

The current code can create and manage a local Codex CLI child task through an
isolated Git worktree, collect its report, and close it through the Runner
lifecycle. The live phase-two pilot proved one Product Owner can survive one
controlled loss, resume on the same responsibility chain, and hand its final
commit to one independent Test/Verification child. Pilot 006 then applied the
disjoint candidate in the Codex worktree and ran a second independent
verification on the applied snapshot. The separate external `main` checkout
received only the explicitly approved path-scoped commits; its two historical
architecture ZIP modifications remain untouched. The disjoint candidate was
automatically applied to a new branch/worktree and verified without changing
unrelated paths. The repository still does not call the Codex Desktop MCP API
directly; that host-specific bridge remains injectable.

## Remaining work in priority order

### Completed: one live bounded loop

The host-independent low-risk Product pilot and its post-integration validation
are complete. The pilot used a dependency-free static HTML check because this
host has no Node runtime; Pilot 008 separately proved the service-backed Product
path. The completed path was:

1. resolve the saved project and exact snapshot;
2. create one Product child task through `CodexCliBridge`;
3. collect one structured ChangeReport;
4. hand off to one independent Test / Verification child task;
5. run the task-declared independent verification and collect TestReport;
6. persist every platform event in RunManifest and close both tasks.

No recursive spawning, cross-domain parallelism, automatic repair, or model
change is allowed in this experiment.

### Completed: failure handling and evidence

- apply `RECOVERY_POLICY.md` only after persisting the decision; **implemented**;
- prove one controlled Runner loss and one bounded same-runner resume;
  **passed in Pilot 005**;
- record actual model calls, tokens and elapsed time from the Host Bridge;
  **implemented and observed live**. After explicit calibration to a 1,000,000
  input-token / 32,000 output-token task budget, the Owner/Test total passed;
- classify service-backed Docker ownership, health, failure and cleanup;
  **passed in Pilot 008** with an isolated Compose project, controlled
  missing-Core failure, and complete cleanup evidence.

### Completed: bounded integration and rollback rehearsal

- define the worktree-to-main integration manifest; **planning, disjoint
  isolated apply, and approved path-scoped main integration implemented**;
- verify changed paths against the final snapshot; **implemented for candidate commit diff**;
- handle conflicts and partial success at a human gate; **disjoint isolated
  auto-integration passed for the Pilot 007 candidate; arbitrary parent changes
  remain HUMAN_REQUIRED**;
- support recoverable rollback without touching unrelated user changes; an
  isolated `git revert` rehearsal passed and preserved an unrelated uncommitted
  user file; the applied parent candidate itself remains human-owned;
- require two independent successful validation rounds, including one after the
  human-approved parent integration; **passed by verifier-007 and verifier-008**.

### Completed: Stage 3 control-plane canary

- route serial Scheduler tasks to explicit per-role `RunnerExecution` factories;
- persist a running snapshot and restore it without calling `start` twice;
- require an exact backend `rebind(task, handle)` and fail closed to
  `human_required` when the host cannot restore the existing Runner;
- validate a closed Product → Core contract handoff with contract version,
  references, consumer scope and the same final snapshot evidence;
- run the model-free multi-role canary recorded in `archive/pilots/PILOT_010_REPORT.md`.

### Remaining: bounded local operation and optional host adapters

- the revision-5 local Codex CLI Host-backed serial multi-role canary passed;
  `PILOT_018_REPORT.md` is the current field evidence;
- optionally wire an external Desktop/MCP Codex Host factory to the same durable
  lookup/hydration path; the local CLI reference implementation and its
  separate-process regression are complete;
- direct integration into `/mnt/c/codes/gwent_v4` `main` was completed after
  explicit approval; the final candidate is present at `eec999c`, while the two
  historical ZIP changes remain uncommitted and untouched;
- preserve the fail-closed decision when any role or platform rebind is absent;
- keep cross-domain parallelism, automatic repair, deployment, promotion, and
  model changes disabled until they receive separate bounded canaries.

## Explicit non-goals for the current phase

- Do not load or replace `models/v3/policy.pt`;
- Do not install Torch on the host to make architecture checks pass;
- Do not start all professional Agents permanently;
- Do not add another Manager Agent;
- Do not pass the parent conversation as child context;
- Do not delete child-task history after completion; preserve reports and close
  or archive the session according to the host policy;
- Do not enable cross-domain parallel orchestration, even though the local CLI
  Host-backed serial role factory, process rebind and independent verification
  gates have passed.

## Document maintenance rule

After each meaningful Agent Loop change, update this file first. Then update
the phase plan or navigation only when a link, invariant, or phase boundary
changed. Never copy a historical test count or old "not implemented" statement
into the current-state section. If a historical document is still useful, add
a link back here and label its claims as historical rather than deleting them.

## Historical evidence

- [Phase 1 status](archive/phases/PHASE_1_STATUS.md), [Phase 2 status](archive/phases/PHASE_2_STATUS.md),
  [Phase 3 status](archive/phases/PHASE_3_STATUS.md), and [Phase 4 status](archive/phases/PHASE_4_STATUS.md)
  are transition records;
- [Pilot 001](pilots/PILOT_001_REPORT.md) is the protocol rehearsal;
- [Pilot 002](pilots/PILOT_002_REPORT.md) is the low-risk Product pilot;
- [Pilot 003](pilots/PILOT_003_REPORT.md) is the blocked first-stage execution record;
- [Pilot 004](archive/pilots/PILOT_004_REPORT.md) is the earlier live CLI Product → Test/Verification pilot;
- [Pilot 005](archive/pilots/PILOT_005_REPORT.md) is the live controlled-loss/recovery pilot;
- [Pilot 006](archive/pilots/PILOT_006_REPORT.md) is the integration, Docker and initial budget audit;
- [Pilot 007](archive/pilots/PILOT_007_REPORT.md) is the automatic duplicate-worktree fallback
  and recalibrated budget audit;
- [Pilot 008](archive/pilots/PILOT_008_REPORT.md) is the service-backed Docker health/failure/
  cleanup pilot;
- [Pilot 010](archive/pilots/PILOT_010_REPORT.md) is the model-free multi-role Scheduler,
  restart/rebind, and cross-domain contract canary;
- [AGENT_LOOP_PHASE_PLAN.md](archive/AGENT_LOOP_PHASE_PLAN.md) defines phase entry and
  exit conditions, while this file defines the current position.
