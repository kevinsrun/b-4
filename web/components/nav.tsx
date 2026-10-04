"use client";

import Link from "next/link";

const LINKS = [
  { href: "/research", label: "Discover" },
  { href: "/research#discovery-results", label: "Results" },
  { href: "/advanced", label: "Advanced" },
  { href: "/methodology", label: "Methodology" },
];

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
        <div className="ml-auto flex items-center gap-1 overflow-x-auto">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="whitespace-nowrap px-2.5 py-1.5 text-[12px] text-muted transition-colors hover:text-text sm:px-3 sm:text-[13px]"
            >
              {link.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
