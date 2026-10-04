"use client";

import { FormEvent, type ReactNode, useEffect, useState } from "react";

import { ApiError, api, type DiscoveryResponse } from "@/lib/api";

const DEFAULT_PROMPT =
  "Find the most promising bacteriocin for suppressing high-density Listeria monocytogenes.";
const EXAMPLES = ["Listeria monocytogenes", "Staphylococcus aureus", "Clostridium difficile"];
const STEPS = [
  "Searching scientific evidence",
  "Evaluating bacteriocin candidates",
  "Testing predictions under target conditions",
  "Reviewing the scientific support",
  "Selecting the next informative experiment",
  "Synthesizing a recommendation",
];

function conditionSummary(conditions: Record<string, number | string | null | undefined>) {
  const bits = [
    conditions.pH === null || conditions.pH === undefined ? null : `pH ${conditions.pH}`,
    conditions.temperature_c === null || conditions.temperature_c === undefined
      ? null
      : `${conditions.temperature_c}°C`,
    conditions.target_cell_density === null || conditions.target_cell_density === undefined
      ? null
      : `${Number(conditions.target_cell_density).toExponential(0)} cells/mL`,
    conditions.incubation_hours === null || conditions.incubation_hours === undefined
      ? null
      : `${conditions.incubation_hours} h`,
  ];
  return bits.filter(Boolean).join(" · ");
}

export function DiscoveryExperience() {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [response, setResponse] = useState<DiscoveryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState(0);
  const [showProcess, setShowProcess] = useState(false);
  const [showDeveloperDetails, setShowDeveloperDetails] = useState(false);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setStage((current) => (current + 1) % STEPS.length), 700);
    return () => window.clearInterval(timer);
  }, [running]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || running) return;
    setRunning(true);
    setResponse(null);
    setError(null);
    setStage(0);
    try {
      setResponse(await api.discover({ prompt: prompt.trim() }));
      setStage(STEPS.length - 1);
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 422
          ? cause.message
          : "The computational evaluation could not safely complete. Please try again.",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-4 pb-20 pt-16 sm:px-6">
      <section className="mx-auto max-w-3xl text-center">
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">BACTERION</p>
        <h1 className="mt-4 text-4xl font-medium tracking-[-0.035em] text-text sm:text-5xl">
          What bacterium do you want to target?
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-[15px] leading-relaxed text-muted">
          Ask one scientific question. BACTERION gathers evidence, evaluates candidates, tests
          computational predictions, and returns one bounded recommendation.
        </p>
      </section>

      <form onSubmit={submit} className="mx-auto mt-10 max-w-3xl border border-line bg-panel p-4 shadow-sm">
        <label className="sr-only" htmlFor="discovery-question">Scientific question</label>
        <textarea
          id="discovery-question"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          maxLength={500}
          rows={3}
          className="w-full resize-none bg-transparent text-[16px] leading-relaxed text-text outline-none placeholder:text-faint"
          placeholder="Find a bacteriocin for Listeria monocytogenes"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
          <div className="flex flex-wrap gap-2" aria-label="Example targets">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setPrompt(`Find the most promising bacteriocin for suppressing high-density ${example}.`)}
                className="border border-line px-2 py-1 text-[11px] text-muted transition-colors hover:border-cyan/50 hover:text-cyan"
              >
                {example}
              </button>
            ))}
          </div>
          <button
            type="submit"
            disabled={running}
            className="border border-cyan/60 bg-cyan/12 px-4 py-2 text-[13px] font-medium text-cyan transition-colors hover:bg-cyan/20 disabled:cursor-wait disabled:border-line disabled:bg-transparent disabled:text-faint"
          >
            {running ? "Discovering…" : "Discover bacteriocin"}
          </button>
        </div>
      </form>

      {(running || response || error) && <WorkflowProgress running={running} response={Boolean(response)} stage={stage} />}
      {error && <p className="mx-auto mt-5 max-w-3xl border border-red/35 bg-red/5 px-4 py-3 text-[13px] text-red">{error}</p>}
      {response && (
        <DiscoveryResult
          response={response}
          showProcess={showProcess}
          setShowProcess={setShowProcess}
          showDeveloperDetails={showDeveloperDetails}
          setShowDeveloperDetails={setShowDeveloperDetails}
        />
      )}
    </main>
  );
}

function WorkflowProgress({ running, response, stage }: { running: boolean; response: boolean; stage: number }) {
  return (
    <section className="mx-auto mt-7 max-w-3xl border border-line bg-panel" aria-live="polite">
      <div className="border-b border-line px-5 py-4">
        <h2 className="text-[14px] font-medium text-text">{running ? "Discovery in progress" : "Autonomous scientific workflow"}</h2>
        <p className="mt-1 text-[12.5px] text-muted">{running ? `${STEPS[stage]}…` : "The complete workflow finished before this recommendation was shown."}</p>
      </div>
      <ol className="grid gap-px bg-line sm:grid-cols-2">
        {STEPS.map((step, index) => {
          const complete = response || (running && index < stage);
          const active = running && index === stage;
          return (
            <li key={step} className="flex items-center gap-3 bg-panel px-5 py-3 text-[12.5px]">
              <span className={complete ? "text-cyan" : active ? "animate-pulse text-cyan" : "text-faint"}>{complete ? "✓" : active ? "●" : "○"}</span>
              <span className={complete || active ? "text-text" : "text-muted"}>{step}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function DiscoveryResult({
  response, showProcess, setShowProcess, showDeveloperDetails, setShowDeveloperDetails,
}: {
  response: DiscoveryResponse;
  showProcess: boolean;
  setShowProcess: (show: boolean) => void;
  showDeveloperDetails: boolean;
  setShowDeveloperDetails: (show: boolean) => void;
}) {
  return (
    <section className="mx-auto mt-7 max-w-3xl space-y-5">
      <div className="border border-cyan/35 bg-cyan/5 p-6">
        <p className="text-[10.5px] font-medium uppercase tracking-[0.16em] text-cyan">Most promising candidate</p>
        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-3xl font-medium tracking-[-0.03em] text-text">{response.recommendation.name}</h2>
          <span className="border border-cyan/35 px-2 py-0.5 text-[11px] text-cyan">{response.recommendation.tier}</span>
        </div>
        <p className="mt-3 max-w-2xl text-[14px] leading-relaxed text-muted">{response.recommendation.summary}</p>
        <p className="mt-4 text-[12px] text-faint">Confidence: <span className="text-text">{response.recommendation.confidence}</span></p>
      </div>
      <ResultPanel title="Target"><p className="text-xl text-text">{response.target.organism}</p></ResultPanel>
      <ResultPanel title="Why it was selected"><ul className="space-y-2 text-[13.5px] leading-relaxed text-muted">{response.why_this_candidate.map((reason) => <li key={reason} className="flex gap-2"><span className="text-cyan">•</span><span>{reason}</span></li>)}</ul></ResultPanel>
      <ResultPanel title="Predicted performance" note={response.predicted_effect.evidence_label}><p className="text-[14px] leading-relaxed text-text">{response.predicted_effect.description}</p><p className="mt-3 text-[12px] text-muted">{conditionSummary(response.predicted_effect.conditions)}</p></ResultPanel>
      <ResultPanel title="Autonomous reasoning">
        <div className="grid gap-3 text-[13px] sm:grid-cols-[1fr_auto_1fr] sm:items-center"><div><p className="text-faint">Initial condition</p><p className="mt-1 text-text">{conditionSummary(response.adaptive_experiment.initial_condition)}</p></div><div className="text-cyan">↓</div><div><p className="text-faint">Scientific review</p><p className="mt-1 text-text">{response.scientific_review.verdict}</p></div></div>
        {response.adaptive_experiment.next_condition && <><div className="my-3 text-cyan">↓</div><p className="text-faint">Next condition</p><p className="mt-1 text-text">{conditionSummary(response.adaptive_experiment.next_condition)}</p></>}
        <p className="mt-4 border-t border-line pt-3 text-[13px] leading-relaxed text-muted">{response.adaptive_experiment.explanation}</p>
      </ResultPanel>
      <ResultPanel title="Uncertainty and limitations"><ul className="space-y-2 text-[13px] leading-relaxed text-muted">{response.uncertainty.map((item) => <li key={item}>{item}</li>)}</ul></ResultPanel>
      <ResultPanel title="Next recommended experiment"><p className="text-[14px] text-text">{response.next_experiment.summary}</p><p className="mt-2 text-[13px] leading-relaxed text-muted">{response.next_experiment.reason}</p></ResultPanel>
      <button type="button" onClick={() => setShowProcess(!showProcess)} className="text-[12px] text-muted underline decoration-line underline-offset-4 hover:text-text">{showProcess ? "Hide scientific process" : "Show scientific process"}</button>
      {showProcess && <div className="border border-line bg-panel p-5 text-[13px] leading-relaxed text-muted"><p className="text-text">Evidence was gathered, candidates were evaluated, computational experiments were run, and the scientific review selected a follow-up before this recommendation was synthesized.</p><p className="mt-2">The displayed effect is a computational prediction, not a wet-lab result.</p></div>}
      <button type="button" onClick={() => setShowDeveloperDetails(!showDeveloperDetails)} className="ml-4 text-[12px] text-faint underline decoration-line underline-offset-4 hover:text-muted">{showDeveloperDetails ? "Hide developer details" : "Developer details"}</button>
      {showDeveloperDetails && <div className="border border-line bg-panel p-5 text-[12px] leading-relaxed text-muted">Technical traces, provenance records, and complete internal state are retained by the existing developer API. They are intentionally excluded from the scientific product view.</div>}
    </section>
  );
}

function ResultPanel({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return <section className="border border-line bg-panel p-5"><div className="flex items-baseline justify-between gap-3"><h2 className="text-[13px] font-medium text-text">{title}</h2>{note && <span className="text-[11px] text-cyan">{note}</span>}</div><div className="mt-3">{children}</div></section>;
}
