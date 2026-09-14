import { getApplications } from "@/lib/api";

export const dynamic = "force-dynamic";

const FUNNEL = [
  "submitted", "acknowledged", "replied", "screen", "interview", "offer",
  "rejected", "ghosted",
] as const;

const TONE: Record<string, string> = {
  offer: "text-fast",
  interview: "text-fast",
  screen: "text-standard",
  replied: "text-standard",
  rejected: "text-marginal",
  ghosted: "text-muted",
};

export default async function ApplicationsPage() {
  const result = await getApplications().catch((error: unknown) => error as Error);

  if (result instanceof Error) {
    return (
      <p className="rounded-xl border border-marginal/40 bg-marginal/5 p-6 text-sm text-marginal">
        Cannot reach the API: {result.message}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Applications</h1>

      <div className="flex flex-wrap gap-2">
        {FUNNEL.map((stage) => (
          <div key={stage} className="rounded-lg border border-edge bg-panel/40 px-3 py-2">
            <p className="font-mono text-lg tabular-nums">{result.funnel[stage] ?? 0}</p>
            <p className={`text-[11px] ${TONE[stage] ?? "text-muted"}`}>{stage}</p>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto rounded-xl border border-edge">
        <table className="w-full text-sm">
          <thead className="bg-panel/60 text-left text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Company</th>
              <th className="px-3 py-2 font-medium">Track</th>
              <th className="px-3 py-2 font-medium">Method</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Submitted</th>
            </tr>
          </thead>
          <tbody>
            {result.applications.map((row) => {
              const job = row.packages?.jobs;
              return (
                <tr key={row.id} className="border-t border-edge/60">
                  <td className="max-w-xs truncate px-3 py-2">
                    {job?.source_url ? (
                      <a href={job.source_url} target="_blank" rel="noreferrer" className="hover:underline">
                        {job.title ?? "—"}
                      </a>
                    ) : (
                      (job?.title ?? "—")
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted">{job?.companies?.name ?? "—"}</td>
                  <td className="px-3 py-2 text-muted">{job?.track?.replace(/_/g, " ") ?? "—"}</td>
                  <td className="px-3 py-2 text-muted">{row.method ?? "—"}</td>
                  <td className={`px-3 py-2 ${TONE[row.status] ?? ""}`}>{row.status}</td>
                  <td className="px-3 py-2 font-mono text-xs text-muted">
                    {row.submitted_at?.slice(0, 10) ?? "—"}
                  </td>
                </tr>
              );
            })}
            {!result.applications.length && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-muted">
                  Nothing submitted yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
