import { SequencingWorkspace } from "@/components/sequencing/sequencing-workspace";

export const metadata = {
  title: "Universal Sequencing Integration | BactroGen Research",
  description:
    "Universal sequencing integration connecting Illumina BaseSpace, Oxford Nanopore MinKNOW, PacBio SMRT Link, and laboratory drop folders to automated bacteriocin discovery pipelines.",
};

export default function SequencingPage() {
  return <SequencingWorkspace />;
}
