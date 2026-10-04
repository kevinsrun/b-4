# Tech debt status

This ledger records remaining architectural work after the reliability hardening pass.

## Resolved in this cycle

1. **Real scientific loop.** `AgentRegistry.default()` now uses thin adapters for the repository's
   real Analysis, Critic, and Knowledge agents. Their envelopes, verdict mapping, uncertainties,
   provenance, and conservative follow-up behavior are preserved. The former local implementations
   remain available only through `AgentRegistry.legacy()` for compatibility fixtures.
2. **Evidence-driven ranking.** Literature evidence is retained with provenance and explicit,
   uncontested activity is allowed to affect candidate ranking. Retrieval remains opt-in (`local`,
   `live_ncbi`, or `hybrid`) so offline runs are deterministic.
3. **Simulator validation cost/safety.** Pass and fail validation outcomes are cached by validation
   revision, model version, and effective parameter-store hash with bounded eviction. Cached failure
   diagnostics are reconstructed fresh; explicit selftests remain uncached; caller overrides are
   frozen at adapter construction.
4. **Typed orchestration errors.** Human-readable `errors` remain for compatibility, while
   `error_details` and trace `error_info` carry stable type, retryability, and bounded details.
5. **Resume and planner fidelity.** Successful route position is persisted in `resume_agent` /
   `resume_route`; planner inputs now retain hypothesis predictions, conditions, and discriminating
   ranges. Missing planner templates are inferred from structured conditions where unambiguous.
6. **Repository hygiene.** The stale planner import path, tracked `.DS_Store`, stale workflow noqa,
   and obsolete external candidate-agent skip were removed or replaced.

## Remaining high-priority decisions

### Canonical experiment contract

The shared contract and simulator schemas still differ in units, factors, and provenance fields.
The orchestration layer currently uses the simulator contract and explicit adapters at the Analysis,
Critic, and Planner boundaries. A future contract-owner decision should promote one backend-neutral
value model and retain one legacy ingress adapter; do not delete bridges until all providers have
migrated and cross-repository fixtures pass.

### Knowledge-state persistence

The real Knowledge Agent's structured state is now carried in `ResearchState.knowledge_state` and
validated after every dispatch. The workflow lists remain a compatibility projection, while pure
mode is used for deterministic orchestration. A future persistence milestone should switch the
workflow to a configured `JsonFileStateStore` and verify the hash-chained event log on resume; this
is deliberately not implicit because it changes operator data-retention behavior.

### External operations

Live NCBI/BLAST and Omnigent LLM execution remain opt-in and credential-dependent. No credentials are
stored in repository state, and no live call is reported as successful unless its exact evidence is
captured. Full-repository Ruff still reports legacy style debt outside the Fleet-enforced checks.

### Operational follow-ups

- add durable idempotency keys for non-simulator providers;
- add persisted route/claim review UX around the shared Knowledge event log;
- decide whether to modernize planner typing style in a dedicated cleanup PR;
- run the external Omnigent manager test only in an environment with the host package installed.
