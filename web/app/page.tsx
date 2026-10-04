"use client";

/**
 * The landing page is one live document.
 *
 * A single run drives the hero console, the log, the predictions and the state
 * below it, so scrolling the page is reading one real campaign rather than
 * browsing marketing copy with a demo embedded in it. Before a run exists each
 * section says what would fill it.
 */

import { AgentNetwork } from "@/components/sections/agent-network";
import { FinalCta } from "@/components/sections/cta";
import { Hero } from "@/components/sections/hero";
import { LiveRun } from "@/components/sections/live-run";
import { LoopExplainer } from "@/components/sections/loop-explainer";
import { ResearchStateSection } from "@/components/sections/research-state";
import { Results } from "@/components/sections/results";
import { WhyBacteriocins } from "@/components/sections/why";
import { useRun } from "@/lib/use-run";

const DEFAULT_OBJECTIVE = {
  goal: "Find a bacteriocin candidate that stays effective against high-density Listeria monocytogenes.",
  species: "Listeria monocytogenes",
  gram: "positive" as const,
  target_cell_density: 1e8,
  ph: 7,
  temperature_c: 37,
  max_candidates: 4,
  max_iterations: 6,
  seed: 42,
};

export default function Home() {
  const run = useRun();
  const busy = run.starting || run.status === "running";

  const startDefault = () => {
    void run.start(DEFAULT_OBJECTIVE);
    // Bring the log into view, since that is where the run becomes legible.
    requestAnimationFrame(() => {
      document.getElementById("run")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  return (
    <>
      <Hero
        stations={run.stations}
        digest={run.digest}
        iteration={run.iteration}
        status={run.status}
        active={run.active}
        onRun={startDefault}
        busy={busy}
      />
      <LoopExplainer />
      <LiveRun run={run} />
      <Results run={run} />
      <ResearchStateSection run={run} />
      <AgentNetwork />
      <WhyBacteriocins />
      <FinalCta onRun={startDefault} busy={busy} />
    </>
  );
}
