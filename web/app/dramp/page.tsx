import { Suspense } from "react";
import { DrampWorkspace } from "@/components/dramp/dramp-workspace";

export const metadata = {
  title: "DRAMP Database Explorer | BactroGen Research",
  description:
    "Official DRAMP reference database queries, dataset provenance tracking, and curated antimicrobial peptide reference records.",
};

export default function DrampPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[1240px] px-4 py-16 text-center text-[13px] text-faint">
          Loading DRAMP reference database...
        </div>
      }
    >
      <DrampWorkspace />
    </Suspense>
  );
}
