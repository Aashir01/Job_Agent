"use client";

import { useEffect, useState } from "react";

import { relativeTime } from "@/lib/format";
import type { BatchRow } from "@/lib/types";

const POLL_MS = 30000;

/**
 * The header's quiet answer to "is anything happening right now". A pulsing
 * dot while a batch runs, the last run's age otherwise. Renders nothing when
 * the API cannot be reached — the page body already says so, louder.
 */
export function RunStatus() {
  const [batch, setBatch] = useState<BatchRow | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch("/api/batch/latest", { cache: "no-store" });
        if (!res.ok) return;
        const body = (await res.json()) as { batch: BatchRow | null };
        if (!cancelled) setBatch(body.batch);
      } catch {
        /* the header stays silent; the page body reports the failure */
      }
    };
    void poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (!batch) return null;

  if (batch.status === "running") {
    return (
      <a
        href="/batches"
        className="hidden items-center gap-2 rounded-full border border-accent/30 bg-accent/10
                   px-2.5 py-1 text-2xs text-accent transition-colors duration-150
                   hover:bg-accent/20 md:flex"
      >
        <span aria-hidden className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent" />
        batch running
      </a>
    );
  }

  return (
    <a
      href="/batches"
      className="hidden text-2xs text-faint transition-colors duration-150 hover:text-muted md:block"
      title={`Last batch ${batch.status}`}
    >
      last run {relativeTime(batch.finished_at ?? batch.started_at)}
    </a>
  );
}
