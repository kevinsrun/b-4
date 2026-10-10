"use client";

import Link from "next/link";
import { useState } from "react";

type ConsoleSection = {
  number: string;
  title: string;
  eyebrow: string;
  detail: string;
  items: string[];
  href?: string;
  actionLabel?: string;
};

const SECTIONS: ConsoleSection[] = [
  {
    number: "01",
    title: "Evidence",
    eyebrow: "Scientific inputs",
    detail: "Published and database-derived support is kept distinct from computational claims.",
    items: ["Literature evidence", "Database evidence", "NCBI source details", "Citations and provenance"],
    href: "/evidence",
    actionLabel: "Search Literature Evidence",
  },
  {
    number: "02",
    title: "Candidate Explorer",
    eyebrow: "Candidate landscape",
    detail: "Known bacteriocins, natural variants, and computational designs are displayed as separate tiers.",
    items: ["Ranked bacteriocins", "Natural variants", "Computational designs", "Scores and rationale"],
    href: "/candidates",
    actionLabel: "Explore Candidates",
  },
  {
    number: "03",
    title: "Sequence Search",
    eyebrow: "Homology context",
    detail: "Sequence search records the source, similarity signal, and whether a local fallback was used.",
    items: ["Closest homologs", "Identity and coverage", "E-value", "Backend and fallback status"],
    href: "/design",
    actionLabel: "Search Sequence Homologs",
  },
  {
    number: "04",
    title: "Variant Discovery",
    eyebrow: "Observed sequence variation",
    detail: "Homolog alignment separates observed substitutions from unsupported design hypotheses.",
    items: ["Substitutions and indels", "Variant frequencies", "Conservation", "Source accessions"],
    href: "/design",
    actionLabel: "Launch Target Designer",
  },
  {
    number: "05",
    title: "Experiment Planner",
    eyebrow: "Adaptive experiment choice",
    detail: "The planner selects a condition that can most clearly challenge the active hypothesis.",
    items: ["Current hypothesis", "Selected experiment", "Alternatives considered", "Selection rationale"],
    href: "/experiments",
    actionLabel: "Plan Adaptive Experiments",
  },
  {
    number: "06",
    title: "Simulator",
    eyebrow: "Computational prediction",
    detail: "Candidate sequence, target, and conditions are evaluated together with their uncertainty.",
    items: ["Candidate and target", "Experimental conditions", "Predicted response", "Uncertainty and model version"],
    href: "/experiments",
    actionLabel: "Run Simulator & Dose Curves",
  },
  {
    number: "07",
    title: "Result Analysis",
    eyebrow: "Interpretation",
    detail: "The analysis compares iterations and reports whether a hypothesis is supported, weakened, or unresolved.",
    items: ["Interpretation", "Hypothesis support", "Cross-iteration comparison", "Condition-response context"],
    href: "/research#discovery-results",
    actionLabel: "View Discovery Analysis",
  },
  {
    number: "08",
    title: "Scientific Critic",
    eyebrow: "Independent challenge",
    detail: "A conservative review checks coverage, provenance, and unresolved evidence gaps before a conclusion is accepted.",
    items: ["Verdict", "Concerns", "Evidence gaps", "Recommended follow-up"],
    href: "/methodology",
    actionLabel: "Review Critic Boundaries",
  },
  {
    number: "09",
    title: "Knowledge State",
    eyebrow: "Research memory",
    detail: "The system retains conclusions, unresolved hypotheses, and the provenance category of every claim.",
    items: ["Current conclusions", "Unresolved hypotheses", "Iteration history", "Provenance categories"],
    href: "/knowledge",
    actionLabel: "Inspect Research State",
  },
  {
    number: "10",
    title: "Orchestration",
    eyebrow: "Workflow control",
    detail: "The autonomous loop routes evidence through evaluation and review, then adapts the next experiment when needed.",
    items: ["Stage sequence", "Current stage", "Adaptive routing", "Iteration transitions"],
    href: "/agents",
    actionLabel: "View Specialist Agents & Selftest",
  },
  {
    number: "11",
    title: "Provenance",
    eyebrow: "Claim boundaries",
    detail: "Every visible statement is classified by what produced it, preventing predictions from being presented as measurements.",
    items: ["Published evidence", "Database evidence", "Computational simulation", "Model prediction", "Experimental evidence"],
    href: "/methodology",
    actionLabel: "Inspect Provenance Rules",
  },
  {
    number: "12",
    title: "Benchmarks",
    eyebrow: "Measured system behavior",
    detail: "Deterministic benchmark outputs quantify retrieval, variant analysis, and adaptive experiment selection where available.",
    items: ["Adaptive decision efficiency", "Retrieval recovery", "Variant accuracy", "Local search latency"],
    href: "/benchmarks",
    actionLabel: "View Benchmark Metrics",
  },
];

export function AdvancedConsole() {
  const [showDeveloperDetails, setShowDeveloperDetails] = useState(false);
  return (
    <main className="mx-auto max-w-6xl px-4 pb-20 pt-14 sm:px-6">
      <header className="max-w-3xl">
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Advanced</p>
        <h1 className="display display-lg mt-4 text-balance text-cyan">Scientific research console</h1>
        <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted">
          Access the individual specialist tools driving the discovery system, or inspect the 12 scientific subsystems behind the autonomous loop.
        </p>
      </header>

      {/* Direct Interactive Tools Launcher */}
      <section className="mt-8 rounded-[5px] border border-sage-deep bg-sage-soft p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-cyan">Interactive Specialist Tools</p>
            <h2 className="mt-1 text-2xl font-medium text-text">Launch autonomous lab modules directly</h2>
          </div>
          <span className="text-[12px] text-muted">6 live interactive interfaces</span>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Link
            href="/design"
            className="group flex flex-col justify-between border border-line bg-panel p-4 transition-colors hover:border-cyan/60 hover:bg-raised"
          >
            <div>
              <div className="text-[11px] text-cyan">Pipeline</div>
              <div className="mt-1 text-[15px] font-medium text-text group-hover:text-cyan">Target-to-Bacteriocin Designer</div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-muted">Known candidates, natural variant discovery, active learning & calibration ladder</p>
            </div>
            <span className="mt-4 text-[12px] font-medium text-cyan">Launch designer →</span>
          </Link>
          <Link
            href="/candidates"
            className="group flex flex-col justify-between border border-line bg-panel p-4 transition-colors hover:border-cyan/60 hover:bg-raised"
          >
            <div>
              <div className="text-[11px] text-cyan">Agent 02</div>
              <div className="mt-1 text-[15px] font-medium text-text group-hover:text-cyan">Candidate Explorer</div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-muted">Ranked candidate proposals, hypothesis discrimination & falsification criteria</p>
            </div>
            <span className="mt-4 text-[12px] font-medium text-cyan">Explore candidates →</span>
          </Link>
          <Link
            href="/experiments"
            className="group flex flex-col justify-between border border-line bg-panel p-4 transition-colors hover:border-cyan/60 hover:bg-raised"
          >
            <div>
              <div className="text-[11px] text-cyan">Agent 04</div>
              <div className="mt-1 text-[15px] font-medium text-text group-hover:text-cyan">Simulator & Dose Curves</div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-muted">Mechanistic simulated microdilution assays, inoculum effect & dose-response sweeps</p>
            </div>
            <span className="mt-4 text-[12px] font-medium text-cyan">Open simulator →</span>
          </Link>
          <Link
            href="/evidence"
            className="group flex flex-col justify-between border border-line bg-panel p-4 transition-colors hover:border-cyan/60 hover:bg-raised"
          >
            <div>
              <div className="text-[11px] text-cyan">Agent 01</div>
              <div className="mt-1 text-[15px] font-medium text-text group-hover:text-cyan">Literature & NCBI Evidence</div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-muted">Live Europe PMC and NCBI extraction with strict provenance boundaries</p>
            </div>
            <span className="mt-4 text-[12px] font-medium text-cyan">Search evidence →</span>
          </Link>
          <Link
            href="/knowledge"
            className="group flex flex-col justify-between border border-line bg-panel p-4 transition-colors hover:border-cyan/60 hover:bg-raised"
          >
            <div>
              <div className="text-[11px] text-cyan">Agent 07</div>
              <div className="mt-1 text-[15px] font-medium text-text group-hover:text-cyan">Research State Memory</div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-muted">Append-only event log, open scientific questions & hash-verified state integrity</p>
            </div>
            <span className="mt-4 text-[12px] font-medium text-cyan">View research state →</span>
          </Link>
          <Link
            href="/agents"
            className="group flex flex-col justify-between border border-line bg-panel p-4 transition-colors hover:border-cyan/60 hover:bg-raised"
          >
            <div>
              <div className="text-[11px] text-cyan">Verification</div>
              <div className="mt-1 text-[15px] font-medium text-text group-hover:text-cyan">Agent Network & Selftest</div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-muted">Interactive roster of all 7 agents and live execution of 14 biology invariants</p>
            </div>
            <span className="mt-4 text-[12px] font-medium text-cyan">Run selftest & view roster →</span>
          </Link>
        </div>
      </section>

      {/* 12 Subsystem Architecture Reference */}
      <div className="mt-12 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-medium text-text">Subsystem Architecture Reference</h2>
        <span className="text-[12px] text-muted">Complete technical map</span>
      </div>
      <section className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Advanced scientific system">
        {SECTIONS.map((section) => <ConsoleCard key={section.number} section={section} />)}
      </section>

      <section className="mt-4 rounded-[5px] border border-sage-deep bg-sage-soft p-5">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-cyan">Adaptive loop</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px] text-text">
          <span>Evidence</span><span className="text-cyan">→</span><span>Candidates</span><span className="text-cyan">→</span><span>Computational experiment</span><span className="text-cyan">→</span><span>Scientific review</span><span className="text-cyan">→</span><span>Next experiment</span>
        </div>
        <p className="mt-3 max-w-3xl text-[13px] leading-relaxed text-muted">
          The system does not expose manual agent controls in standard discovery. It chooses the next bounded action from the current scientific state and preserves uncertainty throughout.
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
  const inner = (
    <div className="flex h-full flex-col justify-between">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <p className="num text-[11px] text-cyan">{section.number}</p>
          <p className="text-[10.5px] uppercase tracking-[0.12em] text-faint">{section.eyebrow}</p>
        </div>
        <h2 className="mt-3 text-[18px] font-medium text-text group-hover:text-cyan">{section.title}</h2>
        <p className="mt-2 min-h-[4rem] text-[12.5px] leading-relaxed text-muted">{section.detail}</p>
        <ul className="mt-4 flex flex-wrap gap-1.5 border-t border-line pt-3">
          {section.items.map((item) => (
            <li key={item} className="border border-line bg-raised px-2 py-1 text-[10.5px] text-muted">
              {item}
            </li>
          ))}
        </ul>
      </div>
      {section.href && (
        <div className="mt-5 flex items-center justify-between border-t border-line/60 pt-3 text-[12px] font-medium text-cyan">
          <span>{section.actionLabel ?? "Open Specialist Tool"}</span>
          <span className="transition-transform group-hover:translate-x-1">→</span>
        </div>
      )}
    </div>
  );

  if (section.href) {
    return (
      <Link
        href={section.href}
        className="group block border border-line bg-panel p-5 transition-colors hover:border-cyan/50 hover:bg-raised"
      >
        {inner}
      </Link>
    );
  }

  return (
    <section className="rounded-[4px] border border-line bg-panel p-5">
      {inner}
    </section>
  );
}
