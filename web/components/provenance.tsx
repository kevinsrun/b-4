/**
 * The provenance tag — the one structural device repeated across the whole site.
 *
 * Every scientific number here is one of three kinds of claim, and the lab's
 * rule is that they are never merged. So the tag is not decoration: it is the
 * single most important thing to read next to any figure on the page.
 *
 * Note which colour never appears. Nothing this system produces is
 * wet-lab-derived, so the green tag exists and is never earned — and the
 * disclosure below the loop says so in words.
 */

import type { EvidenceType } from "@/lib/types";

type Kind = "literature" | "proposal" | "simulation" | "wetlab";

const KINDS: Record<Kind, { label: string; title: string; className: string }> = {
  literature: {
    label: "literature-derived",
    title:
      "Retrieved and structured from published abstracts, with citations. Automated extraction is not independent verification.",
    className: "border-blue/45 text-blue bg-blue/8",
  },
  proposal: {
    label: "proposal",
    title: "A candidate the design agent put forward. Not evidence of activity.",
    className: "border-dashed border-faint/60 text-muted bg-transparent",
  },
  simulation: {
    label: "simulation-derived",
    title:
      "Predicted by the simulator — a hypothesis to test, never an observation. Its priors are coarse and uncalibrated, so a confident number can be wrong by a decade.",
    className: "border-cyan/45 text-cyan bg-cyan/8",
  },
  wetlab: {
    label: "wet-lab-derived",
    title: "Measured at the bench. Nothing in this system produces it.",
    className: "border-green/45 text-green bg-green/8",
  },
};

export function kindFor(evidenceType: string | null | undefined): Kind {
  switch (evidenceType) {
    case "literature-derived":
      return "literature";
    case "wet-lab-derived":
      return "wetlab";
    case "simulation-derived":
    case "computational-prediction":
      return "simulation";
    default:
      return "proposal";
  }
}

export function Provenance({
  kind,
  evidenceType,
  className = "",
}: {
  kind?: Kind;
  evidenceType?: EvidenceType | string | null;
  className?: string;
}) {
  const resolved = kind ?? kindFor(evidenceType);
  const spec = KINDS[resolved];
  return (
    <span
      title={spec.title}
      className={`num inline-flex shrink-0 items-center border px-1.5 py-[2px] text-[10px] leading-none tracking-tight ${spec.className} ${className}`}
    >
      {spec.label}
    </span>
  );
}

/** Spelled out once per page, near the first numbers it applies to. */
export function ProvenanceLegend({ className = "" }: { className?: string }) {
  return (
    <dl className={`flex flex-wrap items-start gap-x-8 gap-y-3 ${className}`}>
      {(["literature", "proposal", "simulation", "wetlab"] as Kind[]).map((kind) => (
        <div key={kind} className="flex max-w-[22rem] items-start gap-2">
          <Provenance kind={kind} className="mt-[3px]" />
          <dd className="text-[12.5px] leading-snug text-faint">
            {kind === "wetlab" ? (
              <>Measured at the bench. Nothing here produces it.</>
            ) : kind === "literature" ? (
              <>Extracted from published abstracts, with citations.</>
            ) : kind === "proposal" ? (
              <>Put forward for testing. Not a claim of activity.</>
            ) : (
              <>Predicted by the model. A hypothesis, not an observation.</>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
