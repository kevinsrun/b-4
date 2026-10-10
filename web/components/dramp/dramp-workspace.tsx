"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { checkBackendConnection } from "@/lib/amp-api";
import { DrampTab } from "@/components/amp/dramp-tab";
import Link from "next/link";
import { ArrowLeft, Database, ExternalLink } from "lucide-react";

export function DrampWorkspace() {
  const router = useRouter();
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [useFixtures, setUseFixtures] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | undefined>();
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    async function init() {
      setIsChecking(true);
      try {
        const conn = await checkBackendConnection();
        setIsBackendConnected(conn.connected);
        setLatencyMs(conn.latencyMs);
      } catch {
        setIsBackendConnected(false);
      } finally {
        setIsChecking(false);
      }
    }
    init();
  }, []);

  const handleSendToPredictor = (sequenceId: string, sequence: string) => {
    // Navigate to AMP workspace with sequence data pre-populated
    router.push(`/amp?sequenceId=${encodeURIComponent(sequenceId)}&sequence=${encodeURIComponent(sequence)}`);
  };

  return (
    <main className="mx-auto max-w-[1240px] px-4 py-8 sm:px-6">
      {/* Top Banner & Context Breadcrumb */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        <div className="flex items-center gap-3">
          <Link
            href="/research"
            className="pressable inline-flex items-center gap-1.5 rounded-[3px] border border-line bg-panel px-2.5 py-1 text-[12px] font-medium text-muted hover:text-text"
          >
            <ArrowLeft size={13} />
            <span>Dashboard</span>
          </Link>
          <span className="text-[12px] text-faint">/</span>
          <span className="text-[12px] font-medium text-text">DRAMP Reference Explorer</span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-[3px] border border-line bg-panel px-3 py-1 text-[12px]">
            <span
              className={`h-2 w-2 rounded-full ${
                isBackendConnected ? "bg-emerald-500" : "bg-amber-500"
              }`}
            />
            <span className="text-muted">
              {isChecking
                ? "Checking API..."
                : isBackendConnected
                ? `FastAPI Connected (${latencyMs ?? 0}ms)`
                : "Fixture Mode (Offline Contract)"}
            </span>
          </div>

          <Link
            href="/amp"
            className="pressable inline-flex items-center gap-1.5 rounded-[3px] bg-sage-soft px-3 py-1 text-[12px] font-medium text-cyan hover:bg-raised"
          >
            <span>Go to AMP Lab</span>
            <ExternalLink size={12} />
          </Link>
        </div>
      </div>

      {/* Main DRAMP Component */}
      <div className="rounded-[4px] border border-line bg-panel p-6 shadow-sm">
        <DrampTab
          isBackendConnected={isBackendConnected}
          useFixtures={useFixtures || !isBackendConnected}
          onSendToPredictor={handleSendToPredictor}
        />
      </div>
    </main>
  );
}
