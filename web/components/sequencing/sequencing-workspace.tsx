"use client";

import { useEffect, useState } from "react";
import {
  ConnectorInfo,
  SequencingConnection,
  SequencingRun,
  SequencingDataset,
} from "@/lib/sequencing-types";
import {
  fetchConnectors,
  fetchConnections,
  fetchRuns,
  fetchDatasets,
} from "@/lib/sequencing-api";
import { OverviewTab } from "./overview-tab";
import { RunsTab } from "./runs-tab";
import { DatasetsTab } from "./datasets-tab";
import { ConnectionsTab } from "./connections-tab";
import { ImportsTab } from "./imports-tab";
import { HandoffModal } from "./handoff-modal";

export function SequencingWorkspace() {
  const [activeTab, setActiveTab] = useState<
    "overview" | "runs" | "datasets" | "connections" | "imports"
  >("overview");

  // Application state
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [connections, setConnections] = useState<SequencingConnection[]>([]);
  const [runs, setRuns] = useState<SequencingRun[]>([]);
  const [datasets, setDatasets] = useState<SequencingDataset[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Modal state
  const [handoffDataset, setHandoffDataset] = useState<SequencingDataset | null>(null);

  // Loading & backend connectivity
  const [isLive, setIsLive] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  async function loadData() {
    setIsLoading(true);
    try {
      const [cRes, connRes, rRes, dsRes] = await Promise.all([
        fetchConnectors(),
        fetchConnections(),
        fetchRuns(),
        fetchDatasets(),
      ]);

      setConnectors(cRes.connectors);
      setConnections(connRes.connections);
      setRuns(rRes.runs);
      setDatasets(dsRes.datasets);
      setIsLive(cRes.isLive);
    } catch {
      setIsLive(false);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  function handleSelectRun(runId: string) {
    setSelectedRunId(runId);
    setActiveTab("datasets");
  }

  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-24 pt-8 sm:px-6">
      {/* Top Breadcrumb & Platform Status Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3 mb-6">
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <span className="text-text font-medium">BactroGen</span>
          <span>/</span>
          <span className="text-accent font-medium">Universal Sequencing Integration</span>
        </div>

        {/* Live / Simulated Engine Badge */}
        <div className="flex items-center gap-4 text-[11px]">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                isLive ? "bg-emerald-400" : "bg-amber-400"
              }`}
            />
            <span className="font-mono text-muted">
              {isLive ? "Live FastAPI Sequencing Engine" : "Verified Offline Contract Mode"}
            </span>
          </div>

          <button
            onClick={() => loadData()}
            className="rounded bg-surface hover:bg-surface/80 border border-line px-2 py-0.5 font-mono text-[11px] text-muted hover:text-text transition-colors"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Main Page Title & Intro */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-text sm:text-3xl">
          Universal Sequencing & Ingestion
        </h1>
        <p className="mt-1 text-sm text-muted max-w-3xl leading-relaxed">
          Connect Illumina BaseSpace, Oxford Nanopore MinKNOW, PacBio SMRT Link, and laboratory drop folders.
          Automatically discover runs, verify data stability, track checksums, and hand off into bacteriocin gene discovery pipelines.
        </p>
      </div>

      {/* Navigation Tabs */}
      <div className="flex border-b border-line mb-6 gap-1 overflow-x-auto">
        {[
          { id: "overview", label: "Overview & Architecture", count: null },
          { id: "runs", label: "Sequencing Runs", count: runs.length },
          { id: "datasets", label: "Datasets & Files", count: datasets.length },
          { id: "connections", label: "Platform Connections", count: connections.length },
          {
            id: "imports",
            label: "Ingestion & Staging",
            count: datasets.filter((d) => d.import_status === "imported").length,
          },
        ].map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-mono uppercase tracking-wider transition-colors whitespace-nowrap ${
                isActive
                  ? "border-accent text-accent font-bold"
                  : "border-transparent text-muted hover:text-text"
              }`}
            >
              <span>{tab.label}</span>
              {tab.count !== null && (
                <span
                  className={`rounded-full px-1.5 py-0.2 text-[10px] ${
                    isActive ? "bg-accent/20 text-accent" : "bg-surface text-muted"
                  }`}
                >
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Active Tab View */}
      {isLoading ? (
        <div className="py-20 text-center text-muted flex flex-col items-center gap-2 font-mono text-xs">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <span>Synchronizing sequencing connectors and indexed metadata...</span>
        </div>
      ) : (
        <>
          {activeTab === "overview" && (
            <OverviewTab
              connectors={connectors}
              connections={connections}
              runs={runs}
              datasets={datasets}
              onNavigateTab={(tab) => setActiveTab(tab)}
              onSelectRun={handleSelectRun}
            />
          )}

          {activeTab === "runs" && (
            <RunsTab runs={runs} onSelectRun={handleSelectRun} />
          )}

          {activeTab === "datasets" && (
            <DatasetsTab
              datasets={datasets}
              selectedRunId={selectedRunId}
              onClearRunFilter={() => setSelectedRunId(null)}
              onOpenHandoff={(ds) => setHandoffDataset(ds)}
              onRefresh={loadData}
            />
          )}

          {activeTab === "connections" && (
            <ConnectionsTab
              connectors={connectors}
              connections={connections}
              onRefresh={loadData}
            />
          )}

          {activeTab === "imports" && (
            <ImportsTab datasets={datasets} />
          )}
        </>
      )}

      {/* Scientific Analysis Handoff Modal */}
      {handoffDataset && (
        <HandoffModal
          dataset={handoffDataset}
          onClose={() => setHandoffDataset(null)}
        />
      )}
    </main>
  );
}
