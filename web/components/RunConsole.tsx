"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  saveAndRunAction,
  saveRunSettingsAction,
  type ActionResult,
} from "@/app/actions";
import { elapsed, usd } from "@/lib/format";
import type { BatchRow, BoardInfo, PlatformInfo, RunFilters, RunSettings } from "@/lib/types";

import { FilterForm } from "./FilterForm";
import { PlatformPicker } from "./PlatformPicker";
import { Toast } from "./Toast";

const POLL_MS = 4000;

async function fetchLatest(): Promise<BatchRow | null> {
  try {
    const res = await fetch("/api/batch/latest", { cache: "no-store" });
    if (!res.ok) return null;
    return ((await res.json()) as { batch: BatchRow | null }).batch;
  } catch {
    return null;
  }
}

/**
 * The console: pick the platforms and filters, then run the agents with them.
 *
 * Saving and starting are one call, so a run can never go out with a
 * configuration the user did not just confirm. The cron reads the same row, so
 * the scheduled batches inherit whatever is saved here.
 */
export function RunConsole({
  platforms,
  boards,
  settings,
}: {
  platforms: PlatformInfo[];
  boards: BoardInfo[];
  settings: RunSettings;
}) {
  const router = useRouter();
  const [selected, setSelected] = useState<string[]>(settings.platforms);
  const [filters, setFilters] = useState<RunFilters>(settings.filters);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<ActionResult | null>(null);
  const [running, setRunning] = useState<BatchRow | null>(null);
  const [, forceTick] = useState(0);

  const finish = useCallback(
    (done: BatchRow) => {
      setRunning(null);
      const stats = done.stats ?? {};
      setToast(
        done.status === "failed"
          ? { ok: false, message: `Batch failed — ${done.error ?? "see Batches for the detail"}` }
          : {
              ok: done.status === "ok",
              message:
                `Batch ${done.status} — ${stats.packages_built ?? 0} packages from ` +
                `${Object.keys(stats.scout?.by_source ?? {}).length} platform(s), ` +
                `${usd(stats.llm_cost_usd)} across ${stats.llm_calls ?? 0} calls`,
            },
      );
      router.refresh();
    },
    [router],
  );

  // Pick up a batch that is already running (the cron, or another tab).
  useEffect(() => {
    let cancelled = false;
    void fetchLatest().then((latest) => {
      if (!cancelled && latest?.status === "running") {
        setRunning(latest);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(async () => {
      const latest = await fetchLatest();
      if (latest?.status === "running") {
        setRunning(latest);
        return;
      }
      if (latest?.id === running.id) finish(latest);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, finish]);

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [running]);

  const togglePlatform = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );

  const trigger = (label: string, action: () => Promise<ActionResult>) => {
    setBusy(label);
    void action().then((result) => {
      setBusy(null);
      setToast(result);
      if (result.ok && label.startsWith("run")) {
        void fetchLatest().then((latest) => latest && setRunning(latest));
      }
    });
  };

  const scope = selected.length ? `${selected.length} platform(s)` : "all platforms";
  const disabled = busy !== null || running !== null;

  return (
    <div className="space-y-3">
      {running && (
        <p className="flex items-center gap-2 rounded-xl border border-edge bg-panel/60 px-4 py-2.5 text-sm text-fg shadow-panel">
          <span aria-hidden className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent" />
          Batch running
          <span className="font-mono text-xs tabular-nums text-muted">
            {elapsed(running.started_at, null)}
          </span>
          <a href="/batches" className="text-xs text-accent hover:underline">
            watch
          </a>
        </p>
      )}

      <PlatformPicker
        platforms={platforms}
        boards={boards}
        selected={selected}
        onToggle={togglePlatform}
      />

      <FilterForm
        initial={settings.filters}
        defaults={settings.defaults}
        ceilings={settings.ceilings}
        onChange={setFilters}
      />

      <section className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border border-edge bg-panel/60 px-4 py-3 shadow-panel">
        <div className="min-w-0">
          <p className="text-2xs uppercase tracking-[0.14em] text-faint">Run</p>
          <p className="mt-0.5 text-sm text-muted">
            {scope}
            {filters.keywords?.length ? ` · keywords: ${filters.keywords.join(", ")}` : ""}
            {filters.remote_only ? " · remote only" : ""}
            {filters.max_jobs ? ` · max ${filters.max_jobs} jobs` : ""}
          </p>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => trigger("save", () => saveRunSettingsAction({ platforms: selected, filters }))}
            disabled={busy !== null}
            className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                       transition-colors duration-150 hover:border-edge-strong hover:text-fg
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "save" ? "Saving…" : "Save only"}
          </button>
          <button
            type="button"
            onClick={() =>
              trigger("run-stored", () =>
                saveAndRunAction({ platforms: selected, filters, skipScout: true }),
              )
            }
            disabled={disabled}
            title="Process jobs already stored, without polling the boards"
            className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                       transition-colors duration-150 hover:border-edge-strong hover:text-fg
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            Run on stored jobs
          </button>
          <button
            type="button"
            onClick={() =>
              trigger("run", () => saveAndRunAction({ platforms: selected, filters, skipScout: false }))
            }
            disabled={disabled}
            className="rounded-lg border border-accent/40 bg-accent/15 px-3.5 py-1.5 text-xs
                       font-medium text-accent transition-colors duration-150 hover:bg-accent/25
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy?.startsWith("run") ? "Starting…" : "Save and run agents"}
          </button>
        </div>
      </section>

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
