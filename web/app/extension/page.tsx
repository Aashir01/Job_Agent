import { ApiError } from "@/components/ApiError";
import { getExtensionQueue, getQuota } from "@/lib/api";
import { dateTime, relativeTime } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "job-agent — extension",
};

const STATUS_TONE: Record<string, { text: string; dot: string }> = {
  pending: { text: "text-standard", dot: "bg-standard" },
  claimed: { text: "text-accent", dot: "bg-accent" },
  filled: { text: "text-accent", dot: "bg-accent" },
  submitted: { text: "text-fast", dot: "bg-fast" },
  abandoned: { text: "text-faint", dot: "bg-faint" },
};

export default async function ExtensionPage() {
  const [queue, quota] = await Promise.allSettled([getExtensionQueue(), getQuota()]);

  if (queue.status === "rejected") {
    return <ApiError error={queue.reason} />;
  }

  const items = queue.value.items;
  const caps = quota.status === "fulfilled" ? quota.value : null;
  const counts: Record<string, number> = {};
  for (const item of items) counts[item.status] = (counts[item.status] ?? 0) + 1;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.02em] text-fg">Extension</h1>
          <p className="mt-0.5 text-sm text-muted">
            Approved packages waiting on the Chrome filler. It fills; you click the site&apos;s
            Submit.
          </p>
        </div>
        {caps && (
          <p className="font-mono text-xs tabular-nums text-faint">
            {caps.counters.extension_submit ?? 0}
            <span className="text-edge-strong">/</span>
            {caps.caps.extension_submit} submissions today
          </p>
        )}
      </div>

      {items.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 px-1">
          {Object.entries(counts).map(([status, count]) => {
            const tone = STATUS_TONE[status] ?? STATUS_TONE.pending!;
            return (
              <span key={status} className="flex items-center gap-2">
                <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
                <span className="text-xs text-muted">{status}</span>
                <span className="font-mono text-sm font-semibold tabular-nums text-fg">
                  {count}
                </span>
              </span>
            );
          })}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-edge bg-panel/60 shadow-panel">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left">
                {["Role", "Company", "Status", "Queued", "Claimed", "Finished"].map((head) => (
                  <th
                    key={head}
                    scope="col"
                    className="px-4 py-2.5 text-2xs font-medium uppercase tracking-[0.12em] text-faint"
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const tone = STATUS_TONE[item.status] ?? STATUS_TONE.pending!;
                const job = item.packages?.jobs;
                return (
                  <tr
                    key={item.id}
                    className="border-b border-edge/50 transition-colors duration-150
                               last:border-0 hover:bg-raised/50"
                  >
                    <td className="max-w-[22rem] truncate px-4 py-3">
                      <a
                        href={item.target_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-fg/90 transition-colors duration-150 hover:text-accent"
                      >
                        {job?.title ?? item.target_url}
                      </a>
                    </td>
                    <td className="px-4 py-3 text-muted">{job?.companies?.name ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1.5 text-xs ${tone.text}`}>
                        <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
                        {item.status}
                      </span>
                    </td>
                    <td
                      className="whitespace-nowrap px-4 py-3 font-mono text-xs tabular-nums text-faint"
                      title={dateTime(item.created_at)}
                    >
                      {relativeTime(item.created_at)}
                    </td>
                    <td
                      className="whitespace-nowrap px-4 py-3 font-mono text-xs tabular-nums text-faint"
                      title={dateTime(item.claimed_at)}
                    >
                      {relativeTime(item.claimed_at)}
                    </td>
                    <td
                      className="whitespace-nowrap px-4 py-3 font-mono text-xs tabular-nums text-faint"
                      title={dateTime(item.completed_at)}
                    >
                      {relativeTime(item.completed_at)}
                    </td>
                  </tr>
                );
              })}

              {!items.length && (
                <tr>
                  <td colSpan={6} className="px-4 py-16 text-center">
                    <p className="text-sm text-fg">The fill queue is empty.</p>
                    <p className="mx-auto mt-1 max-w-sm text-xs text-muted">
                      When the Courier cannot submit through an ATS API, the package lands here
                      for the extension. Load it unpacked from{" "}
                      <code className="font-mono text-fg/70">extension/</code> in{" "}
                      <code className="font-mono text-fg/70">chrome://extensions</code>.
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
