import Image from "next/image";

export default function MethodologyPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 pb-20 pt-14 sm:px-6">
      <Image
        src="/branding/bactrogen-wordmark.png"
        alt="BactroGen Research"
        width={720}
        height={402}
        className="mb-8 h-auto w-full max-w-[22rem] rounded-lg bg-black object-cover"
      />
      <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Methodology</p>
      <h1 className="mt-3 text-4xl font-medium tracking-[-0.035em] text-text">Scientific boundaries</h1>
      <div className="mt-8 space-y-5 text-[14px] leading-relaxed text-muted">
        <section className="border border-line bg-panel p-5"><h2 className="text-[15px] font-medium text-text">Evidence is not prediction</h2><p className="mt-2">Published evidence, database evidence, computational simulations, model predictions, and experimental measurements remain separate provenance categories throughout the workflow.</p></section>
        <section className="border border-line bg-panel p-5"><h2 className="text-[15px] font-medium text-text">Recommendations are bounded</h2><p className="mt-2">Candidates are ranked hypotheses. A computational result does not establish biological activity and must be validated experimentally.</p></section>
        <section className="border border-line bg-panel p-5"><h2 className="text-[15px] font-medium text-text">The next experiment can change</h2><p className="mt-2">Scientific review challenges the available support before the system selects a discriminating follow-up condition. The system records uncertainty rather than silently resolving it.</p></section>
      </div>
    </main>
  );
}
