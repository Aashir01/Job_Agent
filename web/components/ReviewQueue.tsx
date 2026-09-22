"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";

import {
  approveAction,
  approveFastLaneAction,
  editAction,
  rejectAction,
  type ActionResult,
} from "@/app/actions";
import { REJECT_REASONS, type ReviewPackage, type Tier } from "@/lib/types";

import { PackageDetail } from "./PackageDetail";
import { ScorePill, TIER_META, TierBadge } from "./Tier";
import { Toast } from "./Toast";

const TIER_ORDER: Tier[] = ["fast_lane", "standard", "marginal"];

export function ReviewQueue({
  initial,
  focusPackageId,
}: {
  initial: ReviewPackage[];
  /** From `?package=<id>` — a digest links straight to one package, so tapping
   *  a job on a phone lands on it rather than on a list to search. */
  focusPackageId?: string;
}) {
  const [queue, setQueue] = useState(initial);
  const [cursor, setCursor] = useState(() => {
    const index = focusPackageId
      ? initial.findIndex((row) => row.id === focusPackageId)
      : -1;
    return index >= 0 ? index : 0;
  });
  const [awaitingReason, setAwaitingReason] = useState(false);
  const [editing, setEditing] = useState(false);
  const [toast, setToast] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => setQueue(initial), [initial]);

  const current = queue[cursor];
  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const pkg of queue) out[pkg.tier ?? "untiered"] = (out[pkg.tier ?? "untiered"] ?? 0) + 1;
    return out;
  }, [queue]);

  // Remove the decided package locally so the next one is under the cursor
  // immediately — waiting for a refetch is what makes a queue feel slow.
  const settle = useCallback(
    (id: string, result: ActionResult) => {
      setToast(result);
      if (result.ok || result.message.startsWith("Approved")) {
        setQueue((rows) => rows.filter((row) => row.id !== id));
        setCursor((index) => Math.max(0, Math.min(index, queue.length - 2)));
      }
    },
    [queue.length],
  );

  const approve = useCallback(
    (pkg: ReviewPackage) => {
      startTransition(async () => settle(pkg.id, await approveAction(pkg.id)));
    },
    [settle],
  );

  const reject = useCallback(
    (pkg: ReviewPackage, code: string) => {
      startTransition(async () => settle(pkg.id, await rejectAction(pkg.id, code)));
    },
    [settle],
  );

  const save = useCallback(
    (pkg: ReviewPackage, patch: Record<string, unknown>) => {
      startTransition(async () => {
        const result = await editAction(pkg.id, patch);
        setToast(result);
        if (result.ok) {
          setQueue((rows) =>
            rows.map((row) => (row.id === pkg.id ? { ...row, ...patch } : row)),
          );
          setEditing(false);
        }
      });
    },
    [],
  );

  const approveFastLane = useCallback(() => {
    startTransition(async () => {
      const result = await approveFastLaneAction();
      setToast(result);
      if (result.ok) setQueue((rows) => rows.filter((row) => row.tier !== "fast_lane"));
    });
  }, []);

  // §7: J/K to move, A approve, X reject, E edit, 1-5 reject reason.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!current) return;

      const key = event.key.toLowerCase();

      if (awaitingReason) {
        const index = Number(event.key) - 1;
        if (index >= 0 && index < REJECT_REASONS.length) {
          event.preventDefault();
          setAwaitingReason(false);
          reject(current, REJECT_REASONS[index]!.code);
          return;
        }
        if (key === "escape") {
          setAwaitingReason(false);
          return;
        }
      }

      switch (key) {
        case "j":
        case "arrowdown":
          event.preventDefault();
          setCursor((index) => Math.min(index + 1, queue.length - 1));
          break;
        case "k":
        case "arrowup":
          event.preventDefault();
          setCursor((index) => Math.max(index - 1, 0));
          break;
        case "a":
          event.preventDefault();
          approve(current);
          break;
        case "x":
          event.preventDefault();
          setAwaitingReason(true);
          break;
        case "e":
          event.preventDefault();
          setEditing((value) => !value);
          break;
        case "escape":
          setEditing(false);
          setAwaitingReason(false);
          break;
        default: {
          const index = Number(event.key) - 1;
          if (index >= 0 && index < REJECT_REASONS.length) {
            event.preventDefault();
            reject(current, REJECT_REASONS[index]!.code);
          }
        }
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [approve, awaitingReason, current, queue.length, reject]);

  useEffect(() => {
    listRef.current?.children[cursor]?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!queue.length) {
    return (
      <div className="animate-fade-in rounded-2xl border border-dashed border-edge bg-panel/40 px-6 py-16 text-center">
        <p className="text-base font-medium text-fg">The queue is clear.</p>
        <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted">
          Nothing is waiting on you. The next batch runs at 02:00 and 14:00 UTC and will
          refill this queue.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="relative overflow-hidden rounded-xl border border-edge bg-panel/60 shadow-panel">
        {pending && (
          <span
            aria-hidden
            className="absolute inset-x-0 top-0 h-px animate-pulse-dot bg-accent"
          />
        )}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5">
          {TIER_ORDER.map((tier) =>
            counts[tier] ? (
              <span key={tier} className="flex items-center gap-2">
                <span className={`h-1.5 w-1.5 rounded-full ${TIER_META[tier].dot}`} aria-hidden />
                <span className="text-xs text-muted">{TIER_META[tier].label}</span>
                <span className="font-mono text-sm font-semibold tabular-nums text-fg">
                  {counts[tier]}
                </span>
              </span>
            ) : null,
          )}

          <span aria-hidden className="hidden h-4 w-px bg-edge sm:block" />

          <span className="font-mono text-xs tabular-nums text-faint">
            {cursor + 1}
            <span className="text-edge-strong"> / </span>
            {queue.length}
          </span>

          {counts.fast_lane ? (
            <button
              type="button"
              onClick={approveFastLane}
              disabled={pending}
              className="ml-auto rounded-lg border border-fast/40 bg-fast/15 px-3 py-1.5 text-xs
                         font-medium text-fast transition-colors duration-150 hover:bg-fast/25
                         disabled:opacity-50"
            >
              Approve all {counts.fast_lane} fast-lane
            </button>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-20 lg:self-start">
          <p className="mb-2 px-1 text-2xs uppercase tracking-[0.14em] text-faint">Queue</p>
          <ul
            ref={listRef}
            className="max-h-[calc(100vh-11rem)] space-y-1 overflow-y-auto pr-1"
          >
            {queue.map((pkg, index) => {
              const selected = index === cursor;
              return (
                <li key={pkg.id}>
                  <button
                    type="button"
                    onClick={() => setCursor(index)}
                    aria-current={selected}
                    className={`relative block w-full rounded-lg border px-3 py-2.5 text-left
                                transition-colors duration-150 ${
                                  selected
                                    ? "rail-rule border-edge-strong bg-raised shadow-raised"
                                    : "border-transparent bg-panel/40 hover:border-edge hover:bg-panel"
                                }`}
                  >
                    <div className="flex items-baseline gap-2.5">
                      <ScorePill score={pkg.fit_score} />
                      <span
                        className={`truncate text-sm ${selected ? "text-fg" : "text-fg/80"}`}
                      >
                        {pkg.title ?? "Untitled role"}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 pl-[2.1rem]">
                      <span className="truncate text-2xs text-muted">
                        {pkg.company_name ?? "Unknown company"}
                      </span>
                      <span aria-hidden className="text-2xs text-edge-strong">
                        ·
                      </span>
                      <span className="truncate text-2xs text-faint">
                        {pkg.location_raw ?? "—"}
                      </span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="min-w-0">
          {current && (
            <div className="mb-3 flex items-center justify-between gap-3">
              <TierBadge tier={current.tier} />
              <p className="text-2xs text-faint">{TIER_META[current.tier ?? "marginal"].blurb}</p>
            </div>
          )}
          {current && (
            <PackageDetail
              pkg={current}
              editing={editing}
              pending={pending}
              onApprove={() => approve(current)}
              onReject={(code) => reject(current, code)}
              onToggleEdit={() => setEditing((value) => !value)}
              onSave={(patch) => save(current, patch)}
            />
          )}
        </div>
      </div>

      <footer
        className="sticky bottom-0 z-10 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border
                   border-edge bg-ink/85 px-4 py-2.5 text-2xs text-faint backdrop-blur-xl"
      >
        <span className="flex items-center gap-1.5">
          <span className="kbd">J</span>
          <span className="kbd">K</span>
          <span className="ml-0.5">move</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="kbd">A</span>
          <span>approve</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="kbd">X</span>
          <span>reject</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="kbd">E</span>
          <span>edit</span>
        </span>

        {awaitingReason && (
          <span className="font-medium text-marginal">
            Reject as: {REJECT_REASONS.map((r, i) => `${i + 1} ${r.label}`).join("  ·  ")}
          </span>
        )}
      </footer>

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
