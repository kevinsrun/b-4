# Omnigent integration

The literature module participates in the repository's single Omnigent bundle;
it is not a second standalone orchestrator. Its deterministic retrieval and
extraction service is exposed as the `literature_evidence` MCP tool.

## Install and run

From the repository root:

```bash
uv sync --all-extras
python3 install.py
omnigent run .
```

`install.py` generates `tools/mcp/literature.yaml` with machine-specific
absolute paths. The generated declaration is ignored by Git; the portable
template is `tools/mcp/literature.yaml.example`.

## Boundary

1. The orchestrator supplies a scientific question and optional bounded source
   documents.
2. The tool validates the request.
3. Optional, explicit Europe PMC retrieval obtains metadata and abstracts
   through a read-only adapter.
4. Conservative deterministic rules extract conditions, measurements,
   provenance, missing variables, and direct activity conflicts.
5. The tool returns a stateless response. It does not write research state,
   choose a candidate, or launch experiments.
6. The orchestrator or a downstream adjudicator decides whether to request
   full text, human curation, hypothesis generation, or experiment planning.

The MCP tool advertises flat, typed parameters so the model sees bounded
retrieval controls rather than an unconstrained nested object. `retrieval_enabled`
defaults to false, `max_results` is capped at 50, and `timeout_seconds` is capped
at 60.

## Trust model

`literature-derived` identifies the source class, not independent proof.
Measured quantities and author interpretation are distinct fields. Citations,
original units, missing variables, warnings, and contradictions must survive
every downstream handoff. The response always records
`candidate_decision: not-performed` and requires Codex or human adjudication.

## Known limits

- Europe PMC retrieval is abstract-first; tables, figures, supplements, and
  paywalled full text are not parsed.
- The deterministic extractor intentionally favors precision over recall.
- Cell density is preserved as CFU or OD; no conversion is attempted without a
  calibration curve.
- Molar and mass concentrations are not interconverted without molecular
  weight.
- Contradiction detection identifies direct positive/negative activity
  conflicts; quantitative disagreements remain separate records.
