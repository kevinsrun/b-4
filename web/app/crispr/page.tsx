import { Suspense } from "react";
import { CrisprWorkspace } from "@/components/crispr/crispr-workspace";

export const metadata = {
  title: "CRISPR Research & Sequence Variant Explorer | BactroGen Research",
  description:
    "Scientific CRISPR research workspace for sequence coordinate analysis, locus variant comparison, PAM/target region annotations, and evidence documentation.",
};

export default function CrisprPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[1240px] px-4 py-16 text-center text-[13px] text-faint">
          Loading CRISPR research workspace...
        </div>
      }
    >
      <CrisprWorkspace />
    </Suspense>
  );
}
