# Codex Project Task Transport

This document defines the first platform-specific boundary for Agent Loop.
The request builder and lifecycle adapter are implemented; the platform bridge
is still injected and not connected to the Codex app.

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

## What is deliberately not done yet

`codex_bridge.py` and `codex_host_transport.py` do not call the Codex app tool,
create a task, send a message, poll a task, or close a task. The host bridge
must still implement those calls and provide normalized responses to
`CodexHostTransport`, which maps them to the existing `ExternalRunnerAdapter`
event contract.

No model or reasoning override is included. The temporary model scope remains
in force. A non-Git project or a file-hash/working-tree snapshot is rejected
because the platform cannot reproduce that state safely in an isolated
worktree.

## Required host sequence

1. Resolve the saved project and confirm `isGitRepository`.
2. Validate the TaskPacket, ContextBrief, profile, budget and snapshot.
3. Call `build_codex_thread_launch` and create exactly one project task.
4. Store the returned thread id and host id as the Runner reference.
5. Map wait, interrupt, resume and close results to Runner events.
6. Persist every event through `RunnerExecution` before making the next call.
7. Apply `RECOVERY_POLICY.md` after a failure; never retry from the host API
   without a persisted decision.

The first real experiment must remain one domain Owner followed by one
independent Test / Verification task. Recursive spawning and cross-domain
parallelism remain disabled.
