# B-4 HACKATHON DEMONSTRATION RUNBOOK

**Target Date:** October 10, 2026  
**Demonstration Scenario:** End-to-End Bacteriocin Discovery, Universal Sequencing, AMP Inference & CRISPR Locus Analysis  
**Estimated Demo Duration:** 5–7 minutes  
**Primary Demonstrator:** B-4 Engineering Team  

---

## 1. Pre-Flight Preparation (Execute 15 Minutes Before Presentation)

### Step 1.1: Start the Scientific Backend
Open a terminal in the project directory:
```bash
cd /Users/sadius/Documents/ChatGPT/B-4-frontend
uv run python -m bacteriocin_lab.api --port 8000
```
*Expected output: `Uvicorn running on http://127.0.0.1:8000`*

### Step 1.2: Verify Backend Health via Curl
In a second terminal:
```bash
curl -s http://127.0.0.1:8000/health
```
*Expected response: `{"status":"ok","schema_version":"1.0","simulator_version":"0.1.0",...}`*

```bash
curl -s http://127.0.0.1:8000/api/v1/amp/models/health | jq '.models[0].status'
```
*Expected response: `"READY"`*

### Step 1.3: Start the Web Client
In a third terminal:
```bash
cd /Users/sadius/Documents/ChatGPT/B-4-frontend/web
npm run dev -- -p 3000
```
*Expected output: `Ready in ... on http://localhost:3000`*

### Step 1.4: Open Chrome at http://localhost:3000
- Ensure zoom level is set to 100%.
- Dark/light system theme renders in the branded "vanilla-and-sage" palette.

---

## 2. Step-by-Step Demonstration Script

### Scene 1: Platform Overview & Discovery Dashboard (1 Minute)
- **URL:** `http://localhost:3000/research`
- **Action:**
  1. Highlight the top navigation bar showing the unified workflow stages: **Discover**, **Projects**, **Sequencing**, **AMP Lab**, **DRAMP**, **CRISPR**, **Evidence**.
  2. Point out the header status pill: "Connected" with low latency.
- **Talking Points:**
  > *"B-4 is an end-to-end computational biology platform designed to discover, isolate, and characterize bacteriocins—ribosomally synthesized antimicrobial peptides produced by bacteria to inhibit competing pathogens."*

---

### Scene 2: Project-Centered Research Workspace (1.5 Minutes)
- **URL:** Click **Projects** in top navigation (`http://localhost:3000/projects`)
- **Action:**
  1. Select the pre-seeded research project: **"Lactococcus lactis Nisin Biosynthetic Cluster & Immunity"** (`proj_lactis_nisin`).
  2. Switch to the **Biological Samples** tab: View sample `samp_llactis_atcc11454` isolated from dairy starter cultures.
  3. Switch to the **Sequences** tab: Highlight annotated sequence `seq_nisin_cluster_ref` (480 bp) with 4 discrete feature annotations.
  4. Switch to the **Lineage Flow** tab: Walk through the visual provenance flow diagram connecting Instrument Run → FASTQ Dataset → Genome Assembly → Open Reading Frame → Candidate Peptide.
- **Talking Points:**
  > *"Rather than treating sequencing and peptide prediction as disconnected tools, B-4 centers research around stable projects. Every sample, sequencing run, assembled contig, and predicted peptide retains an unbroken lineage in our relational SQLite store."*

---

### Scene 3: Universal Sequencing Integration & Analysis Handoff (1.5 Minutes)
- **URL:** Click **Sequencing** in top navigation (`http://localhost:3000/sequencing`)
- **Action:**
  1. Overview Tab: Show 4 connected platforms—**Illumina BaseSpace**, **Oxford Nanopore MinKNOW**, **PacBio SMRT Link**, and **Laboratory Drop Folder**.
  2. Runs Tab: Select MiSeq Run **`run_bs_miseq_01`** (`Lactococcus_lactis_WGS_Run01`).
  3. Datasets Tab: View the paired-end FASTQ datasets (`ds_bs_miseq_r1` and `ds_bs_miseq_r2`). Point out the SHA-256 byte verification status.
  4. Click **"Analyze Dataset"** on the FASTQ dataset: The **Downstream Analysis Handoff Modal** appears.
- **Talking Points:**
  > *"A critical scientific guardrail in B-4: raw instrument sequencing reads are strictly non-eligible for direct antimicrobial peptide classification. The platform enforces a multi-stage bioinformatic pipeline: Quality Control, Assembly, Gene Calling via Prodigal, and Translation before any sequence is passed to predictive models."*

---

### Scene 4: Real AMP Prediction & Multi-Model Consensus (1.5 Minutes)
- **URL:** Click **AMP Lab** in top navigation (`http://localhost:3000/amp`)
- **Action:**
  1. Submit Tab: Load the demo sequence for **Nisin A Core Peptide**:
     ```
     ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK
     ```
  2. Model Selection: Note that **ampir 1.1.0** and **amPEPpy 1.1.0** are operational and selected.
  3. Point out **AMPlify** and **AMPScanner v2**: Visibly disabled with clear badges explaining legacy runtime incompatibility.
  4. Click **"Execute Predictions"**: Watch the live API call resolve.
  5. Results Tab: Show the consensus classification (**AMP Positive**).
     - **ampir Score:** `0.8528` (High confidence antimicrobial)
     - **amPEPpy Score:** `0.9812` (High confidence antimicrobial)
  6. Point out the scientific callout banner: *"Prediction scores represent statistical probability of antimicrobial property, not biological potency (MIC). Predictions are computational hypotheses requiring experimental broth microdilution validation."*
- **Talking Points:**
  > *"B-4 connects real machine learning inference engines. Here, ampir and amPEPpy independently classify the core lantibiotic with high consensus. We explicitly disable models that cannot be verified locally rather than fabricating scores."*

---

### Scene 5: Official DRAMP Database Search & Literature Evidence (1 Minute)
- **URL:** Click **DRAMP** in top navigation (`http://localhost:3000/dramp`)
- **Action:**
  1. Search for Record ID: **`DRAMP00001`**.
  2. View the resulting reference cards across discrete collections: **Variacin** from *Micrococcus varians*.
  3. Switch filter to **All Datasets Combined**: Search for sequence or view Nisin A reference matches (`DRAMP18174`).
  4. Inspect the reference modal showing PubMed IDs (`PMID: 8633879`), author names, journal titles (*Appl Environ Microbiol*), and Figshare snapshot provenance.
- **Talking Points:**
  > *"Researchers can benchmark their discovered candidates against 20,270 curated peptide records across four discrete DRAMP 3.0 and 4.0 benchmark datasets, complete with exact literature citations and source checksums."*

---

### Scene 6: CRISPR Locus Explorer & Variant Analysis (1 Minute)
- **URL:** Click **CRISPR** in top navigation (`http://localhost:3000/crispr`)
- **Action:**
  1. View the **NisI Immunity Gene Promoter** study (`crispr_nisi_immunity_01`).
  2. Interact with the **Visual Sequence Explorer**:
     - Toggle between **Letters** (residue view) and **Compact** density modes.
     - Move the coordinate window slider.
     - Hover over feature tracks: `nisA` CDS, Core Peptide, and `nisI` immunity lipoprotein.
  3. Variant Comparison: Click **"Run Variant Comparison"** comparing the reference locus against a natural single-nucleotide variant query.
  4. Review the SNV call: Point substitution detected with exact 1-based coordinate, reference allele, and consequence interpretation.
- **Talking Points:**
  > *"In our CRISPR research module, researchers explore natural locus variations and self-immunity mechanisms. The Visual Sequence Explorer provides coordinate-aware feature tracks and variant calling while strictly respecting safety boundaries—excluding unvalidated experimental editing instructions."*

---

## 3. Emergency Troubleshooting & Fallback Plan

| Symptom | Root Cause | Instant Recovery Action |
| :--- | :--- | :--- |
| **Header status shows "Disconnected"** | Port 8000 server stopped | In terminal: `uv run python -m bacteriocin_lab.api --port 8000` |
| **Port 8000 already in use** | Stray Python process | In terminal: `lsof -ti :8000 \| xargs kill -9` then restart server |
| **Port 3000 already in use** | Stray Node process | In terminal: `npx kill-port 3000` then `npm run dev -- -p 3000` |
| **Network failure or external API timeout** | Wi-Fi dropped | The platform automatically falls back to typed local SQLite and fixtures without breaking the UI |
| **Model inference slow** | CPU contention | Pre-cached queries in `artifacts/amp/amp.sqlite3` return in `<10ms` for demo sequences |
