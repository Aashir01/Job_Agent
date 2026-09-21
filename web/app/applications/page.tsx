import { ApiError } from "@/components/ApiError";
import { getApplications } from "@/lib/api";

export const dynamic = "force-dynamic";

const FUNNEL = [
  "submitted", "acknowledged", "replied", "screen", "interview", "offer",
  "rejected", "ghosted",
] as const;

type Status = (typeof FUNNEL)[number];

const TONE: Record<string, { text: string; dot: string }> = {
  offer: { text: "text-fast", dot: "bg-fast" },
  interview: { text: "text-fast", dot: "bg-fast" },
  screen: { text: "text-standard", dot: "bg-standard" },
  replied: { text: "text-standard", dot: "bg-standard" },
  acknowledged: { text: "text-muted", dot: "bg-muted" },
  submitted: { text: "text-muted", dot: "bg-muted" },
  rejected: { text: "text-marginal", dot: "bg-marginal" },
  ghosted: { text: "text-faint", dot: "bg-faint" },
};

export default async function ApplicationsPage() {
  const result = await getApplications().catch((error: unknown) => error as Error);

  if (result instanceof Error) {
    return <ApiError error={result} />;
  }

  const total = result.applications.length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.02em] text-fg">Applications</h1>
          <p className="mt-0.5 text-sm text-muted">
            Everything that left the system, and what came back.
          </p>
        </div>
        <p className="font-mono text-xs tabular-nums text-faint">
          {total} {total === 1 ? "application" : "applications"}
        </p>
      </div>

      <section
        aria-label="Pipeline"
        className="grid grid-cols-2 divide-y divide-edge overflow-hidden rounded-xl border
                   border-edge bg-panel/60 shadow-panel sm:grid-cols-4 sm:divide-y-0
                   lg:grid-cols-8"
      >
        {FUNNEL.map((stage, index) => {
          const tone = TONE[stage]!;
          const count = result.funnel[stage] ?? 0;
          return (
            <div
              key={stage}
              className={`px-4 py-3 ${index > 0 ? "sm:border-l sm:border-edge" : ""}`}
            >
              <p
                className={`font-mono text-xl font-semibold tabular-nums ${
                  count > 0 ? tone.text : "text-faint"
                }`}
              >
                {count}
              </p>
              <p className="mt-0.5 flex items-center gap-1.5 text-2xs text-muted">
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 rounded-full ${count > 0 ? tone.dot : "bg-edge-strong"}`}
                />
                {stage}
              </p>
            </div>
          );
        })}
      </section>

      <div className="overflow-hidden rounded-xl border border-edge bg-panel/60 shadow-panel">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left">
                {["Role", "Company", "Track", "Method", "Status", "Submitted"].map((head, index) => (
                  <th
                    key={head}
                    scope="col"
                    className={`px-4 py-2.5 text-2xs font-medium uppercase tracking-[0.12em]
                                text-faint ${index === 5 ? "text-right" : ""}`}
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.applications.map((row) => {
                const job = row.packages?.jobs;
                const tone = TONE[(row.status as Status) ?? "submitted"] ?? TONE.submitted!;
                return (
                  <tr
                    key={row.id}
                    className="border-b border-edge/50 transition-colors duration-150
                               last:border-0 hover:bg-raised/50"
                  >
                    <td className="max-w-[22rem] truncate px-4 py-3 text-fg/90">
                      {job?.source_url ? (
                        <a
                          href={job.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="transition-colors duration-150 hover:text-accent"
                        >
                          {job.title ?? "—"}
                        </a>
                      ) : (
                        (job?.title ?? "—")
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted">{job?.companies?.name ?? "—"}</td>
                    <td className="px-4 py-3 text-muted">
                      {job?.track ? (
                        <span className="rounded-full border border-edge px-2 py-0.5 text-2xs">
                          {job.track.replace(/_/g, " ")}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted">{row.method ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1.5 text-xs ${tone.text}`}>
                        <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
                        {row.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs tabular-nums text-faint">
                      {row.submitted_at?.slice(0, 10) ?? "—"}
                    </td>
                  </tr>
                );
              })}

              {!total && (
                <tr>
                  <td colSpan={6} className="px-4 py-16 text-center">
                    <p className="text-sm text-fg">Nothing submitted yet.</p>
                    <p className="mx-auto mt-1 max-w-sm text-xs text-muted">
                      Approve a package on the review queue and it will show up here with its
                      submission method and status.
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
