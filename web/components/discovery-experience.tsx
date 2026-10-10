"use client";

import { FormEvent, type ReactNode, useEffect, useState } from "react";
import { Check, ChevronDown, Loader2 } from "lucide-react";

import { ApiError, api, type DiscoveryResponse } from "@/lib/api";
import { Button } from "@/components/interactive";
import { Provenance } from "@/components/provenance";
import { Scene } from "@/components/scene";
import { useElapsed } from "@/lib/motion";

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

const MAX_PROMPT = 500;

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
  const [showProcess, setShowProcess] = useState(false);
  const [showDeveloperDetails, setShowDeveloperDetails] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || running) return;
    setRunning(true);
    setResponse(null);
    setError(null);
    try {
      setResponse(await api.discover({ prompt: prompt.trim() }));
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

  const empty = !prompt.trim();
  const remaining = MAX_PROMPT - prompt.length;

  return (
    <div className="relative isolate">
      {/* The artwork sits behind the prompt only. Once results arrive the page
          scrolls past it onto plain vanilla, so nothing scientific is ever read
          against a picture. */}
      <Scene
        src="/backgrounds/discover-field.png"
        priority
        position="center top"
        scrim="center"
        drift={8}
        className="h-[clamp(34rem,60vh,44rem)] [mask-image:linear-gradient(to_bottom,black_55%,transparent_100%)]"
      />

      <div className="relative mx-auto max-w-4xl px-4 pb-24 pt-14 sm:px-6 sm:pt-20">
      <section className="mx-auto max-w-3xl text-center">
        <p className="eyebrow">Discovery</p>
        <h1 className="display display-xl mt-5 text-balance text-cyan">
          What bacterium do you want to target?
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-[15.5px] leading-relaxed text-muted">
          Discover, evaluate and computationally design bacteriocin candidates
          with an autonomous scientific loop.
        </p>
      </section>

      <form
        onSubmit={submit}
        className="mx-auto mt-10 max-w-3xl rounded-[5px] border border-line bg-panel p-4 shadow-[var(--shadow-md)] transition-colors focus-within:border-cyan focus-within:ring-2 focus-within:ring-cyan/20"
      >
        <label className="sr-only" htmlFor="discovery-question">
          Scientific question
        </label>
        <textarea
          id="discovery-question"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          maxLength={MAX_PROMPT}
          rows={3}
          aria-describedby="prompt-help"
          className="w-full resize-none bg-transparent text-[16px] leading-relaxed text-text outline-none placeholder:text-faint"
          placeholder="Find a bacteriocin for Listeria monocytogenes"
        />

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
          <div className="flex flex-wrap items-center gap-2" aria-label="Example targets">
            <span className="text-[11.5px] text-faint">Try:</span>
            {EXAMPLES.map((example) => (
              <Button
                key={example}
                type="button"
                variant="ghost"
                size="sm"
                onClick={() =>
                  setPrompt(
                    `Find the most promising bacteriocin for suppressing high-density ${example}.`,
                  )
                }
                className="border-line text-[11.5px] italic hover:border-cyan/40 hover:text-cyan"
              >
                {example}
              </Button>
            ))}
          </div>

          <div className="flex items-center gap-3">
            {/* The counter only appears once it is close enough to matter. */}
            {remaining < 120 && (
              <span className="num text-[11px] text-faint" aria-live="polite">
                {remaining} left
              </span>
            )}
            <Button type="submit" variant="primary" size="md" disabled={running || empty}>
              {running && <Loader2 size={14} className="animate-spin" aria-hidden />}
              {running ? "Discovering…" : "Discover bacteriocin"}
            </Button>
          </div>
        </div>

        <p id="prompt-help" className="mt-3 text-[12px] leading-relaxed text-faint">
          Name an organism and the conditions that matter. Results are
          simulation-derived predictions, not measurements.
        </p>
      </form>

      {(running || response || error) && (
        <WorkflowProgress running={running} response={Boolean(response)} />
      )}

      {error && (
        <p
          role="alert"
          className="reveal mx-auto mt-5 max-w-3xl rounded-[4px] border border-red/40 bg-red/10 px-4 py-3 text-[13px] leading-relaxed text-red"
        >
          {error}
        </p>
      )}

      {response && (
        <DiscoveryResult
          response={response}
          showProcess={showProcess}
          setShowProcess={setShowProcess}
          showDeveloperDetails={showDeveloperDetails}
          setShowDeveloperDetails={setShowDeveloperDetails}
        />
      )}
      </div>
    </div>
  );
}

/**
 * What the run is doing, without inventing how far along it is.
 *
 * `/api/discover` is a single synchronous call: it returns the finished answer
 * and reports nothing while it works. An earlier version of this panel walked a
 * tick through these six stages on a 700ms timer, which looked like progress
 * and was not — the highlighted stage had no relationship to what the backend
 * was doing. So while the call is in flight the list is shown as *what the run
 * performs*, with one indeterminate indicator and a real elapsed clock, and no
 * stage claims to be complete until the response actually arrives.
 *
 * The event-driven loop (lib/use-run.ts) does report real per-agent progress,
 * and the run console drives its stations from those events.
 */
function WorkflowProgress({ running, response }: { running: boolean; response: boolean }) {
  const elapsed = useElapsed(running);

  return (
    <section
      className="reveal mx-auto mt-8 max-w-3xl overflow-hidden rounded-[5px] border border-line bg-panel shadow-[var(--shadow-sm)]"
      aria-live="polite"
      aria-busy={running}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 className="flex items-center gap-2 text-[14px] font-semibold text-text">
            {running && (
              <span
                aria-hidden
                className="station-live inline-block h-2 w-2 shrink-0 rounded-full bg-cyan"
              />
            )}
            {running ? "Workflow running" : "Autonomous scientific workflow"}
          </h2>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
            {running
              ? "The service reports completion, not per-stage progress, so no stage is marked done until the result arrives."
              : "The complete workflow finished before this recommendation was shown."}
          </p>
        </div>
        {running && (
          <span className="num shrink-0 text-[12px] text-faint">
            {elapsed}s elapsed
          </span>
        )}
      </div>

      {/* An indeterminate bar, because the duration is genuinely unknown. */}
      {running && (
        <div className="sweep relative h-[3px] overflow-hidden bg-raised" role="presentation" />
      )}

      <ol className="grid gap-px bg-line sm:grid-cols-2">
        {STEPS.map((step, index) => (
          <li
            key={step}
            className={`flex items-center gap-3 bg-panel px-5 py-3.5 text-[12.5px] ${
              response ? `reveal reveal-${Math.min(index + 1, 6)}` : ""
            }`}
          >
            <span
              aria-hidden
              className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] ${
                response ? "border-cyan bg-cyan text-ink" : "border-line text-faint"
              }`}
            >
              {response ? <Check size={11} strokeWidth={3} /> : index + 1}
            </span>
            <span className={response ? "text-text" : "text-muted"}>{step}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function DiscoveryResult({
  response,
  showProcess,
  setShowProcess,
  showDeveloperDetails,
  setShowDeveloperDetails,
}: {
  response: DiscoveryResponse;
  showProcess: boolean;
  setShowProcess: (show: boolean) => void;
  showDeveloperDetails: boolean;
  setShowDeveloperDetails: (show: boolean) => void;
}) {
  return (
    <section id="discovery-results" className="mx-auto mt-8 max-w-3xl space-y-5">
      {/* The headline result. It is the only panel that gets a sage ground —
          so the recommendation is findable without reading the labels. */}
      <div className="reveal card-arrive rounded-[5px] border border-sage-deep bg-sage-soft p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="eyebrow text-cyan">Most promising candidate</p>
          <Provenance kind="simulation" />
        </div>
        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-2">
          <h2 className="display display-md text-cyan">{response.recommendation.name}</h2>
          <span className="num rounded-[3px] border border-cyan/40 bg-panel/70 px-2 py-[3px] text-[11px] text-cyan">
            {response.recommendation.tier}
          </span>
        </div>
        <p className="mt-4 max-w-2xl text-[14.5px] leading-relaxed text-text/85">
          {response.recommendation.summary}
        </p>
        <p className="mt-5 border-t border-cyan/15 pt-4 text-[12.5px] text-muted">
          Confidence:{" "}
          <span className="num text-text">{response.recommendation.confidence}</span>
        </p>
      </div>

      <ResultPanel title="Target" delay={1}>
        <p className="display text-[22px] text-text">{response.target.organism}</p>
      </ResultPanel>

      <ResultPanel title="Why it was selected" delay={2}>
        <ul className="space-y-2.5 text-[13.5px] leading-relaxed text-muted">
          {response.why_this_candidate.map((reason) => (
            <li key={reason} className="flex gap-2.5">
              <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-cyan" />
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      </ResultPanel>

      <ResultPanel
        title="Predicted performance"
        note={response.predicted_effect.evidence_label}
        delay={3}
      >
        <p className="text-[14px] leading-relaxed text-text">
          {response.predicted_effect.description}
        </p>
        <p className="num mt-3 text-[12px] text-muted">
          {conditionSummary(response.predicted_effect.conditions)}
        </p>
      </ResultPanel>

      <ResultPanel title="Autonomous reasoning" delay={4}>
        <div className="grid gap-4 text-[13px] sm:grid-cols-[1fr_auto_1fr] sm:items-center">
          <div>
            <p className="text-[11.5px] text-faint">Initial condition</p>
            <p className="num mt-1.5 text-text">
              {conditionSummary(response.adaptive_experiment.initial_condition)}
            </p>
          </div>
          <div aria-hidden className="text-cyan sm:text-center">
            →
          </div>
          <div>
            <p className="text-[11.5px] text-faint">Scientific review</p>
            <p className="mt-1.5 text-text">{response.scientific_review.verdict}</p>
          </div>
        </div>

        {response.adaptive_experiment.next_condition && (
          <div className="mt-4 border-t border-line pt-4">
            <p className="text-[11.5px] text-faint">Next condition</p>
            <p className="num mt-1.5 text-[13px] text-text">
              {conditionSummary(response.adaptive_experiment.next_condition)}
            </p>
          </div>
        )}

        <p className="mt-4 border-t border-line pt-4 text-[13px] leading-relaxed text-muted">
          {response.adaptive_experiment.explanation}
        </p>
      </ResultPanel>

      <ResultPanel title="Uncertainty and limitations" delay={5}>
        <ul className="space-y-2.5 text-[13px] leading-relaxed text-muted">
          {response.uncertainty.map((item) => (
            <li key={item} className="flex gap-2.5">
              <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-amber" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </ResultPanel>

      <ResultPanel title="Next recommended experiment" delay={6}>
        <p className="text-[14px] leading-relaxed text-text">
          {response.next_experiment.summary}
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-muted">
          {response.next_experiment.reason}
        </p>
      </ResultPanel>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Disclosure
          open={showProcess}
          onToggle={() => setShowProcess(!showProcess)}
          label={showProcess ? "Hide scientific process" : "Show scientific process"}
        />
        <Disclosure
          open={showDeveloperDetails}
          onToggle={() => setShowDeveloperDetails(!showDeveloperDetails)}
          label={showDeveloperDetails ? "Hide developer details" : "Developer details"}
        />
      </div>

      {showProcess && (
        <div className="reveal rounded-[4px] border border-line bg-panel p-5 text-[13px] leading-relaxed text-muted">
          <p className="text-text">
            Evidence was gathered, candidates were evaluated, computational
            experiments were run, and the scientific review selected a follow-up
            before this recommendation was synthesized.
          </p>
          <p className="mt-2">
            The displayed effect is a computational prediction, not a wet-lab
            result.
          </p>
        </div>
      )}

      {showDeveloperDetails && (
        <div className="reveal rounded-[4px] border border-line bg-panel p-5 text-[12.5px] leading-relaxed text-muted">
          Technical traces, provenance records and complete internal state are
          retained by the existing developer API. They are intentionally
          excluded from the scientific product view.
        </div>
      )}
    </section>
  );
}

function Disclosure({
  open,
  onToggle,
  label,
}: {
  open: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <Button variant="ghost" size="sm" onClick={onToggle} aria-expanded={open}>
      {label}
      <ChevronDown
        size={13}
        aria-hidden
        className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
      />
    </Button>
  );
}

function ResultPanel({
  title,
  note,
  delay,
  children,
}: {
  title: string;
  note?: string;
  delay?: number;
  children: ReactNode;
}) {
  return (
    <section
      className={`reveal rounded-[5px] border border-line bg-panel p-5 shadow-[var(--shadow-sm)] ${
        delay ? `reveal-${Math.min(delay, 6)}` : ""
      }`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-[13.5px] font-semibold text-text">{title}</h2>
        {note && <span className="num text-[11px] text-cyan">{note}</span>}
      </div>
      <div className="mt-3.5">{children}</div>
    </section>
  );
}
