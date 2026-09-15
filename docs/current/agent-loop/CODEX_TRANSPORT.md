# Codex Project Task Transport

This document defines the first platform-specific boundary for Agent Loop.
The request builder, lifecycle adapter, and durable Host rebind boundary are
implemented. A concrete Codex CLI bridge is available for local bounded runs;
the Desktop app's MCP bridge remains an optional host integration.

## What is created

The host may translate a validated `RunnerLaunchSpec` into one Codex project
task request using `scripts/agent_loop/codex_bridge.py`.

The request contains:

- the saved project id;
- a Git worktree target starting from the declared snapshot ref;
- TaskPacket, ContextBrief and AgentProfile repository-relative references;
- task identity, write scope and bounded budgets;
- an explicit no-child-task policy.

The child task is therefore a project task with its own session and worktree.
The parent does not pass its chat transcript. The child reads the structured
files and the repository rules from the selected snapshot.

## Concrete local bridge

`scripts/agent_loop/codex_cli_bridge.py` implements the Host Bridge contract
against the installed Codex CLI. It resolves an explicit project id, verifies
the Git snapshot, creates a detached temporary worktree (or a self-contained
clone when linked Git worktree metadata is explicitly read-only), starts
`codex exec --json`, and maps the process to create/wait/interrupt/resume/close. On close
it validates changed paths, commits only the declared scope, returns the final
commit, copies the structured final response to an ignored artifact directory,
and removes only the temporary worktree/clone it created. It also persists a
Host-owned session record under the configured registry root, including the
thread, PID, worktree, stdout/stderr and task identity. A new bridge process
can call `rebind_task` with the original `runner_ref`; it validates identity,
attaches to the existing PID/worktree and never calls `create_task`.

`scripts/agent_loop/bounded_loop.py` composes exactly one domain Owner with
one independent Test/Verification Runner. It requires the verifier to start
from the Owner final snapshot, validates the TestReport, and projects the
execution records into a RunManifest with a human gate.

## Platform boundary and remaining live proof

The repository code does not call the Codex Desktop MCP tool directly. A host
integration may implement `CodexHostBridge` with the app's create/wait/resume
and durable `rebind_task` operations and provide normalized responses to
`CodexHostTransport`, which maps them to the existing `ExternalRunnerAdapter`
event contract. The local CLI bridge is the reference implementation for the
same contract. The code-level independent-process rebind regression passes.
The current complete field evidence is [`PILOT_018_REPORT.md`](PILOT_018_REPORT.md);
Pilot 011 is historical evidence of an earlier privacy/budget stop and is not
the current canary result.

No model or reasoning override is included. The temporary model scope remains
in force. A non-Git project or a file-hash/working-tree snapshot is rejected
because the platform cannot reproduce that state safely in an isolated
worktree.

## Required host sequence

1. Resolve the saved project and confirm `isGitRepository`.
2. Validate the TaskPacket, ContextBrief, profile, budget and snapshot.
3. Call `build_codex_thread_launch` and create exactly one project task.
4. Store the returned thread id and host id as the Runner reference.
5. Persist the Host session registry entry before treating the task as running.
6. Map wait, interrupt, resume and close results to Runner events; on process
   restart use lookup/rebind and never call create/open a second time.
7. Persist every event through `RunnerExecution` before making the next call.
8. Apply `RECOVERY_POLICY.md` after a failure; never retry from the host API
   without a persisted decision.

`run_stage3_live.py` and Pilot 011 are historical compatibility artifacts only;
they use an old task, snapshot and budget and must not be used as the current
canary entry point. The first real experiment must remain one domain Owner
followed by one independent Test / Verification task. Recursive spawning and
cross-domain parallelism remain disabled.
