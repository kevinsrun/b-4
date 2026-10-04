import type { Metadata } from "next";
import { JetBrains_Mono, Space_Grotesk } from "next/font/google";

import { Nav } from "@/components/nav";
import { StatusRail } from "@/components/status-rail";

import "./globals.css";

const grotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-grotesk",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono-jb",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Bacterion — autonomous bacteriocin discovery",
  description:
    "An autonomous lab where specialist agents investigate bacteriocins, run simulated experiments, learn from the results and choose the next experiment.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${grotesk.variable} ${mono.variable}`}>
      <body className="min-h-screen bg-ink text-text antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-cyan focus:bg-panel focus:px-3 focus:py-2 focus:text-[13px]"
        >
          Skip to content
        </a>
        <Nav />
        <StatusRail />
        <main id="main">{children}</main>
        <footer className="mt-24 border-t border-line">
          <div className="mx-auto flex max-w-[1180px] flex-col gap-3 px-4 py-8 text-[12px] leading-relaxed text-faint sm:px-6">
            <p className="max-w-[72ch]">
              Bacterion reports three kinds of claim and never merges them:
              evidence extracted from the literature, candidates proposed for
              testing, and predictions produced by a simulator. None of them is
              an experimental result. Nothing shown here has been measured at a
              bench.
            </p>
            <p className="num text-[11px] text-faint">
              Orchestrated by Omnigent. The scientific system is the Python
              package in this repository; this interface only reads it.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
