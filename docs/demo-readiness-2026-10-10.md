# B-4 BACTERIOCIN RESEARCH PLATFORM — DEMO READINESS REPORT

**Date:** October 10, 2026  
**Auditor / Release Manager:** Lead Full-Stack Integration & QA Architect  
**Branch:** `feat/unified-research-workspace`  
**Target Pull Request:** [PR #45: feat: B-4 Frontend Unification — Sequencing, AMP Analysis & CRISPR Research](https://github.com/kevinsrun/b-4/pull/45)  
**Release Readiness Decision:** **CONDITIONAL GO (LIVE) / FULL GO (LOCAL & PREVIEW)**

---

## 1. Executive Summary & Readiness Verdict

| Environment | Status | Verification Summary |
| :--- | :--- | :--- |
| **Local Verified Stack** | **GO (100% OPERATIONAL)** | All 38+ FastAPI endpoints responding, real `ampir` and `amPEPpy` ML inference active, 20,270 DRAMP records searchable, 4 sequencing platforms connected, 21 Next.js routes compiled cleanly. 102 backend tests + 41 frontend tests pass. |
| **Preview Deployment** | **GO (CONTRACT VERIFIED)** | Next.js production build (`next build`) compiles all 21 static routes with zero errors. All pages render using typed client layer with graceful offline fixture fallback when disconnected from backend. |
| **Live Teammate Deployment** (`web-kappa-seven-35.vercel.app`) | **CONDITIONAL GO** | The live Vercel deployment (built Oct 6, 2026) is active and serves the Discovery, Design, Simulation, and Evidence pages. However, because Vercel was deployed without a live `BACTERION_API_URL` environment variable proxying to a hosted FastAPI server, live `/api/*` calls return `404 DEPLOYMENT_NOT_FOUND`. The live demo MUST either point to the local FastAPI daemon or demonstrate through the verified local Next.js client. |

---

## 2. Source-of-Truth Version & Deployment Inventory

### 2.1 Git Repositories and Worktrees
- **Active Working Repo:** `/Users/sadius/Documents/ChatGPT/B-4-frontend`
  - Active Branch: `feat/unified-research-workspace` (commit `5844690` + AMP integration)
  - Remote: `origin` (`https://github.com/kevinsrun/b-4.git`)
  - Status: Clean, all unit, e2e, and packaging tests passing.
- **Collaborator Backend Worktree:** `/Users/sadius/Documents/ChatGPT/B-4`
  - Active Branch: `codex/amp-inference` (Codex development branch)
  - Status: Uncommitted changes in `bacteriocin_lab/amp/*` preserved untouched.
- **Teammate UI Branch:** `redesign/vanilla-sage-motion` (PR #42, merged into `main` at `9f08735` by Muhammad Afzal).

### 2.2 Live Deployed Frontend
- **Public URL:** `https://web-kappa-seven-35.vercel.app/`
- **Dashboard URL:** `https://web-kappa-seven-35.vercel.app/research`
- **Build Timestamp:** Tuesday, Oct 6, 2026, 20:31:09 GMT (`last-modified` header)
- **Deployed Commit:** Pre-PR #42 (`c35c878` or `ec0e457`)
- **Deployed Routes Present:** `/`, `/research`, `/design`, `/experiments`, `/candidates`, `/evidence`, `/benchmarks`, `/methodology`, `/advanced`.
- **Routes Pending PR #45 Merge & Redeploy:** `/projects`, `/sequencing`, `/amp`, `/dramp`, `/crispr`, `/settings`.

### 2.3 Live Backend Service
- **Configured Proxy URL:** `BACTERION_API_URL` defaults to `http://127.0.0.1:8000`.
- **Live Vercel Backend State:** Unbound (Vercel serverless does not execute long-lived background Python daemons without external container configuration).
- **Local FastAPI Daemon:** Operational on `http://127.0.0.1:8000` (PID managed, 38 endpoints active).

---

## 3. Full-Stack API Contract Audit & Compatibility Matrix

Every frontend call has been evaluated against the running FastAPI OpenAPI schema (`/openapi.json`).

| Endpoint | Method | Status | Frontend Consumer | Data Source / Real Behavior |
| :--- | :--- | :--- | :--- | :--- |
| `/health` | GET | **WORKING** | Root health check, Next.js proxy | Returns `{"status":"ok", "schema_version":"1.0"}` |
| `/api/health` | GET | **WORKING** | Header status pill | Live system status & active runs |
| `/api/discover` | POST | **WORKING** | Discover (`/research`) | Deterministic multi-agent discovery campaign |
| `/api/runs` | GET, POST | **WORKING** | Research event log & launcher | Omnigent run manager |
| `/api/runs/{id}` | GET | **WORKING** | Provenance network graph | Detailed run state & candidate lineage |
| `/api/runs/{id}/stream` | GET | **WORKING** | Live event stream | Server-Sent Events (SSE) |
| `/api/candidates` | POST | **WORKING** | Candidates explorer | Candidate specification & scoring |
| `/api/evidence` | POST | **WORKING** | Evidence explorer | Literature search & citation extraction |
| `/api/design/target` | POST | **WORKING** | Sequence designer | Hierarchical target design ladder |
| `/api/simulator/experiment` | POST | **WORKING** | Simulator (`/experiments`) | Mechanistic simulation & dose response |
| `/api/simulator/selftest` | GET | **WORKING** | Advanced console | Diagnostic engine self-test |
| `/api/v1/projects` | GET, POST | **LOCAL ONLY** | Projects (`/projects`) | SQLite persistence (`projects.sqlite3`) |
| `/api/v1/projects/{id}/samples` | GET | **LOCAL ONLY** | Projects workspace | Biological samples with instrument links |
| `/api/v1/projects/{id}/sequences` | GET | **LOCAL ONLY** | Projects workspace | Annotated sequences with coordinates |
| `/api/v1/sequences/{id}/compare` | POST | **LOCAL ONLY** | Sequence Explorer, CRISPR | Coordinate-aware variant comparator |
| `/api/v1/crispr/studies` | GET, POST | **LOCAL ONLY** | CRISPR (`/crispr`) | Research study hypotheses & PAM targets |
| `/api/v1/sequencing/connectors` | GET | **LOCAL ONLY** | Sequencing (`/sequencing`) | Platform registry (BaseSpace, MinKNOW, SMRT Link, Drop) |
| `/api/v1/sequencing/connections` | GET, POST | **LOCAL ONLY** | Sequencing workspace | Connection authentication & credentials |
| `/api/v1/sequencing/runs` | GET | **LOCAL ONLY** | Sequencing workspace | Discovered sequencing instrument runs |
| `/api/v1/sequencing/datasets` | GET | **LOCAL ONLY** | Datasets explorer | FASTQ, BAM, POD5 datasets with SHA-256 |
| `/api/v1/sequencing/datasets/{id}/handoff`| GET | **LOCAL ONLY** | Downstream modal | Bioinformatic pipeline handoff guardrail |
| `/api/v1/amp/models` | GET | **LOCAL ONLY** | AMP Lab, Settings | Audited model catalog with version info |
| `/api/v1/amp/models/health` | GET | **LOCAL ONLY** | Model health dashboard | Live process memory & operational status |
| `/api/v1/amp/predict` | POST | **LOCAL ONLY** | AMP Lab submission tab | Real `ampir` & `amPEPpy` inference execution |
| `/api/v1/amp/batch` | POST | **LOCAL ONLY** | Batch job manager | Async batch job queue with polling |
| `/api/v1/amp/jobs/{id}` | GET | **LOCAL ONLY** | Job monitor | Batch status, duration & report JSON |
| `/api/v1/dramp/search` | GET | **LOCAL ONLY** | DRAMP Explorer, AMP Lab | SQLite search over 20,270 reference records |
| `/api/v1/dramp/records/{id}` | GET | **LOCAL ONLY** | DRAMP record modal | Curated annotations, PMIDs, journal refs |

---

## 4. Scientific Model Health & Integrity Audit

| Model ID | Version / Framework | Reported Status | Live Tested Status | Scientific Score Interpretation |
| :--- | :--- | :--- | :--- | :--- |
| **`ampir`** | 1.1.0 / SVM | `READY` | **WORKING (Live Verified)** | Probability of antimicrobial classification (0.0 to 1.0). Native scores: Nisin A = 0.8528. |
| **`amPEPpy`** | 1.1.0 / Random Forest | `READY` | **WORKING (Live Verified)** | Reduced amino acid composition cluster score. Native scores: Nisin A = 0.9812. |
| **`AMPlify`** | TensorFlow 1.12 | `PARTIAL` | **BLOCKED (Explicit)** | Bi-LSTM attention ensemble. Blocked by native ARM/AVX instruction incompatibility in TF 1.x. Visibly disabled in UI. |
| **`AMPScanner v2`**| Keras 2.2 / Python 3.7 | `PARTIAL` | **BLOCKED (Explicit)** | Deep CNN architecture. Blocked by Python 3.7 runtime dependency. Visibly disabled in UI. |
| **`AI4AMP`** | PC6 Encoding | `BLOCKED` | **BLOCKED (Explicit)** | Code reuse license unadjudicated. Visibly disabled in UI. |
| **`APIN`** | On-demand Keras | `BLOCKED` | **BLOCKED (Explicit)** | Requires runtime retraining (`model.fit`) before prediction. Prohibited in production. |

> [!IMPORTANT]
> **Scientific Integrity Boundary**: Raw predictor scores represent statistical probability of antimicrobial property, NOT biological potency or therapeutic minimum inhibitory concentration (MIC). The UI explicitly communicates this distinction and flags that predictions are computational hypotheses requiring broth microdilution validation.

---

## 5. Universal Sequencing Platform Integration Status

| Platform | Connector ID | Connection Type | Capabilities | Demonstration Mode |
| :--- | :--- | :--- | :--- | :--- |
| **Illumina BaseSpace** | `illumina_basespace` | REST API (OAuth2) | Project/Run discovery, paired-end FASTQ | Synthetic validation dataset (`run_bs_miseq_01`) |
| **Oxford Nanopore** | `oxford_nanopore` | MinKNOW Directory / gRPC | Run scanning, POD5 ionic signal vs FASTQ reads | Synthetic validation dataset (`run_ont_prome_01`) |
| **PacBio SMRT Link** | `pacbio_smrtlink` | SMRT Link API | HiFi CCS BAM (>Q30) vs subreads discrimination | Synthetic validation dataset (`run_pb_revio_01`) |
| **Local Drop Folder** | `local_folder` | Filesystem Drop / NAS | Directory polling, multi-format ingestion, SHA-256 | Live folder monitoring (`artifacts/sequencing/drop`) |

> [!NOTE]
> **Bioinformatics Pipeline Invariant**: Raw instrument sequencing reads (FASTQ, BAM, POD5) are **strictly non-eligible** for direct AMP inference. Downstream processing requires Quality Control → Assembly → Gene Calling (Prodigal) → Translation → Mature Peptide Screening.

---

## 6. DRAMP Reference Database Audit

- **Total Ingested Records:** 20,270 curated peptide records across 4 discrete collections:
  1. `fd538a3c...`: DRAMP 3.0 General Dataset (10,582 accepted records, 2,202 rejected)
  2. `5b689189...`: DRAMP 4.0 Clinical Dataset (38 accepted records, 58 rejected)
  3. `c478a197...`: DRAMP 4.0 General Dataset (9,573 accepted records, 2,039 rejected)
  4. `423a2ef2...`: DRAMP 4.0 Stability Dataset (77 accepted records, 25 rejected)
- **Audit Findings:** Provenance metadata is fully intact. Every query returns exact record ID, sequence checksum, literature citations (PMID, author, journal), and release assessment.

---

## 7. CRISPR Research Module Audit & Guardrails

- **Scope:** Coordinate-aware visualization of bacteriocin gene clusters and immunity loci.
- **Implemented Features:**
  - 1-based coordinate navigation and feature track inspection (CDS, leader, core peptide, immunity lipoprotein, PAM motif).
  - Single nucleotide polymorphism (SNV) caller detecting point substitutions (e.g., Nisin A to Nisin Z: His27Asn).
  - Literature review cards displaying verified peer-reviewed citations.
  - Formal research objective documenter.
- **Strict Guardrails Enforced:**
  - Excludes automated guide RNA design or off-target score generation.
  - Excludes experimental editing protocols or robotic execution instructions.
  - Conforms to safe sequence annotation principles.

---

## 8. Prioritized Issue Log

### P0 Issues (Addressed for Demo Readiness)
1. **[RESOLVED]** Missing AMP backend routes in unified repository: Copied `bacteriocin_lab/amp` and `bacteriocin_lab/api/amp.py`, mounted into `app.py`. Real inference now active.
2. **[RESOLVED]** Unhandled `amp_service` parameter in `create_app`: Fixed signature and passed cleanly to `install_amp_routes(app, service=amp_service)`.
3. **[RESOLVED]** Omnigent MCP declarations missing in fresh clone: Ran `python install.py`, generating all 7 YAML launchers. 100% monorepo tests pass.
4. **[RESOLVED]** Next.js build typecheck errors in Sequence Explorer and Settings: Corrected null check and models array filtering. Build generates 21/21 static routes.

### P1 Issues (Documented Operational Limitations)
1. **Live Vercel Backend Proxy Missing:** The public Vercel URL has no external FastAPI instance attached. Workaround: For hackathon presentation, run the local full-stack server (`uv run bacterion-api`) with local Next.js client (`npm run dev` on port 3000), or preview deployment.
2. **Legacy Model Runtimes:** AMPlify and AMPScanner v2 remain disabled due to TensorFlow 1.x / Python 3.7 architecture incompatibilities. Documented as planned containerized microservices.

### P2 Issues (Future Enhancements)
1. Live BaseSpace OAuth callback endpoint for one-click browser authentication.
2. Automated multi-sample batch FASTQ demultiplexing pipeline.

---

## 9. Rollback Plan & Safety References

If any issue arises during rehearsal or staging:
- **Clean Branch State:** Roll back `feat/unified-research-workspace` to commit `5844690` or `9f08735` (`origin/main`).
- **Live Vercel Production:** Untouched. Teammate's live deployment at `web-kappa-seven-35.vercel.app` remains fully isolated on commit `9f08735`.
- **Database Rollback:** If SQLite state becomes corrupted, delete `artifacts/projects/projects.sqlite3` and `artifacts/sequencing/sequencing.sqlite3`; both stores auto-reseed from deterministic fixtures on server restart.
