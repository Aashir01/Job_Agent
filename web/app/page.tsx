import { ReviewQueue } from "@/components/ReviewQueue";
import { getQueue, getQuota } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ReviewPage() {
  const [queue, quota] = await Promise.allSettled([getQueue(), getQuota()]);

  if (queue.status === "rejected") {
    return (
      <div className="rounded-xl border border-marginal/40 bg-marginal/5 p-6">
        <h1 className="text-sm font-medium text-marginal">Cannot reach the API</h1>
        <p className="mt-1 text-sm text-muted">
          {queue.reason instanceof Error ? queue.reason.message : "unknown error"}
        </p>
        <p className="mt-2 text-xs text-muted">
          Check <code className="font-mono">API_URL</code> and{" "}
          <code className="font-mono">AGENT_KEY</code> in the dashboard environment.
        </p>
      </div>
    );
  }

  const caps = quota.status === "fulfilled" ? quota.value : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Review queue</h1>
        {caps && (
          <p className="text-xs text-muted">
            today: {caps.counters.extension_submit ?? 0}/{caps.caps.extension_submit} submissions ·{" "}
            {caps.counters.outbound_email ?? 0}/{caps.caps.outbound_email} emails ·{" "}
            {caps.llm_calls_today} LLM calls (${caps.llm_cost_usd_today.toFixed(4)})
          </p>
        )}
      </div>
      <ReviewQueue initial={queue.value.packages} />
    </div>
  );
}
