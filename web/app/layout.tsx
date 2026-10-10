import type { Metadata } from "next";
import { DM_Serif_Display, Inter, JetBrains_Mono } from "next/font/google";

import { Nav } from "@/components/nav";
import { SiteFooter } from "@/components/site-footer";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const serif = DM_Serif_Display({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-serif-dm",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono-jb",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: "BactroGen Research",
  description:
    "Autonomous AI for bacteriocin discovery and computational antimicrobial design.",
  icons: {
    icon: "/branding/bactrogen-favicon.png",
    apple: "/branding/apple-icon.png",
  },
  openGraph: {
    title: "BactroGen Research",
    description: "Autonomous AI for bacteriocin discovery and computational antimicrobial design.",
    images: ["/branding/bactrogen-wordmark.png"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${serif.variable} ${mono.variable}`}>
      <body className="min-h-screen bg-ink text-text antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-[3px] focus:border focus:border-cyan focus:bg-panel focus:px-3 focus:py-2 focus:text-[13px] focus:text-text"
        >
          Skip to content
        </a>
        <Nav />
        <main id="main">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
