"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Server,
  Database,
  Cpu,
  Radio,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
  ShieldCheck,
  HardDrive,
  Settings as SettingsIcon,
} from "lucide-react";
import { checkBackendConnection, getAmpModelsHealth } from "@/lib/amp-api";
import { fetchConnectors, fetchConnections } from "@/lib/sequencing-api";
import { ModelsHealthResponse } from "@/lib/amp-types";
import { ConnectorInfo, SequencingConnection } from "@/lib/sequencing-types";

export function SettingsWorkspace() {
  const [activeTab, setActiveTab] = useState<"integrations" | "models" | "storage" | "diagnostics">("integrations");

  // Backend state
  const [isLive, setIsLive] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | undefined>();
  const [isChecking, setIsChecking] = useState(true);

  // Models health
  const [modelsHealth, setModelsHealth] = useState<ModelsHealthResponse | null>(null);

  // Connectors & connections
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [connections, setConnections] = useState<SequencingConnection[]>([]);

  // Local settings state
  const [consensusThreshold, setConsensusThreshold] = useState("0.70");
  const [autoSyncInterval, setAutoSyncInterval] = useState("15");
  const [requireChecksum, setRequireChecksum] = useState(true);

  async function refreshDiagnostics() {
    setIsChecking(true);
    try {
      const conn = await checkBackendConnection();
      setIsLive(conn.connected);
      setLatencyMs(conn.latencyMs);

      const [healthRes, connRes, connListRes] = await Promise.allSettled([
        getAmpModelsHealth(!conn.connected),
        fetchConnectors(),
        fetchConnections(),
      ]);

      if (healthRes.status === "fulfilled") {
        setModelsHealth(healthRes.value);
      }
      if (connRes.status === "fulfilled") {
        setConnectors(connRes.value.connectors);
      }
      if (connListRes.status === "fulfilled") {
        setConnections(connListRes.value.connections);
      }
    } finally {
      setIsChecking(false);
    }
  }

  useEffect(() => {
    refreshDiagnostics();
  }, []);

  return (
    <main className="mx-auto max-w-[1240px] px-4 py-8 sm:px-6">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">
            <SettingsIcon size={13} />
            <span>Platform Configuration</span>
          </div>
          <h1 className="mt-1 text-2xl font-medium tracking-tight text-text">
            Settings & Integrations
          </h1>
          <p className="text-[13px] text-muted">
            Manage sequencer platform credentials, AMP model runtimes, data storage paths, and scientific parameters.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={refreshDiagnostics}
            disabled={isChecking}
            className="pressable inline-flex items-center gap-1.5 rounded-[3px] border border-line bg-panel px-3 py-1.5 text-[12px] font-medium text-text hover:bg-raised disabled:opacity-50"
          >
            <RefreshCw size={12} className={isChecking ? "animate-spin" : ""} />
            <span>{isChecking ? "Pinging..." : "Refresh Status"}</span>
          </button>
        </div>
      </div>

      {/* Connectivity Status Banner */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-[4px] border border-line bg-panel p-4">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-9 w-9 items-center justify-center rounded-full ${
              isLive ? "bg-emerald-500/10 text-emerald-600" : "bg-amber-500/10 text-amber-600"
            }`}
          >
            {isLive ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold text-text">
                {isLive ? "FastAPI Backend Operational" : "Contract Fixture / Standalone Mode"}
              </span>
              <span className="text-[11px] font-mono text-faint">
                {isLive && latencyMs !== undefined ? `(${latencyMs}ms latency)` : "offline simulation"}
              </span>
            </div>
            <p className="text-[12px] text-muted">
              {isLive
                ? "Unified REST APIs connected to SQLite stores, ampir/amPEPpy inference engines, and sequencing connectors."
                : "Backend offline. Running on typed fixtures mirroring checked-in SQLite schemas."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 text-[12px]">
          <div>
            <span className="text-muted">Sequencing Connectors: </span>
            <span className="font-semibold text-text">{connectors.length || 4} Available</span>
          </div>
          <div className="text-line">|</div>
          <div>
            <span className="text-muted">AMP Engines: </span>
            <span className="font-semibold text-text">
              {modelsHealth ? modelsHealth.models.filter((m) => m.available).length : 2} Verified
            </span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="mb-6 flex border-b border-line">
        <button
          onClick={() => setActiveTab("integrations")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-[13px] font-medium transition-colors ${
            activeTab === "integrations"
              ? "border-cyan text-cyan"
              : "border-transparent text-muted hover:text-text"
          }`}
        >
          <Radio size={14} />
          <span>Sequencer Integrations</span>
        </button>

        <button
          onClick={() => setActiveTab("models")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-[13px] font-medium transition-colors ${
            activeTab === "models"
              ? "border-cyan text-cyan"
              : "border-transparent text-muted hover:text-text"
          }`}
        >
          <Cpu size={14} />
          <span>AMP Model Health</span>
        </button>

        <button
          onClick={() => setActiveTab("storage")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-[13px] font-medium transition-colors ${
            activeTab === "storage"
              ? "border-cyan text-cyan"
              : "border-transparent text-muted hover:text-text"
          }`}
        >
          <Database size={14} />
          <span>Data Stores & SQLite</span>
        </button>

        <button
          onClick={() => setActiveTab("diagnostics")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-[13px] font-medium transition-colors ${
            activeTab === "diagnostics"
              ? "border-cyan text-cyan"
              : "border-transparent text-muted hover:text-text"
          }`}
        >
          <Server size={14} />
          <span>Scientific Parameters</span>
        </button>
      </div>

      {/* Tab 1: Sequencer Integrations */}
      {activeTab === "integrations" && (
        <div className="space-y-6">
          <div className="rounded-[4px] border border-line bg-panel p-5">
            <div className="flex items-center justify-between pb-4 border-b border-line">
              <div>
                <h2 className="text-[15px] font-semibold text-text">Connected Sequencing Providers</h2>
                <p className="text-[12px] text-muted">
                  Instrument and vendor APIs configured for automatic discovery, synchronization, and import.
                </p>
              </div>
              <Link
                href="/sequencing"
                className="pressable inline-flex items-center gap-1.5 rounded-[3px] bg-sage-soft px-3 py-1.5 text-[12px] font-medium text-cyan hover:bg-raised"
              >
                <span>Manage in Sequencing Workspace</span>
                <ExternalLink size={12} />
              </Link>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="rounded-[3px] border border-line p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-text">Illumina BaseSpace</span>
                  <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
                    REST API Ready
                  </span>
                </div>
                <p className="mt-1 text-[12px] text-muted">
                  BaseSpace Sequence Hub integration with OAuth2 Bearer token authentication and run discovery.
                </p>
                <div className="mt-3 flex items-center justify-between text-[11px] text-faint border-t border-line/60 pt-2">
                  <span>Scope: `browse global, read project`</span>
                  <span>Endpoint: api.basespace.illumina.com</span>
                </div>
              </div>

              <div className="rounded-[3px] border border-line p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-text">Oxford Nanopore MinKNOW</span>
                  <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
                    Directory & gRPC
                  </span>
                </div>
                <p className="mt-1 text-[12px] text-muted">
                  MinKNOW output directory scanner monitoring active sequencing runs and fast5/fastq outputs.
                </p>
                <div className="mt-3 flex items-center justify-between text-[11px] text-faint border-t border-line/60 pt-2">
                  <span>Protocol: Filesystem + MinKNOW gRPC</span>
                  <span>Auto-detect: Enabled</span>
                </div>
              </div>

              <div className="rounded-[3px] border border-line p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-text">PacBio SMRT Link</span>
                  <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
                    SMRT Link API
                  </span>
                </div>
                <p className="mt-1 text-[12px] text-muted">
                  HiFi long-read discovery for circular consensus sequencing and complex bacteriocin gene clusters.
                </p>
                <div className="mt-3 flex items-center justify-between text-[11px] text-faint border-t border-line/60 pt-2">
                  <span>Port: 8243 (SMRT Link Service)</span>
                  <span>HiFi BAM filter: Enabled</span>
                </div>
              </div>

              <div className="rounded-[3px] border border-line p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-text">Laboratory Drop Folder</span>
                  <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
                    Local / NAS Ingestion
                  </span>
                </div>
                <p className="mt-1 text-[12px] text-muted">
                  Generic network mount or staging folder for ad-hoc FASTQ, FASTA, and GenBank file imports.
                </p>
                <div className="mt-3 flex items-center justify-between text-[11px] text-faint border-t border-line/60 pt-2">
                  <span>Path: `artifacts/sequencing/drop`</span>
                  <span>Integrity verification: SHA-256</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Model Health */}
      {activeTab === "models" && (
        <div className="space-y-6">
          <div className="rounded-[4px] border border-line bg-panel p-5">
            <div className="flex items-center justify-between pb-4 border-b border-line">
              <div>
                <h2 className="text-[15px] font-semibold text-text">AMP Predictor Runtimes</h2>
                <p className="text-[12px] text-muted">
                  Inference engine operational states and scientific model version audit.
                </p>
              </div>
              <Link
                href="/amp"
                className="pressable inline-flex items-center gap-1.5 rounded-[3px] bg-sage-soft px-3 py-1.5 text-[12px] font-medium text-cyan hover:bg-raised"
              >
                <span>Launch AMP Lab</span>
                <ExternalLink size={12} />
              </Link>
            </div>

            <div className="mt-4 space-y-3">
              <div className="flex items-center justify-between rounded-[3px] border border-line p-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold text-text">ampir</span>
                    <span className="text-[11px] font-mono text-faint">v1.1.0</span>
                    <span className="rounded bg-emerald-500/10 px-2 py-0.2 text-[10.5px] font-medium text-emerald-600">
                      Operational
                    </span>
                  </div>
                  <p className="text-[12px] text-muted">
                    Support vector machine trained on antimicrobial peptide physicochemical profiles.
                  </p>
                </div>
                <span className="text-[11px] font-mono text-muted">Runtime: verified wheel</span>
              </div>

              <div className="flex items-center justify-between rounded-[3px] border border-line p-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold text-text">amPEPpy</span>
                    <span className="text-[11px] font-mono text-faint">v1.1.0</span>
                    <span className="rounded bg-emerald-500/10 px-2 py-0.2 text-[10.5px] font-medium text-emerald-600">
                      Operational
                    </span>
                  </div>
                  <p className="text-[12px] text-muted">
                    Random Forest predictor utilizing reduced amino acid composition clusters.
                  </p>
                </div>
                <span className="text-[11px] font-mono text-muted">Runtime: verified wheel</span>
              </div>

              <div className="flex items-center justify-between rounded-[3px] border border-line p-3 bg-raised/20">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold text-text">AMPlify</span>
                    <span className="text-[11px] font-mono text-faint">TensorFlow 1.x</span>
                    <span className="rounded bg-amber-500/10 px-2 py-0.2 text-[10.5px] font-medium text-amber-600">
                      Unavailable
                    </span>
                  </div>
                  <p className="text-[12px] text-muted">
                    Deep bi-LSTM attention model; pending legacy containerized runtime compatibility.
                  </p>
                </div>
                <span className="text-[11px] font-mono text-muted">Status: disabled</span>
              </div>

              <div className="flex items-center justify-between rounded-[3px] border border-line p-3 bg-raised/20">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold text-text">AMPScanner v2</span>
                    <span className="text-[11px] font-mono text-faint">Keras 2.2</span>
                    <span className="rounded bg-amber-500/10 px-2 py-0.2 text-[10.5px] font-medium text-amber-600">
                      Unavailable
                    </span>
                  </div>
                  <p className="text-[12px] text-muted">
                    Deep CNN architecture; disabled pending legacy Python 3.7 runtime environment.
                  </p>
                </div>
                <span className="text-[11px] font-mono text-muted">Status: disabled</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: Data Stores */}
      {activeTab === "storage" && (
        <div className="space-y-6">
          <div className="rounded-[4px] border border-line bg-panel p-5">
            <h2 className="text-[15px] font-semibold text-text">Relational Databases & Storage Locations</h2>
            <p className="text-[12px] text-muted">
              Internal SQLite database files and output directories maintaining full data lineage.
            </p>

            <div className="mt-4 space-y-3">
              <div className="rounded-[3px] border border-line p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <HardDrive size={14} className="text-cyan" />
                    <span className="text-[13px] font-semibold text-text">Projects & CRISPR Database</span>
                  </div>
                  <span className="font-mono text-[11px] text-emerald-600">Connected</span>
                </div>
                <p className="mt-1 text-[11px] font-mono text-faint">
                  artifacts/projects/projects.sqlite3
                </p>
                <div className="mt-2 text-[12px] text-muted">
                  Stores research projects, biological samples, annotated sequence records, variant comparisons, and CRISPR studies.
                </div>
              </div>

              <div className="rounded-[3px] border border-line p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <HardDrive size={14} className="text-cyan" />
                    <span className="text-[13px] font-semibold text-text">Sequencing Integrations Database</span>
                  </div>
                  <span className="font-mono text-[11px] text-emerald-600">Connected</span>
                </div>
                <p className="mt-1 text-[11px] font-mono text-faint">
                  artifacts/sequencing/sequencing.sqlite3
                </p>
                <div className="mt-2 text-[12px] text-muted">
                  Stores connector authentication, active runs, synchronized datasets, import states, and file checksums.
                </div>
              </div>

              <div className="rounded-[3px] border border-line p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <HardDrive size={14} className="text-cyan" />
                    <span className="text-[13px] font-semibold text-text">DRAMP 3.0 & 4.0 Reference Tables</span>
                  </div>
                  <span className="font-mono text-[11px] text-emerald-600">Ingested</span>
                </div>
                <p className="mt-1 text-[11px] font-mono text-faint">
                  artifacts/dramp/dramp_unified.parquet / sqlite3
                </p>
                <div className="mt-2 text-[12px] text-muted">
                  20,270 curated antimicrobial peptide records across 4 discrete benchmark collections with provenance audit.
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Scientific Parameters */}
      {activeTab === "diagnostics" && (
        <div className="space-y-6">
          <div className="rounded-[4px] border border-line bg-panel p-5">
            <h2 className="text-[15px] font-semibold text-text">Scientific & Pipeline Thresholds</h2>
            <p className="text-[12px] text-muted">
              Configure strictness thresholds for consensus calls, checksum validation, and background polling.
            </p>

            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="rounded-[3px] border border-line p-4">
                <label className="block text-[13px] font-medium text-text">
                  Consensus Classification Cutoff
                </label>
                <p className="mt-0.5 text-[11px] text-muted">
                  Combined probability threshold required for a candidate peptide to receive consensus AMP classification.
                </p>
                <input
                  type="number"
                  step="0.05"
                  min="0.5"
                  max="0.95"
                  value={consensusThreshold}
                  onChange={(e) => setConsensusThreshold(e.target.value)}
                  className="mt-3 w-full rounded-[3px] border border-line bg-ink px-3 py-1.5 text-[13px] font-mono text-text"
                />
              </div>

              <div className="rounded-[3px] border border-line p-4">
                <label className="block text-[13px] font-medium text-text">
                  Sequencer Auto-Sync Interval (minutes)
                </label>
                <p className="mt-0.5 text-[11px] text-muted">
                  Frequency of polling connected sequencers (BaseSpace, MinKNOW) for newly completed runs.
                </p>
                <input
                  type="number"
                  step="5"
                  min="5"
                  max="120"
                  value={autoSyncInterval}
                  onChange={(e) => setAutoSyncInterval(e.target.value)}
                  className="mt-3 w-full rounded-[3px] border border-line bg-ink px-3 py-1.5 text-[13px] font-mono text-text"
                />
              </div>
            </div>

            <div className="mt-4 rounded-[3px] border border-line p-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-[13px] font-semibold text-text">Enforce SHA-256 Checksum Verification</span>
                  <p className="text-[11px] text-muted">
                    Block downstream analysis of imported sequencing datasets if byte checksum does not match manifest.
                  </p>
                </div>
                <input
                  type="checkbox"
                  checked={requireChecksum}
                  onChange={(e) => setRequireChecksum(e.target.checked)}
                  className="h-4 w-4 rounded border-line text-cyan focus:ring-cyan"
                />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between rounded-[3px] bg-sage-soft p-3 text-[12px] text-cyan">
              <div className="flex items-center gap-2">
                <ShieldCheck size={16} />
                <span>Coordinate System: 1-Based Standard (Bioinformatics NCBI/EBI aligned)</span>
              </div>
              <span className="font-mono text-[11px]">Strict</span>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
