import type { ReactNode } from "react";

/**
 * Sections are separated by a hairline and vertical rhythm, not by card
 * borders. The heading sits in a left column with its standfirst so the eye
 * has one entry point per band of content.
 */
export function Section({
  id,
  heading,
  standfirst,
  aside,
  children,
  wide = false,
}: {
  id?: string;
  heading: ReactNode;
  standfirst?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
  wide?: boolean;
}) {
  return (
    <section id={id} className="border-t border-line">
      <div className={`mx-auto px-4 py-14 sm:px-6 ${wide ? "max-w-[1180px]" : "max-w-[1180px]"}`}>
        <header className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="max-w-[46ch]">
            <h2 className="text-balance text-[26px] font-medium leading-[1.15] tracking-[-0.015em] text-text sm:text-[30px]">
              {heading}
            </h2>
            {standfirst && (
              <p className="mt-3 max-w-[58ch] text-[14px] leading-relaxed text-muted">{standfirst}</p>
            )}
          </div>
          {aside && <div className="shrink-0">{aside}</div>}
        </header>
        {children}
      </div>
    </section>
  );
}
