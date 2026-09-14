# Agent Loop Recovery Policy

This policy is deterministic. It decides whether a failed step may continue;
it does not launch a model, a child task, or Docker.

## Decision rules

| Situation | Action | Model call | Human gate |
|---|---|---:|---:|
| PASS | COMPLETE | no | no |
| CANCELLED | STOP | no | no |
| Invalid or incomplete TestReport | WAIT_HUMAN | no | yes |
| Budget exhausted | STOP_BUDGET | no | yes |
| Lost runner, resume budget available | RESUME_SAME_RUNNER | yes | no |
| Lost runner, resume limit reached | WAIT_HUMAN | no | yes |
| Docker or environment failure | WAIT_HUMAN | no | yes |
| Permission or external dependency | WAIT_HUMAN | no | yes |
| Control-plane protocol failure | STOP | no | no |
| Flaky test within attempt limit | RETRY_TEST | no | no |
| Owner defect within attempt limit | RETURN_TO_OWNER | yes | no |
| Any failure at attempt limit | WAIT_HUMAN | no | yes |

## Safety invariants

1. A failed test never starts an unbounded loop.
2. Environment failures never spend another model call automatically.
3. A lost runner can resume only the same responsibility chain; it cannot
   silently become a new owner task.
4. An invalid report blocks completion before any retry decision.
5. A protocol failure is stopped for inspection instead of being retried.
6. `RunnerExecution.recover()` persists the decision and counters in the
   ExecutionJournal before it invokes a bounded resume; the caller must project
   the same entry into the RunManifest before executing any later action.

## Current implementation boundary

`scripts/agent_loop/recovery.py` implements the policy, while
`RunnerExecution.recover()` connects it to the per-attempt ExecutionJournal
and the existing bounded `resume()` operation. Pilot 005 provided live evidence
that a persisted Codex CLI rollout can survive one injected loss and resume on
the same Runner. An earlier immediate-loss attempt failed with Codex's
`no rollout found` because persistence had not completed; it correctly stopped
instead of fabricating recovery. The local CLI bridge now exposes token and
elapsed metrics; Pilot 006 recorded them and correctly stopped when the
TaskPacket budget was exceeded.
