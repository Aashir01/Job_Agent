import { notFound } from "next/navigation";

import { ApiError } from "@/components/ApiError";
import { AutoRefresh } from "@/components/AutoRefresh";
import { StatusBadge } from "@/components/BatchStatus";
import { ResendDigest } from "@/components/ResendDigest";
import { getBatch } from "@/lib/api";
import { dateTime, elapsed, usd } from "@/lib/format";
import type { RunFilters } from "@/lib/types";

export const dynamic = "force-dynamic";

/** One line describing the filters this run was given, for the header readout. */
function describeFilters(filters: RunFilters | undefined): string {
  if (!filters) return "";
  const parts: string[] = [];
  if (filters.keywords?.length) parts.push(`keywords ${filters.keywords.join(", ")}`);
  if (filters.locations?.length) parts.push(`locations ${filters.locations.join(", ")}`);
  if (filters.exclude_keywords?.length) {
    parts.push(`excluding ${filters.exclude_keywords.join(", ")}`);
  }
  if (filters.remote_only) parts.push("remote only");
  if (filters.seniority?.length) parts.push(`seniority ${filters.seniority.join(", ")}`);
  if (filters.salary_floor_usd) parts.push(`floor $${filters.salary_floor_usd}`);
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}

export default async function BatchDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await getBatch(id).catch((error: unknown) => error as Error);

  if (result instanceof Error) {
    if (result.message.includes("no such batch")) notFound();
    return <ApiError error={result} />;
  }

  const { batch, llm_by_agent } = result;
  const stats = batch.stats ?? {};
  const agents = Object.entries(llm_by_agent);
  const scout = (stats.scout ?? {}) as Record<string, unknown>;
  const bySource = Object.entries(stats.scout?.by_source ?? {}).sort(([, a], [, b]) => b - a);
  const filtered = Object.entries(stats.scout?.filtered ?? {});

  return (
    <div className="space-y-5">
      <AutoRefresh active={batch.status === "running"} intervalMs={5000} />

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-2xs uppercase tracking-[0.14em] text-faint">
            <a href="/batches" className="transition-colors duration-150 hover:text-muted">
              Batches
            </a>
            <span aria-hidden className="mx-1.5 text-edge-strong">/</span>
            {batch.kind}
          </p>
          <h1 className="mt-1 flex items-center gap-3 text-2xl font-semibold tracking-[-0.02em] text-fg">
            {dateTime(batch.started_at)}
            <StatusBadge status={batch.status} />
          </h1>
          <p className="mt-0.5 text-sm text-muted">
            {batch.finished_at
              ? `Ran ${elapsed(batch.started_at, batch.finished_at)}`
              : "Running now"}
            {stats.quota_exhausted && (
              <span className="text-standard"> — LLM budget exhausted, the rest rolls over</span>
            )}
          </p>
        </div>

        <ResendDigest batchId={batch.id} delivered={stats.notifications} />
      </div>

      <section
        aria-label="Batch stats"
        className="grid grid-cols-2 divide-y divide-edge overflow-hidden rounded-xl border
                   border-edge bg-panel/60 shadow-panel sm:grid-cols-3 sm:divide-y-0
                   lg:grid-cols-6"
      >
        <Stat label="Analysed" value={stats.analysed ?? 0} />
        <Stat label="Gatekept" value={stats.killed_by_gatekeeper ?? 0} />
        <Stat label="Score kills" value={stats.killed_by_score ?? 0} />
        <Stat label="Packages" value={stats.packages_built ?? 0} highlight />
        <Stat label="LLM calls" value={stats.llm_calls ?? 0} />
        <Stat label="Cost" value={usd(stats.llm_cost_usd)} />
      </section>

      {Object.keys(stats.tiers ?? {}).length > 0 && (
        <p className="text-xs text-muted">
          Tiers:{" "}
          {Object.entries(stats.tiers ?? {})
            .map(([tier, count]) => `${tier.replace(/_/g, " ")} ${count}`)
            .join(" · ")}
          {(stats.rejected_rewrites ?? 0) > 0 && (
            <span className="text-faint">
              {" "}
              · {stats.rejected_rewrites} rewrites rejected by the traceability check
            </span>
          )}
        </p>
      )}

      {/* What this run was asked for, and what each platform gave back. A thin
          queue is nearly always one of these two, so both are on the page. */}
      <p className="text-xs text-muted">
        <span className="text-faint">asked for</span>{" "}
        {stats.platforms?.length ? stats.platforms.join(", ") : "all platforms"}
        {stats.max_jobs ? ` · max ${stats.max_jobs} jobs` : ""}
        {stats.llm_budget ? ` · ${stats.llm_budget} LLM calls` : ""}
        {describeFilters(stats.filters)}
      </p>

      {bySource.length > 0 && (
        <section aria-label="Jobs by platform">
          <h2 className="mb-2 px-1 text-2xs uppercase tracking-[0.14em] text-faint">
            Jobs by platform
          </h2>
          <div className="flex flex-wrap gap-x-5 gap-y-1.5 rounded-xl border border-edge bg-panel/60 px-4 py-3 shadow-panel">
            {bySource.map(([source, count]) => (
              <span key={source} className="text-xs text-muted">
                <span className="text-fg/80">{source}</span>{" "}
                <span className="font-mono tabular-nums">{count}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {filtered.length > 0 && (
        <p className="text-xs text-muted">
          <span className="text-faint">dropped by filters</span>{" "}
          {filtered.map(([reason, count]) => `${reason.replace(/_/g, " ")} ${count}`).join(" · ")}
        </p>
      )}

      {agents.length > 0 && (
        <section aria-label="LLM cost by agent">
          <h2 className="mb-2 px-1 text-2xs uppercase tracking-[0.14em] text-faint">
            LLM cost by agent
          </h2>
          <div className="overflow-hidden rounded-xl border border-edge bg-panel/60 shadow-panel">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-edge text-left">
                  {["Agent", "Calls", "Failures", "Cost"].map((head) => (
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
                {agents.map(([agent, entry]) => (
                  <tr key={agent} className="border-b border-edge/50 last:border-0">
                    <td className="px-4 py-2.5 text-fg/90">{agent}</td>
                    <td className="px-4 py-2.5 font-mono text-xs tabular-nums text-muted">
                      {entry.calls}
                    </td>
                    <td
                      className={`px-4 py-2.5 font-mono text-xs tabular-nums ${
                        entry.failures > 0 ? "text-marginal" : "text-muted"
                      }`}
                    >
                      {entry.failures}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs tabular-nums text-muted">
                      {usd(entry.cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {Object.keys(scout).length > 0 && (
        <section aria-label="Scout">
          <h2 className="mb-2 px-1 text-2xs uppercase tracking-[0.14em] text-faint">Scout</h2>
          <div className="rounded-xl border border-edge bg-panel/60 shadow-panel">
            <div className="flex flex-wrap gap-x-5 gap-y-1.5 px-4 py-3">
              {Object.entries(scout)
                .filter(([, value]) => typeof value !== "object" || value === null)
                .map(([key, value]) => (
                  <span key={key} className="text-xs text-muted">
                    <span className="text-faint">{key.replace(/_/g, " ")}</span>{" "}
                    <span className="font-mono tabular-nums text-fg/90">{String(value)}</span>
                  </span>
                ))}
            </div>
            {Object.entries(scout)
              .filter(([, value]) => typeof value === "object" && value !== null)
              .map(([key, value]) => (
                <div key={key} className="border-t border-edge/60 px-4 py-3">
                  <p className="mb-1.5 text-2xs uppercase tracking-[0.14em] text-faint">
                    {key.replace(/_/g, " ")}
                  </p>
                  <ul className="space-y-1">
                    {Object.entries(value as Record<string, unknown>).map(([name, detail]) => (
                      <li key={name} className="font-mono text-2xs leading-relaxed text-muted">
                        <span className="text-fg/80">{name}</span>
                        <span aria-hidden className="mx-1.5 text-edge-strong">·</span>
                        <span className="text-marginal/80">
                          {String(detail).split("\n")[0]?.slice(0, 120)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
          </div>
        </section>
      )}

      {(stats.errors?.length ?? 0) > 0 && (
        <section aria-label="Errors">
          <h2 className="mb-2 px-1 text-2xs uppercase tracking-[0.14em] text-marginal">Errors</h2>
          <ul className="space-y-1.5 rounded-xl border border-marginal/30 bg-marginal/[0.05] px-4 py-3">
            {(stats.errors ?? []).map((error, index) => (
              <li key={index} className="font-mono text-2xs leading-relaxed text-marginal/90">
                {error}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: number | string;
  highlight?: boolean;
}) {
  return (
    <div className="px-4 py-3 sm:border-l sm:border-edge sm:first:border-l-0">
      <p className="text-2xs uppercase tracking-[0.14em] text-faint">{label}</p>
      <p
        className={`mt-1 font-mono text-xl font-semibold tabular-nums ${
          highlight ? "text-accent" : "text-fg"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
