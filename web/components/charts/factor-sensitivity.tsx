"use client";

/**
 * Which variables drove one prediction.
 *
 * Bars run left and right from a zero rule, so *position* carries the sign and
 * colour does not have to. That leaves one hue for the data and keeps amber
 * free to mean the only thing it means on this site: the model supplied this
 * value because the spec did not. A factor with high sensitivity and an
 * imputed source is the single most important thing to notice here — it means
 * the prediction describes an assumed condition, not the one you specified.
 *
 * Sensitivities are on the simulator's own scale and are comparable to each
 * other within a result, not across results, so no axis numbers are shown;
 * the bar lengths and the hover values carry it.
 */

import { factorUnit, humanizeFactor, sig } from "@/lib/format";
import type { ImportantFactor } from "@/lib/types";

const MARK = "#0e9eb8";

export function FactorSensitivity({
  factors,
  max = 7,
}: {
  factors: ImportantFactor[];
  max?: number;
}) {
  const shown = [...factors]
    .sort((a, b) => Math.abs(b.sensitivity) - Math.abs(a.sensitivity))
    .slice(0, max);
  if (!shown.length) {
    return <p className="text-[12px] text-faint">No factor sensitivities reported.</p>;
  }
  const scale = Math.max(...shown.map((f) => Math.abs(f.sensitivity))) || 1;

  return (
    <figure className="m-0">
      <ul className="space-y-[7px]">
        {shown.map((factor) => {
          const width = (Math.abs(factor.sensitivity) / scale) * 50;
          const negative = factor.sensitivity < 0;
          const imputed = (factor.source ?? "").startsWith("imputed");
          const unit = factorUnit(factor.factor);
          return (
            <li key={factor.factor} className="grid grid-cols-[minmax(0,11rem)_1fr] items-center gap-3">
              <div className="min-w-0">
                <div className="truncate text-[12px] leading-tight text-muted" title={factor.factor}>
                  {humanizeFactor(factor.factor)}
                </div>
                <div className="num text-[10.5px] leading-tight text-faint">
                  {factor.value === null || factor.value === undefined
                    ? "—"
                    : typeof factor.value === "number"
                      ? `${sig(factor.value, 3)}${unit ? ` ${unit}` : ""}`
                      : String(factor.value)}
                  {imputed && (
                    <span className="ml-1.5 text-amber" title={`source: ${factor.source}`}>
                      assumed
                    </span>
                  )}
                </div>
              </div>
              <div
                className="relative h-[18px]"
                title={`${factor.factor}: sensitivity ${sig(factor.sensitivity, 3)} (${
                  factor.direction ?? "unspecified direction"
                })`}
              >
                {/* the zero rule */}
                <div className="absolute inset-y-0 left-1/2 w-px bg-line-strong" aria-hidden />
                <div
                  className="absolute top-1/2 h-[9px] -translate-y-1/2"
                  style={{
                    width: `${width}%`,
                    [negative ? "right" : "left"]: "50%",
                    backgroundColor: MARK,
                    opacity: imputed ? 0.45 : 0.95,
                    // 2px surface gap so the bar never touches the zero rule
                    [negative ? "marginRight" : "marginLeft"]: "2px",
                  }}
                />
                <span
                  className={`num absolute top-1/2 -translate-y-1/2 text-[10px] text-faint ${
                    negative ? "right-0" : "left-auto right-0"
                  }`}
                  style={negative ? { right: `calc(50% + ${width}% + 6px)` } : { left: `calc(50% + ${width}% + 6px)`, right: "auto" }}
                >
                  {sig(factor.sensitivity, 2)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      <figcaption className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-2 text-[10.5px] text-faint">
        <span>left of the rule: decreases activity</span>
        <span>right: increases it</span>
        <span className="text-amber">assumed: the spec left this out</span>
      </figcaption>
    </figure>
  );
}
