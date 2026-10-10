"use client";

/**
 * A full-bleed scientific illustration behind a band of content.
 *
 * These are rendered artwork, not data: they depict a peptide-like cluster near
 * a membrane, and they are captioned as decorative wherever they could be
 * mistaken for a result. Nothing about them is derived from a run.
 *
 * The image goes through next/image, so it is served as AVIF/WebP at a size
 * matched to the viewport rather than as a 1.8MB PNG.
 */

import Image from "next/image";
import { useEffect, useRef } from "react";

import { usePrefersReducedMotion } from "@/lib/motion";

export function Scene({
  src,
  priority = false,
  position = "right center",
  /** How far the artwork drifts with the pointer, in pixels. Kept tiny: this
   *  is a suggestion of depth, not a parallax showpiece. */
  drift = 10,
  className = "",
  scrim = "left",
}: {
  src: string;
  priority?: boolean;
  position?: string;
  drift?: number;
  className?: string;
  scrim?: "left" | "center" | "none";
}) {
  const layer = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const node = layer.current;
    if (!node || reduced || drift <= 0) return;

    // Pointer parallax only where there is a real pointer. On touch this would
    // either never fire or fight the scroll.
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    if (!fine.matches) return;

    let frame = 0;
    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        // Normalised to [-1, 1] across the viewport, then scaled to `drift`.
        const x = (event.clientX / window.innerWidth - 0.5) * 2;
        const y = (event.clientY / window.innerHeight - 0.5) * 2;
        node.style.transform = `translate3d(${(-x * drift).toFixed(2)}px, ${(-y * drift * 0.6).toFixed(2)}px, 0) scale(1.04)`;
      });
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
    };
  }, [reduced, drift]);

  const scrimClass = {
    // The text sits on the left, so the vanilla wash is heaviest there and
    // clears away over the artwork.
    left: "bg-[linear-gradient(100deg,var(--color-ink)_0%,var(--color-ink)_30%,color-mix(in_srgb,var(--color-ink)_72%,transparent)_52%,transparent_82%)]",
    center:
      "bg-[radial-gradient(ellipse_70%_60%_at_50%_45%,var(--color-ink)_0%,color-mix(in_srgb,var(--color-ink)_82%,transparent)_45%,transparent_78%)]",
    none: "",
  }[scrim];

  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
    >
      <div
        ref={layer}
        className="absolute inset-0 will-change-transform"
        style={{ transform: "scale(1.04)", transition: "transform 400ms var(--ease)" }}
      >
        <Image
          src={src}
          alt=""
          fill
          priority={priority}
          sizes="100vw"
          className="object-cover"
          style={{ objectPosition: position }}
        />
      </div>
      {scrim !== "none" && <div className={`absolute inset-0 ${scrimClass}`} />}
    </div>
  );
}
