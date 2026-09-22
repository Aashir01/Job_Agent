import { usd } from "@/lib/format";
import type { StatsOverview } from "@/lib/types";

import { Sparkline } from "./Sparkline";
import { TIER_META } from "./Tier";

const TIER_ORDER = ["fast_lane", "standard", "marginal"] as const;

/**
 * The home page's situational strip: what is waiting, what is moving, and
 * what the machine spent. One row of modules, each answering one question.
 */
export function StatsStrip({ stats }: { stats: StatsOverview }) {
  // The dashboard and the API deploy to different hosts, independently, so
  // there is always a window where one is newer than the other. This strip is
  // decoration; the review queue underneath it is the product. Read every
  // field defensively so a shape that arrived from a lagging API degrades the
  // ribbon instead of blanking the page.
  const daily = stats.llm_daily ?? [];
  const funnel = stats.funnel ?? {};
  const queue = stats.queue ?? { total: 0, by_tier: {} };
  const byTier = queue.by_tier ?? {};
  const decisions = stats.decisions_30d ?? {};

  const today = daily[daily.length - 1];
  const approved = decisions["approved"] ?? 0;
  const rejected = decisions["rejected"] ?? 0;
  const decided = approved + rejected;
  const replied =
    (funnel["replied"] ?? 0) + (funnel["screen"] ?? 0) +
    (funnel["interview"] ?? 0) + (funnel["offer"] ?? 0);

  return (
    <section
      aria-label="Overview"
      className="grid grid-cols-2 divide-y divide-edge overflow-hidden rounded-xl border
                 border-edge bg-panel/60 shadow-panel sm:grid-cols-4 sm:divide-y-0"
    >
      <Module label="In the queue">
        <p className="font-mono text-xl font-semibold tabular-nums text-fg">
          {queue.total ?? 0}
        </p>
        <p className="mt-0.5 flex items-center gap-2 text-2xs text-muted">
          {TIER_ORDER.map((tier) =>
            byTier[tier] ? (
              <span key={tier} className="flex items-center gap-1">
                <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${TIER_META[tier].dot}`} />
                {byTier[tier]}
              </span>
            ) : null,
          )}
          {!queue.total && <span className="text-faint">clear</span>}
        </p>
      </Module>

      <Module label="Outreach due">
        <p
          className={`font-mono text-xl font-semibold tabular-nums ${
            (stats.outreach_due ?? 0) > 0 ? "text-standard" : "text-fg"
          }`}
        >
          {stats.outreach_due ?? 0}
        </p>
        <p className="mt-0.5 text-2xs text-muted">
          {(stats.outreach_due ?? 0) > 0 ? (
            <a href="/outreach" className="text-accent hover:underline">
              review follow-ups
            </a>
          ) : (
            "nothing waiting"
          )}
        </p>
      </Module>

      <Module label="Applications">
        <p className="font-mono text-xl font-semibold tabular-nums text-fg">
          {stats.applications_total ?? 0}
        </p>
        <p className="mt-0.5 text-2xs text-muted">
          {replied > 0 ? (
            <span className="text-fast">{replied} answered</span>
          ) : (
            <span className="text-faint">none answered yet</span>
          )}
        </p>
      </Module>

      <Module label="LLM spend, 14 days">
        <div className="flex items-end justify-between gap-2">
          <div>
            <p className="font-mono text-xl font-semibold tabular-nums text-fg">
              {usd(today?.cost_usd ?? 0)}
            </p>
            <p className="mt-0.5 text-2xs text-muted">
              {today?.calls ?? 0} calls today
              {decided > 0 && (
                <span className="text-faint">
                  {" "}
                  · {Math.round((approved / decided) * 100)}% approved
                </span>
              )}
            </p>
          </div>
          <Sparkline
            values={daily.map((point) => point.cost_usd)}
            label={`Daily LLM cost for the last 14 days, latest ${usd(today?.cost_usd ?? 0)}`}
          />
        </div>
      </Module>
    </section>
  );
}

function Module({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="px-4 py-3 sm:border-l sm:border-edge sm:first:border-l-0">
      <p className="text-2xs uppercase tracking-[0.14em] text-faint">{label}</p>
      <div className="mt-1">{children}</div>
    </div>
  );
}
