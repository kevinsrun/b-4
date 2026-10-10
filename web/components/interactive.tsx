"use client";

/**
 * The interaction layer: one ripple implementation, one press behaviour, one
 * set of button shapes. Nothing else on the site animates a click.
 *
 * The ripple is deliberately damped — a research tool should feel responsive,
 * not playful. It is a single translucent forest circle expanding from the
 * pointer and fading out in 460ms, clipped to the control's own border radius.
 */

import {
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  type ButtonHTMLAttributes,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import Link from "next/link";

function prefersReducedMotion() {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Attaches a ripple to whatever element the returned handlers are spread onto.
 *
 * Pointer events cover mouse, touch and pen in one handler, so there is no way
 * to get two ripples from a single press. Keyboard activation arrives as a
 * click with `detail === 0` — a real pointer click always reports 1 or more —
 * and that one starts from the centre, since there are no coordinates.
 */
export function useRipple<T extends HTMLElement>() {
  const spans = useRef<Set<HTMLSpanElement>>(new Set());

  useEffect(() => {
    const live = spans.current;
    return () => {
      live.forEach((span) => span.remove());
      live.clear();
    };
  }, []);

  const spawn = useCallback((host: T, x: number | null, y: number | null) => {
    if (prefersReducedMotion()) return;

    const rect = host.getBoundingClientRect();
    const originX = x ?? rect.width / 2;
    const originY = y ?? rect.height / 2;

    // Radius reaches the furthest corner, so the ripple always covers the
    // whole control however off-centre the press was.
    const radius = Math.hypot(
      Math.max(originX, rect.width - originX),
      Math.max(originY, rect.height - originY),
    );

    const span = document.createElement("span");
    span.className = "ripple";
    span.style.width = span.style.height = `${radius * 2}px`;
    span.style.left = `${originX - radius}px`;
    span.style.top = `${originY - radius}px`;

    const remove = () => {
      span.remove();
      spans.current.delete(span);
    };
    span.addEventListener("animationend", remove, { once: true });
    // Belt and braces: if the animation never fires (background tab, interrupted
    // paint) the span would otherwise sit on the control forever.
    window.setTimeout(remove, 800);

    spans.current.add(span);
    host.appendChild(span);
  }, []);

  const onPointerDown = useCallback(
    (event: PointerEvent<T>) => {
      // Primary button / primary touch only — a right-click is not an activation.
      if (event.button !== 0) return;
      const host = event.currentTarget;
      const rect = host.getBoundingClientRect();
      spawn(host, event.clientX - rect.left, event.clientY - rect.top);
    },
    [spawn],
  );

  const onClick = useCallback(
    (event: MouseEvent<T>) => {
      if (event.detail === 0) spawn(event.currentTarget, null, null);
    },
    [spawn],
  );

  return { onPointerDown, onClick };
}

/* -------------------------------------------------------------------------- */

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

/**
 * Sage is a fill, never a text colour: primary buttons put deep forest text on
 * sage, which clears AA comfortably, rather than white on sage, which does not.
 */
const VARIANTS: Record<Variant, string> = {
  primary:
    "border border-sage-deep bg-sage text-cyan hover:bg-sage-deep hover:border-cyan/40 shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-md)] disabled:border-line disabled:bg-raised disabled:text-faint disabled:shadow-none",
  secondary:
    "border border-line bg-panel text-text hover:border-line-strong hover:bg-raised/60 disabled:bg-transparent disabled:text-faint",
  ghost:
    "border border-transparent bg-transparent text-muted hover:bg-raised/70 hover:text-text disabled:text-faint",
  danger:
    "border border-red/45 bg-red/8 text-red hover:bg-red/14 hover:border-red/60 disabled:border-line disabled:bg-transparent disabled:text-faint",
};

const SIZES: Record<Size, string> = {
  sm: "px-3 py-1.5 text-[12.5px] gap-1.5",
  md: "px-4 py-2 text-[13.5px] gap-2",
  lg: "px-5 py-2.5 text-[14.5px] gap-2",
};

const BASE =
  "ripple-host pressable inline-flex shrink-0 items-center justify-center rounded-[3px] font-medium leading-none disabled:cursor-not-allowed";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className = "", onPointerDown, onClick, ...rest },
  ref,
) {
  const ripple = useRipple<HTMLButtonElement>();
  return (
    <button
      ref={ref}
      // The ripple runs first and never calls preventDefault, so submission,
      // navigation and the caller's own handler all behave exactly as before.
      onPointerDown={(event) => {
        if (!rest.disabled) ripple.onPointerDown(event);
        onPointerDown?.(event);
      }}
      onClick={(event) => {
        if (!rest.disabled) ripple.onClick(event);
        onClick?.(event);
      }}
      className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    />
  );
});

/** The same shapes, for navigation. */
export function LinkButton({
  href,
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...rest
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const ripple = useRipple<HTMLAnchorElement>();
  const external = href.startsWith("http") || href.startsWith("#");
  const classes = `${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`;

  if (external) {
    return (
      <a href={href} className={classes} {...ripple} {...rest}>
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={classes} {...ripple} {...rest}>
      {children}
    </Link>
  );
}

/** A square control carrying only an icon. `label` is required — it is the
 *  element's entire accessible name. */
export function IconButton({
  label,
  size = "md",
  variant = "ghost",
  className = "",
  onPointerDown,
  onClick,
  children,
  ...rest
}: {
  label: string;
  size?: Size;
  variant?: Variant;
  children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const ripple = useRipple<HTMLButtonElement>();
  const box = { sm: "h-7 w-7", md: "h-8 w-8", lg: "h-10 w-10" }[size];
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onPointerDown={(event) => {
        if (!rest.disabled) ripple.onPointerDown(event);
        onPointerDown?.(event);
      }}
      onClick={(event) => {
        if (!rest.disabled) ripple.onClick(event);
        onClick?.(event);
      }}
      className={`${BASE} ${VARIANTS[variant]} ${box} rounded-[3px] p-0 ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/* -------------------------------------------------------------------------- */

/**
 * A magnetic call-to-action: the button leans a few pixels toward the pointer.
 *
 * Reserved for the one or two large desktop CTAs — applied broadly it makes a
 * page feel unstable and makes small controls hard to hit. It is off entirely
 * for coarse pointers and for reduced motion, and the translation is capped at
 * 6px so the hit target never runs away from the cursor.
 */
export function Magnetic({
  children,
  strength = 0.22,
  max = 6,
  className = "",
}: {
  children: ReactNode;
  strength?: number;
  max?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const host = ref.current;
    if (!host) return;

    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!fine.matches || still.matches) return;

    let frame = 0;
    const clamp = (n: number) => Math.max(-max, Math.min(max, n));

    const move = (event: globalThis.PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = host.getBoundingClientRect();
        const dx = clamp((event.clientX - (rect.left + rect.width / 2)) * strength);
        const dy = clamp((event.clientY - (rect.top + rect.height / 2)) * strength);
        host.style.transform = `translate3d(${dx}px, ${dy}px, 0)`;
      });
    };

    const reset = () => {
      cancelAnimationFrame(frame);
      host.style.transform = "";
    };

    host.addEventListener("pointermove", move);
    host.addEventListener("pointerleave", reset);
    // A focused control must sit where the keyboard user expects it.
    host.addEventListener("focusout", reset, true);
    return () => {
      cancelAnimationFrame(frame);
      host.removeEventListener("pointermove", move);
      host.removeEventListener("pointerleave", reset);
      host.removeEventListener("focusout", reset, true);
    };
  }, [strength, max]);

  return (
    <span
      ref={ref}
      className={`inline-block transition-transform duration-200 ease-[var(--ease)] ${className}`}
    >
      {children}
    </span>
  );
}
