"use client";

import Link from "next/link";
import Image from "next/image";

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
        <Link href="/" className="group flex items-center gap-2.5">
          <Image
            src="/branding/bactrogen-mark.png"
            alt=""
            width={30}
            height={30}
            className="h-7 w-7 rounded-md object-cover"
            priority
          />
          <span className="text-[14px] font-medium tracking-[-0.01em] text-text sm:text-[15px]">
            BactroGen <span className="text-cyan">Research</span>
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
