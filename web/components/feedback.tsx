"use client";

/**
 * Small feedback pieces: a copy control that confirms, a tooltip for the terms
 * a reader may not know, and a reveal wrapper for figures.
 *
 * All three are deliberately quiet. The rule on this site is that motion marks
 * something that actually happened — a value was copied, data arrived — and
 * never decorates something that did not.
 */

import { useId, useRef, useState, type ReactNode } from "react";
import { Check, Copy, X } from "lucide-react";

import { useCopy, useInView } from "@/lib/motion";

/* ------------------------------------------------------------------ copy -- */

export function CopyButton({
  value,
  label = "Copy",
  className = "",
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const { copied, failed, copy } = useCopy();

  return (
    <button
      type="button"
      onClick={() => void copy(value)}
      // The accessible name changes with the state, so a screen reader is told
      // the copy happened rather than being left on a stale label.
      aria-label={copied ? `${label}: copied` : failed ? `${label}: copy failed` : label}
      className={`ripple-host pressable inline-flex items-center gap-1.5 rounded-[3px] border px-2 py-1 text-[11.5px] ${
        copied
          ? "border-green/50 bg-green/12 text-green"
          : failed
            ? "border-red/50 bg-red/10 text-red"
            : "border-line bg-panel text-muted hover:border-line-strong hover:text-text"
      } ${className}`}
    >
      <span aria-hidden className="inline-flex">
        {copied ? <Check size={12} strokeWidth={3} /> : failed ? <X size={12} /> : <Copy size={12} />}
      </span>
      <span>{copied ? "Copied" : failed ? "Copy failed" : label}</span>
    </button>
  );
}

/* --------------------------------------------------------------- tooltip -- */

/**
 * A contextual definition for a scientific term.
 *
 * It opens on hover *and* on focus, closes on Escape, and the trigger keeps a
 * dotted underline so the term is discoverable without a pointer. The content
 * is also wired through aria-describedby, so it is not pointer-only
 * information.
 */
export function Tooltip({
  term,
  children,
  side = "top",
}: {
  term: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom";
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const close = useRef<number | null>(null);

  const show = () => {
    if (close.current) window.clearTimeout(close.current);
    setOpen(true);
  };
  // A short grace period, so moving the pointer across the gap to read a long
  // definition does not dismiss it.
  const hide = () => {
    if (close.current) window.clearTimeout(close.current);
    close.current = window.setTimeout(() => setOpen(false), 120);
  };

  return (
    <span className="relative inline-block">
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        className="cursor-help rounded-[2px] underline decoration-dotted decoration-from-font underline-offset-[3px] transition-colors hover:text-cyan"
      >
        {term}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          onMouseEnter={show}
          onMouseLeave={hide}
          className={`reveal absolute left-1/2 z-30 w-[16rem] -translate-x-1/2 rounded-[4px] border border-line bg-panel px-3 py-2 text-[12px] font-normal leading-relaxed text-muted shadow-[var(--shadow-lg)] ${
            side === "top" ? "bottom-[calc(100%+8px)]" : "top-[calc(100%+8px)]"
          }`}
        >
          {children}
        </span>
      )}
    </span>
  );
}

/* ---------------------------------------------------------------- reveal -- */

/**
 * Fades a figure up the first time it scrolls into view.
 *
 * Charts keep their own scales and axes — this animates opacity and a 6px
 * offset only, so a value is never shown mid-transit at the wrong position,
 * and the figure is fully readable the moment it settles.
 */
export function RevealOnView({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const [ref, seen] = useInView<HTMLDivElement>();

  return (
    <div
      ref={ref}
      className={`${className} ${seen ? "reveal" : "opacity-0"}`}
      style={seen && delay ? { animationDelay: `${delay}ms` } : undefined}
    >
      {children}
    </div>
  );
}

/* --------------------------------------------------------------- ambient -- */

/**
 * The drifting cluster used behind empty states.
 *
 * Decorative: it depicts nothing, and it is marked aria-hidden so it is not
 * announced as content. Twelve nodes and CSS keyframes — no render loop, and
 * it stops dead under prefers-reduced-motion.
 */
export function AmbientMolecules({ className = "" }: { className?: string }) {
  const nodes = [
    { x: 14, y: 32, r: 5, d: 0 },
    { x: 30, y: 18, r: 3.5, d: 1.4 },
    { x: 46, y: 38, r: 6.5, d: 2.8 },
    { x: 62, y: 22, r: 4, d: 0.7 },
    { x: 78, y: 42, r: 5.5, d: 2.1 },
    { x: 24, y: 58, r: 4.5, d: 3.5 },
    { x: 54, y: 66, r: 5, d: 1.1 },
    { x: 86, y: 64, r: 3.5, d: 2.4 },
  ];
  const bonds: [number, number][] = [
    [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 2], [6, 7], [7, 4],
  ];

  return (
    <svg
      viewBox="0 0 100 80"
      aria-hidden
      focusable="false"
      className={`pointer-events-none select-none ${className}`}
      preserveAspectRatio="xMidYMid slice"
    >
      <g stroke="var(--color-cyan)" strokeWidth={0.45} strokeLinecap="round">
        {bonds.map(([a, b], i) => (
          <line
            key={i}
            x1={nodes[a].x}
            y1={nodes[a].y}
            x2={nodes[b].x}
            y2={nodes[b].y}
            className="molecule-bond"
            style={{ ["--delay" as string]: `${(i % 5) * 1.1}s` }}
          />
        ))}
      </g>
      {nodes.map((n, i) => (
        <circle
          key={i}
          cx={n.x}
          cy={n.y}
          r={n.r}
          fill={i % 3 === 0 ? "var(--color-cyan)" : i % 3 === 1 ? "var(--color-mark)" : "var(--color-sage-deep)"}
          opacity={0.3}
          className="molecule-node"
          style={{
            ["--delay" as string]: `${n.d}s`,
            ["--dx" as string]: `${(i % 3) - 1}px`,
            ["--dy" as string]: `${((i + 1) % 3) - 1.5}px`,
          }}
        />
      ))}
    </svg>
  );
}
