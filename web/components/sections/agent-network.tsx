"use client";

import { useEffect, useState } from "react";

import { Section } from "@/components/section";
import { Failure } from "@/components/ui";
import { api } from "@/lib/api";
import type { AgentDescriptor } from "@/lib/types";

/**
 * The roster, read from the API rather than written here, so the versions shown
 * are the ones that produced the numbers on this page.
 *
 * `transport` is a real distinction in this system: deterministic backends are
 * MCP tools, because the same input must give the same output, and only the
 * steps that genuinely decide something are reasoning sub-agents.
 */
export function AgentNetwork() {
  const [agents, setAgents] = useState<AgentDescriptor[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .agents()
      .then((r) => setAgents(r.agents))
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <Section
      heading="Seven specialists, one claim each"
      standfirst="Nothing here is a general-purpose assistant asked to be a scientist. Each agent has one responsibility and one kind of statement it is permitted to make, and the orchestrator is not allowed to merge them."
    >
      {error && <Failure message={error} />}
      {agents && (
        <div className="overflow-x-auto border border-line bg-panel">
          <table className="w-full min-w-[42rem] border-collapse text-left">
            <thead>
              <tr className="border-b border-line">
                {["Agent", "Produces", "Transport", "Version"].map((head) => (
                  <th
                    key={head}
                    scope="col"
                    className="px-4 py-2.5 text-[11.5px] font-normal text-faint"
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr key={agent.role} className="border-b border-line/60 last:border-b-0 align-top">
                  <th scope="row" className="px-4 py-3 text-left font-normal">
                    <div className="text-[13px] text-text">{agent.label}</div>
                    <div className="num mt-0.5 text-[10.5px] text-faint">{agent.agent_name}</div>
                  </th>
                  <td className="px-4 py-3">
                    <div className="num text-[11.5px] text-cyan/90">{agent.produces}</div>
                    <p className="mt-1 max-w-[52ch] text-[12px] leading-snug text-muted">
                      {agent.claim}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <span className="num text-[11px] text-muted">{agent.transport}</span>
                    {agent.deterministic && (
                      <div
                        className="num mt-0.5 text-[10.5px] text-faint"
                        title="Same input, same output — no model call"
                      >
                        deterministic
                      </div>
                    )}
                  </td>
                  <td className="num px-4 py-3 text-[11px] text-faint">
                    {agent.model_version ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-4 max-w-[76ch] text-[12.5px] leading-relaxed text-faint">
        Deterministic backends are MCP tools on purpose. A pure function given a
        model loop costs a call and loses the reproducibility it exists to
        guarantee, so only the planner and the two interpretive steps reason.
        Orchestration is handled by Omnigent.
      </p>
    </Section>
  );
}
