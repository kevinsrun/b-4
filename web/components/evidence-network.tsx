"use client";

/**
 * The provenance graph: which candidate a hypothesis is about, and which
 * evidence it rests on.
 *
 * Every node and every edge here comes from identifiers the knowledge agent
 * actually recorded — `candidate_id` and `evidence_ids` on each hypothesis.
 * Nothing is inferred, nothing is laid out to look fuller than it is, and when
 * a hypothesis cites no evidence that is drawn as a hypothesis with no edges,
 * because that is the true and interesting shape.
 *
 * The layout is three deterministic columns rather than a force simulation: it
 * is stable between renders, it reads left-to-right as "candidate → hypothesis
 * → evidence", and it costs no animation frames. Highlighting is pure CSS on a
 * selected id, so hovering does not re-render the graph.
 */

import { useMemo, useState } from "react";

import type { Hypothesis } from "@/lib/types";

type Kind = "candidate" | "hypothesis" | "evidence";

interface Node {
  id: string;
  kind: Kind;
  label: string;
  title: string;
  x: number;
  y: number;
  status?: string;
}

// Columns sit inside the viewBox with room for a 16-character mono label on
// each outer side, so candidate and evidence ids are never clipped.
const COLUMN_X: Record<Kind, number> = { candidate: 150, hypothesis: 380, evidence: 610 };
const VIEW_W = 770;

const FILL: Record<Kind, string> = {
  // Proposals, predictions and literature keep the colours they carry
  // everywhere else in the product.
  candidate: "var(--color-sage-deep)",
  hypothesis: "var(--color-cyan)",
  evidence: "var(--color-blue)",
};

const ROW = 46;
const PAD_TOP = 34;

function short(id: string, max = 16) {
  return id.length > max ? `${id.slice(0, max - 1)}…` : id;
}

export function EvidenceNetwork({
  hypotheses,
  className = "",
}: {
  hypotheses: Hypothesis[];
  className?: string;
}) {
  const [active, setActive] = useState<string | null>(null);

  const { nodes, edges, height } = useMemo(() => {
    const candidates = new Map<string, Node>();
    const hyps: Node[] = [];
    const evidence = new Map<string, Node>();
    const edges: { from: string; to: string }[] = [];

    for (const h of hypotheses) {
      const hid = h.hypothesis_id;
      if (!hid) continue;

      hyps.push({
        id: hid,
        kind: "hypothesis",
        label: short(hid),
        title: h.statement ? `${hid} — ${h.statement}` : hid,
        status: h.status,
        x: COLUMN_X.hypothesis,
        y: 0,
      });

      if (h.candidate_id) {
        if (!candidates.has(h.candidate_id)) {
          candidates.set(h.candidate_id, {
            id: h.candidate_id,
            kind: "candidate",
            label: short(h.candidate_id),
            title: `Candidate ${h.candidate_id}`,
            x: COLUMN_X.candidate,
            y: 0,
          });
        }
        edges.push({ from: h.candidate_id, to: hid });
      }

      for (const eid of h.evidence_ids ?? []) {
        if (!evidence.has(eid)) {
          evidence.set(eid, {
            id: eid,
            kind: "evidence",
            label: short(eid),
            title: `Evidence ${eid}`,
            x: COLUMN_X.evidence,
            y: 0,
          });
        }
        edges.push({ from: hid, to: eid });
      }
    }

    // Each column is centred on its own height, so short columns sit beside
    // long ones without the graph looking top-heavy.
    const columns: Node[][] = [[...candidates.values()], hyps, [...evidence.values()]];
    const tallest = Math.max(1, ...columns.map((c) => c.length));
    for (const column of columns) {
      const offset = ((tallest - column.length) * ROW) / 2;
      column.forEach((node, i) => {
        node.y = PAD_TOP + offset + i * ROW;
      });
    }

    return {
      nodes: columns.flat(),
      edges,
      height: PAD_TOP * 2 + tallest * ROW,
    };
  }, [hypotheses]);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  // A node is lit when it is the active one or shares an edge with it.
  const lit = useMemo(() => {
    if (!active) return null;
    const set = new Set<string>([active]);
    for (const e of edges) {
      if (e.from === active) set.add(e.to);
      if (e.to === active) set.add(e.from);
    }
    return set;
  }, [active, edges]);

  if (!nodes.length) {
    return (
      <p className={`px-4 py-8 text-[13px] leading-relaxed text-faint sm:px-5 ${className}`}>
        No provenance relationships are recorded yet. The graph is drawn from the
        identifiers on each hypothesis — the candidate it concerns and the
        evidence it cites — so it appears once the loop has written hypotheses to
        the research state.
      </p>
    );
  }

  const counts = {
    candidate: nodes.filter((n) => n.kind === "candidate").length,
    hypothesis: nodes.filter((n) => n.kind === "hypothesis").length,
    evidence: nodes.filter((n) => n.kind === "evidence").length,
  };

  return (
    <div className={className}>
      <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2 px-4 pt-4 sm:px-5">
        {(["candidate", "hypothesis", "evidence"] as Kind[]).map((kind) => (
          <span key={kind} className="flex items-center gap-1.5 text-[11.5px] text-muted">
            <span
              aria-hidden
              className="h-2.5 w-2.5 rounded-full"
              style={{ background: FILL[kind] }}
            />
            {kind} <span className="num text-faint">{counts[kind]}</span>
          </span>
        ))}
        <span className="num ml-auto text-[11px] text-faint">{edges.length} links</span>
      </div>

      <div className="overflow-x-auto px-4 pb-4 sm:px-5">
        <svg
          viewBox={`0 0 ${VIEW_W} ${height}`}
          className="h-auto w-full min-w-[660px]"
          role="img"
          aria-label={`Provenance graph: ${counts.candidate} candidates, ${counts.hypothesis} hypotheses, ${counts.evidence} evidence records, ${edges.length} recorded links.`}
        >
          <g>
            {edges.map((e, i) => {
              const a = byId.get(e.from);
              const b = byId.get(e.to);
              if (!a || !b) return null;
              const on = !lit || (lit.has(e.from) && lit.has(e.to));
              // A flat cubic, so edges separate instead of overlapping as
              // straight lines between evenly spaced rows.
              const mid = (a.x + b.x) / 2;
              return (
                <path
                  key={i}
                  d={`M ${a.x + 7} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${b.x - 7} ${b.y}`}
                  fill="none"
                  stroke={on ? "var(--color-line-strong)" : "var(--color-line)"}
                  strokeWidth={on && lit ? 1.6 : 1}
                  opacity={on ? 1 : 0.35}
                  className="transition-all duration-200"
                />
              );
            })}
          </g>

          <g>
            {nodes.map((node) => {
              const on = !lit || lit.has(node.id);
              const anchor = node.kind === "evidence" ? "start" : node.kind === "candidate" ? "end" : "start";
              const dx = node.kind === "evidence" ? 12 : node.kind === "candidate" ? -12 : 12;
              return (
                <g
                  key={node.id}
                  tabIndex={0}
                  role="button"
                  aria-label={node.title}
                  aria-pressed={active === node.id}
                  onMouseEnter={() => setActive(node.id)}
                  onMouseLeave={() => setActive(null)}
                  onFocus={() => setActive(node.id)}
                  onBlur={() => setActive(null)}
                  onClick={() => setActive((c) => (c === node.id ? null : node.id))}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") setActive(null);
                  }}
                  className="cursor-pointer outline-none [&:focus-visible>circle]:stroke-cyan [&:focus-visible>circle]:stroke-[3]"
                  opacity={on ? 1 : 0.3}
                  style={{ transition: "opacity 200ms var(--ease)" }}
                >
                  <title>{node.title}</title>
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={active === node.id ? 8.5 : 6.5}
                    fill={FILL[node.kind]}
                    stroke="var(--color-panel)"
                    strokeWidth={2}
                    style={{ transition: "r 160ms var(--ease)" }}
                  />
                  <text
                    x={node.x + dx}
                    y={node.y + 4}
                    textAnchor={anchor}
                    className="num"
                    fontSize={10.5}
                    fill="var(--color-muted)"
                  >
                    {node.label}
                  </text>
                  {node.status && (
                    <text
                      x={node.x + dx}
                      y={node.y + 15}
                      textAnchor={anchor}
                      className="num"
                      fontSize={8.5}
                      fill="var(--color-faint)"
                    >
                      {node.status.replace(/_/g, " ")}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
      </div>

      <p className="border-t border-line px-4 py-3 text-[11.5px] leading-relaxed text-faint sm:px-5">
        Edges are the identifiers the knowledge agent recorded, not inferred
        relationships. A hypothesis drawn with no evidence edge is one that
        cites none.
      </p>
    </div>
  );
}
