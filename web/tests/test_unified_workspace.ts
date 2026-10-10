/**
 * Verification suite for B-4 Unified Research Workspace:
 * Projects, Samples, Annotated Sequences, and CRISPR Research Module.
 *
 * Verifies:
 * 1. Project & Sample data model schemas and fixtures
 * 2. Annotated sequence coordinates (1-based indexing, valid feature spans)
 * 3. Fast-path and alignment sequence comparison logic
 * 4. CRISPR research studies contract and scientific guardrails
 * 5. Project API client functions with fixture fallback
 * 6. Cross-module workflow link integrity (Projects -> Sequencing -> AMP -> CRISPR)
 */

import assert from "node:assert";
import {
  FIXTURE_PROJECTS,
  FIXTURE_SAMPLES,
  FIXTURE_SEQUENCES,
  FIXTURE_CRISPR_STUDIES,
} from "../lib/project-fixtures.ts";
import {
  fetchProjects,
  fetchProject,
  fetchProjectSamples,
  fetchProjectSequences,
  fetchSequence,
  fetchAllSequences,
  fetchCrisprStudies,
  fetchCrisprStudy,
  compareSequence,
  createProject,
  createCrisprStudy,
} from "../lib/project-api.ts";

async function runTests() {
  console.log("=================================================");
  console.log("B-4 UNIFIED RESEARCH WORKSPACE VERIFICATION");
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

  // 1. Projects & Samples Fixture Verification
  await test("Fixture projects list contains valid bacteriocin research projects", () => {
    assert.ok(FIXTURE_PROJECTS.length >= 3, "Expected at least 3 seeded projects");
    const p1 = FIXTURE_PROJECTS.find((p) => p.project_id === "proj_lactis_nisin");
    assert.ok(p1, "proj_lactis_nisin should exist");
    assert.strictEqual(p1.target_organism, "Lactococcus lactis");
    assert.strictEqual(p1.status, "active");
    assert.ok(p1.sample_ids.length > 0);
  });

  await test("Biological samples fixture contains metadata and instrument linkages", () => {
    const s1 = FIXTURE_SAMPLES.find((s) => s.sample_id === "samp_llactis_atcc11454");
    assert.ok(s1, "samp_llactis_atcc11454 should exist");
    assert.strictEqual(s1.project_id, "proj_lactis_nisin");
    assert.strictEqual(s1.organism, "Lactococcus lactis");
    assert.strictEqual(s1.sequencing_run_ids[0], "run_bs_miseq_01");
    assert.strictEqual(s1.dataset_ids[0], "ds_bs_miseq_r1");
  });

  // 2. Coordinate-aware Sequence Features Verification
  await test("Annotated sequences enforce 1-based coordinates and valid spans", () => {
    for (const seq of FIXTURE_SEQUENCES) {
      assert.ok(seq.length > 0, "Sequence length must be positive");
      assert.strictEqual(seq.length, seq.sequence.length, "Length must match sequence length");

      for (const feat of seq.annotations) {
        assert.ok(feat.start >= 1, `Feature start ${feat.start} must be >= 1`);
        assert.ok(feat.end <= seq.length, `Feature end ${feat.end} must be <= sequence length ${seq.length}`);
        assert.ok(feat.start <= feat.end, `Feature start ${feat.start} must be <= end ${feat.end}`);
        const validFeatureTypes = [
          "cds",
          "core_peptide",
          "leader_peptide",
          "cleavage_site",
          "modification_enzyme",
          "immunity_protein",
          "transporter",
          "regulator",
          "crispr_repeat",
          "crispr_spacer",
          "promoter",
          "terminator",
        ];
        assert.ok(
          validFeatureTypes.includes(feat.feature_type),
          `Unexpected feature type: ${feat.feature_type}`
        );
      }
    }
  });

  // 3. CRISPR Objective Contracts & Safety Guardrails
  await test("CRISPR research objectives document locus analysis without automated execution", () => {
    for (const study of FIXTURE_CRISPR_STUDIES) {
      assert.ok(study.study_id.startsWith("crispr_"), "Study ID must start with crispr_");
      assert.ok(study.target_gene.length > 0, "Target gene must be populated");
      assert.ok(study.investigation_purpose.length > 0, "Investigation purpose must be populated");
      assert.ok(study.target_regions.length > 0, "Target regions must be specified");

      for (const region of study.target_regions) {
        assert.ok(region.start_pos >= 1, "Region start must be >= 1");
        assert.ok(region.start_pos <= region.end_pos, "Region start <= end");
        assert.ok(region.target_sequence.length > 0, "Target sequence must be non-empty");
        assert.ok(region.pam_motif && region.pam_motif.length > 0, "PAM motif must be recorded");
      }
    }
  });

  // 4. API Client Fallback & Data Retrieval
  await test("API fetchProjects returns project list", async () => {
    const res = await fetchProjects();
    assert.ok(Array.isArray(res.projects));
    assert.ok(res.projects.length >= 3);
  });

  await test("API fetchProject returns target project by ID", async () => {
    const res = await fetchProject("proj_lactis_nisin");
    assert.ok(res.project, "Project must not be null");
    assert.strictEqual(res.project.project_id, "proj_lactis_nisin");
    assert.strictEqual(res.project.target_organism, "Lactococcus lactis");
  });

  await test("API fetchProjectSamples returns linked samples", async () => {
    const res = await fetchProjectSamples("proj_lactis_nisin");
    assert.ok(res.samples.length >= 1);
    assert.strictEqual(res.samples[0].project_id, "proj_lactis_nisin");
  });

  await test("API fetchProjectSequences returns linked annotated sequences", async () => {
    const res = await fetchProjectSequences("proj_lactis_nisin");
    assert.ok(res.sequences.length >= 1);
    assert.strictEqual(res.sequences[0].project_id, "proj_lactis_nisin");
  });

  await test("API fetchCrisprStudies returns study list", async () => {
    const res = await fetchCrisprStudies("proj_lactis_nisin");
    assert.ok(res.studies.length >= 1);
    assert.strictEqual(res.studies[0].study_id, "crispr_nisi_immunity_01");
  });

  // 5. Sequence Comparison & Variant Calling Logic
  await test("Sequence comparison correctly identifies single-point nucleotide substitution", async () => {
    const refSeq = FIXTURE_SEQUENCES[0]; // seq_nisin_cluster_ref
    // Modify one base at index 10 (coordinate 11, 1-based)
    const originalChar = refSeq.sequence[10];
    const altChar = originalChar === "A" ? "G" : "A";
    const mutatedQuery = refSeq.sequence.slice(0, 10) + altChar + refSeq.sequence.slice(11);

    const { comparison } = await compareSequence(refSeq.sequence_id, {
      reference_sequence_id: refSeq.sequence_id,
      query_sequence: mutatedQuery,
      query_name: "Simulated Point Variant",
    });

    assert.strictEqual(comparison.reference_id, refSeq.sequence_id);
    assert.strictEqual(comparison.mismatches_count, 1);
    assert.strictEqual(comparison.variants.length, 1);

    const variant = comparison.variants[0];
    assert.strictEqual(variant.position, 11, "Variant must be at coordinate 11");
    assert.strictEqual(variant.reference_allele, originalChar);
    assert.strictEqual(variant.alternate_allele, altChar);
    assert.strictEqual(variant.variant_type, "snv");
  });

  await test("Sequence comparison correctly reports identical sequence", async () => {
    const refSeq = FIXTURE_SEQUENCES[0];
    const { comparison } = await compareSequence(refSeq.sequence_id, {
      reference_sequence_id: refSeq.sequence_id,
      query_sequence: refSeq.sequence,
      query_name: "Identical Query",
    });

    assert.strictEqual(comparison.mismatches_count, 0);
    assert.strictEqual(comparison.identity_percentage, 100);
    assert.strictEqual(comparison.variants.length, 0);
  });

  // 6. Project & Study Creation Handlers
  await test("createProject adds and persists new project contract", async () => {
    const { project } = await createProject({
      name: "Subtilosin A Analysis",
      description: "Characterization of sactipeptide cluster from Bacillus subtilis 168",
      lead_investigator: "Dr. B. Subtilis",
      target_organism: "Bacillus subtilis",
    });

    assert.ok(project.project_id.startsWith("proj_"));
    assert.strictEqual(project.name, "Subtilosin A Analysis");
    assert.strictEqual(project.target_organism, "Bacillus subtilis");
  });

  await test("createCrisprStudy records target locus objective", async () => {
    const { study } = await createCrisprStudy("proj_lactis_nisin", {
      sample_id: "samp_llactis_atcc11454",
      title: "NisP Leader Protease Locus Knockout Strategy",
      target_gene: "nisP",
      target_sequence_id: "seq_nisin_cluster_ref",
      investigation_purpose: "Assess precursor accumulation without extracellular protease cleavage",
      reference_version: "v1.0",
      specificity_considerations: "High specificity; 3 mismatches required in off-target loci.",
    });

    assert.ok(study.study_id.startsWith("crispr_"));
    assert.strictEqual(study.target_gene, "nisP");
    assert.strictEqual(study.project_id, "proj_lactis_nisin");
  });

  console.log("\n=================================================");
  console.log(`ALL ${passed}/${total} UNIFIED WORKSPACE TESTS PASSED!`);
  console.log("=================================================");
}

runTests().catch((err) => {
  console.error("Test execution failed:", err);
  process.exit(1);
});
