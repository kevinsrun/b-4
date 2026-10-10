"use client";

/**
 * Shared motion primitives.
 *
 * Everything that moves on this site goes through one of these, so there is a
 * single place that honours prefers-reduced-motion and a single place that
 * decides when something is on screen. No component sets up its own observer
 * or media query.
 */

import { useEffect, useRef, useState, type RefObject } from "react";

/** Tracks the user's motion preference, and keeps tracking it if they change it. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

/** True once the element has been scrolled into view. It never flips back —
 *  a chart that re-animates every time it scrolls past is a distraction. */
export function useInView<T extends HTMLElement>(
  options: { rootMargin?: string; threshold?: number } = {},
): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || seen) return;

    // Without IntersectionObserver the content shows rather than hides.
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { rootMargin: options.rootMargin ?? "0px 0px -10% 0px", threshold: options.threshold ?? 0.15 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [seen, options.rootMargin, options.threshold]);

  return [ref, seen];
}

/**
 * Elapsed seconds since `from`, ticking while `active`.
 *
 * This is the honest alternative to a progress bar for a call that reports no
 * progress: it says how long the work has actually been running, and claims
 * nothing about how far along it is.
 */
export function useElapsed(active: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const start = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      start.current = null;
      setElapsed(0);
      return;
    }
    start.current = Date.now();
    setElapsed(0);
    // One tick a second: enough to show the clock moving, cheap enough to
    // leave running for the length of a discovery call.
    const timer = window.setInterval(() => {
      if (start.current !== null) {
        setElapsed(Math.floor((Date.now() - start.current) / 1000));
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  return elapsed;
}

/**
 * The pre-Clipboard-API copy path: a selected, off-screen textarea plus
 * `execCommand`. Deprecated, but it is the only thing that works when the
 * async API is unavailable, and it is synchronous so it stays inside the user
 * gesture that triggered it.
 */
function legacyCopy(text: string): boolean {
  try {
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    // Off-screen rather than hidden: a display:none field cannot be selected.
    field.style.cssText = "position:fixed;top:-1000px;left:-1000px;opacity:0;";
    document.body.appendChild(field);
    field.select();
    field.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    field.remove();
    return ok;
  } catch {
    return false;
  }
}

/**
 * Copy-to-clipboard with a short confirmation window.
 *
 * Returns the handler and whether the confirmation is showing, so the caller
 * can swap a label or an icon without owning a timer.
 */
export function useCopy(resetAfter = 1800): {
  copied: boolean;
  failed: boolean;
  copy: (text: string) => Promise<void>;
} {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = async (text: string) => {
    if (timer.current) window.clearTimeout(timer.current);

    let done = false;
    try {
      await navigator.clipboard.writeText(text);
      done = true;
    } catch {
      // The async Clipboard API is refused on insecure origins, inside some
      // embeds, and wherever the permission is denied. A selected textarea and
      // the legacy copy command still work in those cases, and a sequence a
      // reader cannot copy is a real loss — so fall back rather than give up.
      done = legacyCopy(text);
    }

    setCopied(done);
    setFailed(!done);
    timer.current = window.setTimeout(() => {
      setCopied(false);
      setFailed(false);
    }, resetAfter);
  };

  return { copied, failed, copy };
}
