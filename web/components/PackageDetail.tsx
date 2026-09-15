"use client";

import { useEffect, useState } from "react";

import { REJECT_REASONS, type ReviewPackage } from "@/lib/types";

import { ResumeDiffView } from "./ResumeDiff";
import { ScoreMeter, TierBadge } from "./Tier";

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
  const outreach = Object.entries(pkg.outreach_drafts ?? {});

  return (
    <article className="animate-fade-up overflow-hidden rounded-2xl border border-edge bg-panel shadow-raised">
      <header className="bg-raised/50 px-5 py-4">
        <div className="flex items-start gap-5">
          <ScoreMeter score={pkg.fit_score} />

          <div className="min-w-0 flex-1">
            <h2 className="truncate text-xl font-semibold tracking-[-0.01em] text-fg">
              {pkg.title ?? "Untitled role"}
            </h2>
            <p className="mt-0.5 truncate text-sm text-muted">
              <span className="text-fg/90">{pkg.company_name ?? "Unknown company"}</span>
              <span className="mx-1.5 text-faint">·</span>
              {pkg.location_raw ?? "location unknown"}
              {(pkg.salary_min || pkg.salary_max) && (
                <>
                  <span className="mx-1.5 text-faint">·</span>
                  <span className="font-mono text-xs">
                    {pkg.currency ?? ""} {pkg.salary_min?.toLocaleString() ?? "?"}–
                    {pkg.salary_max?.toLocaleString() ?? "?"}
                  </span>
                </>
              )}
            </p>
          </div>

          <div className="flex shrink-0 flex-col items-end gap-2">
            <TierBadge tier={pkg.tier} />
            {pkg.posted_at && (
              <span className="font-mono text-2xs text-faint">
                posted {pkg.posted_at.slice(0, 10)}
              </span>
            )}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-1.5">
          {pkg.track && <Chip>{pkg.track.replace(/_/g, " ")}</Chip>}
          {pkg.remote_policy && <Chip>{pkg.remote_policy.replace(/_/g, " ")}</Chip>}
          {pkg.geo_restriction?.length ? (
            <Chip tone="warn">restricted to {pkg.geo_restriction.join(", ")}</Chip>
          ) : null}
          {pkg.hires_internationally && <Chip tone="good">hires internationally</Chip>}
          {pkg.ats_type && <Chip>{pkg.ats_type}</Chip>}

          <div className="ml-auto flex items-center gap-2">
            {pkg.resume_url && (
              <a
                href={`/api/resume/${pkg.id}`}
                download
                className="inline-flex items-center gap-1.5 rounded-lg border border-edge-strong
                           bg-ink/50 px-2.5 py-1 text-xs text-fg transition-colors
                           duration-150 hover:border-accent/50 hover:text-accent"
              >
                <DownloadIcon /> Resume .docx
              </a>
            )}
            {pkg.source_url && (
              <a
                href={pkg.source_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-edge-strong
                           bg-ink/50 px-2.5 py-1 text-xs text-fg transition-colors
                           duration-150 hover:border-accent/50 hover:text-accent"
              >
                Open posting <ExternalIcon />
              </a>
            )}
          </div>
        </div>
      </header>

      <div className="divide-y divide-edge/60">
        <Section title="Why this scored where it did">
          <p className="text-sm leading-relaxed text-fg/90">{pkg.fit_rationale ?? "—"}</p>
          {pkg.reasons_against && pkg.reasons_against !== "none identified" && (
            <p className="mt-2 text-sm text-marginal">
              <span className="mr-1.5 text-2xs uppercase tracking-wider">Against</span>
              {pkg.reasons_against}
            </p>
          )}
        </Section>

        {elig && (
          <Section title="Eligibility" aside={<Verdict verdict={elig.verdict} />}>
            <ul className="space-y-1 text-sm">
              {elig.evidence.map((line) => (
                <li key={line} className="flex gap-2">
                  <Glyph tone="good">+</Glyph>
                  <span className="text-fg/90">{line}</span>
                </li>
              ))}
              {elig.blockers.map((line) => (
                <li key={line} className="flex gap-2">
                  <Glyph tone="bad">−</Glyph>
                  <span className="text-marginal">{line}</span>
                </li>
              ))}
            </ul>
            {showEverything && elig.signals && Object.keys(elig.signals).length > 0 && (
              <details className="mt-3 group">
                <summary className="cursor-pointer text-2xs uppercase tracking-wider text-faint hover:text-muted">
                  Raw signals
                </summary>
                <pre className="mt-2 overflow-x-auto rounded-lg border border-edge bg-ink/60 p-3 font-mono text-2xs text-muted">
                  {JSON.stringify(elig.signals, null, 2)}
                </pre>
              </details>
            )}
          </Section>
        )}

        {warnings.length > 0 && (
          <Section title="Check before sending">
            <ul className="space-y-1 text-sm">
              {warnings.map((warning) => (
                <li key={warning} className="flex gap-2 text-standard">
                  <Glyph tone="warn">!</Glyph>
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {showBody && (
          <>
            <Section title="Resume diff">
              <ResumeDiffView diff={pkg.resume_diff} />
            </Section>

            <Section
              title="Cover letter"
              aside={
                !editing && pkg.cover_letter ? (
                  <CopyButton text={pkg.cover_letter} />
                ) : undefined
              }
            >
              {editing ? (
                <div className="space-y-3">
                  <textarea
                    value={letter}
                    onChange={(event) => setLetter(event.target.value)}
                    rows={14}
                    className="w-full rounded-lg border border-edge-strong bg-ink/60 p-3.5 font-sans
                               text-sm leading-relaxed text-fg outline-none transition-colors
                               focus:border-accent/60"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => onSave({ cover_letter: letter })}
                      disabled={pending}
                      className="rounded-lg border border-accent/50 bg-accent/10 px-3.5 py-1.5 text-xs
                                 font-medium text-accent transition-colors duration-150
                                 hover:bg-accent/20 disabled:opacity-50"
                    >
                      Save changes
                    </button>
                    <button
                      type="button"
                      onClick={onToggleEdit}
                      className="rounded-lg border border-edge px-3.5 py-1.5 text-xs text-muted
                                 transition-colors duration-150 hover:text-fg"
                    >
                      Cancel <span className="kbd ml-1.5">Esc</span>
                    </button>
                  </div>
                </div>
              ) : (
                <p className="whitespace-pre-wrap text-sm leading-[1.75] text-fg/90">
                  {pkg.cover_letter || <span className="text-faint">Not drafted.</span>}
                </p>
              )}
            </Section>
          </>
        )}

        {showBody && answers.length > 0 && (
          <Section title="Screening answers">
            <ul className="space-y-2.5">
              {answers.map((answer) => (
                <li key={answer.question} className="rounded-lg border border-edge bg-ink/40 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-xs text-muted">{answer.question}</p>
                    {answer.confidence === "low" && (
                      <span className="shrink-0 text-2xs text-marginal">low confidence</span>
                    )}
                  </div>
                  <p className="mt-1.5 text-sm leading-relaxed text-fg/90">{answer.answer}</p>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {showEverything && outreach.length > 0 && (
          <Section
            title="Outreach drafts"
            aside={
              <span className="text-2xs text-faint">nothing sends without approval</span>
            }
          >
            <ul className="space-y-2.5">
              {outreach.map(([kind, body]) => (
                <li key={kind} className="rounded-lg border border-edge bg-ink/40 p-3">
                  <p className="mb-1.5 text-2xs uppercase tracking-wider text-faint">
                    {kind.replace(/_/g, " ")}
                  </p>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg/90">{body}</p>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {showEverything && pkg.referral_plan?.length ? (
          <Section title="Referral leads">
            <ul className="space-y-1 text-sm text-muted">
              {pkg.referral_plan.map((lead) => (
                <li key={lead.hint} className="flex gap-2">
                  <Glyph tone="neutral">›</Glyph>
                  <span>{lead.hint}</span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}
      </div>

      <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-edge bg-ink/90 px-5 py-3 backdrop-blur-xl">
        <button
          type="button"
          onClick={onApprove}
          disabled={pending}
          className="inline-flex items-center gap-2 rounded-lg border border-fast/40 bg-fast/15 px-3.5
                     py-2 text-sm font-medium text-fast transition-colors duration-150
                     hover:bg-fast/25 disabled:opacity-50"
        >
          Approve &amp; submit <span className="kbd kbd-on">A</span>
        </button>
        <button
          type="button"
          onClick={onToggleEdit}
          className="inline-flex items-center gap-2 rounded-lg border border-edge-strong px-3.5 py-2
                     text-sm text-muted transition-colors duration-150 hover:text-fg"
        >
          Edit <span className="kbd">E</span>
        </button>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-2xs uppercase tracking-wider text-faint">Reject</span>
          {REJECT_REASONS.map((reason, index) => (
            <button
              key={reason.code}
              type="button"
              onClick={() => onReject(reason.code)}
              disabled={pending}
              className="inline-flex items-center gap-1.5 rounded-lg border border-edge px-2.5 py-1.5
                         text-2xs text-muted transition-colors duration-150
                         hover:border-marginal/50 hover:text-marginal disabled:opacity-50"
            >
              <span className="kbd">{index + 1}</span>
              {reason.label}
            </button>
          ))}
        </div>
      </div>
    </article>
  );
}

function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="px-5 py-4">
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <h3 className="text-2xs font-medium uppercase tracking-[0.14em] text-faint">{title}</h3>
        {aside}
      </div>
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
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-2xs ${toneClass}`}>{children}</span>
  );
}

function Glyph({ tone, children }: { tone: "good" | "bad" | "warn" | "neutral"; children: React.ReactNode }) {
  const toneClass =
    tone === "good"
      ? "text-fast"
      : tone === "bad"
        ? "text-marginal"
        : tone === "warn"
          ? "text-standard"
          : "text-faint";
  return (
    <span aria-hidden className={`mt-px w-3 shrink-0 text-center font-mono text-xs ${toneClass}`}>
      {children}
    </span>
  );
}

function Verdict({ verdict }: { verdict: "clear" | "uncertain" | "blocked" }) {
  const map = {
    clear: { cls: "border-fast/40 text-fast", glyph: "✓", word: "clear" },
    uncertain: { cls: "border-standard/40 text-standard", glyph: "~", word: "uncertain" },
    blocked: { cls: "border-marginal/40 text-marginal", glyph: "✕", word: "blocked" },
  }[verdict];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-2xs ${map.cls}`}>
      <span aria-hidden>{map.glyph}</span>
      {map.word}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          setCopied(false);
        }
      }}
      className="text-2xs text-faint transition-colors duration-150 hover:text-fg"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function DownloadIcon() {
  return (
    <svg aria-hidden width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path
        d="M6 1v6.5M6 7.5 3.5 5M6 7.5 8.5 5M2 9.5v1h8v-1"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ExternalIcon() {
  return (
    <svg aria-hidden width="11" height="11" viewBox="0 0 12 12" fill="none">
      <path
        d="M4.5 2H2v8h8V7.5M7 1h4v4M11 1 5.5 6.5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
