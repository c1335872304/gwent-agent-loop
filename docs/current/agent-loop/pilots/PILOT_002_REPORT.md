# Pilot 002: Product stale-state recovery

## Conclusion

Pilot 002 passed. The Product Owner changed one frontend file so a fresh game snapshot clears pending actions, selected card state, and the acted-turn marker. The change does not modify Core actions, HTTP contracts, Teacher behavior, models, or Trainer code.

## Observed problem

`GamePage` reloads the current state after a `stale_state` response, but the old local interaction state was not cleared. A pending action or selected card from the previous revision could therefore remain active after reload.

## Change

The successful `load()` path now resets:

- `pendingActions`
- `selectedCardId`
- `actedTurn`

Changed path: `apps/web/frontend/src/pages/GamePage.tsx`

## Evidence

| Check | Result |
|---|---|
| Frontend production build | PASS: `npm run build` |
| Canonical Docker pytest | PASS: 62 tests |
| Architecture gate | PASS: 25 Agent Loop tests |
| Host backend pytest | INCONCLUSIVE: missing `pytest-asyncio`, classified as environment failure |
| Contract/model/Core scope | PASS: unchanged |
| Docker cleanup | PASS: `run --rm`, no global compose cleanup |

## Agent Loop result

The manual Owner to Test/Verification handoff worked with a bounded scope and preserved snapshot evidence. Docker is now the authoritative Python pytest environment through `python scripts/check.py docker-test`. This pilot still does not prove a real Codex child session or automatic resume; the external Runner remains the next stage.
