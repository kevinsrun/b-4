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

## NCBI E-Utilities & BLAST Integration

The Evidence Agent provides live access to the NCBI E-utilities (PubMed, PMC, Protein, FASTA) and the official NCBI BLAST URL API for protein sequence similarity (`blastp`).

### How BLAST Works in the System

1. **Submission**: Sequence is validated and normalized (rejecting invalid characters and malformed headers), then submitted via `submit_blastp` to `https://blast.ncbi.nlm.nih.gov/Blast.cgi` with `PROGRAM=blastp` and `DATABASE=nr` (or `swissprot`). NCBI assigns a Request ID (`RID`) and estimated wait time (`RTOE`).
2. **Polling**: The system respects the `RTOE` on the initial wait, then checks status via `check_blast_status(rid)` using bounded intervals (`BLAST_POLL_INTERVAL_SECONDS`, default 5s) and bounded attempts/timeout (`BLAST_TIMEOUT_SECONDS`, default 60s).
3. **Retrieval & Parsing**: When status is `READY`, XML output is retrieved via `fetch_blast_results(rid)` and parsed deterministically into structured records (`accession`, `title`, `organism`, `identity_percent`, `alignment_length`, `e_value`, `bit_score`, etc.).
4. **Novelty Estimation**: `summarize_blast_similarity(result)` calculates a heuristic novelty signal (`low`, `moderate`, `high`, `unknown`).

### Provenance and Scientific Caveats

- **Database-derived provenance**: BLAST results carry strictly `provenance: "database-derived"` and `source: "ncbi_blast"`. They are **never** labeled as `literature-derived` or `simulation-derived`.
- **Similarity != Biological Validation**: A sequence hit in NCBI Protein indicates sequence homology, **not** experimental antimicrobial activity or physical expression. Candidates must still undergo simulation and wet-lab testing.

### Agent Tool Usage

Both the Evidence Agent and the Candidate Generation Agent can execute sequence similarity searches:

```python
from bacteriocin_lab.agents.evidence import LiteratureEvidenceAgent, blastp

# 1. Direct tool usage
result = blastp("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK", database="nr", candidate_id="nisin_a")

# 2. Via LiteratureEvidenceAgent
evidence_agent = LiteratureEvidenceAgent()
sim = evidence_agent.check_sequence_similarity("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK", candidate_id="cand_1")

# 3. Via CandidateGenerationAgent
from bacteriocin_lab.agents.candidate import CandidateGenerationAgent
cand_agent = CandidateGenerationAgent()
sim = cand_agent.check_candidate_similarity(candidate_id="cand_1", sequence="ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK")
```

### Rate Limiting, Safety & Concurrency

- **Concurrency**: Bounded by `BLAST_MAX_CONCURRENT_REQUESTS` (default: 2).
- **Run Budget**: Bounded by `MAX_BLAST_QUERIES_PER_RUN` (default: 5) to prevent autonomous loops from unbounded submissions.
- **Caching**: Cached in memory by sequence, database, and parameters to avoid duplicate remote submissions.

### Environment Configuration & Credentials

Copy `.env.example` to `.env` to configure settings:

```bash
# E-utilities
NCBI_API_KEY=your_key_here
NCBI_EMAIL=user@example.com
NCBI_TOOL=b4-bacteriocin-lab

# BLAST
BLAST_TIMEOUT_SECONDS=60.0
BLAST_POLL_INTERVAL_SECONDS=5.0
BLAST_MAX_POLL_ATTEMPTS=30
BLAST_MAX_CONCURRENT_REQUESTS=2
MAX_BLAST_QUERIES_PER_RUN=5
BLAST_CACHE_ENABLED=true
```

### Live BLAST Smoke Test

An opt-in live test is provided against live NCBI BLAST servers:

```bash
RUN_LIVE_NCBI_BLAST_TESTS=1 uv run pytest bacteriocin_lab/tests/evidence/test_blast.py -k test_live_ncbi_blast_smoke
```

