"use client";

import { useEffect, useState } from "react";
import type {
  ModelsHealthResponse,
  PredictionReport,
  JobResponse,
} from "@/lib/amp-types";
import {
  checkBackendConnection,
  getAmpModelsHealth,
} from "@/lib/amp-api";
import { FIXTURE_MODELS_HEALTH, getFixtureJobResponse } from "@/lib/amp-fixtures";
import { DashboardTab } from "./dashboard-tab";
import { SubmissionTab } from "./submission-tab";
import { ResultsTab } from "./results-tab";
import { ModelsTab } from "./models-tab";
import { DrampTab } from "./dramp-tab";
import { JobsTab } from "./jobs-tab";

export function AmpWorkspace() {
  const [activeTab, setActiveTab] = useState<
    "dashboard" | "submit" | "results" | "models" | "dramp" | "jobs"
  >("dashboard");

  // Backend state
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [useFixtures, setUseFixtures] = useState(false);
  const [backendLatency, setBackendLatency] = useState<number | undefined>();
  const [isCheckingBackend, setIsCheckingBackend] = useState(true);

  // Application data state
  const [healthData, setHealthData] = useState<ModelsHealthResponse | null>(null);
  const [currentReport, setCurrentReport] = useState<PredictionReport | null>(null);
  const [jobs, setJobs] = useState<JobResponse[]>([]);

  // Navigation transfer state
  const [drampTargetRecordId, setDrampTargetRecordId] = useState<string | null>(null);

  // Check connection and fetch initial health
  async function initBackend() {
    setIsCheckingBackend(true);
    const conn = await checkBackendConnection();
    setIsBackendConnected(conn.connected);
    setBackendLatency(conn.latencyMs);

    try {
      const health = await getAmpModelsHealth(!conn.connected);
      setHealthData(health);
    } catch {
      setHealthData(FIXTURE_MODELS_HEALTH);
    } finally {
      setIsCheckingBackend(false);
    }
  }

  useEffect(() => {
    initBackend();

    // Populate default demonstration job in history
    const demoJob = getFixtureJobResponse("batch-sample-demo-1", [
      { sequence_id: "nisin_a_mature", sequence: "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK" },
      { sequence_id: "glfdiv_ref", sequence: "GLFDIVKKVVGALG" },
    ]);
    setJobs([demoJob]);
  }, []);

  function handlePredictionComplete(report: PredictionReport) {
    setCurrentReport(report);
    setActiveTab("results");
  }

  function handleBatchSubmitted(job: JobResponse) {
    setJobs((prev) => [job, ...prev]);
    setActiveTab("jobs");
  }

  function handleSendFromDrampToPredictor(seqId: string, sequence: string) {
    setActiveTab("submit");
  }

  function handleNavigateToDramp(recordId: string) {
    setDrampTargetRecordId(recordId);
    setActiveTab("dramp");
  }

  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-24 pt-8 sm:px-6">
      {/* Top Breadcrumb & Live System Status Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3 mb-6">
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <span className="text-text font-medium">BactroGen</span>
          <span>/</span>
          <span className="text-cyan font-medium">AMP Inference & DRAMP Platform</span>
        </div>

        {/* Connection status indicator */}
        <div className="flex items-center gap-4 text-[11px]">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                isBackendConnected ? "bg-green" : "bg-amber"
              }`}
            />
            <span className="text-muted">
              Backend Status:{" "}
              <strong className={isBackendConnected ? "text-green" : "text-amber"}>
                {isBackendConnected
                  ? `FastAPI Online (${backendLatency ?? 0}ms)`
                  : "Offline (Demonstration Mode)"}
              </strong>
            </span>
          </div>

          <label className="flex items-center gap-1.5 cursor-pointer text-muted hover:text-text transition-colors">
            <input
              type="checkbox"
              checked={useFixtures}
              onChange={(e) => setUseFixtures(e.target.checked)}
              className="accent-cyan"
            />
            <span>Force Demo Fixtures</span>
          </label>

          <button
            onClick={initBackend}
            disabled={isCheckingBackend}
            className="text-[10px] text-cyan hover:underline disabled:opacity-50"
          >
            ↻ Check API
          </button>
        </div>
      </div>

      {/* Main Tab Navigation Bar */}
      <div className="flex items-center gap-1 overflow-x-auto border-b border-line bg-panel p-1 mb-8">
        <button
          onClick={() => setActiveTab("dashboard")}
          className={`px-4 py-2 text-[12.5px] font-medium transition-colors whitespace-nowrap border ${
            activeTab === "dashboard"
              ? "border-cyan/50 bg-cyan/15 text-cyan"
              : "border-transparent text-muted hover:text-text hover:bg-raised/50"
          }`}
        >
          Overview & Dashboard
        </button>
        <button
          onClick={() => setActiveTab("submit")}
          className={`px-4 py-2 text-[12.5px] font-medium transition-colors whitespace-nowrap border ${
            activeTab === "submit"
              ? "border-cyan/50 bg-cyan/15 text-cyan"
              : "border-transparent text-muted hover:text-text hover:bg-raised/50"
          }`}
        >
          Sequence Submission
        </button>
        <button
          onClick={() => setActiveTab("results")}
          className={`px-4 py-2 text-[12.5px] font-medium transition-colors whitespace-nowrap border ${
            activeTab === "results"
              ? "border-cyan/50 bg-cyan/15 text-cyan"
              : "border-transparent text-muted hover:text-text hover:bg-raised/50"
          }`}
        >
          Prediction Results {currentReport && <span className="ml-1 text-[11px] text-green">●</span>}
        </button>
        <button
          onClick={() => setActiveTab("models")}
          className={`px-4 py-2 text-[12.5px] font-medium transition-colors whitespace-nowrap border ${
            activeTab === "models"
              ? "border-cyan/50 bg-cyan/15 text-cyan"
              : "border-transparent text-muted hover:text-text hover:bg-raised/50"
          }`}
        >
          Model Health & Registry (6)
        </button>
        <button
          onClick={() => setActiveTab("dramp")}
          className={`px-4 py-2 text-[12.5px] font-medium transition-colors whitespace-nowrap border ${
            activeTab === "dramp"
              ? "border-cyan/50 bg-cyan/15 text-cyan"
              : "border-transparent text-muted hover:text-text hover:bg-raised/50"
          }`}
        >
          DRAMP Explorer (4 Datasets)
        </button>
        <button
          onClick={() => setActiveTab("jobs")}
          className={`px-4 py-2 text-[12.5px] font-medium transition-colors whitespace-nowrap border ${
            activeTab === "jobs"
              ? "border-cyan/50 bg-cyan/15 text-cyan"
              : "border-transparent text-muted hover:text-text hover:bg-raised/50"
          }`}
        >
          Job Monitor ({jobs.length})
        </button>
      </div>

      {/* Tab Content Display */}
      {activeTab === "dashboard" && (
        <DashboardTab
          healthData={healthData}
          recentJobs={jobs}
          currentReport={currentReport}
          isBackendConnected={isBackendConnected}
          useFixtures={useFixtures}
          onNavigateTab={(tab) => setActiveTab(tab as any)}
          onLoadJobReport={(report) => {
            setCurrentReport(report);
            setActiveTab("results");
          }}
        />
      )}

      {activeTab === "submit" && (
        <SubmissionTab
          modelsHealth={healthData?.models ?? []}
          isBackendConnected={isBackendConnected}
          useFixtures={useFixtures}
          onPredictionComplete={handlePredictionComplete}
          onBatchSubmitted={handleBatchSubmitted}
        />
      )}

      {activeTab === "results" && (
        <ResultsTab
          report={currentReport}
          onNavigateToDramp={handleNavigateToDramp}
          onNavigateToSubmit={() => setActiveTab("submit")}
        />
      )}

      {activeTab === "models" && (
        <ModelsTab
          healthData={healthData}
          onRefresh={initBackend}
          isBackendConnected={isBackendConnected}
        />
      )}

      {activeTab === "dramp" && (
        <DrampTab
          isBackendConnected={isBackendConnected}
          useFixtures={useFixtures}
          initialRecordId={drampTargetRecordId}
          onSendToPredictor={handleSendFromDrampToPredictor}
        />
      )}

      {activeTab === "jobs" && (
        <JobsTab
          jobs={jobs}
          onLoadJobReport={(report) => {
            setCurrentReport(report);
            setActiveTab("results");
          }}
          isBackendConnected={isBackendConnected}
          useFixtures={useFixtures}
        />
      )}
    </main>
  );
}
