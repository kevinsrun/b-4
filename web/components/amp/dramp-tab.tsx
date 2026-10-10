"use client";

import { useEffect, useState } from "react";
import type { DRAMPRecord, DRAMPDatasetManifest, DRAMPSearchResponse } from "@/lib/amp-types";
import { searchDramp, getDrampRecord } from "@/lib/amp-api";
import { FIXTURE_DRAMP_DATASETS, FIXTURE_DRAMP_STATS } from "@/lib/amp-fixtures";
import { Panel, Status, Id } from "@/components/ui";

interface DrampTabProps {
  isBackendConnected: boolean;
  useFixtures: boolean;
  initialRecordId?: string | null;
  onSendToPredictor?: (sequenceId: string, sequence: string) => void;
}

export function DrampTab({
  isBackendConnected,
  useFixtures,
  initialRecordId,
  onSendToPredictor,
}: DrampTabProps) {
  // Search parameters
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState(initialRecordId || "DRAMP00001");
  const [searchMode, setSearchMode] = useState<"record_id" | "sequence">("record_id");
  const [offset, setOffset] = useState(0);
  const limit = 10;

  // Search Results
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchResponse, setSearchResponse] = useState<DRAMPSearchResponse | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<DRAMPRecord | null>(null);

  async function performSearch(queryText = searchQuery, pageOffset = offset) {
    const trimmed = queryText.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);

    const params: {
      sequence?: string;
      record_id?: string;
      dataset_id?: string;
      limit: number;
      offset: number;
    } = {
      limit,
      offset: pageOffset,
    };

    if (selectedDatasetId !== "all") {
      params.dataset_id = selectedDatasetId;
    }

    if (searchMode === "record_id") {
      params.record_id = trimmed;
    } else {
      params.sequence = trimmed.toUpperCase();
    }

    try {
      const data = await searchDramp(params, useFixtures || !isBackendConnected);
      setSearchResponse(data);
      if (data.records.length > 0) {
        setSelectedRecord(data.records[0]);
      } else {
        setSelectedRecord(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    performSearch(initialRecordId || "DRAMP00001", 0);
  }, [initialRecordId]);

  const activeDatasetManifest =
    selectedDatasetId === "all"
      ? null
      : FIXTURE_DRAMP_DATASETS.find((d) => d.dataset_id === selectedDatasetId);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">DRAMP 3.0 & 4.0 Reference Explorer</p>
          <h2 className="mt-1 text-2xl font-medium tracking-tight text-text">
            Official DRAMP Datasets & Provenance
          </h2>
          <p className="text-[12px] text-muted">
            Search verified reference antimicrobial peptide records across four independently ingested datasets.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted">Total Ingested:</span>
          <span className="num font-semibold text-text">20,270 records</span>
          <span className="text-[11px] text-muted">·</span>
          <span className="text-[11px] text-faint">Quarantined: 4,332 rows</span>
        </div>
      </div>

      {/* Dataset Filter Tabs — Four Individual Collections */}
      <div>
        <div className="text-[11px] font-medium text-muted uppercase tracking-wider mb-2">
          Select DRAMP Dataset Collection:
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div
            onClick={() => setSelectedDatasetId("all")}
            className={`cursor-pointer border p-3 transition-colors ${
              selectedDatasetId === "all"
                ? "border-cyan bg-cyan/10"
                : "border-line bg-panel hover:border-line-strong"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-[12px] font-semibold text-text">All Datasets Combined</span>
              <span className="num text-[11px] text-cyan">20,270</span>
            </div>
            <p className="mt-1 text-[10.5px] text-muted">Unified reference lookup</p>
          </div>

          {FIXTURE_DRAMP_DATASETS.map((ds, idx) => {
            const stats = FIXTURE_DRAMP_STATS.byDataset[idx];
            const isSelected = selectedDatasetId === ds.dataset_id;

            return (
              <div
                key={ds.dataset_id}
                onClick={() => setSelectedDatasetId(ds.dataset_id)}
                className={`cursor-pointer border p-3 transition-colors ${
                  isSelected
                    ? "border-cyan bg-cyan/10"
                    : "border-line bg-panel hover:border-line-strong"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[12px] font-semibold text-text truncate max-w-[140px]" title={stats?.name}>
                    {idx === 0 ? "DRAMP 3.0 General" : idx === 1 ? "DRAMP 4 Clinical" : idx === 2 ? "DRAMP 4 General" : "DRAMP 4 Stability"}
                  </span>
                  <span className="num text-[11px] text-text font-medium">{stats?.records.toLocaleString()}</span>
                </div>
                <div className="mt-1 flex items-center justify-between text-[10px] text-muted">
                  <span>Rejected: {stats?.rejected}</span>
                  <span className="text-cyan-dim">{ds.license}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Dataset Provenance Drawer if specific dataset selected */}
      {activeDatasetManifest && (
        <div className="border border-line bg-raised/30 p-3 text-[11px] text-muted space-y-1.5">
          <div className="flex items-center justify-between font-medium text-text">
            <span>Dataset Provenance: {activeDatasetManifest.source_version}</span>
            <span className="num text-faint">Revision {activeDatasetManifest.ingestion_revision}</span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div>
              Source URL:{" "}
              <a
                href={activeDatasetManifest.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-cyan underline truncate inline-block max-w-xs align-bottom"
              >
                {activeDatasetManifest.source_url}
              </a>
            </div>
            <div>
              Distribution SHA-256: <Id>{activeDatasetManifest.source_sha256.slice(0, 16)}...</Id>
            </div>
            <div>Attribution: {activeDatasetManifest.attribution}</div>
            <div>
              Snapshot Status:{" "}
              <span className="text-green font-mono">
                {activeDatasetManifest.source_provenance?.release_version_status || "official_snapshot"}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Search Bar */}
      <Panel title="Reference Query">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1 border border-line bg-ink p-1">
              <button
                type="button"
                onClick={() => setSearchMode("record_id")}
                className={`px-3 py-1 text-[11px] font-medium transition-colors ${
                  searchMode === "record_id" ? "bg-cyan/20 text-cyan" : "text-muted hover:text-text"
                }`}
              >
                By Record ID (e.g. DRAMP00001)
              </button>
              <button
                type="button"
                onClick={() => setSearchMode("sequence")}
                className={`px-3 py-1 text-[11px] font-medium transition-colors ${
                  searchMode === "sequence" ? "bg-cyan/20 text-cyan" : "text-muted hover:text-text"
                }`}
              >
                By Sequence Residues
              </button>
            </div>

            <div className="flex-1 min-w-[240px]">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && performSearch(searchQuery, 0)}
                placeholder={
                  searchMode === "record_id"
                    ? "Enter DRAMP identifier, e.g. DRAMP00001, DRAMP00002..."
                    : "Enter amino acid sequence, e.g. GLFDIVKKVVGALG..."
                }
                className="w-full border border-line bg-ink px-3 py-2 text-[12px] text-text font-mono focus:border-cyan focus:outline-none"
              />
            </div>

            <button
              type="button"
              disabled={loading || !searchQuery.trim()}
              onClick={() => performSearch(searchQuery, 0)}
              className="border border-cyan/40 bg-cyan/15 px-4 py-2 text-[12px] font-medium text-cyan hover:bg-cyan/25 transition-colors disabled:opacity-50"
            >
              {loading ? "Searching..." : "Search DRAMP"}
            </button>
          </div>

          <div className="flex items-center gap-2 text-[11px] text-faint">
            <span>Examples:</span>
            <button
              type="button"
              onClick={() => {
                setSearchMode("record_id");
                setSearchQuery("DRAMP00001");
                performSearch("DRAMP00001", 0);
              }}
              className="text-cyan hover:underline"
            >
              DRAMP00001 (Nisin A)
            </button>
            <span>·</span>
            <button
              type="button"
              onClick={() => {
                setSearchMode("record_id");
                setSearchQuery("DRAMP00002");
                performSearch("DRAMP00002", 0);
              }}
              className="text-cyan hover:underline"
            >
              DRAMP00002 (Magainin-2)
            </button>
            <span>·</span>
            <button
              type="button"
              onClick={() => {
                setSearchMode("record_id");
                setSearchQuery("DRAMP00038");
                performSearch("DRAMP00038", 0);
              }}
              className="text-cyan hover:underline"
            >
              DRAMP00038 (Subtilin)
            </button>
          </div>
        </div>
      </Panel>

      {/* Error state */}
      {error && (
        <div className="border border-red/40 bg-red/10 p-3 text-[12px] text-red">
          {error}
        </div>
      )}

      {/* Search Results Workspace */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Results List */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center justify-between text-[12px] text-muted">
            <span>
              Matches: <strong className="num text-text">{searchResponse?.total ?? 0}</strong>
            </span>
            {searchResponse && searchResponse.total > limit && (
              <div className="flex items-center gap-2">
                <button
                  disabled={offset === 0}
                  onClick={() => {
                    const newOffset = Math.max(0, offset - limit);
                    setOffset(newOffset);
                    performSearch(searchQuery, newOffset);
                  }}
                  className="px-2 py-0.5 border border-line bg-panel text-[11px] disabled:opacity-30"
                >
                  Prev
                </button>
                <span className="num text-[11px]">
                  {Math.floor(offset / limit) + 1} / {Math.ceil(searchResponse.total / limit)}
                </span>
                <button
                  disabled={offset + limit >= searchResponse.total}
                  onClick={() => {
                    const newOffset = offset + limit;
                    setOffset(newOffset);
                    performSearch(searchQuery, newOffset);
                  }}
                  className="px-2 py-0.5 border border-line bg-panel text-[11px] disabled:opacity-30"
                >
                  Next
                </button>
              </div>
            )}
          </div>

          <div className="space-y-2">
            {searchResponse?.records.map((rec) => {
              const isSelected = selectedRecord?.record_id === rec.record_id;

              return (
                <div
                  key={`${rec.record_id}-${rec.provenance.dataset_id}`}
                  onClick={() => setSelectedRecord(rec)}
                  className={`cursor-pointer border p-3 transition-colors ${
                    isSelected
                      ? "border-cyan bg-panel shadow-sm ring-1 ring-cyan/40"
                      : "border-line bg-panel/70 hover:border-line-strong hover:bg-panel"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="num font-semibold text-text text-[13px]">
                      {rec.metadata.Name || rec.record_id}
                    </span>
                    <Id>{rec.record_id}</Id>
                  </div>
                  <p className="mt-1 text-[11px] text-muted truncate">
                    {rec.metadata.Source || "Biological source unrecorded"} · {rec.sequence.length} aa
                  </p>
                  <p className="mt-1 font-mono text-[10px] text-faint truncate">{rec.sequence}</p>
                </div>
              );
            })}

            {searchResponse && searchResponse.records.length === 0 && (
              <div className="p-8 text-center text-[12px] text-muted border border-dashed border-line">
                No matching DRAMP records found.
              </div>
            )}
          </div>
        </div>

        {/* Selected Record Inspector */}
        <div className="lg:col-span-7">
          {selectedRecord ? (
            <Panel
              title={`Record: ${selectedRecord.record_id}`}
              aside={
                onSendToPredictor && (
                  <button
                    onClick={() =>
                      onSendToPredictor(
                        selectedRecord.record_id,
                        selectedRecord.sequence
                      )
                    }
                    className="border border-cyan/40 bg-cyan/15 px-3 py-1 text-[11px] font-medium text-cyan hover:bg-cyan/25 transition-colors"
                  >
                    Test in Predictor Workspace →
                  </button>
                )
              }
            >
              <div className="space-y-4">
                {/* Scientific Provenance Badge */}
                <div className="border border-line bg-raised/30 p-2.5 text-[11px] text-muted flex items-center justify-between">
                  <span>Evidence Type: <strong className="text-cyan">Reference Database Annotation</strong></span>
                  <span className="text-amber">Experimental verification: Not independently assessed</span>
                </div>

                {/* Primary Sequence */}
                <div>
                  <div className="flex items-center justify-between text-[11px] text-faint uppercase tracking-wider mb-1">
                    <span>Primary Amino Acid Residues</span>
                    <span className="num">{selectedRecord.sequence.length} residues</span>
                  </div>
                  <div className="num font-mono text-[12px] text-text bg-ink p-3 border border-line break-all leading-relaxed">
                    {selectedRecord.sequence}
                  </div>
                  <div className="mt-1 text-[10px] text-muted">
                    SHA-256 Checksum: <Id>{selectedRecord.sequence_checksum}</Id>
                  </div>
                </div>

                {/* Annotations Table */}
                <div className="border border-line bg-panel overflow-hidden">
                  <table className="w-full text-left text-[11.5px]">
                    <tbody className="divide-y divide-line/60">
                      <tr>
                        <td className="py-2 px-3 text-muted w-1/3 bg-raised/20">Name</td>
                        <td className="py-2 px-3 text-text font-medium">{selectedRecord.metadata.Name || "—"}</td>
                      </tr>
                      <tr>
                        <td className="py-2 px-3 text-muted bg-raised/20">Source Organism</td>
                        <td className="py-2 px-3 text-text">{selectedRecord.metadata.Source || "—"}</td>
                      </tr>
                      <tr>
                        <td className="py-2 px-3 text-muted bg-raised/20">Target Organism</td>
                        <td className="py-2 px-3 text-text">{selectedRecord.metadata.Target_Organism || "—"}</td>
                      </tr>
                      <tr>
                        <td className="py-2 px-3 text-muted bg-raised/20">Activity</td>
                        <td className="py-2 px-3 text-text">{selectedRecord.metadata.Activity || "—"}</td>
                      </tr>
                      <tr>
                        <td className="py-2 px-3 text-muted bg-raised/20">Hemolytic Activity</td>
                        <td className="py-2 px-3 text-text">{selectedRecord.metadata.Hemolytic_Activity || "Not reported"}</td>
                      </tr>
                      <tr>
                        <td className="py-2 px-3 text-muted bg-raised/20">Structure Type</td>
                        <td className="py-2 px-3 text-text">{selectedRecord.metadata.Linear_Cyclic || "Linear"}</td>
                      </tr>
                      <tr>
                        <td className="py-2 px-3 text-muted bg-raised/20">Swiss-Prot Accession</td>
                        <td className="py-2 px-3 text-text">
                          {selectedRecord.metadata.Swiss_Prot_Entry ? (
                            <Id>{selectedRecord.metadata.Swiss_Prot_Entry}</Id>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-2 px-3 text-muted bg-raised/20">PDB Identifier</td>
                        <td className="py-2 px-3 text-text">
                          {selectedRecord.metadata.PDB_ID ? (
                            <Id>{selectedRecord.metadata.PDB_ID}</Id>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-2 px-3 text-muted bg-raised/20">PubMed ID</td>
                        <td className="py-2 px-3 text-text">
                          {selectedRecord.metadata.Pubmed_ID ? (
                            <a
                              href={`https://pubmed.ncbi.nlm.nih.gov/${selectedRecord.metadata.Pubmed_ID}/`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-cyan underline"
                            >
                              PMID: {selectedRecord.metadata.Pubmed_ID} ↗
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                {/* Dataset Provenance Footer */}
                <div className="text-[10.5px] text-faint border-t border-line pt-2 flex items-center justify-between">
                  <span>Source Collection: {selectedRecord.provenance.source_version}</span>
                  <span>License: {selectedRecord.provenance.license}</span>
                </div>
              </div>
            </Panel>
          ) : (
            <div className="border border-line bg-panel p-12 text-center text-[12px] text-muted">
              Select a DRAMP record on the left to inspect detailed annotations and provenance.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
