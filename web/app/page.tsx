import { ApiError } from "@/components/ApiError";
import { ReviewQueue } from "@/components/ReviewQueue";
import { RunControls } from "@/components/RunControls";
import { StatsStrip } from "@/components/StatsStrip";
import { getQueue, getQuota, getStatsOverview } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ package?: string }>;
}) {
  const { package: focusPackageId } = await searchParams;
  const [queue, quota, stats] = await Promise.allSettled([
    getQueue(),
    getQuota(),
    getStatsOverview(),
  ]);

  if (queue.status === "rejected") {
    return <ApiError error={queue.reason} />;
  }

  const caps = quota.status === "fulfilled" ? quota.value : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.02em] text-fg">Review queue</h1>
          <p className="mt-0.5 text-sm text-muted">
            Approve, edit or reject. Nothing carrying your name leaves without a click.
          </p>
        </div>

        {caps && (
          <dl className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
            <QuotaStat
              label="submissions"
              used={caps.counters.extension_submit ?? 0}
              cap={caps.caps.extension_submit}
            />
            <QuotaStat
              label="emails"
              used={caps.counters.outbound_email ?? 0}
              cap={caps.caps.outbound_email}
            />
            <div className="flex flex-col">
              <dt className="text-2xs uppercase tracking-[0.14em] text-faint">LLM today</dt>
              <dd className="font-mono text-xs tabular-nums text-muted">
                {caps.llm_calls_today} calls
                <span className="text-edge-strong"> · </span>${caps.llm_cost_usd_today.toFixed(4)}
                {caps.llm_failures_today > 0 && (
                  <span className="ml-1.5 text-marginal">{caps.llm_failures_today} failed</span>
                )}
              </dd>
            </div>
          </dl>
        )}
      </div>

      {stats.status === "fulfilled" && <StatsStrip stats={stats.value} />}

      <RunControls />

      <ReviewQueue initial={queue.value.packages} focusPackageId={focusPackageId} />
    </div>
  );
}

function QuotaStat({ label, used, cap }: { label: string; used: number; cap: number }) {
  const ratio = cap > 0 ? Math.min(1, used / cap) : 0;
  const near = ratio >= 0.8;
  return (
    <div className="flex flex-col">
      <dt className="text-2xs uppercase tracking-[0.14em] text-faint">{label}</dt>
      <dd className="flex items-center gap-2">
        <span
          className={`font-mono text-xs tabular-nums ${near ? "text-standard" : "text-muted"}`}
        >
          {used}
          <span className="text-edge-strong">/</span>
          {cap}
        </span>
        <span aria-hidden className="h-1 w-10 overflow-hidden rounded-full bg-edge/70">
          <span
            className={`block h-full rounded-full ${near ? "bg-standard" : "bg-accent/70"}`}
            style={{ width: `${ratio * 100}%` }}
          />
        </span>
      </dd>
    </div>
  );
}
