import type { Tier } from "@/lib/types";

/**
 * §7 sets a review budget per tier. Showing it keeps the queue honest about
 * where the time is supposed to go: review capacity is the bottleneck, not
 * discovery.
 */
export const TIER_META: Record<Tier, { label: string; budget: string; dot: string; ring: string }> = {
  fast_lane: {
    label: "Fast lane",
    budget: "~10s",
    dot: "bg-fast",
    ring: "border-fast/40",
  },
  standard: {
    label: "Standard",
    budget: "~60s",
    dot: "bg-standard",
    ring: "border-standard/40",
  },
  marginal: {
    label: "Marginal",
    budget: "2–3 min",
    dot: "bg-marginal",
    ring: "border-marginal/40",
  },
};

export function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) return null;
  const meta = TIER_META[tier];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border ${meta.ring} px-2 py-0.5 text-[11px]`}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden />
      {meta.label}
      <span className="text-muted">{meta.budget}</span>
    </span>
  );
}

export function ScorePill({ score }: { score: number | null }) {
  const value = score ?? 0;
  const tone =
    value >= 85 ? "text-fast" : value >= 70 ? "text-standard" : "text-marginal";
  return (
    <span className={`font-mono text-lg font-semibold tabular-nums ${tone}`}>
      {value}
    </span>
  );
}
