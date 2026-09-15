import type { Tier } from "@/lib/types";

/**
 * §7 sets a review budget per tier. Showing it keeps the queue honest about
 * where the time is supposed to go: review capacity is the bottleneck, not
 * discovery.
 */
export const TIER_META: Record<
  Tier,
  { label: string; budget: string; dot: string; ring: string; text: string; blurb: string }
> = {
  fast_lane: {
    label: "Fast lane",
    budget: "~10s",
    dot: "bg-fast",
    ring: "border-fast/40",
    text: "text-fast",
    blurb: "Clear it in one click",
  },
  standard: {
    label: "Standard",
    budget: "~60s",
    dot: "bg-standard",
    ring: "border-standard/40",
    text: "text-standard",
    blurb: "Read the diff, then decide",
  },
  marginal: {
    label: "Marginal",
    budget: "2–3 min",
    dot: "bg-marginal",
    ring: "border-marginal/40",
    text: "text-marginal",
    blurb: "Everything, including why it is doubtful",
  },
};

export function scoreTone(score: number | null): string {
  const value = score ?? 0;
  return value >= 85 ? "text-fast" : value >= 70 ? "text-standard" : "text-marginal";
}

export function scoreFill(score: number | null): string {
  const value = score ?? 0;
  return value >= 85 ? "bg-fast" : value >= 70 ? "bg-standard" : "bg-marginal";
}

export function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-edge px-2.5 py-0.5 text-2xs text-faint">
        Untiered
      </span>
    );
  }
  const meta = TIER_META[tier];
  return (
    <span
      title={meta.blurb}
      className={`inline-flex items-center gap-1.5 rounded-full border ${meta.ring} px-2.5 py-0.5 text-2xs`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden />
      <span className={meta.text}>{meta.label}</span>
      <span className="text-faint">{meta.budget}</span>
    </span>
  );
}

/** Compact score for the rail rows. */
export function ScorePill({ score }: { score: number | null }) {
  return (
    <span className={`font-mono text-base font-semibold tabular-nums ${scoreTone(score)}`}>
      {score ?? 0}
    </span>
  );
}

/**
 * The full score, with the tier thresholds marked. Those ticks are the whole
 * point: they say how close this posting is to moving lane, which is the
 * question the number is actually being asked.
 */
export function ScoreMeter({ score, className = "" }: { score: number | null; className?: string }) {
  const value = Math.max(0, Math.min(100, score ?? 0));
  return (
    <div className={`w-40 shrink-0 ${className}`}>
      <div className="flex items-baseline gap-1.5">
        <span className={`font-mono text-2xl font-semibold tabular-nums ${scoreTone(score)}`}>
          {value}
        </span>
        <span className="text-2xs uppercase tracking-[0.14em] text-faint">fit</span>
      </div>
      <div
        role="meter"
        aria-label="Fit score"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        className="relative mt-2 h-1.5 w-full overflow-hidden rounded-full bg-edge/60"
      >
        <div
          className={`h-full rounded-full transition-[width] duration-300 ease-out ${scoreFill(score)}`}
          style={{ width: `${value}%` }}
        />
        {[60, 70, 85].map((threshold) => (
          <span
            key={threshold}
            aria-hidden
            className="absolute top-0 h-full w-px bg-ink/70"
            style={{ left: `${threshold}%` }}
          />
        ))}
      </div>
    </div>
  );
}
