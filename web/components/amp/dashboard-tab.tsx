"use client";

import type { ModelsHealthResponse, JobResponse, PredictionReport } from "@/lib/amp-types";
import { FIXTURE_DRAMP_STATS } from "@/lib/amp-fixtures";
import { Panel, Status, Id } from "@/components/ui";

interface DashboardTabProps {
  healthData: ModelsHealthResponse | null;
  recentJobs: JobResponse[];
  currentReport: PredictionReport | null;
  isBackendConnected: boolean;
  useFixtures: boolean;
  onNavigateTab: (tab: string) => void;
  onLoadJobReport: (report: PredictionReport) => void;
}

export function DashboardTab({
  healthData,
  recentJobs,
  currentReport,
  isBackendConnected,
  useFixtures,
  onNavigateTab,
  onLoadJobReport,
}: DashboardTabProps) {
  const models = healthData?.models ?? [];
  const readyModels = models.filter((m) => m.status === "READY");
  const partialModels = models.filter((m) => m.status === "PARTIAL");
  const blockedModels = models.filter((m) => m.status === "BLOCKED");

  return (
    <div className="space-y-6">
      {/* Platform Banner */}
      <div className="border border-line bg-panel p-6 sm:p-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="max-w-2xl">
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Computational Bacteriocin Research</p>
            <h1 className="mt-2 text-3xl font-medium tracking-tight text-text">
              B-4 Antimicrobial Peptide (AMP) Workspace
            </h1>
            <p className="mt-3 text-[14px] leading-relaxed text-muted">
              Integrated research console connecting independently trained AMP classifiers (ampir, amPEPpy)
              with official DRAMP reference datasets. Built for computational peptide triage with strict
              separation of computational scores, database annotations, and wet-lab biological evidence.
            </p>
          </div>

          <div className="flex flex-col items-end gap-2 border-t sm:border-t-0 sm:border-l border-line sm:pl-6 pt-4 sm:pt-0">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-cyan animate-pulse" />
              <span className="text-[12px] font-medium text-text">
                {isBackendConnected ? "Connected to Verified Backend" : "Demo Fixture State"}
              </span>
            </div>
            <span className="text-[11px] text-faint">
              API origin: <Id>{isBackendConnected ? "http://127.0.0.1:8000" : "Offline Fixtures"}</Id>
            </span>
            <div className="mt-2 flex gap-2">
              <button
                onClick={() => onNavigateTab("submit")}
                className="border border-cyan/40 bg-cyan/15 px-3 py-1.5 text-[12px] font-medium text-cyan hover:bg-cyan/25 transition-colors"
              >
                Submit Sequences →
              </button>
              <button
                onClick={() => onNavigateTab("dramp")}
                className="border border-line bg-raised px-3 py-1.5 text-[12px] font-medium text-text hover:border-cyan/40 hover:text-cyan transition-colors"
              >
                Browse DRAMP →
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Operational Overview Metrics */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {/* Metric 1 */}
        <div className="border border-line bg-panel p-4">
          <span className="text-[10.5px] uppercase tracking-wider text-faint block">Operational Predictors</span>
          <div className="num mt-1 text-2xl font-semibold text-green">
            {readyModels.length} <span className="text-[13px] text-muted font-normal">/ {models.length || 6}</span>
          </div>
          <span className="mt-1 block text-[11px] text-muted">
            {readyModels.map((m) => m.model_id).join(", ") || "ampir, amPEPpy"}
          </span>
        </div>

        {/* Metric 2 */}
        <div className="border border-line bg-panel p-4">
          <span className="text-[10.5px] uppercase tracking-wider text-faint block">Reference Collections</span>
          <div className="num mt-1 text-2xl font-semibold text-cyan">4 Datasets</div>
          <span className="mt-1 block text-[11px] text-muted">
            {FIXTURE_DRAMP_STATS.totalRecords.toLocaleString()} verified DRAMP entries
          </span>
        </div>

        {/* Metric 3 */}
        <div className="border border-line bg-panel p-4">
          <span className="text-[10.5px] uppercase tracking-wider text-faint block">Unavailable / Blocked</span>
          <div className="num mt-1 text-2xl font-semibold text-amber">
            {partialModels.length + blockedModels.length}{" "}
            <span className="text-[13px] text-muted font-normal">models</span>
          </div>
          <span className="mt-1 block text-[11px] text-red/80">
            AMPlify, AMPScanner, AI4AMP, APIN
          </span>
        </div>

        {/* Metric 4 */}
        <div className="border border-line bg-panel p-4">
          <span className="text-[10.5px] uppercase tracking-wider text-faint block">Session Job Activity</span>
          <div className="num mt-1 text-2xl font-semibold text-text">{recentJobs.length}</div>
          <span className="mt-1 block text-[11px] text-muted">
            {recentJobs.filter((j) => j.status === "succeeded").length} succeeded
          </span>
        </div>
      </div>

      {/* Quick Scientific Action Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div
          onClick={() => onNavigateTab("submit")}
          className="cursor-pointer border border-line bg-panel p-5 transition-all hover:border-cyan/50 hover:bg-raised/40 group"
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-cyan uppercase tracking-wider">Workspace 01</span>
            <span className="text-cyan group-hover:translate-x-1 transition-transform">→</span>
          </div>
          <h3 className="mt-2 text-lg font-medium text-text group-hover:text-cyan transition-colors">
            Sequence Submission
          </h3>
          <p className="mt-1 text-[12.5px] text-muted">
            Submit single peptides or Multi-FASTA batches for synchronous analysis or asynchronous job queueing.
          </p>
        </div>

        <div
          onClick={() => onNavigateTab("dramp")}
          className="cursor-pointer border border-line bg-panel p-5 transition-all hover:border-cyan/50 hover:bg-raised/40 group"
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-cyan uppercase tracking-wider">Workspace 02</span>
            <span className="text-cyan group-hover:translate-x-1 transition-transform">→</span>
          </div>
          <h3 className="mt-2 text-lg font-medium text-text group-hover:text-cyan transition-colors">
            DRAMP Database Explorer
          </h3>
          <p className="mt-1 text-[12.5px] text-muted">
            Query 20,270 records across four distinct collections with full attribution and quarantine statistics.
          </p>
        </div>

        <div
          onClick={() => onNavigateTab("models")}
          className="cursor-pointer border border-line bg-panel p-5 transition-all hover:border-cyan/50 hover:bg-raised/40 group"
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-cyan uppercase tracking-wider">Workspace 03</span>
            <span className="text-cyan group-hover:translate-x-1 transition-transform">→</span>
          </div>
          <h3 className="mt-2 text-lg font-medium text-text group-hover:text-cyan transition-colors">
            Model Registry & Health
          </h3>
          <p className="mt-1 text-[12.5px] text-muted">
            Inspect host runtime dependencies, SHA-256 fingerprint verification proofs, and blockers.
          </p>
        </div>
      </div>

      {/* Model Operational Status Overview */}
      <Panel title="Model Availability Matrix">
        <div className="divide-y divide-line/60">
          {models.map((model) => (
            <div key={model.model_id} className="py-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-3">
                <span className="text-[13px] font-semibold text-text capitalize">{model.model_id}</span>
                <span className="font-mono text-[11px] text-muted">v{model.model_version}</span>
                <Status status={model.status} />
              </div>
              <div className="text-[11.5px] text-muted max-w-md truncate">
                {model.blocker ? (
                  <span className="text-red/90">Blocker: {model.blocker}</span>
                ) : model.verification ? (
                  <span className="text-green">Verified against published reference scores</span>
                ) : (
                  <span>{model.score_interpretation}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* Recent Batch Activity */}
      {recentJobs.length > 0 && (
        <Panel
          title="Recent Batch Execution Jobs"
          aside={
            <button
              onClick={() => onNavigateTab("jobs")}
              className="text-[11px] text-cyan hover:underline"
            >
              View all in Job Monitor →
            </button>
          }
        >
          <div className="space-y-2">
            {recentJobs.slice(0, 5).map((job) => (
              <div
                key={job.job_id}
                className="flex items-center justify-between border border-line bg-raised/20 p-2.5 text-[12px]"
              >
                <div className="flex items-center gap-2">
                  <Id>{job.job_id}</Id>
                  <Status status={job.status} />
                  <span className="text-muted text-[11px]">
                    {new Date(job.created_at).toLocaleTimeString()}
                  </span>
                </div>
                {job.report && (
                  <button
                    onClick={() => {
                      onLoadJobReport(job.report!);
                      onNavigateTab("results");
                    }}
                    className="text-[11px] text-cyan hover:underline"
                  >
                    View Report ({job.report.sequences.length} seqs) →
                  </button>
                )}
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
