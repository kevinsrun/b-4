"use client";

/**
 * Literature evidence.
 *
 * The agent retrieves abstracts from Europe PMC and extracts only what a
 * deterministic rule can defend, which means it often finds nothing — and
 * "insufficient evidence" is a real answer this page shows rather than hides.
 *
 * Three things are kept visible for every record, because they are what makes
 * it evidence rather than a quotation: the verbatim excerpt it came from, the
 * citation, and whether the number was measured or was the authors' own
 * interpretation. The list of variables the paper did *not* report is shown at
 * full length, since that list is usually the reason a claim cannot be reused.
 */

import { useState } from "react";

import { Provenance } from "@/components/provenance";
import { Empty, Failure, Field, Id, Meter, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { fixed, humanizeFactor, sig } from "@/lib/format";
import type { EvidenceRecord, LiteratureResponse, NormalizedQuantity } from "@/lib/types";
import { Button } from "@/components/interactive";

const EXAMPLES = [
  {
    question: "pediocin PA-1 MIC against Listeria monocytogenes in broth",
    bacteriocin: "pediocin",
    target_organism: "Listeria monocytogenes",
  },
  {
    question: "nisin log reduction Listeria monocytogenes in milk",
    bacteriocin: "nisin",
    target_organism: "Listeria monocytogenes",
  },
  {
    question: "microcin J25 activity against Escherichia coli",
    bacteriocin: "microcin J25",
    target_organism: "Escherichia coli",
  },
];

export default function EvidencePage() {
  const [query, setQuery] = useState(EXAMPLES[0]);
  const [response, setResponse] = useState<LiteratureResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async () => {
    setBusy(true);
    setError(null);
    try {
      setResponse(await api.evidence({ ...query, max_results: 20 }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Retrieval failed.");
      setResponse(null);
    } finally {
      setBusy(false);
    }
  };

  const decisionStatus = String(response?.decision?.status ?? "");
  const considered = response?.decision?.documents_considered;

  return (
    <>
      <header className="mx-auto max-w-[1180px] px-4 pb-8 pt-12 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="display display-lg text-balance text-cyan">
            Evidence
          </h1>
          <Provenance kind="literature" />
        </div>
        <p className="mt-3 max-w-[68ch] text-[14px] leading-relaxed text-muted">
          Searches Europe PMC and extracts only claims a deterministic rule can
          stand behind, keeping the excerpt each one came from. Automated
          extraction is not independent verification, and finding nothing is a
          legitimate result.
        </p>
      </header>

      <div className="mx-auto max-w-[1180px] space-y-5 px-4 pb-10 sm:px-6">
        <Panel title="Question">
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example.question}
                  type="button"
                  onClick={() => setQuery(example)}
                  className={`border px-2.5 py-1.5 text-left text-[11.5px] transition-colors ${
                    query.question === example.question
                      ? "border-cyan/50 bg-cyan/10 text-cyan"
                      : "border-line text-muted hover:text-text"
                  }`}
                >
                  {example.bacteriocin}
                </button>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto]">
              <label className="block">
                <span className="text-[11.5px] text-faint">What do you want to know</span>
                <input
                  value={query.question}
                  onChange={(e) => setQuery({ ...query, question: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void search();
                  }}
                  className="mt-1 w-full border border-line bg-ink px-2.5 py-2 text-[13px] text-text rounded-[3px] transition-colors focus:border-cyan"
                />
              </label>
              <Button
                type="button"
                onClick={() => void search()}
                disabled={busy}
                variant="primary"
                size="md"
                className="self-end"
              >
                {busy ? "Searching…" : "Search literature"}
              </Button>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="text-[11.5px] text-faint">Bacteriocin</span>
                <input
                  value={query.bacteriocin ?? ""}
                  onChange={(e) => setQuery({ ...query, bacteriocin: e.target.value })}
                  className="num mt-1 w-full border border-line bg-ink px-2.5 py-2 text-[12.5px] text-text rounded-[3px] transition-colors focus:border-cyan"
                />
              </label>
              <label className="block">
                <span className="text-[11.5px] text-faint">Target organism</span>
                <input
                  value={query.target_organism ?? ""}
                  onChange={(e) => setQuery({ ...query, target_organism: e.target.value })}
                  className="num mt-1 w-full border border-line bg-ink px-2.5 py-2 text-[12.5px] text-text rounded-[3px] transition-colors focus:border-cyan"
                />
              </label>
            </div>
            <p className="text-[11px] leading-relaxed text-faint">
              Queries Europe PMC over the network, so results depend on what is
              indexed there today and on the connection.
            </p>
          </div>
        </Panel>

        {error && <Failure message={error} />}

        {response && (
          <div className="grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
            <div className="bg-panel px-4 py-3.5">
              <Field
                label="verdict"
                value={decisionStatus.replace(/-/g, " ") || "—"}
                tone={decisionStatus === "evidence-collected" ? "default" : "amber"}
              />
            </div>
            <div className="bg-panel px-4 py-3.5">
              <Field label="abstracts read" value={String(considered ?? "—")} />
            </div>
            <div className="bg-panel px-4 py-3.5">
              <Field label="records extracted" value={String(response.evidence.length)} />
            </div>
            <div className="bg-panel px-4 py-3.5">
              <Field label="confidence" value={fixed(response.confidence, 2)} />
            </div>
          </div>
        )}

        {response && response.evidence.length === 0 && (
          <div className="rounded-[4px] border border-line bg-panel">
            <Empty>
              The agent read {String(considered ?? "several")} abstracts and
              could not extract a defensible record from any of them. That is
              the honest answer, not a failure — try naming the bacteriocin and
              organism more precisely, or ask about a log reduction rather than
              a MIC.
            </Empty>
          </div>
        )}

        {response?.evidence.map((record) => (
          <EvidenceCard key={record.evidence_id} record={record} />
        ))}

        {response && response.knowledge_gaps.length > 0 && (
          <Panel title={`Gaps the agent names (${response.knowledge_gaps.length})`}>
            <ul className="grid gap-x-8 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
              {response.knowledge_gaps.map((gap, i) => (
                <li key={i} className="text-[12.5px] leading-snug text-muted">
                  {gap}
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {response && response.contradictions.length > 0 && (
          <Panel
            title={`Contradictions between sources (${response.contradictions.length})`}
            aside={<span className="num text-[11px] text-amber">unresolved</span>}
          >
            <ul className="space-y-3">
              {response.contradictions.map((item, i) => (
                <li key={i} className="num max-w-[84ch] text-[11.5px] leading-relaxed text-muted">
                  {JSON.stringify(item)}
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {response && response.recommended_searches.length > 0 && (
          <Panel title="What to search next">
            <ul className="flex flex-wrap gap-2">
              {response.recommended_searches.map((suggestion, i) => (
                <li key={i}>
                  <button
                    type="button"
                    onClick={() => {
                      setQuery({ ...query, question: suggestion });
                      void search();
                    }}
                    className="num border border-line px-2 py-1 text-[11.5px] text-muted transition-colors hover:border-cyan/40 hover:text-cyan"
                  >
                    {suggestion}
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </div>
    </>
  );
}

function EvidenceCard({ record }: { record: EvidenceRecord }) {
  const source = record.source ?? {};
  const measurement = record.measurement ?? {};
  const measured = measurement.data_role === "measured";
  const missing = record.missing_variables ?? [];
  const conditions = Object.entries(record.conditions ?? {}).filter(
    ([, value]) => value !== null && value !== undefined && !(typeof value === "object" && !Object.keys(value).length),
  );

  return (
    <article className="rounded-[4px] border border-line bg-panel">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5 border-b border-line px-4 py-3">
        <h2 className="min-w-0 max-w-[70ch] flex-1 text-[13.5px] leading-snug text-text">
          {source.title ?? "Untitled source"}
        </h2>
        <Provenance evidenceType={record.evidence_type} />
      </header>

      <div className="space-y-4 p-4">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
          {source.year && <Field label="year" value={String(source.year)} />}
          {source.authors?.length ? (
            <Field
              label="authors"
              value={source.authors.length > 2 ? `${source.authors[0]} et al.` : source.authors.join(", ")}
            />
          ) : null}
          {source.doi_or_url && (
            <a
              href={source.doi_or_url}
              target="_blank"
              rel="noreferrer noopener"
              className="num text-[11.5px] text-cyan underline decoration-cyan/35 underline-offset-2 transition-colors hover:decoration-cyan"
            >
              {source.source_id ?? "source"}
            </a>
          )}
          <div className="ml-auto w-28">
            <Meter value={record.confidence} label="extraction confidence" />
          </div>
        </div>

        {record.claim && (
          <p className="max-w-[86ch] text-[13px] leading-relaxed text-text">{record.claim}</p>
        )}

        {/* The measurement, with the author's own words beside it. */}
        <div className="grid gap-4 border-y border-line py-3.5 sm:grid-cols-[minmax(0,15rem)_1fr]">
          <div className="flex flex-wrap gap-x-5 gap-y-3">
            <Field
              label={humanizeFactor(measurement.type ?? "measurement")}
              value={
                measurement.value === null || measurement.value === undefined
                  ? "—"
                  : `${sig(measurement.value, 3)}${measurement.unit ? ` ${measurement.unit}` : ""}`
              }
            />
            <Field
              label="data role"
              value={measured ? "measured" : (measurement.data_role ?? "—")}
              tone={measured ? "default" : "amber"}
              hint={measured ? undefined : "the authors' interpretation, not a measurement"}
            />
          </div>
          {record.provenance?.excerpt && (
            <blockquote className="border-l-2 border-line-strong pl-3">
              <p className="max-w-[72ch] text-[12.5px] italic leading-relaxed text-muted">
                “{record.provenance.excerpt}”
              </p>
              <footer className="num mt-1.5 text-[10.5px] text-faint">
                {record.provenance.locator ?? "source"}
                <span className="ml-4">{record.provenance.extraction_method}</span>
              </footer>
            </blockquote>
          )}
        </div>

        {conditions.length > 0 && (
          <div>
            <h3 className="text-[11.5px] text-faint">Conditions the paper reported</h3>
            <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-3">
              {conditions.map(([key, value]) => (
                <ConditionField key={key} name={key} value={value} />
              ))}
            </dl>
          </div>
        )}

        {missing.length > 0 && (
          <div className="border-t border-line pt-3">
            <h3 className="text-[11.5px] text-amber/90">
              Not reported ({missing.length})
            </h3>
            <p className="mt-1 max-w-[80ch] text-[12px] leading-relaxed text-faint">
              Without these, the claim cannot be turned into an experiment
              specification — which is why the planner treats a literature value
              as a starting point rather than a condition.
            </p>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {missing.map((field) => (
                <li
                  key={field}
                  className="num border border-line px-1.5 py-[3px] text-[10.5px] text-faint"
                >
                  {humanizeFactor(field)}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
          <Id>{record.evidence_id}</Id>
          {record.bacteriocin?.name && (
            <span className="num text-[10.5px] text-faint">{record.bacteriocin.name}</span>
          )}
          {record.target?.organism && (
            <span className="text-[10.5px] italic text-faint">{record.target.organism}</span>
          )}
        </div>
      </div>
    </article>
  );
}

function ConditionField({
  name,
  value,
}: {
  name: string;
  value: NormalizedQuantity | string | number | null;
}) {
  if (value === null || value === undefined) return null;
  if (typeof value !== "object") {
    return <Field label={humanizeFactor(name)} value={String(value)} />;
  }
  const q = value as NormalizedQuantity;
  const shown =
    q.normalized_value !== null && q.normalized_value !== undefined
      ? `${sig(q.normalized_value, 3)}${q.normalized_unit ? ` ${q.normalized_unit}` : ""}`
      : q.value !== null && q.value !== undefined
        ? `${sig(q.value, 3)}${q.unit ? ` ${q.unit}` : ""}`
        : "—";
  const asPublished =
    q.original_value !== null && q.original_value !== undefined
      ? `as published ${q.original_value}${q.original_unit ? ` ${q.original_unit}` : ""}`
      : undefined;
  return <Field label={humanizeFactor(name)} value={shown} hint={asPublished} />;
}
