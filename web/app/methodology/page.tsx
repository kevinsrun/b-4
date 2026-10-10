export default function MethodologyPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 pb-20 pt-14 sm:px-6">
      <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Methodology</p>
      <h1 className="display display-lg mt-4 text-balance text-cyan">Scientific boundaries</h1>
      <div className="mt-8 space-y-5 text-[14px] leading-relaxed text-muted">
        <section className="rounded-[4px] border border-line bg-panel p-5"><h2 className="text-[15px] font-medium text-text">Evidence is not prediction</h2><p className="mt-2">Published evidence, database evidence, computational simulations, model predictions, and experimental measurements remain separate provenance categories throughout the workflow.</p></section>
        <section className="rounded-[4px] border border-line bg-panel p-5"><h2 className="text-[15px] font-medium text-text">Recommendations are bounded</h2><p className="mt-2">Candidates are ranked hypotheses. A computational result does not establish biological activity and must be validated experimentally.</p></section>
        <section className="rounded-[4px] border border-line bg-panel p-5"><h2 className="text-[15px] font-medium text-text">The next experiment can change</h2><p className="mt-2">Scientific review challenges the available support before the system selects a discriminating follow-up condition. The system records uncertainty rather than silently resolving it.</p></section>
      </div>
    </main>
  );
}
