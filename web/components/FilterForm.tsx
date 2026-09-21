"use client";

import { useState } from "react";

import type { RunFilters } from "@/lib/types";

import { Field, inputClass, joinList, splitList } from "./Field";

const LEVELS = ["intern", "junior", "mid", "senior", "staff", "principal", "lead", "director"];

function build(draft: {
  locations: string;
  keywords: string;
  exclude: string;
  remote_only: boolean;
  salary_floor_usd: string;
  seniority: string[];
  max_jobs: string;
  llm_calls: string;
}): RunFilters {
  const whole = (value: string) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
  };

  const filters: RunFilters = {};
  const locations = splitList(draft.locations);
  if (locations.length) filters.locations = locations;
  const keywords = splitList(draft.keywords);
  if (keywords.length) filters.keywords = keywords;
  const exclude = splitList(draft.exclude);
  if (exclude.length) filters.exclude_keywords = exclude;
  if (draft.remote_only) filters.remote_only = true;
  const floor = whole(draft.salary_floor_usd);
  if (floor) filters.salary_floor_usd = floor;
  if (draft.seniority.length) filters.seniority = draft.seniority;
  const maxJobs = whole(draft.max_jobs);
  if (maxJobs) filters.max_jobs = maxJobs;
  const llmCalls = whole(draft.llm_calls);
  if (llmCalls) filters.llm_calls = llmCalls;
  return filters;
}

/**
 * What the Scout keeps, before anything costs money. Every filter is optional
 * and every one is deterministic — no model is asked whether a job is relevant.
 *
 * Two rules are deliberate: an undisclosed salary is never a reason to drop a
 * posting, and an unlevelled title is ambiguous rather than a mismatch.
 */
export function FilterForm({
  initial,
  defaults,
  ceilings,
  onChange,
}: {
  initial: RunFilters;
  defaults: { max_jobs: number; llm_calls: number };
  ceilings: { max_jobs: number; llm_calls: number };
  onChange: (filters: RunFilters) => void;
}) {
  const [draft, setDraft] = useState({
    locations: joinList(initial.locations),
    keywords: joinList(initial.keywords),
    exclude: joinList(initial.exclude_keywords),
    remote_only: Boolean(initial.remote_only),
    salary_floor_usd: initial.salary_floor_usd?.toString() ?? "",
    seniority: initial.seniority ?? [],
    max_jobs: initial.max_jobs?.toString() ?? "",
    llm_calls: initial.llm_calls?.toString() ?? "",
  });

  const update = (patch: Partial<typeof draft>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    onChange(build(next));
  };

  const toggleLevel = (level: string) =>
    update({
      seniority: draft.seniority.includes(level)
        ? draft.seniority.filter((item) => item !== level)
        : [...draft.seniority, level],
    });

  return (
    <section className="rounded-xl border border-edge bg-panel/60 shadow-panel">
      <header className="border-b border-edge/60 px-4 py-3">
        <h2 className="text-sm font-medium text-fg">Filters</h2>
        <p className="mt-0.5 text-2xs text-faint">
          Applied while discovering, so a posting you cannot use never spends an Analyst call.
        </p>
      </header>

      <div className="grid gap-4 px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Keywords" hint="Keep only postings matching any of these.">
          <input
            className={inputClass}
            placeholder="python, platform engineer"
            value={draft.keywords}
            onChange={(event) => update({ keywords: event.target.value })}
          />
        </Field>
        <Field label="Locations" hint="Remote postings always pass; blanks always pass.">
          <input
            className={inputClass}
            placeholder="london, berlin"
            value={draft.locations}
            onChange={(event) => update({ locations: event.target.value })}
          />
        </Field>
        <Field label="Never show" hint="Drop a posting mentioning any of these.">
          <input
            className={inputClass}
            placeholder="clearance, unpaid"
            value={draft.exclude}
            onChange={(event) => update({ exclude: event.target.value })}
          />
        </Field>

        <Field label="Salary floor (USD)" hint="Disclosed ranges only; undisclosed is never dropped.">
          <input
            className={inputClass}
            inputMode="numeric"
            placeholder="60000"
            value={draft.salary_floor_usd}
            onChange={(event) => update({ salary_floor_usd: event.target.value })}
          />
        </Field>
        <Field label="Max jobs this run" hint={`Blank uses ${defaults.max_jobs} (ceiling ${ceilings.max_jobs}).`}>
          <input
            className={inputClass}
            inputMode="numeric"
            placeholder={String(defaults.max_jobs)}
            value={draft.max_jobs}
            onChange={(event) => update({ max_jobs: event.target.value })}
          />
        </Field>
        <Field label="LLM call budget" hint={`Blank uses ${defaults.llm_calls} (ceiling ${ceilings.llm_calls}).`}>
          <input
            className={inputClass}
            inputMode="numeric"
            placeholder={String(defaults.llm_calls)}
            value={draft.llm_calls}
            onChange={(event) => update({ llm_calls: event.target.value })}
          />
        </Field>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-edge/60 px-4 py-3">
        <button
          type="button"
          onClick={() => update({ remote_only: !draft.remote_only })}
          aria-pressed={draft.remote_only}
          className={`rounded-full border px-3 py-1 text-2xs transition-colors duration-150 ${
            draft.remote_only
              ? "border-accent/40 bg-accent/15 text-accent"
              : "border-edge bg-raised text-muted hover:border-edge-strong hover:text-fg"
          }`}
        >
          remote only
        </button>

        <span className="ml-2 text-2xs uppercase tracking-[0.14em] text-faint">seniority</span>
        {LEVELS.map((level) => {
          const on = draft.seniority.includes(level);
          return (
            <button
              key={level}
              type="button"
              onClick={() => toggleLevel(level)}
              aria-pressed={on}
              className={`rounded-full border px-3 py-1 text-2xs transition-colors duration-150 ${
                on
                  ? "border-accent/40 bg-accent/15 text-accent"
                  : "border-edge bg-raised text-muted hover:border-edge-strong hover:text-fg"
              }`}
            >
              {level}
            </button>
          );
        })}
        <span className="text-2xs text-faint">
          an unlevelled title is kept rather than guessed at
        </span>
      </div>
    </section>
  );
}
