"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/research", label: "Research" },
  { href: "/experiments", label: "Experiments" },
  { href: "/candidates", label: "Candidates" },
  { href: "/design", label: "Design" },
  { href: "/evidence", label: "Evidence" },
  { href: "/knowledge", label: "State" },
  { href: "/agents", label: "Agents" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="sticky top-0 z-40 border-b border-line bg-ink/92 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1180px] items-center gap-6 px-4 py-3 sm:px-6">
        <Link href="/" className="group flex items-baseline gap-2">
          {/* The wordmark is set in mono: the lab's own instrument label. */}
          <span className="num text-[15px] font-medium tracking-[0.14em] text-text">
            BACTERION
          </span>
        </Link>
        <ul className="ml-auto hidden items-center gap-1 md:flex">
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={`border-b-2 px-3 py-2 text-[13px] transition-colors ${
                    active
                      ? "border-cyan text-text"
                      : "border-transparent text-muted hover:border-line-strong hover:text-text"
                  }`}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
        <Link
          href="/research"
          className="ml-auto border border-cyan/60 bg-cyan/10 px-3 py-1.5 text-[13px] text-cyan transition-colors hover:bg-cyan/18 md:ml-2"
        >
          Run discovery
        </Link>
      </div>
      {/* On small screens the section links move below the wordmark rather than
          collapsing into a menu: there are seven of them and the row scrolls. */}
      <ul className="flex items-center gap-1 overflow-x-auto border-t border-line px-2 md:hidden">
        {LINKS.map((link) => {
          const active = pathname === link.href;
          return (
            <li key={link.href}>
              <Link
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`inline-block border-b-2 px-3 py-2 text-[13px] ${
                  active ? "border-cyan text-text" : "border-transparent text-muted"
                }`}
              >
                {link.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
