"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Menu, X } from "lucide-react";

import { LinkButton, useRipple } from "@/components/interactive";

/**
 * Every entry here resolves to a real route under app/. The primary row holds
 * the five stages of the discovery workflow; the rest of the product sits in a
 * labelled menu rather than being dropped from the navigation, so nothing
 * becomes unreachable.
 */
const PRIMARY = [
  { href: "/research", label: "Discover" },
  { href: "/sequencing", label: "Sequencing" },
  { href: "/amp", label: "AMP Lab" },
  { href: "/candidates", label: "Candidates" },
  { href: "/experiments", label: "Simulator" },
  { href: "/evidence", label: "Evidence" },
  { href: "/methodology", label: "Methodology" },
];

const MORE = [
  { href: "/design", label: "Designer", hint: "Sequence design workspace" },
  { href: "/knowledge", label: "Research state", hint: "Hypotheses and the event log" },
  { href: "/agents", label: "Agents", hint: "The specialists and their contracts" },
  { href: "/advanced", label: "Advanced console", hint: "Direct tool access" },
  { href: "/benchmarks", label: "Benchmarks", hint: "Simulator calibration" },
];

const ALL = [...PRIMARY, ...MORE];

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  const ripple = useRipple<HTMLAnchorElement>();
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      {...ripple}
      className={`ripple-host pressable relative rounded-[3px] px-3 py-1.5 text-[13px] font-medium whitespace-nowrap ${
        active
          ? "bg-sage-soft text-cyan"
          : "text-muted hover:bg-raised/70 hover:text-text"
      }`}
    >
      {label}
      {/* The active route carries a weight change and a fill as well as the
          underline, so it is not signalled by colour alone. */}
      {active && (
        <span className="absolute inset-x-3 -bottom-[7px] h-[2px] rounded-full bg-cyan" />
      )}
    </Link>
  );
}

export function Nav() {
  const pathname = usePathname() ?? "/";
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Any navigation closes both surfaces, so a link never leaves a panel open
  // over the page it just loaded.
  useEffect(() => {
    setMenuOpen(false);
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (event: globalThis.PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const moreActive = MORE.some((link) => isActive(pathname, link.href));

  return (
    <nav className="sticky top-0 z-40 border-b border-line bg-ink/88 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1180px] items-center gap-4 px-4 py-3 sm:px-6">
        <Link
          href="/"
          className="group flex shrink-0 items-center gap-2.5 rounded-[3px] pressable"
        >
          <Image
            src="/branding/bactrogen-mark.png"
            alt=""
            width={32}
            height={32}
            className="h-7 w-7 rounded-md object-cover"
            priority
          />
          <span className="flex flex-col leading-none">
            <span className="display text-[17px] text-cyan">BactroGen</span>
            <span className="eyebrow mt-[3px] text-[8.5px] tracking-[0.3em] text-faint">
              Research
            </span>
          </span>
        </Link>

        {/* Desktop navigation */}
        <div className="ml-auto hidden items-center gap-0.5 lg:flex">
          {PRIMARY.map((link) => (
            <NavLink
              key={link.href}
              href={link.href}
              label={link.label}
              active={isActive(pathname, link.href)}
            />
          ))}

          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              className={`pressable inline-flex items-center gap-1 rounded-[3px] px-3 py-1.5 text-[13px] font-medium ${
                moreActive || menuOpen
                  ? "bg-sage-soft text-cyan"
                  : "text-muted hover:bg-raised/70 hover:text-text"
              }`}
            >
              More
              <ChevronDown
                size={14}
                className={`transition-transform duration-200 ${menuOpen ? "rotate-180" : ""}`}
                aria-hidden
              />
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="reveal absolute right-0 top-[calc(100%+10px)] w-[270px] rounded-[4px] border border-line bg-panel p-1.5 shadow-[var(--shadow-lg)]"
              >
                {MORE.map((link) => {
                  const active = isActive(pathname, link.href);
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      role="menuitem"
                      aria-current={active ? "page" : undefined}
                      className={`block rounded-[3px] px-3 py-2 transition-colors ${
                        active ? "bg-sage-soft" : "hover:bg-raised/70"
                      }`}
                    >
                      <span
                        className={`block text-[13px] font-medium ${
                          active ? "text-cyan" : "text-text"
                        }`}
                      >
                        {link.label}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] leading-snug text-faint">
                        {link.hint}
                      </span>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>

          <LinkButton href="/research" variant="primary" size="sm" className="ml-3">
            Explore research
          </LinkButton>
        </div>

        {/* Mobile trigger */}
        <button
          type="button"
          onClick={() => setMobileOpen((open) => !open)}
          aria-expanded={mobileOpen}
          aria-controls="mobile-nav"
          className="pressable ml-auto inline-flex items-center gap-2 rounded-[3px] border border-line bg-panel px-3 py-1.5 text-[13px] font-medium text-text lg:hidden"
        >
          {mobileOpen ? <X size={15} aria-hidden /> : <Menu size={15} aria-hidden />}
          <span>Menu</span>
        </button>
      </div>

      {mobileOpen && (
        <div
          id="mobile-nav"
          className="border-t border-line bg-panel lg:hidden"
        >
          <div className="mx-auto max-w-[1180px] px-4 py-3 sm:px-6">
            <ul className="grid gap-0.5">
              {ALL.map((link) => {
                const active = isActive(pathname, link.href);
                return (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      aria-current={active ? "page" : undefined}
                      className={`flex items-center justify-between rounded-[3px] px-3 py-2.5 text-[14px] transition-colors ${
                        active
                          ? "bg-sage-soft font-medium text-cyan"
                          : "text-muted hover:bg-raised/70 hover:text-text"
                      }`}
                    >
                      {link.label}
                      {active && <span className="h-1.5 w-1.5 rounded-full bg-cyan" />}
                    </Link>
                  </li>
                );
              })}
            </ul>
            <LinkButton
              href="/research"
              variant="primary"
              size="md"
              className="mt-3 w-full"
            >
              Explore research
            </LinkButton>
          </div>
        </div>
      )}
    </nav>
  );
}
