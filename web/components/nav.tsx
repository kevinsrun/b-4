"use client";

import Link from "next/link";
export function Nav() {
  return (
    <nav className="sticky top-0 z-40 border-b border-line bg-ink/92 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1180px] items-center gap-6 px-4 py-3 sm:px-6">
        <Link href="/" className="group flex items-baseline gap-2">
          {/* The wordmark is set in mono: the lab's own instrument label. */}
          <span className="num text-[15px] font-medium tracking-[0.14em] text-text">
            BACTERION
          </span>
        </Link>
        <Link
          href="/research"
          className="ml-auto border border-cyan/60 bg-cyan/10 px-3 py-1.5 text-[13px] text-cyan transition-colors hover:bg-cyan/18"
        >
          Discover
        </Link>
      </div>
    </nav>
  );
}
