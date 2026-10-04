"use client";

/**
 * The run form. Short, because the loop derives the rest itself.
 *
 * Gram stain is a required choice rather than a default. Without it the
 * candidate agent skips its envelope-accessibility reasoning entirely, and a
 * Gram-negative-specific candidate can then rank highly against a
 * Gram-positive target on information gain alone — a wrong answer that looks
 * like a confident one. The field says so.
 */

import { useId, useState } from "react";

import type { RunRequestBody } from "@/lib/api";

const PRESETS: { label: string; body: RunRequestBody }[] = [
  {
    label: "Listeria, high density",
    body: {
      goal: "Find a bacteriocin candidate that stays effective against high-density Listeria monocytogenes.",
      species: "Listeria monocytogenes",
      gram: "positive",
      target_cell_density: 1e8,
      ph: 7,
      temperature_c: 37,
      max_candidates: 4,
      max_iterations: 6,
      seed: 42,
    },
  },
  {
    label: "Staphylococcus aureus",
    body: {
      goal: "Find a bacteriocin candidate active against Staphylococcus aureus at neutral pH.",
      species: "Staphylococcus aureus",
      gram: "positive",
      target_cell_density: 1e6,
      ph: 7,
      temperature_c: 37,
      max_candidates: 4,
      max_iterations: 6,
      seed: 42,
    },
  },
  {
    label: "Escherichia coli",
    body: {
      goal: "Find a bacteriocin candidate able to cross the Escherichia coli outer membrane.",
      species: "Escherichia coli",
      gram: "negative",
      target_cell_density: 1e6,
      ph: 7,
      temperature_c: 37,
      max_candidates: 4,
      max_iterations: 6,
      seed: 42,
    },
  },
];

export function RunLauncher({
  onStart,
  busy,
  compact = false,
}: {
  onStart: (body: RunRequestBody) => void;
  busy: boolean;
  compact?: boolean;
}) {
  const [body, setBody] = useState<RunRequestBody>(PRESETS[0].body);
  const uid = useId();

  const set = <K extends keyof RunRequestBody>(key: K, value: RunRequestBody[K]) =>
    setBody((b) => ({ ...b, [key]: value }));

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onStart(body);
      }}
      className="border border-line bg-panel"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-4 py-2.5">
        <h3 className="mr-2 text-[13px] font-medium text-text">Objective</h3>
        {PRESETS.map((preset) => (
          <button
            key={preset.label}
            type="button"
            onClick={() => setBody(preset.body)}
            className={`border px-2 py-1 text-[11.5px] transition-colors ${
              body.species === preset.body.species
                ? "border-cyan/50 bg-cyan/10 text-cyan"
                : "border-line text-muted hover:border-line-strong hover:text-text"
            }`}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="space-y-4 p-4">
        <label className="block">
          <span className="text-[11.5px] text-faint">Scientific goal</span>
          <textarea
            id={`${uid}-goal`}
            value={body.goal}
            onChange={(e) => set("goal", e.target.value)}
            rows={compact ? 2 : 3}
            maxLength={500}
            required
            minLength={3}
            className="mt-1 w-full resize-none border border-line bg-ink px-2.5 py-2 text-[13px] leading-snug text-text placeholder:text-faint focus:border-cyan/60 focus:outline-none"
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="text-[11.5px] text-faint">Target organism</span>
            <input
              value={body.species}
              onChange={(e) => set("species", e.target.value)}
              required
              className="num mt-1 w-full border border-line bg-ink px-2.5 py-2 text-[13px] text-text focus:border-cyan/60 focus:outline-none"
            />
          </label>

          <fieldset className="block">
            <legend className="text-[11.5px] text-faint">
              Gram stain
              <span className="ml-1.5 text-faint/80">
                — drives envelope accessibility; no default
              </span>
            </legend>
            <div className="mt-1 flex">
              {(["positive", "negative"] as const).map((gram) => (
                <label
                  key={gram}
                  className={`num flex-1 cursor-pointer border px-2 py-2 text-center text-[12.5px] transition-colors ${
                    body.gram === gram
                      ? "border-cyan/50 bg-cyan/10 text-cyan"
                      : "border-line text-muted hover:text-text"
                  } ${gram === "negative" ? "-ml-px" : ""}`}
                >
                  <input
                    type="radio"
                    name={`${uid}-gram`}
                    checked={body.gram === gram}
                    onChange={() => set("gram", gram)}
                    className="sr-only"
                  />
                  {gram}
                </label>
              ))}
            </div>
          </fieldset>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <NumberField
            label="Cell density"
            hint="CFU/mL"
            value={body.target_cell_density ?? 1e6}
            onChange={(v) => set("target_cell_density", v)}
            options={[1e4, 1e6, 1e8, 1e10]}
            render={(v) => `1e${Math.round(Math.log10(v))}`}
          />
          <NumberField
            label="pH"
            value={body.ph ?? 7}
            onChange={(v) => set("ph", v)}
            options={[5, 6, 7, 8]}
            render={(v) => v.toFixed(1)}
          />
          <NumberField
            label="Candidates"
            value={body.max_candidates ?? 4}
            onChange={(v) => set("max_candidates", v)}
            options={[2, 4, 6, 8]}
            render={(v) => String(v)}
          />
          <NumberField
            label="Iterations"
            hint="loop laps"
            value={body.max_iterations ?? 6}
            onChange={(v) => set("max_iterations", v)}
            options={[2, 4, 6, 8]}
            render={(v) => String(v)}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-3">
        <button
          type="submit"
          disabled={busy}
          className="border border-cyan/60 bg-cyan/12 px-4 py-2 text-[13px] text-cyan transition-colors hover:bg-cyan/20 disabled:cursor-not-allowed disabled:border-line disabled:bg-transparent disabled:text-faint"
        >
          {busy ? "Running…" : "Run discovery"}
        </button>
        <p className="num text-[11px] leading-tight text-faint">
          seed {body.seed ?? "none"} — same objective, same seed, same run
        </p>
      </div>
    </form>
  );
}

function NumberField({
  label,
  hint,
  value,
  onChange,
  options,
  render,
}: {
  label: string;
  hint?: string;
  value: number;
  onChange: (value: number) => void;
  options: number[];
  render: (value: number) => string;
}) {
  return (
    <div>
      <div className="text-[11.5px] text-faint">
        {label}
        {hint && <span className="ml-1 text-faint/75">{hint}</span>}
      </div>
      <div className="mt-1 flex">
        {options.map((option, i) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={`num flex-1 border px-1 py-1.5 text-[11.5px] transition-colors ${
              value === option
                ? "border-cyan/50 bg-cyan/10 text-cyan"
                : "border-line text-muted hover:text-text"
            } ${i > 0 ? "-ml-px" : ""}`}
          >
            {render(option)}
          </button>
        ))}
      </div>
    </div>
  );
}
