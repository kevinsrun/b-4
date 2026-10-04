"use client";

import { useState } from "react";

type ConsoleSection = {
  number: string;
  title: string;
  eyebrow: string;
  detail: string;
  items: string[];
};

const SECTIONS: ConsoleSection[] = [
  {
    number: "01",
    title: "Evidence",
    eyebrow: "Scientific inputs",
    detail: "Published and database-derived support is kept distinct from computational claims.",
    items: ["Literature evidence", "Database evidence", "NCBI source details", "Citations and provenance"],
  },
  {
    number: "02",
    title: "Candidate Explorer",
    eyebrow: "Candidate landscape",
    detail: "Known bacteriocins, natural variants, and computational designs are displayed as separate tiers.",
    items: ["Ranked bacteriocins", "Natural variants", "Computational designs", "Scores and rationale"],
  },
  {
    number: "03",
    title: "Sequence Search",
    eyebrow: "Homology context",
    detail: "Sequence search records the source, similarity signal, and whether a local fallback was used.",
    items: ["Closest homologs", "Identity and coverage", "E-value", "Backend and fallback status"],
  },
  {
    number: "04",
    title: "Variant Discovery",
    eyebrow: "Observed sequence variation",
    detail: "Homolog alignment separates observed substitutions from unsupported design hypotheses.",
    items: ["Substitutions and indels", "Variant frequencies", "Conservation", "Source accessions"],
  },
  {
    number: "05",
    title: "Experiment Planner",
    eyebrow: "Adaptive experiment choice",
    detail: "The planner selects a condition that can most clearly challenge the active hypothesis.",
    items: ["Current hypothesis", "Selected experiment", "Alternatives considered", "Selection rationale"],
  },
  {
    number: "06",
    title: "Simulator",
    eyebrow: "Computational prediction",
    detail: "Candidate sequence, target, and conditions are evaluated together with their uncertainty.",
    items: ["Candidate and target", "Experimental conditions", "Predicted response", "Uncertainty and model version"],
  },
  {
    number: "07",
    title: "Result Analysis",
    eyebrow: "Interpretation",
    detail: "The analysis compares iterations and reports whether a hypothesis is supported, weakened, or unresolved.",
    items: ["Interpretation", "Hypothesis support", "Cross-iteration comparison", "Condition-response context"],
  },
  {
    number: "08",
    title: "Scientific Critic",
    eyebrow: "Independent challenge",
    detail: "A conservative review checks coverage, provenance, and unresolved evidence gaps before a conclusion is accepted.",
    items: ["Verdict", "Concerns", "Evidence gaps", "Recommended follow-up"],
  },
  {
    number: "09",
    title: "Knowledge State",
    eyebrow: "Research memory",
    detail: "The system retains conclusions, unresolved hypotheses, and the provenance category of every claim.",
    items: ["Current conclusions", "Unresolved hypotheses", "Iteration history", "Provenance categories"],
  },
  {
    number: "10",
    title: "Orchestration",
    eyebrow: "Workflow control",
    detail: "The autonomous loop routes evidence through evaluation and review, then adapts the next experiment when needed.",
    items: ["Stage sequence", "Current stage", "Adaptive routing", "Iteration transitions"],
  },
  {
    number: "11",
    title: "Provenance",
    eyebrow: "Claim boundaries",
    detail: "Every visible statement is classified by what produced it, preventing predictions from being presented as measurements.",
    items: ["Published evidence", "Database evidence", "Computational simulation", "Model prediction", "Experimental evidence"],
  },
  {
    number: "12",
    title: "Benchmarks",
    eyebrow: "Measured system behavior",
    detail: "Deterministic benchmark outputs quantify retrieval, variant analysis, and adaptive experiment selection where available.",
    items: ["Adaptive decision efficiency", "Retrieval recovery", "Variant accuracy", "Local search latency"],
  },
];

export function AdvancedConsole() {
  const [showDeveloperDetails, setShowDeveloperDetails] = useState(false);
  return (
    <main className="mx-auto max-w-6xl px-4 pb-20 pt-14 sm:px-6">
      <header className="max-w-3xl">
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Advanced</p>
        <h1 className="mt-3 text-4xl font-medium tracking-[-0.035em] text-text">Scientific research console</h1>
        <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted">
          An optional map of the full discovery system. Discover remains the normal one-question,
          one-result experience; this view explains the scientific depth behind it.
        </p>
      </header>

      <section className="mt-9 grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Advanced scientific system">
        {SECTIONS.map((section) => <ConsoleCard key={section.number} section={section} />)}
      </section>

      <section className="mt-4 border border-cyan/30 bg-cyan/5 p-5">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-cyan">Adaptive loop</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px] text-text">
          <span>Evidence</span><span className="text-cyan">→</span><span>Candidates</span><span className="text-cyan">→</span><span>Computational experiment</span><span className="text-cyan">→</span><span>Scientific review</span><span className="text-cyan">→</span><span>Next experiment</span>
        </div>
        <p className="mt-3 max-w-3xl text-[13px] leading-relaxed text-muted">
          The system does not expose manual agent controls. It chooses the next bounded action from the current scientific state and preserves uncertainty throughout.
        </p>
      </section>

      <section className="mt-4 border border-line bg-panel">
        <button type="button" onClick={() => setShowDeveloperDetails(!showDeveloperDetails)} className="flex w-full items-center justify-between px-5 py-4 text-left">
          <span><span className="text-[13px] font-medium text-text">Developer Details</span><span className="ml-3 text-[12px] text-faint">Internal diagnostics, deliberately separated from scientific interpretation</span></span>
          <span className="text-cyan">{showDeveloperDetails ? "−" : "+"}</span>
        </button>
        {showDeveloperDetails && <div className="border-t border-line px-5 py-4 text-[13px] leading-relaxed text-muted"><p>Raw run IDs, trace IDs, internal tool names, MCP transport details, complete JSON records, logs, errors, and filesystem/cache diagnostics are retained for engineering investigation.</p><p className="mt-2">They are intentionally not shown in Discover results and are never used as scientific evidence.</p></div>}
      </section>
    </main>
  );
}

function ConsoleCard({ section }: { section: ConsoleSection }) {
  return (
    <section className="border border-line bg-panel p-5 transition-colors hover:border-cyan/35">
      <div className="flex items-baseline justify-between gap-3"><p className="num text-[11px] text-cyan">{section.number}</p><p className="text-[10.5px] uppercase tracking-[0.12em] text-faint">{section.eyebrow}</p></div>
      <h2 className="mt-3 text-[18px] font-medium text-text">{section.title}</h2>
      <p className="mt-2 min-h-[4rem] text-[12.5px] leading-relaxed text-muted">{section.detail}</p>
      <ul className="mt-4 flex flex-wrap gap-1.5 border-t border-line pt-3">{section.items.map((item) => <li key={item} className="border border-line bg-raised px-2 py-1 text-[10.5px] text-muted">{item}</li>)}</ul>
    </section>
  );
}
