"use client";

/**
 * Dose–response around the predicted MIC.
 *
 * One series, so there is no legend and no categorical palette — the title
 * names the candidate. The 95% interval is drawn as an area *under* the line
 * and is the point of the chart: the band widens through the transition region
 * and narrows well above it, which is the model working, not failing.
 *
 * The y axis is the inhibition fraction because that is what the interval is
 * reported on, and a dashed rule marks the predicted MIC so you can see which
 * points sit in the informative window and which are just confirming a dose
 * far above it.
 */

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { sig } from "@/lib/format";

const MARK = "#0e9eb8";
const GRID = "#1b2436";
const AXIS = "#5b6b82";

export interface DosePoint {
  dose: number;
  inhibition: number | null;
  low: number | null;
  high: number | null;
  log10Reduction: number | null;
  confidence: number | null;
}

export function DoseResponse({
  points,
  mic,
  label,
}: {
  points: DosePoint[];
  mic: number | null;
  label: string;
}) {
  // Recharts stacks an area from a floor, so the band is sent as
  // [low, high-low] and the lower piece is drawn transparent.
  const data = points.map((p) => ({
    ...p,
    band0: p.low ?? 0,
    band1: p.low !== null && p.high !== null ? Math.max(0, p.high - p.low) : 0,
  }));

  const ticks = points.map((p) => p.dose);

  return (
    <figure className="m-0">
      <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[12.5px] text-text">{label}</span>
        <span className="num text-[11px] text-faint">
          predicted inhibition fraction, shaded 95% interval
        </span>
      </figcaption>
      <div className="h-[300px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 6, right: 10, bottom: 18, left: -6 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="dose"
              scale="log"
              type="number"
              domain={["dataMin", "dataMax"]}
              ticks={ticks}
              tickFormatter={(v: number) => sig(v, 2)}
              stroke={AXIS}
              tick={{ fontSize: 10 }}
              tickLine={false}
              label={{
                value: "dose (µM, log scale)",
                position: "insideBottom",
                offset: -12,
                fill: AXIS,
                fontSize: 10,
              }}
            />
            <YAxis
              domain={[0, 1]}
              ticks={[0, 0.25, 0.5, 0.75, 1]}
              stroke={AXIS}
              tick={{ fontSize: 10 }}
              tickLine={false}
              width={44}
            />
            <Tooltip content={<DoseTooltip />} cursor={{ stroke: MARK, strokeDasharray: "3 3" }} />
            <Area
              dataKey="band0"
              stackId="ci"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
            />
            <Area
              dataKey="band1"
              stackId="ci"
              stroke="none"
              fill={MARK}
              fillOpacity={0.18}
              isAnimationActive={false}
            />
            {mic !== null && (
              <ReferenceLine
                x={mic}
                stroke={AXIS}
                strokeDasharray="4 3"
                label={{
                  value: `predicted MIC ${sig(mic, 2)} µM`,
                  fill: AXIS,
                  fontSize: 10,
                  position: "insideTopRight",
                }}
              />
            )}
            <Line
              dataKey="inhibition"
              stroke={MARK}
              strokeWidth={2}
              dot={{ r: 3, fill: MARK, stroke: "#0a0f1a", strokeWidth: 2 }}
              activeDot={{ r: 5, fill: MARK, stroke: "#0a0f1a", strokeWidth: 2 }}
              isAnimationActive={false}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

interface TooltipPayload {
  payload?: DosePoint;
}

function DoseTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayload[] }) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  if (!point) return null;
  return (
    <div className="border border-line-strong bg-ink/96 px-2.5 py-2 shadow-none">
      <div className="num text-[11px] text-text">{sig(point.dose, 3)} µM</div>
      <dl className="mt-1 space-y-0.5">
        <Row label="inhibition" value={point.inhibition === null ? "—" : point.inhibition.toFixed(3)} />
        <Row
          label="95% interval"
          value={
            point.low === null || point.high === null
              ? "—"
              : `${point.low.toFixed(3)} – ${point.high.toFixed(3)}`
          }
        />
        <Row
          label="log₁₀ reduction"
          value={point.log10Reduction === null ? "—" : point.log10Reduction.toFixed(2)}
        />
        <Row label="confidence" value={point.confidence === null ? "—" : point.confidence.toFixed(2)} />
      </dl>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <dt className="text-[10.5px] text-faint">{label}</dt>
      <dd className="num ml-auto text-[10.5px] text-muted">{value}</dd>
    </div>
  );
}
