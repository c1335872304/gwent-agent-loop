# Agent Loop Current State

> **Canonical current-state document**
> **Last verified:** 2026-09-14
> **Status:** Stage 3 P0 serial and model-free multi-role Scheduler canary passed; live Host-backed Pilot 011 executed and stopped at HUMAN_REQUIRED on a real Teacher privacy/budget gate
> **Three-stage roadmap:** [`IDEAL_LOOP_3_STAGE_PLAN.md`](IDEAL_LOOP_3_STAGE_PLAN.md)

This is the only document that describes the current Agent Loop status. Phase
status files and pilot reports are historical records and must not be used to
infer the latest implementation state.

## One-line status

The context contracts, deterministic control plane, evidence gates, Docker
canonical test entry point, bounded recovery policy, Codex project-task request
builder, concrete Codex CLI Host Bridge, bounded single-domain orchestration,
recovery journaling, and IntegrationManifest gate are implemented and
verified. Live pilot `GW-REAL-PRODUCT-001` completed one Product Owner with a
controlled Runner loss and same-runner bounded resume, followed by one
independent Test/Verification run. The candidate was integrated into the
phase-two Codex worktree after the explicit human decision and passed a second
independent Test/Verification run there. The separate external `main` checkout
now contains the approved path-scoped Product, line-ending, and Agent Loop
documentation commits `481f3b1`, `eecd26f`, and `49d18de`; two historical
architecture ZIP modifications remain intentionally untouched. The new
isolated branch/worktree path also automatically applied the disjoint candidate
and passed changed-path and clean-worktree checks. Direct mutations outside an
explicitly approved path remain `HUMAN_REQUIRED`. An initial metric audit stopped at
`BUDGET_EXHAUSTED`; after the explicit 1,000,000
input-token policy change, the existing closed Owner/Test evidence was revalidated
under the new 32,000 output cap and passed the budget gate.
Pilot 008 then proved the declared service-backed Product path: isolated Core,
BFF, and Web health, HTTP smoke, controlled missing-Core `DOCKER_FAILURE`, and
ownership-scoped cleanup all passed.
Pilot 009 then proved the Phase 3 P0 serial Scheduler canary: TaskPacket owner
routing, FIFO queueing, pause/resume/end, `max_concurrency=1`, hard budget
limits, and append-only scheduler evidence all passed without model or Docker
side effects.
The `RunnerExecutionBackend` now binds that Scheduler contract to the existing
Runner/Host transport lifecycle, including cumulative-metric deltas, model-turn
accounting, explicit close after a completed report, and persisted-artifact
requirements for resume; its lifecycle regression tests pass. Pilot 010 then
proved explicit product/core role routing, fail-closed Scheduler restore/rebind,
serial completion, and a cross-domain contract handoff. The canary was
model-free and did not start Docker. The Host now persists session identity,
PID, worktree and output logs and supports lookup/rebind from a new bridge
process; the code-level independent-process regression passes. Pilot 011 then
ran a real Product task through a separate Scheduler process, closed Product,
and created the Product → Teacher handoff. Teacher stopped fail-closed after
finding that advanced preview responses still serialize `prompt` into the
browser response, and its real input usage exceeded the 64k Teacher packet
budget; independent Test was not started. The field result is
`HUMAN_REQUIRED`, not PASS.

## Verified evidence

- Architecture gate: 97 deterministic Agent Loop tests passed;
- Docker canonical pytest: 121 tests passed, with 2 existing deprecation warnings;
- Documentation links: 334 local links passed;
- Budget audit: Owner/Test total input `944,919 / 1,000,000`, output
  `21,051 / 32,000`, elapsed `361.315s`, 3 model turns; budget gate passed;
- Python syntax gate: 110 files passed;
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
  `PILOT_008_REPORT.md` and the service TestReport contain the evidence;
- Phase 3 P0 serial Scheduler canary: two owner-routed tasks passed FIFO
  pause/resume and completion with `max_concurrency=1`; 8 scheduler events and
  bounded usage evidence are recorded in `PILOT_009_REPORT.md`;
- Phase 3 multi-role control-plane canary: Product → Core role routing, process
  restart snapshot/rebind without duplicate start, serial completion, and
  cross-domain `product-http:v1` handoff passed in `PILOT_010_REPORT.md`; model
  calls `0`, Docker `not_run`;
- Host rebind regression: a second bridge process looked up the original
  `runner_ref`, attached to the original PID/worktree, and returned `running`
  without invoking create; covered by `test_codex_cli_bridge.py`;
- Pilot 011 live Host evidence: Product created from candidate
  `53fabec954b549f1cdce46720c3461470230ed6e`, rebind succeeded across the
  Scheduler process boundary, Product final snapshot was
  `e1d7d6793ca1f651eedf5e2e34828a4e885c5d5`, Teacher used `512,884` input /
  `10,581` output tokens and stopped on the privacy finding; see
  `PILOT_011_REPORT.md` and the ignored RunManifest path recorded there;
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
| Docker canonical pytest | implemented for the declared Python test suite | `scripts/check.py docker-test` |
| Bounded recovery / circuit breaker | implemented deterministically | `recovery.py`, `RECOVERY_POLICY.md` |
| Recovery decision journaling and bounded resume hook | live controlled loss/resume passed once; bounded | `execution.py`, `PILOT_005_REPORT.md` |
| Codex project-task request | builder implemented | `codex_bridge.py`, `CODEX_TRANSPORT.md` |
| Host lifecycle mapping | implemented with injected bridge | `codex_host_transport.py` |
| Real Codex create / wait / resume / close | implemented via Codex CLI bridge | `codex_cli_bridge.py` |
| Single-domain Owner -> Test orchestration | implemented with bounded waits and evidence gates | `bounded_loop.py` |
| Main scheduler calling the real platform | real Product create + separate-process rebind + Product → Teacher handoff exercised; independent Test remains blocked by Teacher privacy/budget gate | `scheduler_backend.py`, `codex_cli_bridge.py`, `PILOT_011_REPORT.md` |
| Worktree integration planning, conflict/scope detection and rollback rehearsal | implemented; disjoint isolated auto-integration and isolated rollback passed, direct parent mutation remains human-owned | `integration.py`, `INTEGRATION_MANIFEST_TEMPLATE.yaml`, `PILOT_006_REPORT.md`, `PILOT_007_REPORT.md` |
| Real Owner and independent Test child tasks | prior Product/Test pilots passed; Pilot 011 real Product passed its scope/handoff gates, but Teacher stopped before independent Test on a privacy contract blocker | `PILOT_005_REPORT.md`, `PILOT_008_REPORT.md`, `PILOT_011_REPORT.md`, local RunManifest |
| Cross-domain parallel orchestration | intentionally deferred | Phase 6 |

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
- run the model-free multi-role canary recorded in `PILOT_010_REPORT.md`.

### Remaining: Stage 3 live Host closure

- optionally wire an external Desktop/MCP Codex Host factory to the same durable
  lookup/hydration path; the local CLI reference implementation and its
  separate-process regression are complete;
- use a new TaskPacket revision to repair the Teacher browser-response privacy
  contract, then rerun the low-risk Product → Teacher → independent Test canary;
- repair the Teacher browser-response privacy contract, create a new TaskPacket
  revision, and rerun the low-risk live Product → Teacher → independent Test
  canary with RunManifest metrics;
- preserve the fail-closed decision when any role or platform rebind is absent;
- keep cross-domain parallelism, automatic repair, deployment, promotion, and
  model changes disabled until those bounded checks pass.

## Explicit non-goals for the current phase

- Do not load or replace `models/v3/policy.pt`;
- Do not install Torch on the host to make architecture checks pass;
- Do not start all professional Agents permanently;
- Do not add another Manager Agent;
- Do not pass the parent conversation as child context;
- Do not delete child-task history after completion; preserve reports and close
  or archive the session according to the host policy;
- Do not start live cross-domain orchestration before the remaining Host-backed
  role factory, process-rebind, and independent verification gates pass.

## Document maintenance rule

After each meaningful Agent Loop change, update this file first. Then update
the phase plan or navigation only when a link, invariant, or phase boundary
changed. Never copy a historical test count or old "not implemented" statement
into the current-state section. If a historical document is still useful, add
a link back here and label its claims as historical rather than deleting them.

## Historical evidence

- [Phase 1 status](PHASE_1_STATUS.md), [Phase 2 status](PHASE_2_STATUS.md),
  [Phase 3 status](PHASE_3_STATUS.md), and [Phase 4 status](PHASE_4_STATUS.md)
  are transition records;
- [Pilot 001](pilots/PILOT_001_REPORT.md) is the protocol rehearsal;
- [Pilot 002](pilots/PILOT_002_REPORT.md) is the low-risk Product pilot;
- [Pilot 003](pilots/PILOT_003_REPORT.md) is the blocked first-stage execution record;
- [Pilot 004](PILOT_004_REPORT.md) is the earlier live CLI Product → Test/Verification pilot;
- [Pilot 005](PILOT_005_REPORT.md) is the live controlled-loss/recovery pilot;
- [Pilot 006](PILOT_006_REPORT.md) is the integration, Docker and initial budget audit;
- [Pilot 007](PILOT_007_REPORT.md) is the automatic duplicate-worktree fallback
  and recalibrated budget audit;
- [Pilot 008](PILOT_008_REPORT.md) is the service-backed Docker health/failure/
  cleanup pilot;
- [Pilot 010](PILOT_010_REPORT.md) is the model-free multi-role Scheduler,
  restart/rebind, and cross-domain contract canary;
- [AGENT_LOOP_PHASE_PLAN.md](../AGENT_LOOP_PHASE_PLAN.md) defines phase entry and
  exit conditions, while this file defines the current position.
