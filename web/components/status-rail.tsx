"use client";

/**
 * The instrument status bar: what the machine reports about itself.
 *
 * Every figure is read from the API — schema and simulator versions, the live
 * self-test, how many runs are in flight. When the API is down the rail says
 * so and tells you the command to start it, because that is the actual next
 * step and a page of empty panels would not say it.
 */

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Health, Selftest } from "@/lib/types";

export function StatusRail() {
  const [health, setHealth] = useState<Health | null>(null);
  const [selftest, setSelftest] = useState<Selftest | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let alive = true;

    // Health is cheap and says whether the lab is up; the self-test actually
    // simulates, so it is fetched separately and once. Waiting on it would
    // leave the whole rail blank for as long as the invariants take to run.
    const pollHealth = async () => {
      try {
        const h = await api.health();
        if (!alive) return;
        setHealth(h);
        setOffline(false);
      } catch {
        if (alive) setOffline(true);
      }
    };

    void pollHealth();
    void api
      .selftest()
      .then((s) => alive && setSelftest(s))
      .catch(() => undefined);

    const timer = setInterval(pollHealth, 10000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  if (offline) {
    return (
      <div className="border-b border-amber/30 bg-amber/8">
        <div className="mx-auto max-w-[1180px] px-4 py-2 sm:px-6">
          <p className="num text-[11.5px] leading-tight text-amber">
            lab api unreachable — start it with{" "}
            <span className="text-text">uv run bacterion-api</span>
          </p>
        </div>
      </div>
    );
  }

  const checks = selftest ? `${selftest.n_checks - selftest.n_failed}/${selftest.n_checks}` : "—";

  return (
    <div className="border-b border-line bg-panel">
      <div className="mx-auto flex max-w-[1180px] items-stretch overflow-x-auto px-4 sm:px-6">
        <Item
          label="biology invariants"
          value={checks}
          tone={selftest ? (selftest.passed ? "green" : "red") : "muted"}
        />
        <Item
          label="runs in flight"
          value={health ? String(health.active_runs) : "—"}
          tone={health && health.active_runs > 0 ? "cyan" : "muted"}
        />
      </div>
    </div>
  );
}

function Item({
  label,
  value,
  tone = "muted",
}: {
  label: string;
  value: string;
  tone?: "muted" | "cyan" | "green" | "red";
}) {
  const toneClass = {
    muted: "text-muted",
    cyan: "text-cyan",
    green: "text-green",
    red: "text-red",
  }[tone];
  return (
    <div className="flex shrink-0 items-baseline gap-2 border-r border-line py-2 pr-4 last:border-r-0 sm:pr-5">
      <span className="text-[11px] text-faint">{label}</span>
      <span className={`num text-[11.5px] ${toneClass}`}>{value}</span>
    </div>
  );
}
