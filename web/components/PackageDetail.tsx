"use client";

import { useEffect, useState } from "react";

import { REJECT_REASONS, type ReviewPackage } from "@/lib/types";

import { ResumeDiffView } from "./ResumeDiff";
import { ScorePill, TierBadge } from "./Tier";

/**
 * §7 tiers the detail, not just the queue, because review capacity is the
 * bottleneck. Fast lane is a card you can clear in ten seconds; standard adds
 * the diff and the letter; marginal shows everything, including why the
 * Gatekeeper was unsure.
 */
export function PackageDetail({
  pkg,
  editing,
  pending,
  onApprove,
  onReject,
  onToggleEdit,
  onSave,
}: {
  pkg: ReviewPackage;
  editing: boolean;
  pending: boolean;
  onApprove: () => void;
  onReject: (code: string) => void;
  onToggleEdit: () => void;
  onSave: (patch: Record<string, unknown>) => void;
}) {
  const [letter, setLetter] = useState(pkg.cover_letter ?? "");
  useEffect(() => setLetter(pkg.cover_letter ?? ""), [pkg.id, pkg.cover_letter]);

  const tier = pkg.tier ?? "marginal";
  const showBody = tier !== "fast_lane";
  const showEverything = tier === "marginal";
  const elig = pkg.eligibility;
  const answers = pkg.screening_answers?.answers ?? [];
  const warnings = [...(pkg.warnings ?? []), ...(pkg.screening_answers?.warnings ?? [])];

  return (
    <article className="space-y-4 rounded-xl border border-edge bg-panel/40 p-4">
      <header className="space-y-2">
        <div className="flex items-start gap-3">
          <ScorePill score={pkg.fit_score} />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold">{pkg.title ?? "Untitled role"}</h2>
            <p className="truncate text-sm text-muted">
              {pkg.company_name ?? "Unknown company"} · {pkg.location_raw ?? "—"}
              {pkg.salary_min || pkg.salary_max ? (
                <> · {pkg.currency ?? ""} {pkg.salary_min?.toLocaleString() ?? "?"}–
                  {pkg.salary_max?.toLocaleString() ?? "?"}</>
              ) : null}
            </p>
          </div>
          <TierBadge tier={pkg.tier} />
        </div>

        <div className="flex flex-wrap gap-1.5 text-[11px]">
          {pkg.track && <Chip>{pkg.track.replace(/_/g, " ")}</Chip>}
          {pkg.remote_policy && <Chip>{pkg.remote_policy.replace(/_/g, " ")}</Chip>}
          {pkg.geo_restriction?.length ? <Chip tone="warn">{pkg.geo_restriction.join(", ")}</Chip> : null}
          {pkg.hires_internationally && <Chip tone="good">hires internationally</Chip>}
          {pkg.ats_type && <Chip>{pkg.ats_type}</Chip>}
          {pkg.source_url && (
            <a
              href={pkg.source_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-full border border-edge px-2 py-0.5 text-muted hover:text-slate-200"
            >
              posting ↗
            </a>
          )}
        </div>
      </header>

      <Section title="Why this scored where it did">
        <p className="text-sm">{pkg.fit_rationale ?? "—"}</p>
        {pkg.reasons_against && pkg.reasons_against !== "none identified" && (
          <p className="mt-1.5 text-sm text-marginal">Against: {pkg.reasons_against}</p>
        )}
      </Section>

      {elig && (
        <Section title={`Eligibility — ${elig.verdict}`}>
          <ul className="space-y-0.5 text-sm">
            {elig.evidence.map((line) => (
              <li key={line} className="text-fast">+ {line}</li>
            ))}
            {elig.blockers.map((line) => (
              <li key={line} className="text-marginal">− {line}</li>
            ))}
          </ul>
          {showEverything && elig.signals && Object.keys(elig.signals).length > 0 && (
            <pre className="mt-2 overflow-x-auto rounded border border-edge bg-ink/60 p-2 font-mono text-[11px] text-muted">
              {JSON.stringify(elig.signals, null, 2)}
            </pre>
          )}
        </Section>
      )}

      {warnings.length > 0 && (
        <Section title="Check before sending">
          <ul className="space-y-0.5 text-sm text-standard">
            {warnings.map((warning) => (
              <li key={warning}>! {warning}</li>
            ))}
          </ul>
        </Section>
      )}

      {showBody && (
        <>
          <Section title="Resume diff">
            <ResumeDiffView diff={pkg.resume_diff} />
          </Section>

          <Section title="Cover letter">
            {editing ? (
              <div className="space-y-2">
                <textarea
                  value={letter}
                  onChange={(event) => setLetter(event.target.value)}
                  rows={14}
                  className="w-full rounded-lg border border-edge bg-ink/70 p-3 font-sans text-sm
                             leading-relaxed outline-none focus:border-sky-400/60"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => onSave({ cover_letter: letter })}
                    disabled={pending}
                    className="rounded-lg border border-sky-400/40 bg-sky-400/10 px-3 py-1.5
                               text-xs text-sky-200 hover:bg-sky-400/20 disabled:opacity-50"
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    onClick={onToggleEdit}
                    className="rounded-lg border border-edge px-3 py-1.5 text-xs text-muted"
                  >
                    Cancel <span className="kbd ml-1">Esc</span>
                  </button>
                </div>
              </div>
            ) : (
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {pkg.cover_letter || "Not drafted."}
              </p>
            )}
          </Section>
        </>
      )}

      {showBody && answers.length > 0 && (
        <Section title="Screening answers">
          <ul className="space-y-2">
            {answers.map((answer) => (
              <li key={answer.question} className="rounded-lg border border-edge bg-ink/40 p-2.5">
                <p className="text-xs text-muted">
                  {answer.question}
                  {answer.confidence === "low" && (
                    <span className="ml-2 text-marginal">low confidence</span>
                  )}
                </p>
                <p className="mt-1 text-sm">{answer.answer}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {showEverything && pkg.outreach_drafts && Object.keys(pkg.outreach_drafts).length > 0 && (
        <Section title="Outreach drafts (nothing is sent until you approve each one)">
          <ul className="space-y-2">
            {Object.entries(pkg.outreach_drafts).map(([kind, body]) => (
              <li key={kind} className="rounded-lg border border-edge bg-ink/40 p-2.5">
                <p className="text-xs text-muted">{kind.replace(/_/g, " ")}</p>
                <p className="mt-1 whitespace-pre-wrap text-sm">{body}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {showEverything && pkg.referral_plan?.length ? (
        <Section title="Referral leads for the extension to resolve">
          <ul className="space-y-0.5 text-sm text-muted">
            {pkg.referral_plan.map((lead) => (
              <li key={lead.hint}>{lead.hint}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 border-t border-edge pt-3">
        <button
          type="button"
          onClick={onApprove}
          disabled={pending}
          className="rounded-lg border border-fast/40 bg-fast/10 px-3 py-1.5 text-sm
                     font-medium text-fast hover:bg-fast/20 disabled:opacity-50"
        >
          Approve <span className="kbd ml-1">A</span>
        </button>
        <button
          type="button"
          onClick={onToggleEdit}
          className="rounded-lg border border-edge px-3 py-1.5 text-sm text-muted hover:text-slate-200"
        >
          Edit <span className="kbd ml-1">E</span>
        </button>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {REJECT_REASONS.map((reason, index) => (
            <button
              key={reason.code}
              type="button"
              onClick={() => onReject(reason.code)}
              disabled={pending}
              className="rounded-lg border border-edge px-2 py-1 text-[11px] text-muted
                         hover:border-marginal/50 hover:text-marginal disabled:opacity-50"
            >
              <span className="kbd mr-1">{index + 1}</span>
              {reason.label}
            </button>
          ))}
        </div>
      </div>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Chip({ children, tone }: { children: React.ReactNode; tone?: "good" | "warn" }) {
  const toneClass =
    tone === "good"
      ? "border-fast/40 text-fast"
      : tone === "warn"
        ? "border-standard/40 text-standard"
        : "border-edge text-muted";
  return <span className={`rounded-full border px-2 py-0.5 ${toneClass}`}>{children}</span>;
}
