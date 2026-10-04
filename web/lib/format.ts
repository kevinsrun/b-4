/**
 * Display helpers.
 *
 * The rule throughout: a value that was not reported renders as an em dash, not
 * as 0 and not as "N/A". Rounding is for reading only — the exact figure is
 * always available in the raw JSON the pages link to.
 */

import type { Quantity } from "./types";

export const DASH = "—";

/** Significant figures, so 0.000836 and 83.6 both stay readable. */
export function sig(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  if (value === 0) return "0";
  const abs = Math.abs(value);
  if (abs >= 1e5 || abs < 1e-3) return value.toExponential(Math.max(0, digits - 1));
  return Number(value.toPrecision(digits)).toString();
}

export function fixed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return value.toFixed(digits);
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return `${(value * 100).toFixed(digits)}%`;
}

/** 1e8 reads as 10⁸ in prose but CFU/mL counts are conventionally written as powers of ten. */
export function scientific(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  if (value === 0) return "0";
  const exponent = Math.floor(Math.log10(Math.abs(value)));
  const mantissa = value / 10 ** exponent;
  if (Math.abs(mantissa - 1) < 1e-9) return `1e${exponent}`;
  return `${Number(mantissa.toPrecision(2))}e${exponent}`;
}

export function quantity(q: Quantity | number | null | undefined): string {
  if (q === null || q === undefined) return DASH;
  if (typeof q === "number") return sig(q);
  const unit = q.unit ? ` ${prettyUnit(q.unit)}` : "";
  const magnitude = Math.abs(q.value);
  const body = magnitude >= 1e4 ? scientific(q.value) : sig(q.value);
  return `${body}${unit}`;
}

export function prettyUnit(unit: string): string {
  const map: Record<string, string> = {
    uM: "µM",
    um: "µM",
    nM: "nM",
    cfu_per_ml: "CFU/mL",
    cells_per_ml: "cells/mL",
    log10_cfu_per_ml: "log₁₀ CFU/mL",
    od600: "OD₆₀₀",
    h: "h",
    ug_per_ml: "µg/mL",
  };
  return map[unit] ?? unit;
}

/** `target_cell_density_cfu_per_ml` → `target cell density`, for axis and row labels. */
export function humanizeFactor(name: string): string {
  return name
    .replace(/_cfu_per_ml$/, "")
    .replace(/_um$/, "")
    .replace(/_mm$/, "")
    .replace(/_per_h$/, "")
    .replace(/_h$/, "")
    .replace(/_c$/, "")
    .replace(/_/g, " ")
    .replace(/\bph\b/, "pH");
}

export function factorUnit(name: string): string {
  if (name.endsWith("_cfu_per_ml")) return "CFU/mL";
  if (name.endsWith("_um")) return "µM";
  if (name.endsWith("_mm")) return "mM";
  if (name.endsWith("_per_h")) return "/h";
  if (name.endsWith("_h")) return "h";
  if (name === "temperature_c") return "°C";
  return "";
}

/**
 * Make an agent's sentence readable by a person.
 *
 * The agents write for a machine first: content-addressed ids, schema field
 * names and file paths inline. None of that helps someone reading the log, and
 * the exact record is still one click away in the raw JSON, so it is stripped
 * for display only — never from the data.
 */
export function plain(text: string): string {
  return (
    text
      // "Finding find_5131d4…: " / "Created hypothesis hyp_f0a6…: " → drop the id
      .replace(/\b(?:hyp|find|rev|exp|cand|ev|res|run)[_-][0-9a-f]{6,}\b:?\s*/gi, "")
      // "(evidence_type 'inferred-hypothesis' / 'model-predicted')", "(scripts/verify_seed_sequences.py)"
      .replace(/\s*\([^()]*(?:_[a-z]|\.py|\/)[^()]*\)/g, "")
      // leftover schema-ish field names in prose
      .replace(/\bpredicted_inhibition_fraction\b/g, "predicted inhibition")
      .replace(/\btarget_cell_density\b/g, "cell density")
      // "status=rejected, critique=X" is a record, not a sentence
      .replace(/\bstatus=(\w+),\s*critique=/gi, "$1 — ")
      // any remaining "key=value" pair reads as "key value"
      .replace(/\b([a-z][a-z0-9_]*)=(?=\S)/gi, (_m, key: string) => `${key.replace(/_/g, " ")} `)
      // phrases left dangling once their id was removed
      .replace(/\bfor candidate\s*$/i, "")
      .replace(/\(\s*result\s*,?\s*/gi, "(")
      .replace(/\(\s*\)/g, "")
      .replace(/\(\s*,\s*/g, "(")
      .replace(/\s{2,}/g, " ")
      .replace(/\s+([.,;:])/g, "$1")
      .replace(/^[\s:—-]+/, "")
      .replace(/[\s,]+$/, "")
      .trim()
  );
}

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function shortId(id: string | null | undefined, keep = 8): string {
  if (!id) return DASH;
  const [prefix, rest] = id.includes("_") ? [id.slice(0, id.indexOf("_") + 1), id.slice(id.indexOf("_") + 1)] : ["", id];
  return rest.length > keep ? `${prefix}${rest.slice(0, keep)}…` : id;
}

export function elapsed(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return DASH;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** Residues coloured by class, so a peptide reads as chemistry rather than as a string. */
export function residueClass(residue: string): string {
  if ("KRH".includes(residue)) return "text-cyan";
  if ("DE".includes(residue)) return "text-red";
  if ("C".includes(residue)) return "text-amber";
  if ("AVLIMFWPG".includes(residue)) return "text-muted";
  return "text-faint";
}
