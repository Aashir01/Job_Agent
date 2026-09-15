import { ReviewQueue } from "@/components/ReviewQueue";
import { getQueue, getQuota } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ReviewPage() {
  const [queue, quota] = await Promise.allSettled([getQueue(), getQuota()]);

  if (queue.status === "rejected") {
    return (
      <div className="animate-fade-in mx-auto max-w-lg rounded-2xl border border-marginal/40 bg-marginal/[0.06] p-6">
        <h1 className="flex items-center gap-2 text-sm font-medium text-marginal">
          <span aria-hidden>!</span> Cannot reach the API
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          {queue.reason instanceof Error ? queue.reason.message : "unknown error"}
        </p>
        <p className="mt-4 border-t border-marginal/20 pt-3 text-xs text-faint">
          Check <code className="font-mono text-muted">API_URL</code> and{" "}
          <code className="font-mono text-muted">AGENT_KEY</code> in the dashboard environment.
        </p>
      </div>
    );
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

      <ReviewQueue initial={queue.value.packages} />
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
