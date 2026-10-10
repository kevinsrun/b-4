import Link from "next/link";
import { Dna, FlaskConical, Network } from "lucide-react";

import { LinkButton, Magnetic } from "@/components/interactive";
import { Scene } from "@/components/scene";
import { Provenance, ProvenanceLegend } from "@/components/provenance";
import { WhyBacteriocins } from "@/components/sections/why";

export const metadata = {
  title: "BactroGen Research — Bacteriocin discovery",
  description:
    "Explore bacteriocin candidates, investigate molecular properties, and connect computational predictions with scientific evidence.",
};

/**
 * The landing page. It explains the platform and routes into it; it computes
 * nothing. Every figure-shaped thing here is either a label or a link — the
 * real numbers live behind /research, where they arrive with their provenance
 * attached.
 */

const GLANCE = [
  {
    icon: Dna,
    heading: "Candidate discovery",
    body: "Find promising bacteriocin candidates from reference sequence sets, ranked by the properties that make a peptide worth testing.",
    href: "/candidates",
    cta: "Browse candidates",
  },
  {
    icon: Network,
    heading: "Evidence & methods",
    body: "Structured extraction from published abstracts, with citations, kept separate from anything the model proposed on its own.",
    href: "/evidence",
    cta: "Read the evidence",
  },
  {
    icon: FlaskConical,
    heading: "Experiment activity",
    body: "Simulated experiments under stated conditions, each with its interval, its assumptions and the question it was chosen to settle.",
    href: "/experiments",
    cta: "Open the simulator",
  },
];

const TOOLS = [
  {
    href: "/design",
    label: "Sequence designer",
    body: "Compose and inspect candidate sequences against the properties the scoring model actually uses.",
  },
  {
    href: "/knowledge",
    label: "Research state",
    body: "The hypotheses the loop is holding, and the append-only event log that produced them.",
  },
  {
    href: "/benchmarks",
    label: "Benchmarks",
    body: "How the simulator is calibrated, and the directional invariants it is held to.",
  },
  {
    href: "/methodology",
    label: "Methodology",
    body: "What each agent does, what it is allowed to claim, and where the boundaries sit.",
  },
];

export default function Home() {
  return (
    <>
      {/* ---------------------------------------------------------------- Hero */}
      <section className="relative isolate overflow-hidden border-b border-line bg-ink">
        <Scene src="/backgrounds/hero-membrane.png" priority position="right center" scrim="left" />
        <div className="relative mx-auto max-w-[1180px] px-4 py-20 sm:px-6 sm:py-28 lg:py-36">
          <div className="max-w-[46rem] lg:max-w-[34rem]">
            <p className="eyebrow">Computational biology / Bacteriocin discovery</p>
            <h1 className="display display-xl mt-6 text-balance text-cyan">
              Discover the next generation of bacteriocins.
            </h1>
            <p className="mt-7 max-w-[52ch] text-[16px] leading-relaxed text-muted">
              Explore bacteriocin candidates, investigate molecular properties,
              and connect computational predictions with scientific evidence —
              with every claim carrying the kind of claim it is.
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-3">
              {/* The one magnetic control on the site. It is large, it is the
                  primary path into the product, and it is the only place the
                  effect is stable enough to be worth having. */}
              <Magnetic>
                <LinkButton href="/research" variant="primary" size="lg">
                  Explore research
                  <span aria-hidden>→</span>
                </LinkButton>
              </Magnetic>
              <LinkButton href="/methodology" variant="secondary" size="lg">
                How it works
              </LinkButton>
            </div>

            <p className="mt-9 flex max-w-[58ch] flex-wrap items-center gap-x-2 gap-y-1 text-[13px] leading-relaxed text-faint">
              <Provenance kind="simulation" />
              <span>
                Experiments run against a simulator, so every figure in this
                product is a prediction to be tested. Nothing has been measured
                at a bench.
              </span>
            </p>
          </div>
        </div>

        {/* The artwork is the hero's right-hand side, so its disclosure sits at
            the foot of the band rather than under a card. */}
        <p className="relative mx-auto max-w-[1180px] px-4 pb-6 text-[11.5px] leading-relaxed text-faint sm:px-6">
          Illustration: a decorative peptide-like cluster near a lipid membrane.
          Not a rendered structure, and not a depiction of any binding event.
        </p>
      </section>

      {/* ------------------------------------------------- Research at a glance */}
      <section className="border-b border-line bg-panel">
        <div className="mx-auto max-w-[1180px] px-4 py-16 sm:px-6 sm:py-20">
          <div className="grid gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.6fr)] lg:gap-16">
            <div>
              <p className="eyebrow">Research at a glance</p>
              <h2 className="display display-lg mt-5 text-balance text-cyan">
                From data to discovery.
              </h2>
              <p className="mt-5 max-w-[44ch] text-[14.5px] leading-relaxed text-muted">
                BactroGen Research combines literature extraction, candidate
                scoring and simulated experiments into one loop that chooses
                what to test next from what it just learned.
              </p>
            </div>

            <div className="grid gap-px overflow-hidden rounded-[4px] border border-line bg-line sm:grid-cols-3">
              {GLANCE.map(({ icon: Icon, heading, body, href, cta }) => (
                <Link
                  key={heading}
                  href={href}
                  className="liftable group flex flex-col bg-panel p-6 hover:bg-ink/60"
                >
                  <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-sage-soft text-cyan">
                    <Icon size={18} aria-hidden />
                  </span>
                  <h3 className="mt-5 text-[15px] font-semibold text-text">{heading}</h3>
                  <p className="mt-2.5 flex-1 text-[13px] leading-relaxed text-muted">{body}</p>
                  <span className="mt-5 inline-flex items-center gap-1.5 text-[12.5px] font-medium text-cyan">
                    {cta}
                    <span
                      aria-hidden
                      className="transition-transform duration-200 group-hover:translate-x-0.5"
                    >
                      →
                    </span>
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------- Why bacteriocins */}
      <WhyBacteriocins />

      {/* --------------------------------------------------------------- Tools */}
      <section className="border-t border-line bg-panel">
        <div className="mx-auto max-w-[1180px] px-4 py-16 sm:px-6 sm:py-20">
          <div className="max-w-[46ch]">
            <p className="eyebrow">Explore our research</p>
            <h2 className="display display-lg mt-5 text-balance text-cyan">
              Tools for deeper insights.
            </h2>
            <p className="mt-5 text-[14.5px] leading-relaxed text-muted">
              Browse candidates, explore molecular properties, review simulated
              results, and see the reasoning behind each recommendation.
            </p>
          </div>

          <div className="mt-10 grid gap-px overflow-hidden rounded-[4px] border border-line bg-line sm:grid-cols-2">
            {TOOLS.map((tool) => (
              <Link
                key={tool.href}
                href={tool.href}
                className="liftable group flex items-start justify-between gap-6 bg-panel p-6 hover:bg-ink/60"
              >
                <span className="min-w-0">
                  <span className="block text-[15px] font-semibold text-text">{tool.label}</span>
                  <span className="mt-2 block max-w-[46ch] text-[13px] leading-relaxed text-muted">
                    {tool.body}
                  </span>
                </span>
                <span
                  aria-hidden
                  className="mt-1 shrink-0 text-cyan transition-transform duration-200 group-hover:translate-x-0.5"
                >
                  →
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- Provenance */}
      <section className="border-t border-line bg-ink">
        <div className="mx-auto max-w-[1180px] px-4 py-16 sm:px-6 sm:py-20">
          <div className="max-w-[46ch]">
            <p className="eyebrow">How to read this product</p>
            <h2 className="display display-lg mt-5 text-balance text-cyan">
              Three kinds of claim, never merged.
            </h2>
            <p className="mt-5 text-[14.5px] leading-relaxed text-muted">
              Every figure in BactroGen carries a tag naming where it came from.
              The tags are the most important thing on the page, so they travel
              with the number rather than sitting in a footnote.
            </p>
          </div>
          <ProvenanceLegend className="mt-10" />
        </div>
      </section>

      {/* ----------------------------------------------------------------- CTA */}
      <section className="border-t border-line bg-sage-soft">
        <div className="mx-auto max-w-[1180px] px-4 py-16 sm:px-6 sm:py-20">
          <div className="max-w-[52ch]">
            <h2 className="display display-lg text-balance text-cyan">
              Give it an organism. Watch it decide what to test.
            </h2>
            <p className="mt-5 max-w-[58ch] text-[14.5px] leading-relaxed text-text/80">
              A run takes a few seconds. You get the experiments it chose, the
              reason it chose them, the predictions with their intervals, and
              the questions it could not answer.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <LinkButton href="/research" variant="primary" size="lg">
                Start a discovery run
              </LinkButton>
              <LinkButton href="/agents" variant="secondary" size="lg">
                How the agents divide the work
              </LinkButton>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
