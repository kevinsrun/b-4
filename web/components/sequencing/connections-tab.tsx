"use client";

import { useState } from "react";
import {
  ConnectorInfo,
  SequencingConnection,
  ConnectionCreateRequest,
} from "@/lib/sequencing-types";
import { createConnection, deleteConnection, syncConnection } from "@/lib/sequencing-api";

interface ConnectionsTabProps {
  connectors: ConnectorInfo[];
  connections: SequencingConnection[];
  onRefresh: () => void;
}

export function ConnectionsTab({
  connectors,
  connections,
  onRefresh,
}: ConnectionsTabProps) {
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedConnectorId, setSelectedConnectorId] = useState<string>("illumina_basespace");
  const [connName, setConnName] = useState("");
  const [configFields, setConfigFields] = useState<Record<string, any>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const activeConnector = connectors.find((c) => c.connector_id === selectedConnectorId);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const payload: ConnectionCreateRequest = {
        connector_id: selectedConnectorId,
        name: connName || `${activeConnector?.name || "New Connection"}`,
        config: configFields,
        auto_sync: false,
      };
      await createConnection(payload);
      setSuccessMessage("Sequencing connection added and verified successfully!");
      setShowAddModal(false);
      setConnName("");
      setConfigFields({});
      onRefresh();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to create connection");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSync(connectionId: string) {
    setSyncingId(connectionId);
    try {
      const res = await syncConnection(connectionId);
      setSuccessMessage(
        `Synchronized successfully: discovered ${res.result.runs_discovered} run(s) and ${res.result.datasets_discovered} dataset(s).`
      );
      onRefresh();
    } catch (err: any) {
      setErrorMessage(err.message || "Sync failed");
    } finally {
      setSyncingId(null);
    }
  }

  async function handleDelete(connectionId: string) {
    if (!confirm("Are you sure you want to remove this connection? Discovered runs and datasets will be detached.")) {
      return;
    }
    await deleteConnection(connectionId);
    onRefresh();
  }

  return (
    <div className="space-y-6">
      {/* Top action bar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-text">Connected Sequencing Platforms</h2>
          <p className="text-[12px] text-muted">
            Manage authenticated connections to laboratory instruments, cloud hubs, and storage drop folders.
          </p>
        </div>
        <button
          onClick={() => {
            setErrorMessage(null);
            setShowAddModal(true);
          }}
          className="rounded-lg bg-accent px-3 py-1.5 text-[12px] font-semibold text-black hover:brightness-110 transition-all font-mono"
        >
          + Connect New Platform
        </button>
      </div>

      {/* Notifications */}
      {successMessage && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-[12px] text-emerald-300 flex items-center justify-between">
          <span>{successMessage}</span>
          <button onClick={() => setSuccessMessage(null)} className="text-muted hover:text-text">✕</button>
        </div>
      )}
      {errorMessage && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-[12px] text-red-300 flex items-center justify-between">
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage(null)} className="text-muted hover:text-text">✕</button>
        </div>
      )}

      {/* Connection Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {connections.map((conn) => {
          const isSyncing = syncingId === conn.connection_id;
          const isError = conn.status === "error";

          return (
            <div
              key={conn.connection_id}
              className="rounded-xl border border-line bg-card p-5 flex flex-col justify-between hover:border-line/80 transition-all"
            >
              <div>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2.5 w-2.5 rounded-full ${
                        isError
                          ? "bg-red-500 animate-pulse"
                          : conn.status === "connected"
                          ? "bg-emerald-400"
                          : "bg-amber-400"
                      }`}
                    />
                    <h3 className="font-semibold text-text text-[14px]">{conn.name}</h3>
                  </div>
                  <span className="rounded bg-surface px-2 py-0.5 text-[10px] font-mono uppercase text-muted">
                    {conn.vendor}
                  </span>
                </div>

                <p className="text-[11px] font-mono text-muted mt-1 truncate">
                  ID: {conn.connection_id}
                </p>

                {conn.error_message && (
                  <div className="mt-3 rounded border border-red-500/30 bg-red-500/10 p-2 text-[11px] text-red-300">
                    {conn.error_message}
                  </div>
                )}

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-2 mt-4 pt-3 border-t border-line/50 text-[11px]">
                  <div>
                    <span className="text-muted block">Runs</span>
                    <span className="font-mono font-semibold text-text text-sm">
                      {conn.discovered_runs_count}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted block">Datasets</span>
                    <span className="font-mono font-semibold text-text text-sm">
                      {conn.discovered_datasets_count}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted block">Last Sync</span>
                    <span className="font-mono text-muted text-[10px] block truncate">
                      {conn.last_sync_at ? new Date(conn.last_sync_at).toLocaleDateString() : "Never"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center justify-between gap-2 mt-5 pt-3 border-t border-line/50">
                <span className="text-[10px] font-mono text-muted">
                  Interval: {conn.sync_interval_seconds}s
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleSync(conn.connection_id)}
                    disabled={isSyncing}
                    className="rounded bg-surface hover:bg-surface/80 border border-line px-2.5 py-1 text-[11px] font-mono text-text transition-colors flex items-center gap-1.5"
                  >
                    {isSyncing ? (
                      <>
                        <div className="h-3 w-3 animate-spin rounded-full border border-accent border-t-transparent" />
                        Syncing...
                      </>
                    ) : (
                      "↻ Sync Now"
                    )}
                  </button>
                  <button
                    onClick={() => handleDelete(conn.connection_id)}
                    className="rounded hover:bg-red-500/10 hover:text-red-400 p-1 text-[11px] text-muted transition-colors"
                    title="Remove connection"
                  >
                    🗑
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Available Ecosystems Reference Grid */}
      <div className="mt-8 pt-6 border-t border-line">
        <h3 className="text-xs font-mono uppercase tracking-wider text-muted mb-4">
          Supported Sequencing Ecosystems
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {connectors.map((c) => (
            <div
              key={c.connector_id}
              className="rounded-lg border border-line/60 bg-surface/30 p-3 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-text text-[12px]">{c.name}</span>
                  <span className="text-[10px] font-mono text-muted uppercase">{c.vendor}</span>
                </div>
                <p className="text-[11px] text-muted mt-1 leading-snug line-clamp-3">
                  {c.description}
                </p>
              </div>
              <div className="mt-3 pt-2 border-t border-line/40 flex items-center justify-between text-[10px] font-mono text-muted">
                <span>Auth: {c.auth_type}</span>
                <span className="text-accent">{c.capabilities.length} features</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Add Connection Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-xl border border-line bg-card shadow-2xl p-6">
            <div className="flex items-center justify-between border-b border-line pb-3 mb-4">
              <h3 className="text-sm font-semibold text-text">Connect Sequencing Platform</h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-muted hover:text-text"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-4 text-[13px]">
              <div>
                <label className="block text-xs font-medium text-muted mb-1">
                  Sequencing Connector
                </label>
                <select
                  value={selectedConnectorId}
                  onChange={(e) => {
                    setSelectedConnectorId(e.target.value);
                    setConfigFields({});
                  }}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-text font-mono text-xs focus:outline-none focus:border-accent"
                >
                  {connectors.map((c) => (
                    <option key={c.connector_id} value={c.connector_id}>
                      {c.name} ({c.vendor})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-muted mb-1">
                  Connection Display Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. Core Genomics MiSeq"
                  value={connName}
                  onChange={(e) => setConnName(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-text text-xs focus:outline-none focus:border-accent"
                />
              </div>

              {/* Connector-specific fields */}
              {selectedConnectorId === "illumina_basespace" && (
                <div className="space-y-3 rounded-lg border border-line/60 bg-surface/30 p-3">
                  <div>
                    <label className="block text-[11px] font-mono text-muted mb-1">
                      BaseSpace API Access Token
                    </label>
                    <input
                      type="password"
                      placeholder="Enter personal or application access token"
                      value={configFields.api_token || ""}
                      onChange={(e) =>
                        setConfigFields({ ...configFields, api_token: e.target.value })
                      }
                      className="w-full rounded border border-line bg-surface px-2.5 py-1.5 text-xs text-text font-mono focus:outline-none"
                    />
                  </div>
                  <label className="flex items-center gap-2 text-[11px] text-muted cursor-pointer">
                    <input
                      type="checkbox"
                      checked={configFields.use_fixtures ?? true}
                      onChange={(e) =>
                        setConfigFields({ ...configFields, use_fixtures: e.target.checked })
                      }
                      className="rounded border-line text-accent"
                    />
                    Use verified BaseSpace contract fixtures (offline simulation mode)
                  </label>
                </div>
              )}

              {selectedConnectorId === "oxford_nanopore" && (
                <div className="space-y-3 rounded-lg border border-line/60 bg-surface/30 p-3">
                  <div>
                    <label className="block text-[11px] font-mono text-muted mb-1">
                      MinKNOW Output Directory Path
                    </label>
                    <input
                      type="text"
                      placeholder="/data/minknow/runs/..."
                      value={configFields.directory_path || ""}
                      onChange={(e) =>
                        setConfigFields({ ...configFields, directory_path: e.target.value })
                      }
                      className="w-full rounded border border-line bg-surface px-2.5 py-1.5 text-xs text-text font-mono focus:outline-none"
                    />
                  </div>
                  <label className="flex items-center gap-2 text-[11px] text-muted cursor-pointer">
                    <input
                      type="checkbox"
                      checked={configFields.use_fixtures ?? true}
                      onChange={(e) =>
                        setConfigFields({ ...configFields, use_fixtures: e.target.checked })
                      }
                      className="rounded border-line text-accent"
                    />
                    Use verified Oxford Nanopore MinKNOW fixtures
                  </label>
                </div>
              )}

              {selectedConnectorId === "pacbio_smrtlink" && (
                <div className="space-y-3 rounded-lg border border-line/60 bg-surface/30 p-3">
                  <div>
                    <label className="block text-[11px] font-mono text-muted mb-1">
                      SMRT Link Server URL
                    </label>
                    <input
                      type="text"
                      placeholder="https://smrtlink.lab.org:8243"
                      value={configFields.server_url || ""}
                      onChange={(e) =>
                        setConfigFields({ ...configFields, server_url: e.target.value })
                      }
                      className="w-full rounded border border-line bg-surface px-2.5 py-1.5 text-xs text-text font-mono focus:outline-none"
                    />
                  </div>
                  <label className="flex items-center gap-2 text-[11px] text-muted cursor-pointer">
                    <input
                      type="checkbox"
                      checked={configFields.use_fixtures ?? true}
                      onChange={(e) =>
                        setConfigFields({ ...configFields, use_fixtures: e.target.checked })
                      }
                      className="rounded border-line text-accent"
                    />
                    Use verified PacBio SMRT Link fixtures
                  </label>
                </div>
              )}

              {selectedConnectorId === "local_folder" && (
                <div className="space-y-3 rounded-lg border border-line/60 bg-surface/30 p-3">
                  <div>
                    <label className="block text-[11px] font-mono text-muted mb-1">
                      Local Allowlisted Directory Path
                    </label>
                    <input
                      type="text"
                      placeholder="artifacts/sequencing/incoming"
                      value={configFields.directory_path || ""}
                      onChange={(e) =>
                        setConfigFields({ ...configFields, directory_path: e.target.value })
                      }
                      className="w-full rounded border border-line bg-surface px-2.5 py-1.5 text-xs text-text font-mono focus:outline-none"
                    />
                  </div>
                  <label className="flex items-center gap-2 text-[11px] text-muted cursor-pointer">
                    <input
                      type="checkbox"
                      checked={configFields.require_stability ?? true}
                      onChange={(e) =>
                        setConfigFields({ ...configFields, require_stability: e.target.checked })
                      }
                      className="rounded border-line text-accent"
                    />
                    Require file stability (detect active file transfers)
                  </label>
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-line">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="rounded-lg border border-line px-3 py-1.5 text-xs text-text hover:bg-surface"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="rounded-lg bg-accent px-4 py-1.5 text-xs font-semibold text-black hover:brightness-110 font-mono disabled:opacity-50"
                >
                  {isSubmitting ? "Connecting..." : "Save Connection"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
