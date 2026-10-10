"use client";

import { useState, useMemo } from "react";
import { SequenceAnnotation, SequenceVariant } from "@/lib/project-types";

interface SequenceExplorerProps {
  sequence: string;
  name: string;
  moleculeType: "dna" | "protein" | "rna";
  coordinates?: string | null;
  annotations?: SequenceAnnotation[];
  variants?: SequenceVariant[];
  comparisonSequence?: string | null;
  comparisonName?: string | null;
  onAnnotationClick?: (ann: SequenceAnnotation) => void;
  onVariantClick?: (v: SequenceVariant) => void;
}

export function SequenceExplorer({
  sequence,
  name,
  moleculeType,
  coordinates,
  annotations = [],
  variants = [],
  comparisonSequence,
  comparisonName = "Query Sequence",
  onAnnotationClick,
  onVariantClick,
}: SequenceExplorerProps) {
  const [zoomLevel, setZoomLevel] = useState<"detailed" | "compact">("detailed");
  const [chunkSize, setChunkSize] = useState<number>(60);
  const [currentWindowPage, setCurrentWindowPage] = useState<number>(0);
  const [searchCoord, setSearchCoord] = useState<string>("");
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<string | null>(null);
  const [copiedNotification, setCopiedNotification] = useState<boolean>(false);

  const cleanSeq = useMemo(() => sequence.replace(/\s+/g, "").toUpperCase(), [sequence]);
  const cleanComp = useMemo(
    () => (comparisonSequence ? comparisonSequence.replace(/\s+/g, "").toUpperCase() : null),
    [comparisonSequence]
  );

  const totalLength = cleanSeq.length;
  const totalPages = Math.ceil(totalLength / chunkSize);

  const displayPage = Math.min(Math.max(0, currentWindowPage), Math.max(0, totalPages - 1));
  const pageStart = displayPage * chunkSize;
  const pageEnd = Math.min(pageStart + chunkSize, totalLength);

  const windowSeq = cleanSeq.slice(pageStart, pageEnd);
  const windowComp = cleanComp ? cleanComp.slice(pageStart, pageEnd) : null;

  // Active annotations in current page window
  const windowAnnotations = annotations.filter(
    (a) => a.start <= pageEnd && a.end >= pageStart + 1
  );

  // Active variants in current page window
  const windowVariants = variants.filter(
    (v) => v.position >= pageStart + 1 && v.position <= pageEnd
  );

  function handleJump(e: React.FormEvent) {
    e.preventDefault();
    const pos = parseInt(searchCoord, 10);
    if (!isNaN(pos) && pos >= 1 && pos <= totalLength) {
      const targetPage = Math.floor((pos - 1) / chunkSize);
      setCurrentWindowPage(targetPage);
    }
  }

  function handleCopyFasta() {
    const fasta = `>${name} ${coordinates || ""}\n${cleanSeq.match(/.{1,60}/g)?.join("\n") || cleanSeq}\n`;
    navigator.clipboard.writeText(fasta);
    setCopiedNotification(true);
    setTimeout(() => setCopiedNotification(false), 2000);
  }

  function handleDownloadFasta() {
    const fasta = `>${name} ${coordinates || ""}\n${cleanSeq.match(/.{1,60}/g)?.join("\n") || cleanSeq}\n`;
    const blob = new Blob([fasta], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name.replace(/\s+/g, "_")}.fasta`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Color mapping for residues
  function getCharColor(char: string, isVariant = false) {
    if (isVariant) return "bg-red-500/20 text-red-400 font-bold underline";
    if (moleculeType === "dna" || moleculeType === "rna") {
      switch (char) {
        case "A":
          return "text-emerald-400";
        case "T":
        case "U":
          return "text-rose-400";
        case "C":
          return "text-cyan-400";
        case "G":
          return "text-amber-400";
        default:
          return "text-text";
      }
    }
    // Protein color groups
    const basic = "KRH";
    const acidic = "DE";
    const hydrophobic = "AVILMFYW";
    const polar = "STNQC";
    if (basic.includes(char)) return "text-cyan-400 font-semibold";
    if (acidic.includes(char)) return "text-rose-400 font-semibold";
    if (hydrophobic.includes(char)) return "text-emerald-400";
    if (polar.includes(char)) return "text-amber-400";
    return "text-text";
  }

  return (
    <div className="rounded-xl border border-line bg-card overflow-hidden text-[12px] shadow-sm">
      {/* Explorer Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface/50 px-4 py-3">
        <div className="flex items-center gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold text-text text-sm">{name}</span>
              <span className="rounded bg-surface px-1.5 py-0.2 text-[10px] font-mono uppercase text-muted border border-line">
                {moleculeType}
              </span>
              <span className="text-[11px] font-mono text-muted">
                {totalLength.toLocaleString()} {moleculeType === "protein" ? "aa" : "bp"}
              </span>
            </div>
            {coordinates && (
              <span className="text-[10px] font-mono text-muted block mt-0.5">
                Coordinates: {coordinates}
              </span>
            )}
          </div>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Zoom Level */}
          <div className="flex items-center rounded-lg border border-line bg-surface p-0.5 text-[10px] font-mono">
            <button
              onClick={() => setZoomLevel("detailed")}
              className={`rounded px-2 py-0.5 transition-colors ${
                zoomLevel === "detailed"
                  ? "bg-accent text-black font-semibold"
                  : "text-muted hover:text-text"
              }`}
            >
              Letters
            </button>
            <button
              onClick={() => setZoomLevel("compact")}
              className={`rounded px-2 py-0.5 transition-colors ${
                zoomLevel === "compact"
                  ? "bg-accent text-black font-semibold"
                  : "text-muted hover:text-text"
              }`}
            >
              Compact
            </button>
          </div>

          {/* Jump to coordinate */}
          <form onSubmit={handleJump} className="flex items-center gap-1">
            <input
              type="number"
              min={1}
              max={totalLength}
              placeholder="Pos"
              value={searchCoord}
              onChange={(e) => setSearchCoord(e.target.value)}
              className="w-16 rounded border border-line bg-surface px-2 py-1 text-[11px] text-text font-mono focus:outline-none focus:border-accent"
            />
            <button
              type="submit"
              className="rounded bg-surface hover:bg-surface/80 border border-line px-2 py-1 text-[10px] font-mono text-muted hover:text-text"
            >
              Go
            </button>
          </form>

          {/* Export tools */}
          <button
            onClick={handleCopyFasta}
            className="rounded bg-surface hover:bg-surface/80 border border-line px-2.5 py-1 text-[10px] font-mono text-text transition-colors"
          >
            {copiedNotification ? "✓ Copied!" : "Copy FASTA"}
          </button>
          <button
            onClick={handleDownloadFasta}
            className="rounded bg-surface hover:bg-surface/80 border border-line px-2.5 py-1 text-[10px] font-mono text-text transition-colors"
          >
            Download
          </button>
        </div>
      </div>

      {/* Feature Track Legend */}
      {annotations.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line/60 bg-surface/30 px-4 py-2 text-[10px] font-mono">
          <span className="text-muted uppercase tracking-wider font-semibold">Tracks:</span>
          {annotations.map((ann) => {
            const isSelected = selectedAnnotationId === ann.annotation_id;
            return (
              <button
                key={ann.annotation_id}
                onClick={() => {
                  setSelectedAnnotationId(isSelected ? null : ann.annotation_id);
                  if (onAnnotationClick) onAnnotationClick(ann);
                  // Jump to start
                  setCurrentWindowPage(Math.floor((ann.start - 1) / chunkSize));
                }}
                className={`rounded px-2 py-0.5 border transition-all ${
                  isSelected
                    ? "border-accent bg-accent/20 text-accent font-bold"
                    : "border-line/70 bg-surface/70 text-muted hover:text-text"
                }`}
              >
                {ann.name} ({ann.start}..{ann.end})
              </button>
            );
          })}
        </div>
      )}

      {/* Sequence Canvas Body */}
      <div className="p-4 overflow-x-auto font-mono select-text">
        {zoomLevel === "detailed" ? (
          <div className="space-y-4">
            {/* Header Coordinate Ruler */}
            <div className="flex items-center gap-3 text-[10px] text-muted border-b border-line/40 pb-1">
              <span className="w-16 text-right">Coord</span>
              <div className="flex gap-0 font-mono tracking-widest text-muted/80">
                {Array.from({ length: Math.ceil(windowSeq.length / 10) }).map((_, i) => (
                  <span key={i} className="inline-block w-[10ch] text-left">
                    |{pageStart + i * 10 + 1}
                  </span>
                ))}
              </div>
            </div>

            {/* Reference Sequence Line */}
            <div className="flex items-center gap-3">
              <span className="w-16 text-right text-[11px] text-muted">
                {pageStart + 1}
              </span>
              <div className="flex flex-wrap gap-0 font-mono text-[13px] tracking-widest leading-relaxed">
                {windowSeq.split("").map((char, idx) => {
                  const globalPos = pageStart + idx + 1;
                  const matchingVariant = windowVariants.find((v) => v.position === globalPos);
                  const isAnnotated = windowAnnotations.some(
                    (a) => globalPos >= a.start && globalPos <= a.end
                  );

                  return (
                    <span
                      key={idx}
                      title={`Pos: ${globalPos} (${char})${
                        matchingVariant
                          ? ` - Variant: ${matchingVariant.reference_allele}>${matchingVariant.alternate_allele} (${matchingVariant.predicted_effect || ""})`
                          : ""
                      }`}
                      className={`inline-block px-[1px] rounded transition-colors ${
                        matchingVariant
                          ? "bg-rose-500/25 text-rose-300 font-bold border-b border-rose-500"
                          : isAnnotated
                          ? "bg-accent/10 " + getCharColor(char)
                          : getCharColor(char)
                      }`}
                    >
                      {char}
                    </span>
                  );
                })}
              </div>
            </div>

            {/* Comparison Sequence Line (if provided) */}
            {windowComp && (
              <div className="flex items-center gap-3 pt-1 border-t border-line/30">
                <span className="w-16 text-right text-[10px] text-accent truncate" title={comparisonName ?? undefined}>
                  Query
                </span>
                <div className="flex flex-wrap gap-0 font-mono text-[13px] tracking-widest leading-relaxed">
                  {windowComp.split("").map((qChar, idx) => {
                    const globalPos = pageStart + idx + 1;
                    const refChar = windowSeq[idx];
                    const isMismatch = refChar && qChar !== refChar;

                    return (
                      <span
                        key={idx}
                        title={`Query Pos ${globalPos}: ${qChar}${isMismatch ? ` (Mismatch vs ${refChar})` : ""}`}
                        className={`inline-block px-[1px] rounded ${
                          isMismatch
                            ? "bg-rose-500/30 text-rose-200 font-bold underline"
                            : "text-muted"
                        }`}
                      >
                        {qChar}
                      </span>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Active Annotations Spans for this line */}
            {windowAnnotations.length > 0 && (
              <div className="pt-2 pl-20 space-y-1">
                {windowAnnotations.map((ann) => (
                  <div
                    key={ann.annotation_id}
                    className="flex items-center gap-2 text-[10px] text-muted"
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                    <span className="font-bold text-text">{ann.name}</span>
                    <span className="text-muted">
                      [{Math.max(pageStart + 1, ann.start)}..{Math.min(pageEnd, ann.end)}]
                    </span>
                    <span className="text-muted/75 italic">{ann.feature_type}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          /* Compact Density Track Mode */
          <div className="space-y-3 py-2">
            <div className="h-6 w-full rounded bg-surface border border-line relative overflow-hidden flex items-center">
              {/* Density Bar */}
              <div
                className="absolute top-0 bottom-0 bg-accent/20 border-r border-accent"
                style={{
                  left: `${(pageStart / totalLength) * 100}%`,
                  width: `${(chunkSize / totalLength) * 100}%`,
                }}
              />
              {/* Annotation Markers */}
              {annotations.map((ann) => (
                <div
                  key={ann.annotation_id}
                  title={`${ann.name} (${ann.start}..${ann.end})`}
                  className="absolute top-1 bottom-1 bg-accent/60 rounded-sm"
                  style={{
                    left: `${(ann.start / totalLength) * 100}%`,
                    width: `${Math.max(1, ((ann.end - ann.start) / totalLength) * 100)}%`,
                  }}
                />
              ))}
              {/* Variant Markers */}
              {variants.map((v) => (
                <div
                  key={v.variant_id}
                  title={`Variant at ${v.position}`}
                  className="absolute top-0 bottom-0 w-1 bg-rose-500"
                  style={{ left: `${(v.position / totalLength) * 100}%` }}
                />
              ))}
            </div>

            <div className="flex items-center justify-between text-[11px] text-muted">
              <span>Position 1</span>
              <span className="text-accent font-semibold">
                Viewing window: {pageStart + 1} - {pageEnd}
              </span>
              <span>Position {totalLength}</span>
            </div>
          </div>
        )}
      </div>

      {/* Pagination Footer */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface/50 px-4 py-2.5 text-[11px] font-mono">
        <div className="flex items-center gap-2 text-muted">
          <span>Window size:</span>
          <select
            value={chunkSize}
            onChange={(e) => {
              setChunkSize(parseInt(e.target.value, 10));
              setCurrentWindowPage(0);
            }}
            className="rounded border border-line bg-surface px-1.5 py-0.5 text-text"
          >
            <option value={40}>40 bp</option>
            <option value={60}>60 bp</option>
            <option value={100}>100 bp</option>
            <option value={200}>200 bp</option>
          </select>
          <span className="ml-2">
            Showing {pageStart + 1} - {pageEnd} of {totalLength}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setCurrentWindowPage(0)}
            disabled={displayPage === 0}
            className="rounded border border-line bg-surface px-2 py-0.5 disabled:opacity-40 hover:bg-surface/80"
          >
            ⇤ First
          </button>
          <button
            onClick={() => setCurrentWindowPage((p) => Math.max(0, p - 1))}
            disabled={displayPage === 0}
            className="rounded border border-line bg-surface px-2 py-0.5 disabled:opacity-40 hover:bg-surface/80"
          >
            ← Prev
          </button>
          <span className="px-2 text-muted">
            Page {displayPage + 1} / {totalPages || 1}
          </span>
          <button
            onClick={() => setCurrentWindowPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={displayPage >= totalPages - 1}
            className="rounded border border-line bg-surface px-2 py-0.5 disabled:opacity-40 hover:bg-surface/80"
          >
            Next →
          </button>
          <button
            onClick={() => setCurrentWindowPage(totalPages - 1)}
            disabled={displayPage >= totalPages - 1}
            className="rounded border border-line bg-surface px-2 py-0.5 disabled:opacity-40 hover:bg-surface/80"
          >
            Last ⇥
          </button>
        </div>
      </div>
    </div>
  );
}
