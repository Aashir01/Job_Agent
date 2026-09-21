"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  refreshRegistersAction,
  runBatchAction,
  runChaserAction,
  type ActionResult,
} from "@/app/actions";
import { elapsed, usd } from "@/lib/format";
import type { BatchRow } from "@/lib/types";

import { Toast } from "./Toast";

const POLL_MS = 4000;
const START_TIMEOUT_MS = 25000;

async function fetchLatest(): Promise<BatchRow | null> {
  try {
    const res = await fetch("/api/batch/latest", { cache: "no-store" });
    if (!res.ok) return null;
    return ((await res.json()) as { batch: BatchRow | null }).batch;
  } catch {
    return null;
  }
}

type Phase = "idle" | "starting" | "running";

/**
 * The dashboard's start button for the agents. The batch runs in the
 * background on the API (a full run takes minutes, past any serverless
 * request limit), so this fires, then polls /api/batch/latest until the
 * batches row flips from "running" to a terminal state.
 */
export function RunControls() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [batch, setBatch] = useState<BatchRow | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<ActionResult | null>(null);
  const [, forceTick] = useState(0);
  const startedPollingAt = useRef(0);

  const finish = useCallback(
    (done: BatchRow) => {
      setPhase("idle");
      setBatch(null);
      const stats = done.stats ?? {};
      setToast(
        done.status === "failed"
          ? { ok: false, message: `Batch failed — ${done.error ?? "see Batches for the detail"}` }
          : {
              ok: done.status === "ok",
              message: `Batch ${done.status} — ${stats.packages_built ?? 0} packages built, ${
                stats.killed_by_gatekeeper ?? 0
              } gatekept, ${usd(stats.llm_cost_usd)} across ${stats.llm_calls ?? 0} calls`,
            },
      );
      router.refresh();
    },
    [router],
  );

  // A batch may already be running when the page loads (the cron, or another
  // tab started one) — pick it up instead of offering a second run.
  useEffect(() => {
    let cancelled = false;
    void fetchLatest().then((latest) => {
      if (!cancelled && latest?.status === "running") {
        setBatch(latest);
        setPhase("running");
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (phase === "idle") return;
    startedPollingAt.current ||= Date.now();
    const timer = setInterval(async () => {
      const latest = await fetchLatest();
      if (latest?.status === "running") {
        setBatch(latest);
        setPhase("running");
        return;
      }
      if (phase === "running" && batch && latest?.id === batch.id) {
        finish(latest);
        return;
      }
      if (phase === "starting" && Date.now() - startedPollingAt.current > START_TIMEOUT_MS) {
        // The API accepted the run but no batches row appeared — the toast
        // from the action already said what happened; stop watching quietly.
        setPhase("idle");
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [phase, batch, finish]);

  // The elapsed clock under the progress line.
  useEffect(() => {
    if (phase !== "running") return;
    const timer = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  const trigger = (label: string, action: () => Promise<ActionResult>) => {
    setBusy(label);
    void action().then((result) => {
      setBusy(null);
      setToast(result);
      if (result.ok && label === "batch") {
        startedPollingAt.current = Date.now();
        setPhase("starting");
      }
      if (result.ok && label === "chaser") router.refresh();
    });
  };

  const batchDisabled = busy !== null || phase !== "idle";

  return (
    <section
      aria-label="Agents"
      className="relative overflow-hidden rounded-xl border border-edge bg-panel/60 shadow-panel"
    >
      {phase === "running" && (
        <span aria-hidden className="absolute inset-x-0 top-0 h-px animate-pulse-dot bg-accent" />
      )}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3">
        <div className="min-w-0">
          <p className="text-2xs uppercase tracking-[0.14em] text-faint">Agents</p>
          {phase === "running" && batch ? (
            <p className="mt-0.5 flex items-center gap-2 text-sm text-fg">
              <span aria-hidden className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent" />
              Batch running
              <span className="font-mono text-xs tabular-nums text-muted">
                {elapsed(batch.started_at, null)}
              </span>
              <a href="/batches" className="text-xs text-accent hover:underline">
                watch
              </a>
            </p>
          ) : phase === "starting" ? (
            <p className="mt-0.5 flex items-center gap-2 text-sm text-muted">
              <span aria-hidden className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent" />
              Starting the batch…
            </p>
          ) : (
            <p className="mt-0.5 text-sm text-muted">
              Scout, analyse, gatekeep, tailor, draft. Then the queue refills.
            </p>
          )}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => trigger("batch", () => runBatchAction(false))}
            disabled={batchDisabled}
            className="rounded-lg border border-accent/40 bg-accent/15 px-3.5 py-1.5 text-xs
                       font-medium text-accent transition-colors duration-150 hover:bg-accent/25
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "batch" ? "Starting…" : "Run agents"}
          </button>
          <button
            type="button"
            onClick={() => trigger("batch", () => runBatchAction(true))}
            disabled={batchDisabled}
            title="Process jobs already stored, without polling the boards"
            className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                       transition-colors duration-150 hover:border-edge-strong hover:text-fg
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            Skip discovery
          </button>
          <span aria-hidden className="hidden h-4 w-px bg-edge sm:block" />
          <button
            type="button"
            onClick={() => trigger("chaser", runChaserAction)}
            disabled={busy !== null}
            title="Queue due follow-ups and poll Gmail for replies"
            className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                       transition-colors duration-150 hover:border-edge-strong hover:text-fg
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "chaser" ? "Running…" : "Run chaser"}
          </button>
          <button
            type="button"
            onClick={() => trigger("registers", refreshRegistersAction)}
            disabled={busy !== null}
            title="Re-download the UK, NL and CA sponsorship registers"
            className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                       transition-colors duration-150 hover:border-edge-strong hover:text-fg
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "registers" ? "Refreshing…" : "Refresh registers"}
          </button>
        </div>
      </div>

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </section>
  );
}
