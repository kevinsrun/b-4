import { Section } from "@/components/section";

/**
 * Why the subject is worth the machinery. Written for someone who does not
 * already know what a bacteriocin is, and kept to what is actually
 * well-established — no efficacy claims, since this system has produced none.
 */
export function WhyBacteriocins() {
  return (
    <Section
      heading="Why bacteriocins"
      standfirst="Bacteriocins are antimicrobial peptides that bacteria make to kill their competitors. Nisin has been in food preservation for decades; its relatives are studied as alternatives to conventional antibiotics."
    >
      <div className="grid gap-x-12 gap-y-8 md:grid-cols-3">
        <div className="border-t border-line pt-4">
          <h3 className="text-[14px] font-medium text-text">Narrow by design</h3>
          <p className="mt-2 max-w-[44ch] text-[13px] leading-relaxed text-muted">
            A bacteriocin typically recognises a specific receptor on a related
            species, so it can act on a target while leaving much of the
            surrounding community intact — the opposite of a broad-spectrum
            antibiotic.
          </p>
        </div>
        <div className="border-t border-line pt-4">
          <h3 className="text-[14px] font-medium text-text">The envelope decides</h3>
          <p className="mt-2 max-w-[44ch] text-[13px] leading-relaxed text-muted">
            Gram-positive targets expose the membrane a pore-former needs.
            Gram-negative targets hide it behind an outer membrane, which is why
            the gram stain changes which candidates are even plausible, and why
            this lab refuses to guess it.
          </p>
        </div>
        <div className="border-t border-line pt-4">
          <h3 className="text-[14px] font-medium text-text">The search space is large</h3>
          <p className="mt-2 max-w-[44ch] text-[13px] leading-relaxed text-muted">
            Sequence, dose, cell density, pH, temperature, salt and incubation
            time all move the outcome, and they interact. Testing that space one
            well at a time is slow, which is the case for choosing each
            experiment deliberately.
          </p>
        </div>
      </div>

      <div className="mt-10 border-t border-line pt-6">
        <p className="max-w-[80ch] text-[13.5px] leading-relaxed text-muted">
          What a simulated loop can do is narrow the space before anyone picks up
          a pipette: rank what is worth trying, state what would falsify it, and
          say which measurement would settle the question. What it cannot do is
          tell you whether a peptide works. That still takes a bench.
        </p>
      </div>
    </Section>
  );
}
