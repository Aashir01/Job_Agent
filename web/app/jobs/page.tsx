import { ApiError } from "@/components/ApiError";
import { inputClass } from "@/components/Field";
import { getJobs, getSources } from "@/lib/api";
import { dateTime, relativeTime } from "@/lib/format";
import type { JobRow } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "job-agent — all jobs",
};

const REMOTE_POLICIES = ["global", "geo_restricted", "hybrid", "onsite"];
const TRACKS = ["remote_fte", "relocation", "contract"];
const STATUSES = [
  { value: "all", label: "Everything" },
  { value: "unanalysed", label: "Not analysed yet" },
  { value: "analysed", label: "Analysed" },
  { value: "killed", label: "Killed by the Gatekeeper" },
];
const SORTS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "title", label: "Title A–Z" },
];
const PAGE_SIZES = [25, 50, 100, 200];

type Params = Record<string, string | string[] | undefined>;

function one(params: Params, key: string): string {
  const value = params[key];
  return typeof value === "string" ? value.trim() : "";
}

function whole(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function salary(row: JobRow): string {
  if (row.salary_min == null && row.salary_max == null) return "—";
  const currency = row.currency ?? "USD";
  const k = (amount: number) => `${Math.round(amount / 1000)}k`;
  if (row.salary_min != null && row.salary_max != null) {
    return `${currency} ${k(row.salary_min)}–${k(row.salary_max)}`;
  }
  return `${currency} ${k((row.salary_min ?? row.salary_max) as number)}`;
}

const selectClass = `${inputClass} appearance-none pr-8`;

export default async function JobsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const q = one(params, "q");
  const platform = one(params, "platform");
  const remote = one(params, "remote");
  const track = one(params, "track");
  const status = one(params, "status") || "all";
  const sort = one(params, "sort") || "newest";
  const limit = whole(one(params, "limit"), 50);
  const offset = whole(one(params, "offset"), 0);

  const [feed, sources] = await Promise.allSettled([
    getJobs({ q, platform, remotePolicy: remote, track, status, sort, limit, offset }),
    getSources(),
  ]);

  if (feed.status === "rejected") {
    return <ApiError error={feed.reason} />;
  }

  const rows = feed.value.jobs;
  const hasMore = feed.value.has_more;
  const platforms = sources.status === "fulfilled" ? sources.value.platforms : [];

  // Every link on this page keeps the filters, so paging never silently drops
  // them — and the URL is the whole state, so a view can be bookmarked.
  const kept = new URLSearchParams();
  if (q) kept.set("q", q);
  if (platform) kept.set("platform", platform);
  if (remote) kept.set("remote", remote);
  if (track) kept.set("track", track);
  if (status !== "all") kept.set("status", status);
  if (sort !== "newest") kept.set("sort", sort);
  if (limit !== 50) kept.set("limit", String(limit));

  const href = (nextOffset: number) => {
    const query = new URLSearchParams(kept);
    if (nextOffset > 0) query.set("offset", String(nextOffset));
    const query_string = query.toString();
    return query_string ? `/jobs?${query_string}` : "/jobs";
  };

  const filtering = Boolean(q || platform || remote || track || status !== "all");
  const first = rows.length ? offset + 1 : 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.02em] text-fg">All jobs</h1>
          <p className="mt-0.5 text-sm text-muted">
            Everything Scout stored — including what the Gatekeeper killed and what
            never scored high enough to be packaged.
          </p>
        </div>
        <p className="font-mono text-xs tabular-nums text-faint">
          {rows.length ? `${first}–${offset + rows.length} shown` : "nothing shown"}
        </p>
      </div>

      <form method="get" action="/jobs" className="rounded-xl border border-edge bg-panel/60 shadow-panel">
        <div className="grid gap-4 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block lg:col-span-2">
            <span className="mb-1.5 block text-2xs uppercase tracking-[0.12em] text-faint">
              Search
            </span>
            <input
              className={inputClass}
              type="search"
              name="q"
              defaultValue={q}
              placeholder="title, location or source"
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-2xs uppercase tracking-[0.12em] text-faint">
              Platform
            </span>
            <select className={selectClass} name="platform" defaultValue={platform}>
              <option value="">Any platform</option>
              {platforms.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-2xs uppercase tracking-[0.12em] text-faint">
              Status
            </span>
            <select className={selectClass} name="status" defaultValue={status}>
              {STATUSES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-2xs uppercase tracking-[0.12em] text-faint">
              Remote policy
            </span>
            <select className={selectClass} name="remote" defaultValue={remote}>
              <option value="">Any</option>
              {REMOTE_POLICIES.map((item) => (
                <option key={item} value={item}>
                  {item.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-2xs uppercase tracking-[0.12em] text-faint">
              Track
            </span>
            <select className={selectClass} name="track" defaultValue={track}>
              <option value="">Any</option>
              {TRACKS.map((item) => (
                <option key={item} value={item}>
                  {item.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-2xs uppercase tracking-[0.12em] text-faint">
              Sort
            </span>
            <select className={selectClass} name="sort" defaultValue={sort}>
              {SORTS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-2xs uppercase tracking-[0.12em] text-faint">
              Per page
            </span>
            <select className={selectClass} name="limit" defaultValue={String(limit)}>
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-edge/60 px-4 py-3">
          <button
            type="submit"
            className="rounded-lg border border-accent/40 bg-accent/15 px-3.5 py-1.5 text-sm
                       text-accent transition-colors duration-150 hover:bg-accent/25"
          >
            Apply filters
          </button>
          {filtering && (
            <a
              href="/jobs"
              className="text-xs text-faint transition-colors duration-150 hover:text-fg"
            >
              clear
            </a>
          )}
          <span className="text-2xs text-faint">
            Filters are applied by the API, not the browser — the URL is the whole state.
          </span>
        </div>
      </form>

      <div className="overflow-hidden rounded-xl border border-edge bg-panel/60 shadow-panel">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left">
                {["Job", "Platform", "Location", "Salary", "Remote", "Track", "Fit", "Found"].map(
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
              {rows.map((row) => {
                const pkg = row.packages?.[0] ?? null;
                return (
                  <tr
                    key={row.id}
                    className="border-b border-edge/50 transition-colors duration-150
                               last:border-0 hover:bg-raised/50"
                  >
                    <td className="max-w-[34rem] px-4 py-3">
                      <div className="flex flex-col gap-0.5">
                        {row.source_url ? (
                          <a
                            href={row.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="truncate text-fg/90 transition-colors duration-150 hover:text-accent"
                            title={row.title ?? undefined}
                          >
                            {row.title || "(untitled)"}
                          </a>
                        ) : (
                          <span className="truncate text-fg/90">{row.title || "(untitled)"}</span>
                        )}
                        <span className="truncate text-2xs text-faint">
                          {row.companies?.name || "(company not given)"}
                          {row.companies?.hires_internationally && (
                            <span className="ml-1.5 text-accent/80">· hires internationally</span>
                          )}
                          {row.killed_reason && (
                            <span className="ml-1.5 text-marginal" title={row.killed_reason}>
                              · killed
                            </span>
                          )}
                        </span>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <span className="font-mono text-2xs text-muted">
                        {(row.source ?? "—").split(":")[0]}
                      </span>
                    </td>
                    <td className="max-w-[12rem] truncate px-4 py-3 text-xs text-muted">
                      {row.location_raw || "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs tabular-nums text-muted">
                      {salary(row)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-muted">
                      {row.remote_policy?.replace(/_/g, " ") ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-muted">
                      {row.track?.replace(/_/g, " ") ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs tabular-nums">
                      {pkg?.fit_score != null ? (
                        <span className="text-fg/90" title={pkg.tier ?? undefined}>
                          {pkg.fit_score}
                        </span>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td
                      className="whitespace-nowrap px-4 py-3 font-mono text-2xs text-faint"
                      title={dateTime(row.discovered_at)}
                    >
                      {relativeTime(row.discovered_at)}
                    </td>
                  </tr>
                );
              })}

              {!rows.length && (
                <tr>
                  <td colSpan={8} className="px-4 py-16 text-center">
                    <p className="text-sm text-fg">
                      {filtering ? "Nothing matches those filters." : "No jobs stored yet."}
                    </p>
                    <p className="mx-auto mt-1 max-w-md text-xs text-muted">
                      {filtering
                        ? "Loosen a filter, or clear them to see the whole feed."
                        : "Run the agents from the review queue or /setup and every posting they store lands here."}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {(offset > 0 || hasMore) && (
        <div className="flex items-center justify-between">
          {offset > 0 ? (
            <a
              href={href(Math.max(0, offset - limit))}
              className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                         transition-colors duration-150 hover:border-edge-strong hover:text-fg"
            >
              ← Newer
            </a>
          ) : (
            <span />
          )}
          {hasMore && (
            <a
              href={href(offset + limit)}
              className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                         transition-colors duration-150 hover:border-edge-strong hover:text-fg"
            >
              Older →
            </a>
          )}
        </div>
      )}
    </div>
  );
}
