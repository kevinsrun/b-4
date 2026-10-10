"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  CrisprObjective,
  AnnotatedSequence,
  SequenceComparisonResult,
} from "@/lib/project-types";
import {
  fetchCrisprStudies,
  fetchSequence,
  compareSequence,
  createCrisprStudy,
  fetchAllSequences,
} from "@/lib/project-api";
import { SequenceExplorer } from "@/components/sequence-explorer/sequence-explorer";

export function CrisprWorkspace() {
  const searchParams = useSearchParams();
  const initialStudyId = searchParams.get("studyId");
  const initialSeqId = searchParams.get("sequenceId");

  const [studies, setStudies] = useState<CrisprObjective[]>([]);
  const [selectedStudyId, setSelectedStudyId] = useState<string | null>(initialStudyId);
  const [currentSequence, setCurrentSequence] = useState<AnnotatedSequence | null>(null);

  // Variant comparison state
  const [querySequenceInput, setQuerySequenceInput] = useState<string>("");
  const [queryNameInput, setQueryNameInput] = useState<string>("Isolate Variant Query");
  const [comparisonResult, setComparisonResult] = useState<SequenceComparisonResult | null>(null);
  const [isComparing, setIsComparing] = useState(false);

  // New study modal
  const [showNewModal, setShowNewModal] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newPurpose, setNewPurpose] = useState("");
  const [newGene, setNewGene] = useState("");
  const [allAvailableSeqs, setAllAvailableSeqs] = useState<AnnotatedSequence[]>([]);
  const [selectedSeqIdForNew, setSelectedSeqIdForNew] = useState("");

  const [isLoading, setIsLoading] = useState(true);

  // Load studies
  async function loadStudies() {
    setIsLoading(true);
    try {
      const res = await fetchCrisprStudies();
      setStudies(res.studies);
      const targetId = initialStudyId || (res.studies.length > 0 ? res.studies[0].study_id : null);
      setSelectedStudyId(targetId);

      const seqsRes = await fetchAllSequences();
      setAllAvailableSeqs(seqsRes.sequences);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadStudies();
  }, []);

  const activeStudy = studies.find((s) => s.study_id === selectedStudyId);

  // Load sequence when study changes or initialSeqId is set
  useEffect(() => {
    const seqIdToLoad = initialSeqId || (activeStudy ? activeStudy.target_sequence_id : null);
    if (seqIdToLoad) {
      fetchSequence(seqIdToLoad).then((res) => {
        if (res.sequence) {
          setCurrentSequence(res.sequence);
          // Set default query sequence with known variant for comparison preview
          if (activeStudy && activeStudy.variants.length > 0) {
            const v = activeStudy.variants[0];
            const mut = listMutate(res.sequence.sequence, v.position - 1, v.alternate_allele);
            setQuerySequenceInput(mut);
            setQueryNameInput(`Isolate Variant (${v.reference_allele}${v.position}${v.alternate_allele})`);
          }
        }
      });
    }
  }, [selectedStudyId, activeStudy, initialSeqId]);

  function listMutate(original: string, index: number, alt: string) {
    if (index < 0 || index >= original.length) return original;
    return original.substring(0, index) + alt + original.substring(index + 1);
  }

  async function handleRunComparison() {
    if (!currentSequence || !querySequenceInput.trim()) return;
    setIsComparing(true);
    try {
      const res = await compareSequence(currentSequence.sequence_id, {
        reference_sequence_id: currentSequence.sequence_id,
        query_sequence: querySequenceInput.trim(),
        query_name: queryNameInput,
      });
      setComparisonResult(res.comparison);
    } finally {
      setIsComparing(false);
    }
  }

  async function handleCreateStudy(e: React.FormEvent) {
    e.preventDefault();
    if (!newTitle || !newGene || !selectedSeqIdForNew) return;
    const targetSeq = allAvailableSeqs.find((s) => s.sequence_id === selectedSeqIdForNew);
    const projectId = targetSeq?.project_id || "proj_lactis_nisin";

    await createCrisprStudy(projectId, {
      title: newTitle,
      investigation_purpose: newPurpose,
      target_gene: newGene,
      target_sequence_id: selectedSeqIdForNew,
    });
    setShowNewModal(false);
    setNewTitle("");
    setNewPurpose("");
    setNewGene("");
    loadStudies();
  }

  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-24 pt-8 sm:px-6">
      {/* Breadcrumb & Navigation */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3 mb-6">
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <span className="text-text font-medium">BactroGen</span>
          <span>/</span>
          <span className="text-accent font-medium">CRISPR Research & Sequence Annotation</span>
        </div>

        <button
          onClick={() => setShowNewModal(true)}
          className="rounded-lg bg-accent px-3 py-1.5 text-[11px] font-semibold text-black hover:brightness-110 transition-all font-mono"
        >
          + Record Research Objective
        </button>
      </div>

      {/* Main Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-text sm:text-3xl">
          CRISPR Sequence Annotation & Variant Study
        </h1>
        <p className="mt-1 text-sm text-muted max-w-3xl leading-relaxed">
          Coordinate-aware reference sequence viewer, genomic variant comparison, target region annotations,
          and published literature evidence review.
        </p>
      </div>

      {/* Scientific Invariant Advisory */}
      <div className="rounded-xl border border-line bg-surface/50 p-4 mb-8">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 text-accent font-mono font-bold">ⓘ</span>
          <div className="text-[12px]">
            <h3 className="font-semibold text-text">Regulatory & Annotation Objective Notice</h3>
            <p className="text-muted mt-0.5 leading-relaxed">
              This module documents sequence annotations, reference comparisons, natural variants, and target-region specificity.
              In accordance with research safety guidelines, automated generation of experimental CRISPR editing instructions or guide execution is disabled.
            </p>
          </div>
        </div>
      </div>

      {/* Study Selector Row */}
      <div className="flex items-center gap-2 border-b border-line pb-3 mb-6 overflow-x-auto">
        <span className="text-xs font-mono uppercase text-muted tracking-wider mr-2">
          Studies:
        </span>
        {studies.map((s) => {
          const isSelected = s.study_id === selectedStudyId;
          return (
            <button
              key={s.study_id}
              onClick={() => {
                setSelectedStudyId(s.study_id);
                setComparisonResult(null);
              }}
              className={`rounded-lg px-3 py-1.5 text-xs font-mono transition-colors whitespace-nowrap border ${
                isSelected
                  ? "border-accent bg-accent/15 text-accent font-bold"
                  : "border-line bg-surface text-muted hover:text-text"
              }`}
            >
              {s.title.length > 35 ? `${s.title.slice(0, 35)}...` : s.title}
            </button>
          );
        })}
      </div>

      {activeStudy && currentSequence ? (
        <div className="space-y-8">
          {/* Section 1: Study Objective Documentation */}
          <div className="rounded-xl border border-line bg-card p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/60 pb-3">
              <div>
                <span className="rounded bg-surface px-2 py-0.5 text-[10px] font-mono uppercase text-muted border border-line">
                  Study ID: {activeStudy.study_id}
                </span>
                <h2 className="text-lg font-bold text-text mt-1">{activeStudy.title}</h2>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-emerald-500/15 text-emerald-400 px-2 py-0.5 text-[10px] font-mono uppercase font-semibold">
                  Status: {activeStudy.review_status}
                </span>
                <span className="text-[11px] font-mono text-muted">
                  Ref: {activeStudy.reference_version}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-[12px]">
              <div>
                <span className="text-muted block font-mono text-[11px] uppercase">Target Gene</span>
                <span className="font-semibold text-text font-mono text-sm mt-0.5 block">
                  {activeStudy.target_gene}
                </span>
              </div>
              <div>
                <span className="text-muted block font-mono text-[11px] uppercase">Linked Project</span>
                <span className="font-mono text-text mt-0.5 block truncate">
                  {activeStudy.project_id}
                </span>
              </div>
              <div>
                <span className="text-muted block font-mono text-[11px] uppercase">Target Regions</span>
                <span className="font-mono text-text mt-0.5 block">
                  {activeStudy.target_regions.length} annotated locus / loci
                </span>
              </div>
            </div>

            <div className="pt-2 border-t border-line/40 text-[12px]">
              <span className="text-muted font-mono text-[11px] uppercase block mb-1">
                Investigation Objective
              </span>
              <p className="text-text leading-relaxed bg-surface/40 p-3 rounded-lg border border-line/50">
                {activeStudy.investigation_purpose}
              </p>
            </div>

            {activeStudy.specificity_considerations && (
              <div className="text-[12px] bg-amber-500/10 border border-amber-500/30 p-3 rounded-lg text-amber-200">
                <span className="font-semibold font-mono text-[11px] uppercase block mb-0.5">
                  Specificity & Homology Considerations
                </span>
                <p className="leading-relaxed opacity-90">{activeStudy.specificity_considerations}</p>
              </div>
            )}
          </div>

          {/* Section 2: Reference Sequence Viewer */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-text">
                  Reference Sequence & Feature Tracks
                </h3>
                <p className="text-[12px] text-muted">
                  Interactive coordinate ruler with annotated coding sequences, core peptides, and CRISPR target protospacers.
                </p>
              </div>
            </div>

            <SequenceExplorer
              sequence={currentSequence.sequence}
              name={currentSequence.name}
              moleculeType={currentSequence.molecule_type}
              coordinates={currentSequence.genomic_coordinates}
              annotations={currentSequence.annotations}
              variants={activeStudy.variants}
              comparisonSequence={comparisonResult ? querySequenceInput : null}
              comparisonName={comparisonResult ? comparisonResult.query_name : undefined}
            />
          </div>

          {/* Section 3: Coordinate-Aware Variant Comparison */}
          <div className="rounded-xl border border-line bg-card p-5 space-y-4">
            <div>
              <h3 className="text-base font-semibold text-text">Coordinate-Aware Variant Comparison</h3>
              <p className="text-[12px] text-muted">
                Compare reference sequence against a natural isolate sequence or query variant to identify SNVs, insertions, and deletions.
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="Query Name (e.g. Isolate E980 Variant)"
                  value={queryNameInput}
                  onChange={(e) => setQueryNameInput(e.target.value)}
                  className="rounded-lg border border-line bg-surface px-3 py-1.5 text-xs text-text font-mono focus:outline-none focus:border-accent w-64"
                />
                <button
                  onClick={handleRunComparison}
                  disabled={isComparing || !querySequenceInput.trim()}
                  className="rounded-lg bg-accent px-4 py-1.5 text-xs font-semibold text-black hover:brightness-110 font-mono disabled:opacity-50"
                >
                  {isComparing ? "Aligning..." : "Compare Sequences"}
                </button>
              </div>

              <textarea
                rows={3}
                placeholder="Paste query nucleotide sequence..."
                value={querySequenceInput}
                onChange={(e) => setQuerySequenceInput(e.target.value)}
                className="w-full rounded-lg border border-line bg-surface p-3 text-xs text-text font-mono focus:outline-none focus:border-accent"
              />
            </div>

            {/* Comparison Results Card */}
            {comparisonResult && (
              <div className="rounded-xl border border-accent/30 bg-accent/5 p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/50 pb-2">
                  <span className="font-semibold text-text text-sm font-mono">
                    Alignment: {comparisonResult.query_name} vs {comparisonResult.reference_name}
                  </span>
                  <span className="rounded bg-accent/20 px-2 py-0.5 text-accent font-mono font-bold text-xs">
                    {comparisonResult.identity_percentage}% Sequence Identity
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-3 text-xs font-mono">
                  <div>
                    <span className="text-muted block text-[11px]">Mismatches (SNVs)</span>
                    <span className="text-text font-bold text-sm">
                      {comparisonResult.mismatches_count}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted block text-[11px]">Gaps / Indels</span>
                    <span className="text-text font-bold text-sm">{comparisonResult.gaps_count}</span>
                  </div>
                  <div>
                    <span className="text-muted block text-[11px]">Length Ratio</span>
                    <span className="text-text font-bold text-sm">
                      {comparisonResult.length_query} / {comparisonResult.length_reference} bp
                    </span>
                  </div>
                </div>

                {comparisonResult.variants.length > 0 && (
                  <div className="mt-3 pt-2 border-t border-line/40">
                    <span className="text-xs font-mono uppercase text-muted block mb-2">
                      Detected Sequence Variations:
                    </span>
                    <div className="space-y-1.5">
                      {comparisonResult.variants.map((v) => (
                        <div
                          key={v.variant_id}
                          className="rounded border border-line bg-card p-2 text-xs font-mono flex items-center justify-between"
                        >
                          <div>
                            <span className="text-rose-400 font-bold">
                              Pos {v.position}: {v.reference_allele} → {v.alternate_allele}
                            </span>
                            <span className="text-muted ml-2 text-[11px]">({v.variant_type})</span>
                            {v.predicted_effect && (
                              <span className="text-text ml-3 text-[11px]">
                                {v.predicted_effect}
                              </span>
                            )}
                          </div>
                          <span className="rounded bg-surface px-1.5 py-0.2 text-[10px] text-muted">
                            Uncertainty: {v.uncertainty_level}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Section 4: CRISPR Target Region & Literature Evidence Review */}
          <div className="rounded-xl border border-line bg-card p-5 space-y-4">
            <div>
              <h3 className="text-base font-semibold text-text">
                Target Regions & Published Evidence Review
              </h3>
              <p className="text-[12px] text-muted">
                Validation status, documented experimental citations, and protospacer sequence parameters.
              </p>
            </div>

            <div className="space-y-3">
              {activeStudy.target_regions.map((target) => (
                <div
                  key={target.target_id}
                  className="rounded-lg border border-line bg-surface/30 p-4 space-y-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-text text-sm font-mono">
                        {target.target_name}
                      </span>
                      <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-mono text-muted border border-line">
                        Pos {target.start_pos}..{target.end_pos} ({target.strand})
                      </span>
                    </div>
                    <span className="rounded bg-emerald-500/15 text-emerald-400 px-2 py-0.5 text-[10px] font-mono uppercase font-semibold">
                      {target.validation_status.replace(/_/g, " ")}
                    </span>
                  </div>

                  <div className="font-mono text-xs bg-surface p-2 rounded border border-line/60 break-all text-emerald-400">
                    Protospacer: {target.target_sequence}
                    {target.pam_motif && (
                      <span className="text-accent ml-2 font-bold">[PAM: {target.pam_motif}]</span>
                    )}
                  </div>

                  {target.published_evidence.length > 0 && (
                    <div className="pt-2 border-t border-line/40">
                      <span className="text-[11px] font-mono text-muted uppercase block mb-1">
                        Published Experimental Evidence
                      </span>
                      <ul className="space-y-1 text-xs">
                        {target.published_evidence.map((ev, i) => (
                          <li key={i} className="flex items-start gap-2 text-muted">
                            <span className="text-accent font-mono text-[11px]">[{ev.pmid}]</span>
                            <span className="text-text">{ev.title}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="py-20 text-center text-muted font-mono text-xs">
          Loading CRISPR research investigation details...
        </div>
      )}

      {/* New Study Modal */}
      {showNewModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-xl border border-line bg-card shadow-2xl p-6">
            <div className="flex items-center justify-between border-b border-line pb-3 mb-4">
              <h3 className="text-sm font-semibold text-text">Record CRISPR Research Objective</h3>
              <button onClick={() => setShowNewModal(false)} className="text-muted hover:text-text">
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateStudy} className="space-y-4 text-xs">
              <div>
                <label className="block text-muted mb-1 font-medium">Objective Title</label>
                <input
                  type="text"
                  placeholder="e.g. Lantibiotic Immunity Promoter Variation Analysis"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-text focus:outline-none focus:border-accent"
                  required
                />
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Target Gene</label>
                <input
                  type="text"
                  placeholder="e.g. nisI, as-48A, trn-alpha"
                  value={newGene}
                  onChange={(e) => setNewGene(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-text font-mono focus:outline-none focus:border-accent"
                  required
                />
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Target Reference Sequence</label>
                <select
                  value={selectedSeqIdForNew}
                  onChange={(e) => setSelectedSeqIdForNew(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-text font-mono focus:outline-none focus:border-accent"
                  required
                >
                  <option value="">Select an annotated sequence...</option>
                  {allAvailableSeqs.map((s) => (
                    <option key={s.sequence_id} value={s.sequence_id}>
                      {s.name} ({s.length} bp)
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Investigation Purpose</label>
                <textarea
                  rows={3}
                  placeholder="Document the scientific purpose of this sequence investigation..."
                  value={newPurpose}
                  onChange={(e) => setNewPurpose(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface p-2.5 text-text focus:outline-none focus:border-accent"
                  required
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-line">
                <button
                  type="button"
                  onClick={() => setShowNewModal(false)}
                  className="rounded-lg border border-line px-3 py-1.5 text-text hover:bg-surface"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-accent px-4 py-1.5 font-semibold text-black hover:brightness-110 font-mono"
                >
                  Save Study
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
