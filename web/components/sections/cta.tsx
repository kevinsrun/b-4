"use client";

import Link from "next/link";
import { Button, LinkButton } from "@/components/interactive";

export function FinalCta({ onRun, busy }: { onRun: () => void; busy: boolean }) {
  return (
    <section className="border-t border-line bg-panel">
      <div className="mx-auto max-w-[1180px] px-4 py-16 sm:px-6">
        <div className="max-w-[52ch]">
          <h2 className="text-balance text-[28px] font-medium leading-[1.1] tracking-[-0.02em] text-text sm:text-[34px]">
            Give it an organism. Watch it decide what to test.
          </h2>
          <p className="mt-4 max-w-[58ch] text-[14.5px] leading-relaxed text-muted">
            A run takes a few seconds. You get the experiments it chose, the
            reason it chose them, the predictions with their intervals, and the
            questions it could not answer.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button
              type="button"
              onClick={onRun}
              disabled={busy}
              variant="primary"
              size="lg"
            >
              {busy ? "Discovery running…" : "Run discovery"}
            </Button>
            <LinkButton
              href="/research"
              variant="secondary"
              size="lg"
            >
              Set up a run
            </LinkButton>
            <Link
              href="/agents"
              className="px-2 py-2.5 text-[14px] text-muted underline decoration-line underline-offset-4 transition-colors hover:text-text"
            >
              How the agents divide the work
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
