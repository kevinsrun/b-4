"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ResearchProject,
  BiologicalSample,
  AnnotatedSequence,
  CrisprObjective,
} from "@/lib/project-types";
import {
  fetchProjects,
  fetchProjectSamples,
  fetchProjectSequences,
  fetchCrisprStudies,
  createProject,
} from "@/lib/project-api";
import { SequenceExplorer } from "@/components/sequence-explorer/sequence-explorer";

export function ProjectsWorkspace() {
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  // Child data for selected project
  const [samples, setSamples] = useState<BiologicalSample[]>([]);
  const [sequences, setSequences] = useState<AnnotatedSequence[]>([]);
  const [crisprStudies, setCrisprStudies] = useState<CrisprObjective[]>([]);

  const [activeTab, setActiveTab] = useState<"overview" | "samples" | "sequences" | "lineage">("overview");
  const [selectedSequence, setSelectedSequence] = useState<AnnotatedSequence | null>(null);

  // New project modal
  const [showNewModal, setShowNewModal] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newInvestigator, setNewInvestigator] = useState("");
  const [newOrganism, setNewOrganism] = useState("");

  const [isLoading, setIsLoading] = useState(true);

  async function loadProjects() {
    setIsLoading(true);
    try {
      const res = await fetchProjects();
      setProjects(res.projects);
      if (res.projects.length > 0 && !selectedProjectId) {
        setSelectedProjectId(res.projects[0].project_id);
      }
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadProjects();
  }, []);

  const activeProject = projects.find((p) => p.project_id === selectedProjectId);

  // Load project details
  useEffect(() => {
    if (!selectedProjectId) return;
    Promise.all([
      fetchProjectSamples(selectedProjectId),
      fetchProjectSequences(selectedProjectId),
      fetchCrisprStudies(selectedProjectId),
    ]).then(([sRes, seqRes, cRes]) => {
      setSamples(sRes.samples);
      setSequences(seqRes.sequences);
      setCrisprStudies(cRes.studies);
      if (seqRes.sequences.length > 0) {
        setSelectedSequence(seqRes.sequences[0]);
      } else {
        setSelectedSequence(null);
      }
    });
  }, [selectedProjectId]);

  async function handleCreateProject(e: React.FormEvent) {
    e.preventDefault();
    if (!newName || !newOrganism) return;
    await createProject({
      name: newName,
      description: newDesc,
      lead_investigator: newInvestigator || undefined,
      target_organism: newOrganism,
    });
    setShowNewModal(false);
    setNewName("");
    setNewDesc("");
    setNewInvestigator("");
    setNewOrganism("");
    loadProjects();
  }

  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-24 pt-8 sm:px-6">
      {/* Breadcrumb Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3 mb-6">
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <span className="text-text font-medium">BactroGen</span>
          <span>/</span>
          <span className="text-accent font-medium">Project-Centered Research Workspace</span>
        </div>

        <button
          onClick={() => setShowNewModal(true)}
          className="rounded-lg bg-accent px-3 py-1.5 text-[11px] font-semibold text-black hover:brightness-110 transition-all font-mono"
        >
          + New Research Project
        </button>
      </div>

      {/* Main Title */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-text sm:text-3xl">
          Projects & Samples Workspace
        </h1>
        <p className="mt-1 text-sm text-muted max-w-3xl leading-relaxed">
          Centralized research repository connecting biological samples, sequencing runs, imported datasets,
          annotated sequences, AMP predictions, and CRISPR studies with end-to-end provenance.
        </p>
      </div>

      {/* Project Selector Bar */}
      <div className="flex items-center gap-2 border-b border-line pb-3 mb-6 overflow-x-auto">
        <span className="text-xs font-mono uppercase text-muted tracking-wider mr-2">Projects:</span>
        {projects.map((p) => {
          const isSelected = p.project_id === selectedProjectId;
          return (
            <button
              key={p.project_id}
              onClick={() => setSelectedProjectId(p.project_id)}
              className={`rounded-lg px-3 py-1.5 text-xs font-mono transition-colors whitespace-nowrap border ${
                isSelected
                  ? "border-accent bg-accent/15 text-accent font-bold"
                  : "border-line bg-surface text-muted hover:text-text"
              }`}
            >
              {p.name.length > 32 ? `${p.name.slice(0, 32)}...` : p.name}
            </button>
          );
        })}
      </div>

      {activeProject ? (
        <div className="space-y-6">
          {/* Active Project Banner */}
          <div className="rounded-xl border border-line bg-card p-5">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line/60 pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="rounded bg-surface px-2 py-0.5 text-[10px] font-mono uppercase text-muted border border-line">
                    ID: {activeProject.project_id}
                  </span>
                  <span className="rounded bg-emerald-500/15 text-emerald-400 px-2 py-0.5 text-[10px] font-mono uppercase font-semibold">
                    {activeProject.status}
                  </span>
                </div>
                <h2 className="text-xl font-bold text-text mt-1">{activeProject.name}</h2>
                <p className="text-xs text-muted mt-0.5">{activeProject.description}</p>
              </div>

              {/* Quick Actions to Child Workspaces */}
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  href="/sequencing"
                  className="rounded-lg bg-surface hover:bg-surface/80 border border-line px-2.5 py-1 text-[11px] font-mono text-text transition-colors"
                >
                  Sequencing Runs ({activeProject.sequencing_run_ids.length}) →
                </Link>
                <Link
                  href="/amp"
                  className="rounded-lg bg-surface hover:bg-surface/80 border border-line px-2.5 py-1 text-[11px] font-mono text-text transition-colors"
                >
                  AMP Lab ({activeProject.amp_job_ids.length}) →
                </Link>
                <Link
                  href={`/crispr?projectId=${activeProject.project_id}`}
                  className="rounded-lg bg-accent/15 hover:bg-accent/25 border border-accent/30 px-2.5 py-1 text-[11px] font-mono text-accent transition-colors font-medium"
                >
                  CRISPR Studies ({activeProject.crispr_study_ids.length}) →
                </Link>
              </div>
            </div>

            {/* Quick Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-3 text-xs font-mono">
              <div>
                <span className="text-muted block text-[11px]">Target Organism</span>
                <span className="font-semibold text-text text-sm italic">{activeProject.target_organism}</span>
              </div>
              <div>
                <span className="text-muted block text-[11px]">Lead Investigator</span>
                <span className="text-text font-medium">{activeProject.lead_investigator || "Laboratory Staff"}</span>
              </div>
              <div>
                <span className="text-muted block text-[11px]">Biological Samples</span>
                <span className="text-text font-bold text-sm">{samples.length}</span>
              </div>
              <div>
                <span className="text-muted block text-[11px]">Annotated Sequences</span>
                <span className="text-text font-bold text-sm">{sequences.length}</span>
              </div>
            </div>
          </div>

          {/* Subtabs for Project Details */}
          <div className="flex border-b border-line gap-2 overflow-x-auto">
            {[
              { id: "overview", label: "Overview & Traceability" },
              { id: "samples", label: `Biological Samples (${samples.length})` },
              { id: "sequences", label: `Sequence Records (${sequences.length})` },
              { id: "lineage", label: "Provenance Flow" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`border-b-2 px-3 py-2 text-xs font-mono uppercase tracking-wider transition-colors ${
                  activeTab === tab.id
                    ? "border-accent text-accent font-bold"
                    : "border-transparent text-muted hover:text-text"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab 1: Overview & Traceability */}
          {activeTab === "overview" && (
            <div className="space-y-6">
              {/* Linked Resources Cards */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-[12px]">
                <div className="rounded-xl border border-line bg-card p-4 space-y-2">
                  <span className="text-[11px] font-mono uppercase text-muted block">Sequencing Linkage</span>
                  <p className="text-text font-semibold">
                    {activeProject.sequencing_run_ids.length} linked instrument run(s)
                  </p>
                  <p className="text-muted text-[11px]">
                    Datasets: {activeProject.dataset_ids.join(", ") || "None"}
                  </p>
                  <Link href="/sequencing" className="text-accent text-[11px] font-mono hover:underline block pt-1">
                    Open in Sequencing Explorer →
                  </Link>
                </div>

                <div className="rounded-xl border border-line bg-card p-4 space-y-2">
                  <span className="text-[11px] font-mono uppercase text-muted block">Bacteriocin Inference</span>
                  <p className="text-text font-semibold">
                    {activeProject.amp_job_ids.length} prediction job(s)
                  </p>
                  <p className="text-muted text-[11px]">
                    Tied to ampir & amPEPpy multi-model scoring
                  </p>
                  <Link href="/amp" className="text-accent text-[11px] font-mono hover:underline block pt-1">
                    Open in AMP Lab →
                  </Link>
                </div>

                <div className="rounded-xl border border-line bg-card p-4 space-y-2">
                  <span className="text-[11px] font-mono uppercase text-muted block">CRISPR & Variants</span>
                  <p className="text-text font-semibold">
                    {activeProject.crispr_study_ids.length} locus investigation(s)
                  </p>
                  <p className="text-muted text-[11px]">
                    Coordinate-aware variant & immunity study
                  </p>
                  <Link href={`/crispr?projectId=${activeProject.project_id}`} className="text-accent text-[11px] font-mono hover:underline block pt-1">
                    Open in CRISPR Workspace →
                  </Link>
                </div>
              </div>

              {/* Lead Sequence Preview */}
              {selectedSequence && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-text">
                      Primary Annotated Sequence: {selectedSequence.name}
                    </h3>
                    <span className="text-xs font-mono text-muted">
                      {selectedSequence.length} {selectedSequence.molecule_type === "protein" ? "aa" : "bp"}
                    </span>
                  </div>
                  <SequenceExplorer
                    sequence={selectedSequence.sequence}
                    name={selectedSequence.name}
                    moleculeType={selectedSequence.molecule_type}
                    coordinates={selectedSequence.genomic_coordinates}
                    annotations={selectedSequence.annotations}
                  />
                </div>
              )}
            </div>
          )}

          {/* Tab 2: Biological Samples */}
          {activeTab === "samples" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-line bg-card overflow-hidden">
                <table className="w-full text-left text-[12px]">
                  <thead className="border-b border-line bg-surface/50 font-mono text-[11px] text-muted uppercase">
                    <tr>
                      <th className="px-4 py-3">Sample Name & ID</th>
                      <th className="px-4 py-3">Organism & Strain</th>
                      <th className="px-4 py-3">Gram Stain</th>
                      <th className="px-4 py-3">Isolation Source</th>
                      <th className="px-4 py-3">Sequencing Runs</th>
                      <th className="px-4 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/40">
                    {samples.map((s) => (
                      <tr key={s.sample_id} className="hover:bg-surface/30 transition-colors">
                        <td className="px-4 py-3">
                          <div className="font-semibold text-text">{s.sample_name}</div>
                          <div className="font-mono text-[10px] text-muted">{s.sample_id}</div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="italic text-text">{s.organism}</div>
                          <div className="text-[11px] text-muted">{s.strain || "Unspecified strain"}</div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-mono uppercase text-muted border border-line">
                            {s.gram_stain}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-muted">{s.isolation_source || "Laboratory culture"}</td>
                        <td className="px-4 py-3 font-mono text-[11px] text-muted">
                          {s.sequencing_run_ids.join(", ") || "None"}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Link
                            href="/sequencing"
                            className="rounded bg-surface hover:bg-surface/80 border border-line px-2 py-1 text-[11px] font-mono text-text"
                          >
                            View Runs →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Tab 3: Sequence Records */}
          {activeTab === "sequences" && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {sequences.map((seq) => {
                  const isSel = selectedSequence?.sequence_id === seq.sequence_id;
                  return (
                    <div
                      key={seq.sequence_id}
                      onClick={() => setSelectedSequence(seq)}
                      className={`rounded-xl border p-4 cursor-pointer transition-all ${
                        isSel
                          ? "border-accent bg-accent/10 shadow-sm"
                          : "border-line bg-card hover:border-line/80"
                      }`}
                    >
                      <div className="flex items-center justify-between text-[10px] font-mono uppercase text-muted">
                        <span>{seq.molecule_type}</span>
                        <span>{seq.length} bp</span>
                      </div>
                      <h4 className="font-bold text-text text-sm mt-1 truncate">{seq.name}</h4>
                      <p className="text-[11px] text-muted mt-1 line-clamp-2">{seq.description}</p>
                      <div className="mt-3 pt-2 border-t border-line/40 flex items-center justify-between text-[10px] font-mono text-muted">
                        <span>{seq.annotations.length} features</span>
                        <span className="text-accent">Click to inspect</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {selectedSequence && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold text-text">
                      Interactive Sequence Explorer: {selectedSequence.name}
                    </h3>
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/crispr?sequenceId=${selectedSequence.sequence_id}`}
                        className="rounded bg-surface hover:bg-surface/80 border border-line px-2.5 py-1 text-[11px] font-mono text-text"
                      >
                        Open in CRISPR Viewer →
                      </Link>
                    </div>
                  </div>
                  <SequenceExplorer
                    sequence={selectedSequence.sequence}
                    name={selectedSequence.name}
                    moleculeType={selectedSequence.molecule_type}
                    coordinates={selectedSequence.genomic_coordinates}
                    annotations={selectedSequence.annotations}
                  />
                </div>
              )}
            </div>
          )}

          {/* Tab 4: Provenance Flow & Lineage */}
          {activeTab === "lineage" && (
            <div className="rounded-xl border border-line bg-card p-6 space-y-6">
              <div>
                <h3 className="text-base font-semibold text-text">End-to-End Workflow Continuity</h3>
                <p className="text-[12px] text-muted">
                  Tracing biological data from sequencer output through gene discovery and functional characterization.
                </p>
              </div>

              <div className="flex flex-col md:flex-row items-center justify-between gap-4 py-4 text-center">
                <div className="flex-1 rounded-xl border border-line bg-surface/50 p-4 w-full">
                  <span className="text-[10px] font-mono uppercase text-accent font-bold block">SOURCE</span>
                  <h4 className="font-bold text-text text-sm mt-1">Sequencing Run</h4>
                  <p className="font-mono text-[11px] text-muted mt-1 truncate">
                    {activeProject.sequencing_run_ids[0] || "run_bs_miseq_01"}
                  </p>
                  <span className="text-[10px] text-muted block mt-2">MiSeq / PromethION</span>
                </div>

                <div className="text-muted font-mono font-bold text-lg">→</div>

                <div className="flex-1 rounded-xl border border-line bg-surface/50 p-4 w-full">
                  <span className="text-[10px] font-mono uppercase text-accent font-bold block">ISOLATE</span>
                  <h4 className="font-bold text-text text-sm mt-1">Biological Sample</h4>
                  <p className="font-mono text-[11px] text-muted mt-1 truncate">
                    {samples[0]?.sample_name || "L. lactis ATCC 11454"}
                  </p>
                  <span className="text-[10px] text-muted block mt-2">Gram-positive</span>
                </div>

                <div className="text-muted font-mono font-bold text-lg">→</div>

                <div className="flex-1 rounded-xl border border-line bg-surface/50 p-4 w-full">
                  <span className="text-[10px] font-mono uppercase text-accent font-bold block">ASSEMBLY</span>
                  <h4 className="font-bold text-text text-sm mt-1">Annotated Sequence</h4>
                  <p className="font-mono text-[11px] text-muted mt-1 truncate">
                    {sequences[0]?.name || "Nisin A / NisI locus"}
                  </p>
                  <span className="text-[10px] text-muted block mt-2">{sequences[0]?.length || 480} bp</span>
                </div>

                <div className="text-muted font-mono font-bold text-lg">→</div>

                <div className="flex-1 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 w-full text-emerald-300">
                  <span className="text-[10px] font-mono uppercase text-emerald-400 font-bold block">ANALYSIS</span>
                  <h4 className="font-bold text-text text-sm mt-1">AMP / CRISPR Lab</h4>
                  <p className="font-mono text-[11px] text-emerald-400 mt-1 truncate">
                    Verified ampir & amPEPpy
                  </p>
                  <span className="text-[10px] text-muted block mt-2">DRAMP verified</span>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="py-20 text-center text-muted font-mono text-xs">
          Loading research project information...
        </div>
      )}

      {/* New Project Modal */}
      {showNewModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-xl border border-line bg-card shadow-2xl p-6">
            <div className="flex items-center justify-between border-b border-line pb-3 mb-4">
              <h3 className="text-sm font-semibold text-text">Create Research Project</h3>
              <button onClick={() => setShowNewModal(false)} className="text-muted hover:text-text">
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateProject} className="space-y-4 text-xs">
              <div>
                <label className="block text-muted mb-1 font-medium">Project Name</label>
                <input
                  type="text"
                  placeholder="e.g. Streptococcus thermophilus Bacteriocin Profiling"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-text focus:outline-none focus:border-accent"
                  required
                />
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Target Organism</label>
                <input
                  type="text"
                  placeholder="e.g. Streptococcus thermophilus"
                  value={newOrganism}
                  onChange={(e) => setNewOrganism(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-text italic focus:outline-none focus:border-accent"
                  required
                />
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Lead Investigator</label>
                <input
                  type="text"
                  placeholder="e.g. Dr. A. Smith"
                  value={newInvestigator}
                  onChange={(e) => setNewInvestigator(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-text focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Project Description</label>
                <textarea
                  rows={3}
                  placeholder="Scientific summary and scope of project..."
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
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
                  Create Project
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
