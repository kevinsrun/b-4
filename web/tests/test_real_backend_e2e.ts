/**
 * End-to-end integration test against the live FastAPI AMP backend.
 */

import assert from "node:assert";

const BASE_URL = "http://127.0.0.1:8000";

async function runE2eTests() {
  console.log("=================================================");
  console.log("REAL BACKEND END-TO-END INTEGRATION TEST");
  console.log(`Connecting to: ${BASE_URL}`);
  console.log("=================================================\n");

  let passed = 0;
  let total = 0;

  async function test(name: string, fn: () => Promise<void>) {
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

  // 1. GET /api/v1/amp/models
  await test("GET /api/v1/amp/models returns all 6 audited models", async () => {
    const res = await fetch(`${BASE_URL}/api/v1/amp/models`);
    assert.strictEqual(res.status, 200);
    const data = (await res.json()) as { models: any[] };
    assert.strictEqual(data.models.length, 6);
    const modelIds = data.models.map((m: any) => m.model_id);
    assert(modelIds.includes("ampir"));
    assert(modelIds.includes("ampeppy"));
    assert(modelIds.includes("amplify"));
    assert(modelIds.includes("ampscanner_v2"));
    assert(modelIds.includes("ai4amp"));
    assert(modelIds.includes("apin"));
  });

  // 2. GET /api/v1/amp/models/health
  await test("GET /api/v1/amp/models/health returns verified READY status for ampir and ampeppy", async () => {
    const res = await fetch(`${BASE_URL}/api/v1/amp/models/health`);
    assert.strictEqual(res.status, 200);
    const data = (await res.json()) as { models: any[]; resources: any };
    assert(data.resources);
    assert(typeof data.resources.api_process_peak_rss_kib === "number");

    const statusMap = Object.fromEntries(data.models.map((m: any) => [m.model_id, m.status]));
    assert.strictEqual(statusMap.ampir, "READY");
    assert.strictEqual(statusMap.ampeppy, "READY");
    assert.strictEqual(statusMap.amplify, "PARTIAL");
    assert.strictEqual(statusMap.ampscanner_v2, "PARTIAL");
    assert.strictEqual(statusMap.ai4amp, "BLOCKED");
    assert.strictEqual(statusMap.apin, "BLOCKED");
  });

  // 3. POST /api/v1/amp/predict (Synchronous inference)
  await test("POST /api/v1/amp/predict executes real inference with ampir and ampeppy", async () => {
    const payload = {
      sequences: [
        { sequence_id: "test_glfdiv", sequence: "GLFDIVKKVVGALG" },
        { sequence_id: "nisin_core", sequence: "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK" },
      ],
      models: ["ampir", "ampeppy"],
      ampir_model: "mature",
      timeout_seconds: 30,
    };

    const res = await fetch(`${BASE_URL}/api/v1/amp/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    assert.strictEqual(res.status, 200);
    const report = (await res.json()) as any;
    assert.strictEqual(report.status, "succeeded");
    assert.strictEqual(report.sequences.length, 2);

    for (const seq of report.sequences) {
      assert.strictEqual(seq.predictions.length, 2);
      for (const pred of seq.predictions) {
        assert.strictEqual(pred.status, "succeeded");
        assert(typeof pred.raw_score === "number");
        assert(pred.raw_score >= 0 && pred.raw_score <= 1);
        assert(pred.binary_prediction === null || typeof pred.binary_prediction === "boolean");
        assert(pred.score_interpretation);
      }
    }
    console.log(`    -> GLFDIV scores: ampir=${report.sequences[0].predictions[0].raw_score.toFixed(4)}, ampeppy=${report.sequences[0].predictions[1].raw_score.toFixed(4)}`);
    console.log(`    -> Nisin scores: ampir=${report.sequences[1].predictions[0].raw_score.toFixed(4)}, ampeppy=${report.sequences[1].predictions[1].raw_score.toFixed(4)}`);
  });

  // 4. POST /api/v1/amp/batch & GET /api/v1/amp/jobs/{job_id} (Asynchronous batch)
  await test("POST /api/v1/amp/batch and GET /api/v1/amp/jobs/{job_id} monitor batch lifecycle", async () => {
    const payload = {
      sequences: [{ sequence_id: "batch_seq_1", sequence: "GLFDIVKKVVGALG" }],
      models: ["ampir", "ampeppy"],
    };

    const idempotencyKey = `e2e-test-${Date.now()}`;
    const submitRes = await fetch(`${BASE_URL}/api/v1/amp/batch`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(payload),
    });

    assert.strictEqual(submitRes.status, 202);
    const jobData = (await submitRes.json()) as any;
    assert(jobData.job_id);

    // Poll until complete
    let completed = false;
    let finalJob: any = null;
    for (let attempt = 0; attempt < 20; attempt++) {
      const pollRes = await fetch(`${BASE_URL}/api/v1/amp/jobs/${jobData.job_id}`);
      assert.strictEqual(pollRes.status, 200);
      finalJob = (await pollRes.json()) as any;
      if (finalJob.status === "succeeded" || finalJob.status === "failed") {
        completed = true;
        break;
      }
      await new Promise((r) => setTimeout(r, 200));
    }

    assert(completed, "Batch job did not complete within deadline");
    assert.strictEqual(finalJob.status, "succeeded");
    assert(finalJob.report);
    assert.strictEqual(finalJob.report.sequences.length, 1);
    console.log(`    -> Batch job ${jobData.job_id} finished with status: ${finalJob.status}`);
  });

  // 5. GET /api/v1/dramp/search
  await test("GET /api/v1/dramp/search queries DRAMP reference records", async () => {
    const res = await fetch(`${BASE_URL}/api/v1/dramp/search?record_id=DRAMP00001`);
    assert.strictEqual(res.status, 200);
    const data = (await res.json()) as any;
    assert(data.total >= 1);
    assert(data.records.length >= 1);
    const record = data.records[0];
    assert.strictEqual(record.record_id, "DRAMP00001");
    assert.strictEqual(record.sequence, "GSGVIPTISHECHMNSFQFVFTCCS");
    assert.strictEqual(record.metadata.Name, "Variacin (Bacteriocin)");
    assert(record.provenance);
    assert.strictEqual(record.evidence_type, "reference-database-annotation");
    console.log(`    -> Found ${data.total} DRAMP00001 records across ${data.datasets.length} datasets (Name: ${record.metadata.Name})`);
  });

  // 6. GET /api/v1/dramp/records/{record_id}
  await test("GET /api/v1/dramp/records/{record_id} returns exact record and annotations", async () => {
    const res = await fetch(`${BASE_URL}/api/v1/dramp/records/DRAMP00001`);
    assert.strictEqual(res.status, 200);
    const data = (await res.json()) as any;
    assert(data.records.length >= 1);
    const rec = data.records[0];
    assert.strictEqual(rec.metadata.Name, "Variacin (Bacteriocin)");
    console.log(`    -> DRAMP00001 metadata Name: ${rec.metadata.Name}, Source: ${rec.metadata.Source}`);
  });

  // 7. Error handling: Unknown model rejection
  await test("POST /api/v1/amp/predict rejects unavailable/unknown models with 422", async () => {
    const payload = {
      sequences: [{ sequence_id: "s1", sequence: "GLFDIVKKVVGALG" }],
      models: ["nonexistent_model"],
    };
    const res = await fetch(`${BASE_URL}/api/v1/amp/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    assert.strictEqual(res.status, 422);
  });

  console.log(`\nAll ${passed}/${total} live end-to-end integration tests PASSED!`);
}

runE2eTests();
