# Agent Loop Current State

> **Canonical current-state document**
> **Last verified:** 2026-09-14
> **Status:** Phase 4 pilot gate / pre-Phase 5 real transport
> **Three-stage roadmap:** [`IDEAL_LOOP_3_STAGE_PLAN.md`](IDEAL_LOOP_3_STAGE_PLAN.md)

This is the only document that describes the current Agent Loop status. Phase
status files and pilot reports are historical records and must not be used to
infer the latest implementation state.

## One-line status

The context contracts, deterministic control plane, evidence gates, Docker
canonical test entry point, bounded recovery policy, Codex project-task request
builder, and injected Host Transport lifecycle mapping are implemented and
verified. A real Codex host bridge, child task, automatic orchestration, and Git
integration are not connected.

## Verified evidence

- Architecture gate: 67 deterministic Agent Loop tests passed;
- Docker canonical pytest: 105 tests passed, with 2 existing deprecation warnings;
- Documentation links: 149 local links passed;
- Python syntax gate: 95 files passed;
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
| Codex project-task request | builder implemented | `codex_bridge.py`, `CODEX_TRANSPORT.md` |
| Host lifecycle mapping | implemented with injected bridge | `codex_host_transport.py` |
| Real Codex create / wait / resume / close | platform bridge not connected | host API integration is missing |
| Main scheduler calling the real platform | not implemented | no automatic runtime loop |
| Worktree merge, conflict and rollback | not implemented | integration gate is missing |
| Real Owner and independent Test child tasks | not yet proven | Phase 4 exit condition |
| Cross-domain parallel orchestration | intentionally deferred | Phase 6 |

## Actual execution boundary

```text
validated TaskPacket + ContextBrief
        -> deterministic LaunchSpec
        -> Codex project-task request builder
        -/-> real Codex child task        [not connected]
        -/-> Test child task              [not connected]
        -/-> automatic recovery           [policy only]
```

The current code can validate what a child task would receive and map an
injected bridge through the Runner lifecycle. It cannot yet create the child
task, poll its real status, collect its report, or close the session through
the Codex host API.

## Remaining work in priority order

### P0: prove one real bounded loop

Pilot 003 attempted the bounded Product path, but did not exit PASS: the Product
change and Main Docker review passed, while the independent Test/Verification
executor was blocked by a Windows setup failure. Repeat the same bounded path
after the executor and Git baseline blockers are resolved:

1. resolve the saved project and exact snapshot;
2. create one Product child task from `CodexThreadLaunch`;
3. collect one structured ChangeReport;
4. hand off to one independent Test / Verification child task;
5. run the declared Docker verification and collect TestReport;
6. persist every platform event in RunManifest and close both tasks.

No recursive spawning, cross-domain parallelism, automatic repair, or model
change is allowed in this experiment.

### P1: make failure handling real

- map host task states to RunnerEvent;
- apply `RECOVERY_POLICY.md` only after persisting the decision;
- prove one controlled Runner loss and one bounded resume;
- classify Docker ownership, health, cleanup and service failures;
- record actual model calls, tokens, elapsed time and stop reason.

### P2: integrate code safely

- define the worktree-to-main integration manifest;
- verify changed paths against the final snapshot;
- handle conflicts and partial success at a human gate;
- support recoverable rollback without touching unrelated user changes;
- require two independent successful validation rounds.

## Explicit non-goals for the current phase

- Do not load or replace `models/v3/policy.pt`;
- Do not install Torch on the host to make architecture checks pass;
- Do not start all professional Agents permanently;
- Do not add another Manager Agent;
- Do not pass the parent conversation as child context;
- Do not delete child-task history after completion; preserve reports and close
  or archive the session according to the host policy;
- Do not start cross-domain orchestration before P0 and P1 evidence exists.

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
- [AGENT_LOOP_PHASE_PLAN.md](../AGENT_LOOP_PHASE_PLAN.md) defines phase entry and
  exit conditions, while this file defines the current position.
