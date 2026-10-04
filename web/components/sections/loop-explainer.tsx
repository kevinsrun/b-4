import { Section } from "@/components/section";
import { Provenance } from "@/components/provenance";

/**
 * The loop, in words, as a genuine sequence — so the numbered markers here are
 * carrying real information rather than decorating a list.
 */
const STEPS = [
  {
    role: "Evidence",
    does: "Retrieves published work on the target and records what was measured separately from what the authors concluded.",
    keeps: "citations, missing fields, contradictions",
    kind: "literature" as const,
  },
  {
    role: "Candidates",
    does: "Scores known bacteriocins and designed variants against the target, and states what would falsify each one.",
    keeps: "ranked proposals, competing hypotheses",
    kind: "proposal" as const,
  },
  {
    role: "Planner",
    does: "Picks the experiment whose outcome it cannot already predict, varying one factor at a time around the predicted transition.",
    keeps: "an experiment spec, and why that one",
    kind: null,
  },
  {
    role: "Simulator",
    does: "Integrates peptide decay against regrowth and returns a continuous prediction with an uncertainty budget.",
    keeps: "MIC, log₁₀ reduction, confidence interval",
    kind: "simulation" as const,
  },
  {
    role: "Analysis",
    does: "Says whether the result supports its hypothesis, weakens it, or fails to distinguish anything.",
    keeps: "a finding, and what drove it",
    kind: null,
  },
  {
    role: "Critic",
    does: "Challenges the claim before the state accepts it. Approval is what is left when no rule objects.",
    keeps: "a review, or a demand for more evidence",
    kind: null,
  },
  {
    role: "Research state",
    does: "Appends the outcome to a hash-chained log and hands the planner what is still open.",
    keeps: "every belief the lab has held, and when it changed",
    kind: null,
  },
];

export function LoopExplainer() {
  return (
    <Section
      id="loop"
      heading="The loop is the product, not the prediction"
      standfirst="Most tools generate candidates and stop. Bacterion closes the circuit: the result of each experiment is what chooses the next one. Seven specialists, each with one job and one kind of claim it is allowed to make."
    >
      <ol className="grid gap-x-10 gap-y-7 sm:grid-cols-2 lg:grid-cols-3">
        {STEPS.map((step, index) => (
          <li key={step.role} className="relative border-t border-line pt-4">
            <div className="flex items-baseline gap-3">
              <span className="num text-[11px] text-cyan/70">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className="text-[14px] font-medium text-text">{step.role}</h3>
              {step.kind && <Provenance kind={step.kind} className="ml-auto" />}
            </div>
            <p className="mt-2 max-w-[44ch] text-[13px] leading-relaxed text-muted">{step.does}</p>
            <p className="num mt-2.5 text-[11px] leading-snug text-faint">{step.keeps}</p>
          </li>
        ))}
        <li className="relative border-t border-cyan/30 pt-4">
          <div className="flex items-baseline gap-3">
            <span className="num text-[11px] text-cyan/70">↺</span>
            <h3 className="text-[14px] font-medium text-cyan">Back to the planner</h3>
          </div>
          <p className="mt-2 max-w-[44ch] text-[13px] leading-relaxed text-muted">
            The next experiment is chosen from what the last one changed. That
            return edge is the only reason any of this is autonomous.
          </p>
        </li>
      </ol>
    </Section>
  );
}
