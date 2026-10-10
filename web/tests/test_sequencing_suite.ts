/**
 * Comprehensive verification suite for Universal Sequencing Integration frontend.
 *
 * Verifies:
 * 1. Platform Connectors registry (Illumina BaseSpace, Oxford Nanopore, PacBio, Local Drop)
 * 2. Capability matrix and file format specifications
 * 3. BaseSpace contracts: FASTQ pairs, run metadata, project associations
 * 4. Oxford Nanopore: MinKNOW summary metrics, POD5 raw signal vs FASTQ long reads
 * 5. PacBio SMRT Link: HiFi CCS BAM (>Q30) vs subreads
 * 6. Scientific Analysis Handoff invariant: Raw reads must NEVER be directly AMP eligible
 * 7. Multi-stage bioinformatics pipeline enforcement (QC -> Assembly -> ORF -> Translation -> AMP)
 * 8. API client offline fallback fidelity
 */

import assert from "node:assert";
import {
  FIXTURE_CONNECTORS,
  FIXTURE_CONNECTIONS,
  FIXTURE_RUNS,
  FIXTURE_DATASETS,
  FIXTURE_HANDOFFS,
} from "../lib/sequencing-fixtures.ts";
import {
  fetchConnectors,
  fetchConnections,
  fetchRuns,
  fetchDatasets,
  fetchAnalysisHandoff,
  initiateImport,
} from "../lib/sequencing-api.ts";

async function runTests() {
  console.log("=================================================");
  console.log("B-4 UNIVERSAL SEQUENCING INTEGRATION SUITE");
  console.log("=================================================\n");

  let passed = 0;
  let total = 0;

  async function test(name: string, fn: () => void | Promise<void>) {
    total++;
    try {
      await fn();
      console.log(`✓ [PASS] ${name}`);
      passed++;
    } catch (err) {
      console.error(`✗ [FAIL] ${name}:`, err);
      throw err;
    }
  }

  // 1. Connectors registry
  await test("Connectors registry contains all 4 major platform ecosystems", () => {
    assert.strictEqual(FIXTURE_CONNECTORS.length, 4);
    const ids = FIXTURE_CONNECTORS.map((c) => c.connector_id);
    assert.ok(ids.includes("illumina_basespace"));
    assert.ok(ids.includes("oxford_nanopore"));
    assert.ok(ids.includes("pacbio_smrtlink"));
    assert.ok(ids.includes("local_folder"));
  });

  // 2. Vendor file format specifications
  await test("Each connector defines appropriate sequencing file extensions", () => {
    const illumina = FIXTURE_CONNECTORS.find((c) => c.connector_id === "illumina_basespace")!;
    assert.ok(illumina.supported_file_types.includes(".fastq.gz"));

    const ont = FIXTURE_CONNECTORS.find((c) => c.connector_id === "oxford_nanopore")!;
    assert.ok(ont.supported_file_types.includes(".pod5"));
    assert.ok(ont.supported_file_types.includes(".fast5"));

    const pb = FIXTURE_CONNECTORS.find((c) => c.connector_id === "pacbio_smrtlink")!;
    assert.ok(pb.supported_file_types.includes(".bam"));
  });

  // 3. Illumina BaseSpace Run & Dataset Contracts
  await test("Illumina BaseSpace runs contain paired-end FASTQ datasets", () => {
    const bsRun = FIXTURE_RUNS.find((r) => r.vendor === "illumina")!;
    assert.strictEqual(bsRun.instrument_model, "Illumina MiSeq");

    const bsDatasets = FIXTURE_DATASETS.filter((d) => d.run_id === bsRun.run_id);
    assert.strictEqual(bsDatasets.length, 2);
    const r1 = bsDatasets.find((d) => d.read_type === "paired_end_R1")!;
    const r2 = bsDatasets.find((d) => d.read_type === "paired_end_R2")!;
    assert.ok(r1.file_name.includes("R1_001.fastq.gz"));
    assert.ok(r2.file_name.includes("R2_001.fastq.gz"));
    assert.ok(r1.checksum && r1.checksum.length === 64);
  });

  // 4. Oxford Nanopore MinKNOW Contracts
  await test("Oxford Nanopore separates raw ionic signal (POD5) from basecalled reads", () => {
    const ontRun = FIXTURE_RUNS.find((r) => r.vendor === "nanopore")!;
    assert.strictEqual(ontRun.instrument_model, "PromethION 2 Solo");

    const ontDatasets = FIXTURE_DATASETS.filter((d) => d.run_id === ontRun.run_id);
    const pod5 = ontDatasets.find((d) => d.read_type === "raw_signal")!;
    const fastq = ontDatasets.find((d) => d.read_type === "long_read")!;

    assert.strictEqual(pod5.file_format, "pod5");
    assert.strictEqual(pod5.analysis_eligibility.requires_basecalling, true);

    assert.strictEqual(fastq.file_format, "fastq_gz");
    assert.strictEqual(fastq.analysis_eligibility.requires_basecalling ?? false, false);
  });

  // 5. PacBio SMRT Link Contracts
  await test("PacBio SMRT Link distinguishes HiFi CCS BAM from subreads", () => {
    const pbRun = FIXTURE_RUNS.find((r) => r.vendor === "pacbio")!;
    assert.strictEqual(pbRun.instrument_model, "PacBio Revio");

    const pbDataset = FIXTURE_DATASETS.find((d) => d.run_id === pbRun.run_id)!;
    assert.strictEqual(pbDataset.read_type, "hifi_ccs");
    assert.strictEqual(pbDataset.analysis_eligibility.is_hifi, true);
  });

  // 6. Scientific Analysis Handoff Invariant
  await test("CRITICAL: Raw sequencing reads are strictly NOT eligible for direct AMP classification", () => {
    const fastqHandoff = FIXTURE_HANDOFFS["ds_bs_miseq_r1"];
    assert.strictEqual(fastqHandoff.direct_amp_eligible, false);
    assert.strictEqual(fastqHandoff.data_type, "raw_short_reads");
    assert.ok(
      fastqHandoff.prerequisite_notice.includes(
        "Raw nucleotide reads cannot be classified by ampir or amPEPpy"
      )
    );
  });

  // 7. Multi-Stage Pipeline Progression
  await test("Analysis handoff requires QC -> Assembly -> Gene Calling -> Translation -> AMP Screening", () => {
    const fastqHandoff = FIXTURE_HANDOFFS["ds_bs_miseq_r1"];
    const stageIds = fastqHandoff.pipeline_stages.map((s) => s.stage_id);
    assert.deepStrictEqual(stageIds, [
      "qc",
      "assembly",
      "gene_calling",
      "translation",
      "amp_screening",
    ]);

    // FastQC is ready first; AMP screening is pending prerequisite
    const qcStage = fastqHandoff.pipeline_stages.find((s) => s.stage_id === "qc")!;
    const ampStage = fastqHandoff.pipeline_stages.find((s) => s.stage_id === "amp_screening")!;
    assert.strictEqual(qcStage.status, "ready");
    assert.strictEqual(ampStage.status, "pending_prerequisite");
  });

  // 8. Candidate peptide extraction for AMP predictor handoff
  await test("PacBio HiFi dataset handoff extracts candidate bacteriocin peptides", () => {
    const hifiHandoff = FIXTURE_HANDOFFS["ds_pb_hifi_01"];
    assert.ok(hifiHandoff.extracted_peptides_preview.length >= 2);
    for (const pep of hifiHandoff.extracted_peptides_preview) {
      assert.ok(pep.sequence.length >= 10);
      assert.strictEqual(pep.ready_for_amp, true);
    }
  });

  // 9. API client safe fallback functionality
  await test("API client returns structured datasets and connectors in fallback mode", async () => {
    const { connectors } = await fetchConnectors();
    assert.strictEqual(connectors.length, 4);

    const { connections } = await fetchConnections();
    assert.ok(connections.length >= 3);

    const { runs } = await fetchRuns();
    assert.ok(runs.length >= 3);

    const { datasets } = await fetchDatasets();
    assert.ok(datasets.length >= 4);

    const { handoff } = await fetchAnalysisHandoff("ds_bs_miseq_r1");
    assert.strictEqual(handoff.direct_amp_eligible, false);

    const { importJob } = await initiateImport("ds_bs_miseq_r1");
    assert.strictEqual(importJob.status, "completed");
    assert.strictEqual(importJob.checksum_verified, true);
  });

  console.log(`\n=================================================`);
  console.log(`ALL TESTS PASSED: ${passed}/${total}`);
  console.log(`=================================================`);
}

runTests().catch((err) => {
  console.error("Test execution failed:", err);
  process.exit(1);
});
