import { Suspense } from "react";
import { ProjectsWorkspace } from "@/components/projects/projects-workspace";

export const metadata = {
  title: "Projects & Samples | BactroGen Research",
  description:
    "Unified project workspace connecting biological samples, sequencing runs, annotated sequences, AMP prediction, and CRISPR study records.",
};

export default function ProjectsPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[1240px] px-4 py-16 text-center text-[13px] text-faint">
          Loading project workspace...
        </div>
      }
    >
      <ProjectsWorkspace />
    </Suspense>
  );
}
