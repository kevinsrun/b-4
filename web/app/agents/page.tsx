"use client";

/**
 * The agents, and the checks that say whether the simulator is behaving.
 *
 * The self-test is the most useful thing on this page: fourteen directional
 * biology invariants — more dose must not reduce killing, a Gram-negative
 * target must not be easier than a Gram-positive one, and so on. It is run
 * live and reported in full, including any invariant the model is known to
 * violate, because a self-test that hid its known failures would be worthless.
 */

import { useEffect, useState } from "react";

import { AgentNetwork } from "@/components/sections/agent-network";
import { Empty, Failure, Field, Panel, Status } from "@/components/ui";
import { api } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { Selftest } from "@/lib/types";

export default function AgentsPage() {
  const [selftest, setSelftest] = useState<Selftest | null>(null);
  const [backends, setBackends] = useState<Record<string, Record<string, unknown>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.selftest(), api.backends()])
      .then(([s, b]) => {
        setSelftest(s);
        setBackends(b);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <>
      <header className="mx-auto max-w-[1180px] px-4 pb-8 pt-12 sm:px-6">
        <h1 className="text-[32px] font-medium leading-[1.1] tracking-[-0.02em] text-text sm:text-[38px]">
          Agents
        </h1>
        <p className="mt-3 max-w-[66ch] text-[14px] leading-relaxed text-muted">
          Who does what, which of them are deterministic, and whether the
          simulator currently satisfies the biology it is supposed to respect.
        </p>
      </header>

      {error && (
        <div className="mx-auto max-w-[1180px] px-4 sm:px-6">
          <Failure message={error} />
        </div>
      )}

      <AgentNetwork />

      <section className="border-t border-line">
        <div className="mx-auto max-w-[1180px] px-4 py-14 sm:px-6">
          <header className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 className="text-[26px] font-medium leading-[1.15] tracking-[-0.015em] text-text sm:text-[30px]">
                Does the simulator still obey biology?
              </h2>
              <p className="mt-3 max-w-[62ch] text-[14px] leading-relaxed text-muted">
                These invariants check the direction of each effect rather than
                its magnitude: a model can be badly calibrated and still get
                every direction right, but one that gets a direction wrong is
                broken. Anyone installing refitted priors should re-run them.
              </p>
            </div>
            {selftest && (
              <div className="flex gap-6">
                <Field
                  label="passing"
                  value={`${selftest.n_checks - selftest.n_failed}/${selftest.n_checks}`}
                  tone={selftest.passed ? "default" : "amber"}
                />
                <Field label="known failures" value={String(selftest.n_known_failures)} />
              </div>
            )}
          </header>

          {selftest ? (
            <>
              {selftest.note && (
                <p className="mb-5 border border-amber/35 bg-amber/6 px-4 py-3 text-[12.5px] leading-relaxed text-amber">
                  {selftest.note}
                </p>
              )}
              <ul className="grid gap-px border border-line bg-line sm:grid-cols-2">
                {selftest.checks.map((check) => (
                  <li key={check.check} className="bg-panel px-4 py-3">
                    <div className="flex items-baseline gap-2">
                      <span className="text-[12.5px] text-text">{titleCase(check.check)}</span>
                      <Status status={check.status} className="ml-auto" />
                    </div>
                    <p className="num mt-1.5 max-w-[60ch] text-[11px] leading-snug text-faint">
                      {check.detail}
                    </p>
                    {check.known_failure_reason && (
                      <p className="mt-1.5 max-w-[60ch] text-[11.5px] leading-snug text-amber">
                        {check.known_failure_reason}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <div className="border border-line bg-panel">
              <Empty>Running the invariants…</Empty>
            </div>
          )}
        </div>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto max-w-[1180px] px-4 py-14 sm:px-6">
          <h2 className="text-[26px] font-medium leading-[1.15] tracking-[-0.015em] text-text sm:text-[30px]">
            Experiment backends
          </h2>
          <p className="mt-3 max-w-[62ch] text-[14px] leading-relaxed text-muted">
            An experiment is routed by its assay domain. The simulated backend
            runs; the wet-lab backend is a stub, which is the structural reason
            nothing here can be reported as measured.
          </p>
          <div className="mt-8 grid gap-5 md:grid-cols-2">
            {backends &&
              Object.entries(backends).map(([name, capabilities]) => (
                <Panel
                  key={name}
                  title={titleCase(name)}
                  aside={
                    <Status status={capabilities.available === false ? "failed" : "approved"} />
                  }
                >
                  <dl className="space-y-2">
                    {Object.entries(capabilities)
                      .filter(([key]) => key !== "name")
                      .map(([key, value]) => (
                        <div key={key} className="flex items-baseline gap-4">
                          <dt className="text-[11.5px] text-faint">{titleCase(key)}</dt>
                          <dd className="num ml-auto max-w-[60%] break-words text-right text-[11.5px] text-muted">
                            {Array.isArray(value)
                              ? value.join(", ")
                              : typeof value === "boolean"
                                ? String(value)
                                : typeof value === "object" && value !== null
                                  ? JSON.stringify(value)
                                  : String(value)}
                          </dd>
                        </div>
                      ))}
                  </dl>
                </Panel>
              ))}
          </div>
        </div>
      </section>
    </>
  );
}
