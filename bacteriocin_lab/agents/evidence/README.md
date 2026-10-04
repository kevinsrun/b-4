# B⁴ Literature & Evidence Agent

A bounded, stateless evidence layer for an Omnigent-orchestrated bacteriocin discovery system. The agent retrieves literature metadata/abstracts, extracts reported experimental conditions and antimicrobial responses, preserves provenance and contradictory findings, and exposes explicit uncertainty. It does **not** select candidates or run experiments.

## What is implemented

- Strict JSON-compatible Pydantic request/response models and exported JSON Schemas.
- Read-only Europe PMC retrieval adapter with result and timeout limits.
- Conservative deterministic extraction for concentrations, cell density, pH, temperature, medium, incubation time, assay type, activity, MIC, inhibition zones, log reduction, and percentage response.
- Safe unit normalization where dimensional equivalence is exact; original units otherwise remain authoritative.
- Stable evidence, query, and contradiction IDs.
- Explicit missing-variable and knowledge-gap reporting.
- Direct positive/negative activity contradiction detection without silent reconciliation.
- CLI, Python API, and bounded MCP/Omnigent boundaries.
- Synthetic examples and deterministic tests.

## Quick start

```bash
uv sync --extra dev
uv run b4-literature-evidence --input examples/queries/nisin_listeria.json
```

Enable live literature retrieval in a request only when network access is intended:

```json
{
  "question": "nisin activity against Listeria monocytogenes under acidic conditions",
  "bacteriocin": "nisin",
  "target_organism": "Listeria monocytogenes",
  "retrieval": {
    "enabled": true,
    "sources": ["europe_pmc"],
    "max_results": 10,
    "timeout_seconds": 15
  }
}
```

Run validation:

```bash
uv run ruff check .
uv run pytest
```

Regenerate schemas and the example output:

```bash
uv run python scripts/export_schemas.py
uv run b4-literature-evidence \
  --input examples/queries/nisin_listeria.json \
  --output examples/output/nisin_listeria.json
```

## Trust model

`literature-derived` identifies the source class, not independent proof. Each record distinguishes measured values from author interpretation and includes its source, locator, excerpt, extraction method, confidence, and missing variables. Automated extraction can be incomplete or wrong; downstream agents must retain provenance and uncertainty.

See [Omnigent integration](OMNIGENT.md) for orchestration and current runtime limitations.
