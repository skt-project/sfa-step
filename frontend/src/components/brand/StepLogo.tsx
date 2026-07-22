import { useId } from "react";

interface StepLogoProps {
  /** Rendered pixel size of the square mark. */
  size?: number;
  /** Render the rounded gradient tile behind the glyph (app-icon style). */
  container?: boolean;
  className?: string;
  /** Accessible label; set "" to mark decorative when a text logotype sits beside it. */
  title?: string;
}

/**
 * STEP product mark — three ascending steps rising to a checkpoint.
 * Communicates: Step of the Call · progress · route · achievement.
 *
 * `container` on  → white glyph inside a Skintific-blue gradient tile (sidebar,
 *                   login, favicon, launcher).
 * `container` off → gradient glyph on a transparent background (on light surfaces).
 */
export function StepLogo({ size = 40, container = true, className = "", title = "STEP" }: StepLogoProps) {
  const uid = useId().replace(/:/g, "");
  const tile = `step-tile-${uid}`;
  const glyph = `step-glyph-${uid}`;
  const decorative = title === "";

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      role={decorative ? "presentation" : "img"}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : title}
    >
      <defs>
        <linearGradient id={tile} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#7ccbff" />
          <stop offset="55%" stopColor="#5cb8ff" />
          <stop offset="100%" stopColor="#2884d1" />
        </linearGradient>
        <linearGradient id={glyph} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#2884d1" />
          <stop offset="100%" stopColor="#5cb8ff" />
        </linearGradient>
      </defs>

      {container && <rect x="0" y="0" width="40" height="40" rx="11" fill={`url(#${tile})`} />}

      {/* three ascending steps */}
      <g fill={container ? "#ffffff" : `url(#${glyph})`}>
        <rect x="9" y="23" width="6" height="8" rx="3" />
        <rect x="17" y="17" width="6" height="14" rx="3" />
        <rect x="25" y="11" width="6" height="20" rx="3" />
      </g>

      {/* checkpoint / outlet pin above the tallest step */}
      <circle cx="28" cy="8" r="3" fill={container ? "#ffffff" : "#5cb8ff"} />
    </svg>
  );
}

export default StepLogo;
