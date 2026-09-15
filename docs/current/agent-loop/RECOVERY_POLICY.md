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

For `RETRY_TEST` and `RETURN_TO_OWNER`, `RunnerExecution.recover()` additionally
requires a valid `RetryLearningDelta`. A missing, malformed, repeated, or
unapproved delta changes the action to `STOP_NO_LEARNING` and requires human
review. `RESUME_SAME_RUNNER` is a recovery of the same logical attempt and is
recorded separately; it does not require inventing a Lesson.

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
7. A model-spending retry requires a failure signature, a changed reference,
   preflight checks, and an explicit fallback action. The same failure
   signature with unchanged preconditions and the same delta is stopped.
8. A successful retry writes only a candidate-only ExperienceManifest and
   Lesson when the execution has an evidence journal; it never injects the
   candidate into a later ContextBrief automatically.
9. Savings are recorded as `unavailable` unless a caller supplies a measured
   counterfactual baseline. Zero is not interpreted as zero cost saved.

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

The Retry Learning Gate is implemented in
`scripts/agent_loop/retry_learning.py`. It is called by
`RunnerExecution.recover()`, journals `lesson_created`, `lesson_applied`,
`learning_delta` and savings fields, and generates candidate-only experience
after a successful fallback. E2/E3 promotion remains an explicit later step.
