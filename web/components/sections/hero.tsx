"use client";

import { LoopConsole } from "@/components/loop-console";
import { Provenance } from "@/components/provenance";
import type { AgentRole, RunDigest } from "@/lib/types";
import type { StationState } from "@/lib/use-run";

/**
 * The hero opens on the loop, running. The headline makes a claim and the panel
 * beside it is the claim being carried out — not an illustration of one.
 */
export function Hero({
  stations,
  digest,
  iteration,
  status,
  active,
  onRun,
  busy,
}: {
  stations: Record<AgentRole, StationState>;
  digest: RunDigest | null;
  iteration: number;
  status: "idle" | "running" | "finished" | "error";
  active: AgentRole | null;
  onRun: () => void;
  busy: boolean;
}) {
  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-14 pt-16 sm:px-6 sm:pt-20">
      <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-16">
        <div className="max-w-[34ch] lg:max-w-none">
          <p className="num text-[11px] uppercase tracking-[0.2em] text-cyan/85">
            Autonomous bacteriocin discovery
          </p>
          <h1 className="mt-5 text-balance text-[44px] font-medium leading-[0.98] tracking-[-0.03em] text-text sm:text-[60px] lg:text-[68px]">
            AI that learns what to test next.
          </h1>
          <p className="mt-6 max-w-[56ch] text-[15.5px] leading-relaxed text-muted">
            Bacterion is an autonomous lab. Specialist agents gather evidence on
            bacteriocins, propose candidates, run simulated experiments, read
            the results, and choose the next experiment from what they just
            learned.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={onRun}
              disabled={busy}
              className="border border-cyan/60 bg-cyan/12 px-5 py-2.5 text-[14px] text-cyan transition-colors hover:bg-cyan/20 disabled:cursor-not-allowed disabled:border-line disabled:bg-transparent disabled:text-faint"
            >
              {busy ? "Discovery running…" : "Run discovery"}
            </button>
            <a
              href="#loop"
              className="border border-line px-5 py-2.5 text-[14px] text-muted transition-colors hover:border-line-strong hover:text-text"
            >
              Explore the lab
            </a>
          </div>

          {/* The honesty note belongs next to the button that produces numbers,
              not buried in a footer. */}
          <p className="mt-7 flex max-w-[58ch] flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] leading-relaxed text-faint">
            <Provenance kind="simulation" />
            <span>
              Experiments run against a simulator, so every figure here is a
              prediction to be tested. Nothing has been measured at a bench.
            </span>
          </p>
        </div>

        <div className="lg:pt-2">
          <LoopConsole
            stations={stations}
            digest={digest}
            iteration={iteration}
            status={status}
            active={active}
          />
        </div>
      </div>
    </div>
  );
}
