import { ApiError } from "@/components/ApiError";
import { AutoRefresh } from "@/components/AutoRefresh";
import { StatusBadge } from "@/components/BatchStatus";
import { getBatches } from "@/lib/api";
import { dateTime, elapsed, relativeTime, usd } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "job-agent — batches",
};

export default async function BatchesPage() {
  const result = await getBatches(30).catch((error: unknown) => error as Error);

  if (result instanceof Error) {
    return <ApiError error={result} />;
  }

  const batches = result.batches;
  const anyRunning = batches.some((batch) => batch.status === "running");

  return (
    <div className="space-y-5">
      <AutoRefresh active={anyRunning} />

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.02em] text-fg">Batches</h1>
          <p className="mt-0.5 text-sm text-muted">
            Every pipeline run: what it found, what it killed, what it cost.
          </p>
        </div>
        <p className="font-mono text-xs tabular-nums text-faint">
          {batches.length} {batches.length === 1 ? "run" : "runs"}
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-edge bg-panel/60 shadow-panel">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left">
                {["Started", "Kind", "Status", "Packages", "Gatekept", "Score kills", "LLM", "Cost", "Duration"].map(
                  (head) => (
                    <th
                      key={head}
                      scope="col"
                      className="px-4 py-2.5 text-2xs font-medium uppercase tracking-[0.12em] text-faint"
                    >
                      {head}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => {
                const stats = batch.stats ?? {};
                return (
                  <tr
                    key={batch.id}
                    className="border-b border-edge/50 transition-colors duration-150
                               last:border-0 hover:bg-raised/50"
                  >
                    <td className="whitespace-nowrap px-4 py-3">
                      <a
                        href={`/batches/${batch.id}`}
                        className="text-fg/90 transition-colors duration-150 hover:text-accent"
                        title={dateTime(batch.started_at)}
                      >
                        {relativeTime(batch.started_at)}
                      </a>
                    </td>
                    <td className="px-4 py-3 text-muted">{batch.kind}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={batch.status} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs tabular-nums text-fg/90">
                      {stats.packages_built ?? 0}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs tabular-nums text-muted">
                      {stats.killed_by_gatekeeper ?? 0}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs tabular-nums text-muted">
                      {stats.killed_by_score ?? 0}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs tabular-nums text-muted">
                      {stats.llm_calls ?? 0}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs tabular-nums text-muted">
                      {usd(stats.llm_cost_usd)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs tabular-nums text-faint">
                      {elapsed(batch.started_at, batch.finished_at)}
                    </td>
                  </tr>
                );
              })}

              {!batches.length && (
                <tr>
                  <td colSpan={9} className="px-4 py-16 text-center">
                    <p className="text-sm text-fg">No batches yet.</p>
                    <p className="mx-auto mt-1 max-w-sm text-xs text-muted">
                      Use Run agents on the review queue, or wait for the 02:00 and 14:00 UTC
                      cron. Every run lands here.
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
