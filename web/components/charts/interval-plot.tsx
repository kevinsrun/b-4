"use client";

/**
 * Predicted log₁₀ reduction, one row per experiment, with its uncertainty.
 *
 * Plotted on log₁₀ reduction rather than the inhibition fraction on purpose:
 * the fraction pins near 1.0 above the MIC and stops carrying signal, so a row
 * of saturated bars would make every experiment look equally strong. Reduction
 * keeps separating them.
 *
 * The interval is drawn as the mark and the point estimate as a dot on it,
 * because the interval is the result. Rows whose interval covers zero are the
 * ones no conclusion can be drawn from, and they look like it.
 */

import { fixed, sig } from "@/lib/format";
import type { ExperimentResult } from "@/lib/types";
import { Provenance } from "@/components/provenance";
import { RevealOnView } from "@/components/feedback";

const MARK = "#5c7a52";

export interface IntervalRow {
  id: string;
  label: string;
  sublabel?: string;
  value: number | null;
  spread: number | null;
  confidence: number | null;
  evidenceType: string;
}

export function rowsFromResults(
  results: ExperimentResult[],
  nameFor: (candidateId: string | null | undefined) => string,
): IntervalRow[] {
  return results.map((result) => {
    const dose = result.conditions?.bacteriocin_concentration;
    const doseValue = typeof dose === "object" && dose ? dose.value : (dose as number | null);
    const density = result.conditions?.target_cell_density;
    const densityValue =
      typeof density === "object" && density ? density.value : (density as number | null);
    return {
      id: result.result_id,
      label: nameFor(result.candidate_id),
      // A conditions readout, not a meta string: each field is labelled by its unit.
      sublabel: `${sig(doseValue, 2)} µM   ${sig(densityValue, 2)} CFU/mL   pH ${fixed(
        result.conditions?.ph ?? null,
        1,
      )}   ${sig(result.conditions?.incubation_time ?? null, 2)} h`,
      value: result.measurement?.predicted_log10_reduction_vs_control ?? null,
      spread: result.measurement?.uncertainty_log10_reduction ?? null,
      confidence: result.confidence ?? null,
      evidenceType: result.evidence_type,
    };
  });
}

export function IntervalPlot({
  rows,
  selectedId,
  onSelect,
}: {
  rows: IntervalRow[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}) {
  if (!rows.length) return null;

  const bounds = rows.flatMap((r) =>
    r.value === null ? [] : [r.value - (r.spread ?? 0), r.value + (r.spread ?? 0)],
  );
  const lo = Math.min(0, ...bounds);
  const hi = Math.max(1, ...bounds);
  const span = hi - lo || 1;
  const pos = (v: number) => ((v - lo) / span) * 100;

  const zeroAt = pos(0);

  return (
    <RevealOnView>
    {/* The figure fades up the first time it is seen. Only opacity and a 6px
        offset animate — the scales, ticks and marks are final from the first
        frame, so no value is ever shown at a position it does not hold. */}
    <figure className="m-0">
      <div className="relative">
        <ul className="divide-y divide-line/70" role="list">
          {rows.map((row) => {
            const hasValue = row.value !== null;
            const spread = row.spread ?? 0;
            const low = hasValue ? Math.max(lo, row.value! - spread) : 0;
            const high = hasValue ? Math.min(hi, row.value! + spread) : 0;
            const coversZero = hasValue && row.value! - spread <= 0;
            const selected = selectedId === row.id;
            const Row = onSelect ? "button" : "div";
            return (
              <li key={row.id}>
                <Row
                  {...(onSelect
                    ? {
                        type: "button" as const,
                        onClick: () => onSelect(row.id),
                        "aria-pressed": selected,
                      }
                    : {})}
                  className={`grid w-full grid-cols-1 items-center gap-x-3 gap-y-1 px-2 py-2.5 text-left transition-colors sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_minmax(0,9rem)] ${
                    onSelect ? "hover:bg-raised/60" : ""
                  } ${selected ? "bg-cyan/8" : ""}`}
                >
                <div className="min-w-0 pr-3">
                  <div className="truncate text-[12.5px] leading-tight text-text">{row.label}</div>
                  <div className="num truncate text-[10.5px] leading-tight text-faint" title={row.sublabel}>
                    {row.sublabel}
                  </div>
                </div>
                <div className="relative h-[26px]">
                  {/* Zero sits inside each track, so it stays aligned with the
                      marks whatever the surrounding columns do. */}
                  <div
                    className="absolute inset-y-1 w-px bg-line-strong"
                    style={{ left: `${zeroAt}%` }}
                    aria-hidden
                  />
                  {hasValue ? (
                    <>
                      <div
                        className="absolute top-1/2 h-[3px] -translate-y-1/2"
                        style={{
                          left: `${pos(low)}%`,
                          width: `${Math.max(0.4, pos(high) - pos(low))}%`,
                          backgroundColor: MARK,
                          opacity: coversZero ? 0.3 : 0.55,
                        }}
                        aria-hidden
                      />
                      <div
                        className="absolute top-1/2 h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2"
                        style={{
                          left: `${pos(row.value!)}%`,
                          backgroundColor: MARK,
                          borderColor: "#fcfaf5",
                        }}
                        title={`log₁₀ reduction ${fixed(row.value, 2)} ± ${fixed(row.spread, 2)}`}
                      />
                    </>
                  ) : null}
                </div>
                {/* The value gets its own column rather than floating beside
                    the mark, so a long interval cannot push it off the track. */}
                <div className="num text-[11px] leading-tight sm:text-right">
                  {hasValue ? (
                    <>
                      <span className="text-muted">{fixed(row.value, 2)}</span>
                      <span className="text-faint"> ± {fixed(row.spread, 2)}</span>
                      {coversZero && (
                        <span
                          className="ml-2 text-amber"
                          title="The interval includes zero reduction, so this experiment settles nothing"
                        >
                          covers 0
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-faint">not reported</span>
                  )}
                </div>
                </Row>
              </li>
            );
          })}
        </ul>
      </div>
      <figcaption className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-2.5 text-[10.5px] text-faint">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-[3px] w-6" style={{ backgroundColor: MARK, opacity: 0.55 }} />
          uncertainty on log₁₀ reduction
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="h-[9px] w-[9px] rounded-full border-2"
            style={{ backgroundColor: MARK, borderColor: "#fcfaf5" }}
          />
          point estimate
        </span>
        <span>vertical rule: no reduction</span>
        <Provenance kind="simulation" />
      </figcaption>
    </figure>
    </RevealOnView>
  );
}
