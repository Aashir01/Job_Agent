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

const TIER_ORDER: Tier[] = ["fast_lane", "standard", "marginal"];

export function ReviewQueue({ initial }: { initial: ReviewPackage[] }) {
  const [queue, setQueue] = useState(initial);
  const [cursor, setCursor] = useState(0);
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
      <div className="rounded-xl border border-edge bg-panel/50 p-10 text-center">
        <p className="text-sm">The queue is empty.</p>
        <p className="mt-1 text-xs text-muted">
          The next batch runs at 02:00 and 14:00 UTC.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {TIER_ORDER.map((tier) =>
          counts[tier] ? (
            <span key={tier} className="flex items-center gap-1.5 text-xs text-muted">
              <span className={`h-1.5 w-1.5 rounded-full ${TIER_META[tier].dot}`} aria-hidden />
              {TIER_META[tier].label}: <b className="text-slate-200">{counts[tier]}</b>
            </span>
          ) : null,
        )}
        <span className="text-xs text-muted">·</span>
        <span className="text-xs text-muted">
          {cursor + 1} of {queue.length}
        </span>
        {counts.fast_lane ? (
          <button
            type="button"
            onClick={approveFastLane}
            disabled={pending}
            className="ml-auto rounded-lg border border-fast/40 bg-fast/10 px-3 py-1.5 text-xs
                       font-medium text-fast hover:bg-fast/20 disabled:opacity-50"
          >
            Approve all {counts.fast_lane} fast-lane
          </button>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <ul ref={listRef} className="max-h-[70vh] space-y-1.5 overflow-y-auto pr-1">
          {queue.map((pkg, index) => (
            <li key={pkg.id}>
              <button
                type="button"
                onClick={() => setCursor(index)}
                aria-current={index === cursor}
                className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                  index === cursor
                    ? "border-sky-400/60 bg-sky-400/10"
                    : "border-edge bg-panel/40 hover:border-edge/80"
                }`}
              >
                <div className="flex items-baseline gap-2">
                  <ScorePill score={pkg.fit_score} />
                  <span className="truncate text-sm">{pkg.title ?? "Untitled role"}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 truncate text-[11px] text-muted">
                  <span className="truncate">{pkg.company_name ?? "Unknown company"}</span>
                  <span>·</span>
                  <span className="truncate">{pkg.location_raw ?? "—"}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>

        <div className="min-w-0">
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
        className="sticky bottom-0 flex flex-wrap items-center gap-x-4 gap-y-1 border-t
                   border-edge bg-ink/95 py-2 text-[11px] text-muted backdrop-blur"
      >
        <span><span className="kbd">J</span> <span className="kbd">K</span> move</span>
        <span><span className="kbd">A</span> approve</span>
        <span><span className="kbd">X</span> reject</span>
        <span><span className="kbd">E</span> edit</span>
        <span>
          <span className="kbd">1</span>–<span className="kbd">5</span> reject reason
        </span>
        {awaitingReason && (
          <span className="font-medium text-marginal">
            Reject as: {REJECT_REASONS.map((r, i) => `${i + 1} ${r.label}`).join("  ·  ")}
          </span>
        )}
        {toast && (
          <span
            role="status"
            className={`ml-auto ${toast.ok ? "text-fast" : "text-marginal"}`}
          >
            {toast.message}
          </span>
        )}
      </footer>
    </div>
  );
}
