import Image from "next/image";
import Link from "next/link";

/**
 * The footer carries the disclosure, not the marketing. The three-claims rule
 * is the most load-bearing sentence on the site, so it stays at full body size
 * rather than shrinking into legal boilerplate.
 */
const COLUMNS = [
  {
    heading: "Research",
    links: [
      { href: "/research", label: "Discover" },
      { href: "/candidates", label: "Candidates" },
      { href: "/experiments", label: "Simulator" },
      { href: "/design", label: "Designer" },
    ],
  },
  {
    heading: "Evidence",
    links: [
      { href: "/evidence", label: "Literature evidence" },
      { href: "/knowledge", label: "Research state" },
      { href: "/benchmarks", label: "Benchmarks" },
    ],
  },
  {
    heading: "About",
    links: [
      { href: "/methodology", label: "Methodology" },
      { href: "/agents", label: "Agents" },
      { href: "/advanced", label: "Advanced console" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-line bg-panel">
      <div className="mx-auto max-w-[1180px] px-4 py-14 sm:px-6">
        <div className="grid gap-10 md:grid-cols-[minmax(0,1.5fr)_repeat(3,minmax(0,1fr))] md:gap-12">
          <div>
            <div className="flex items-center gap-2.5">
              <Image
                src="/branding/bactrogen-mark.png"
                alt=""
                width={32}
                height={32}
                className="h-7 w-7 rounded-md object-cover"
              />
              <span className="flex flex-col leading-none">
                <span className="display text-[17px] text-cyan">BactroGen</span>
                <span className="eyebrow mt-[3px] text-[8.5px] tracking-[0.3em] text-faint">
                  Research
                </span>
              </span>
            </div>
            <p className="mt-4 max-w-[34ch] text-[13.5px] leading-relaxed text-muted">
              Better molecules. Healthier tomorrows. An autonomous loop for
              bacteriocin discovery and computational antimicrobial design.
            </p>
          </div>

          {COLUMNS.map((column) => (
            <nav key={column.heading} aria-label={column.heading}>
              <h2 className="eyebrow">{column.heading}</h2>
              <ul className="mt-4 space-y-2.5">
                {column.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="rounded-[2px] text-[13.5px] text-muted transition-colors hover:text-cyan"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <div className="mt-12 border-t border-line pt-8">
          <p className="max-w-[78ch] text-[13px] leading-relaxed text-muted">
            BactroGen Research reports three kinds of claim and never merges
            them: evidence extracted from the literature, candidates proposed
            for testing, and predictions produced by a simulator. None of them
            is an experimental result.{" "}
            <strong className="font-medium text-text">
              Nothing shown here has been measured at a bench.
            </strong>
          </p>
          <p className="mt-3 max-w-[78ch] text-[12.5px] leading-relaxed text-faint">
            Computational predictions are presented with their uncertainty and
            require experimental validation.
          </p>
          <p className="num mt-6 text-[11px] text-faint">
            © {new Date().getFullYear()} BactroGen Research · Computational
            biology / Bacteriocin discovery
          </p>
        </div>
      </div>
    </footer>
  );
}
