/**
 * The small shared pieces. Deliberately few, and deliberately not all the same
 * shape: a Panel is an instrument enclosure with a titled header rail, a Field
 * is a labelled readout, and neither is a generic rounded card.
 */

import type { ReactNode } from "react";

import { AmbientMolecules } from "@/components/feedback";

export function Panel({
  title,
  aside,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`rounded-[4px] border border-line bg-panel shadow-[var(--shadow-sm)] ${className}`}>
      {(title || aside) && (
        <header className="flex items-center justify-between gap-4 border-b border-line px-4 py-3">
          <h3 className="text-[13.5px] font-semibold tracking-tight text-text">{title}</h3>
          {aside}
        </header>
      )}
      <div className={bodyClassName || "p-4"}>{children}</div>
    </section>
  );
}

/** A labelled measurement. The label is quiet; the number is the thing. */
export function Field({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "amber" | "cyan" | "muted";
}) {
  const toneClass = {
    default: "text-text",
    amber: "text-amber",
    cyan: "text-cyan",
    muted: "text-muted",
  }[tone];
  return (
    <div className="min-w-0">
      <div className="text-[11.5px] leading-tight text-faint">{label}</div>
      <div className={`num mt-1 text-[15.5px] leading-none ${toneClass}`}>{value}</div>
      {hint && <div className="mt-1 text-[11px] leading-tight text-faint">{hint}</div>}
    </div>
  );
}

/** A technical identifier. Monospace, selectable, visibly a machine value. */
export function Id({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <code
      title={title ?? (typeof children === "string" ? children : undefined)}
      className="num rounded-[3px] border border-line bg-raised/70 px-1.5 py-[2px] text-[11px] text-muted"
    >
      {children}
    </code>
  );
}

const STATUS_TONES: Record<string, string> = {
  supported: "border-green/50 text-green bg-green/12",
  approved: "border-green/50 text-green bg-green/12",
  pass: "border-green/50 text-green bg-green/12",
  open: "border-cyan/45 text-cyan bg-cyan/10",
  running: "border-cyan/45 text-cyan bg-cyan/10",
  weakened: "border-amber/50 text-amber bg-amber/12",
  inconclusive: "border-line-strong text-muted bg-raised/50",
  needs_more_evidence: "border-amber/50 text-amber bg-amber/12",
  known_failure: "border-amber/50 text-amber bg-amber/12",
  contradicted: "border-red/50 text-red bg-red/12",
  rejected: "border-red/50 text-red bg-red/12",
  failed: "border-red/50 text-red bg-red/12",
  failure: "border-red/50 text-red bg-red/12",
  fail: "border-red/50 text-red bg-red/12",
  error: "border-red/50 text-red bg-red/12",
};

export function Status({ status, className = "" }: { status: string; className?: string }) {
  const tone = STATUS_TONES[status] ?? "border-line-strong text-muted bg-transparent";
  return (
    <span
      className={`num inline-flex shrink-0 items-center rounded-[3px] border px-1.5 py-[3px] text-[10px] leading-none ${tone} ${className}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

/**
 * An empty state is an invitation to act, so it says what to do rather than
 * that there is nothing here.
 */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="relative overflow-hidden">
      {/* Decorative, aria-hidden, and stopped entirely under reduced motion.
          It gives an empty panel something to be rather than a blank box. */}
      <AmbientMolecules className="absolute inset-y-0 right-0 h-full w-[46%] opacity-55" />
      <p className="relative max-w-[60ch] px-4 py-10 text-[13px] leading-relaxed text-faint sm:px-5">
        {children}
      </p>
    </div>
  );
}

export function Failure({ message }: { message: string }) {
  return (
    <div className="rounded-[4px] border border-red/40 bg-red/10 px-4 py-3">
      <p className="text-[13px] leading-snug text-red">{message}</p>
    </div>
  );
}

/** A horizontal meter. Used for confidence, where the bar is easier than the digits. */
export function Meter({
  value,
  tone = "cyan",
  label,
}: {
  value: number | null | undefined;
  tone?: "cyan" | "amber" | "green";
  label?: string;
}) {
  const safe = typeof value === "number" && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : null;
  const bar = { cyan: "bg-cyan", amber: "bg-amber", green: "bg-green" }[tone];
  return (
    <div
      className="flex items-center gap-2"
      role="meter"
      aria-valuenow={safe ?? undefined}
      aria-valuemin={0}
      aria-valuemax={1}
      aria-label={label}
    >
      <div className="h-[5px] w-full min-w-10 overflow-hidden rounded-full bg-raised">
        {safe !== null && <div
          className={`h-full rounded-full ${bar} transition-[width] duration-500 ease-[var(--ease)]`}
          style={{ width: `${safe * 100}%` }}
        />}
      </div>
      <span className="num shrink-0 text-[11px] text-muted">
        {safe === null ? "—" : safe.toFixed(2)}
      </span>
    </div>
  );
}

export function Hairline({ className = "" }: { className?: string }) {
  return <div className={`h-px bg-line ${className}`} />;
}

/**
 * Declared limitations, shown as the agents emit them.
 *
 * An agent that names its own weaknesses is more trustworthy than one that does
 * not, so these are given the same weight as its conclusions rather than being
 * tucked away: severity is on the left, and what the limitation affects is
 * named.
 */
export function Uncertainties({ items }: { items: (UncertaintyRecord | string)[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-3.5">
      {items.map((item, i) => {
        if (typeof item === "string") {
          return (
            <li key={i} className="max-w-[84ch] text-[12.5px] leading-relaxed text-muted">
              {item}
            </li>
          );
        }
        const severity = item.severity ?? "";
        const tone =
          severity === "high"
            ? "border-amber/50 bg-amber/10 text-amber"
            : severity === "medium"
              ? "border-line-strong text-muted"
              : "border-line text-faint";
        return (
          <li key={i} className="flex gap-3">
            <span
              className={`num mt-[2px] h-fit shrink-0 rounded-[3px] border px-1.5 py-[3px] text-[10px] leading-none ${tone}`}
              title={`severity: ${severity || "unstated"}`}
            >
              {item.kind}
            </span>
            <div className="min-w-0">
              <p className="max-w-[80ch] text-[12.5px] leading-relaxed text-muted">
                {item.description}
              </p>
              {item.affects && item.affects.length > 0 && (
                <p className="num mt-1 text-[10.5px] leading-snug text-faint">
                  affects {item.affects.length} candidate
                  {item.affects.length === 1 ? "" : "s"}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

interface UncertaintyRecord {
  kind: string;
  description: string;
  affects?: string[] | null;
  severity?: string | null;
}
