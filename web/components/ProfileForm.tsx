"use client";

import { useState } from "react";

import { saveProfileAction, type ActionResult } from "@/app/actions";
import type { Profile, ProfilePatch } from "@/lib/types";

import { Field, inputClass, joinList, monoInputClass, splitList } from "./Field";
import { Toast } from "./Toast";

const SENIORITY = ["intern", "junior", "mid", "senior", "staff", "principal", "lead", "director"];

function asJson(value: unknown): string {
  return JSON.stringify(value ?? [], null, 2);
}

/**
 * The profile the agents work from. Everything here is a fact about the
 * candidate — the Tailor, Scribe and Connector may cite nothing else, so this
 * form is the difference between a tailored package and a plausible fiction.
 */
export function ProfileForm({ initial }: { initial: Profile }) {
  const [draft, setDraft] = useState({
    full_name: initial.full_name ?? "",
    headline: initial.headline ?? "",
    location: initial.location ?? "",
    email: initial.email ?? "",
    phone: initial.phone ?? "",
    seniority: initial.seniority ?? "",
    years_experience: initial.years_experience?.toString() ?? "",
    salary_floor_usd: initial.salary_floor_usd?.toString() ?? "",
    skills: joinList(initial.skills),
    regions: joinList(initial.work_auth?.remote_ok_regions),
    needs_sponsorship: initial.work_auth?.needs_sponsorship ?? true,
    github: initial.links?.github ?? "",
    linkedin: initial.links?.linkedin ?? "",
    portfolio: initial.links?.portfolio ?? "",
    upwork: initial.links?.upwork ?? "",
    roles: asJson(initial.roles),
    education: asJson(initial.education),
    projects: asJson(initial.projects),
  });
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<ActionResult | null>(null);

  const text = (key: keyof typeof draft) => ({
    value: String(draft[key]),
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setDraft((current) => ({ ...current, [key]: event.target.value })),
  });

  const save = () => {
    let roles: unknown;
    let education: unknown;
    let projects: unknown;
    try {
      roles = JSON.parse(draft.roles || "[]");
      education = JSON.parse(draft.education || "[]");
      projects = JSON.parse(draft.projects || "[]");
    } catch (error) {
      setToast({ ok: false, message: `That JSON does not parse: ${(error as Error).message}` });
      return;
    }

    const whole = (value: string) => {
      const parsed = Number.parseInt(value, 10);
      return Number.isFinite(parsed) ? parsed : null;
    };

    const patch: ProfilePatch = {
      full_name: draft.full_name.trim() || null,
      headline: draft.headline.trim() || null,
      location: draft.location.trim() || null,
      email: draft.email.trim() || null,
      phone: draft.phone.trim() || null,
      seniority: draft.seniority || null,
      years_experience: whole(draft.years_experience),
      salary_floor_usd: whole(draft.salary_floor_usd),
      skills: splitList(draft.skills),
      roles: roles as Profile["roles"],
      education: education as Profile["education"],
      projects: projects as Profile["projects"],
      links: {
        github: draft.github.trim(),
        linkedin: draft.linkedin.trim(),
        portfolio: draft.portfolio.trim(),
        upwork: draft.upwork.trim(),
      },
      work_auth: {
        ...(initial.work_auth ?? {}),
        needs_sponsorship: draft.needs_sponsorship,
        remote_ok_regions: splitList(draft.regions),
      },
    };

    setBusy(true);
    void saveProfileAction(patch).then((result) => {
      setBusy(false);
      setToast(result);
    });
  };

  return (
    <section className="rounded-xl border border-edge bg-panel/60 shadow-panel">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-edge/60 px-4 py-3">
        <h2 className="text-sm font-medium text-fg">Profile</h2>
        <p className="text-2xs text-faint">
          The only facts the agents may cite about you. Nothing here is inferred.
        </p>
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="ml-auto rounded-lg border border-accent/40 bg-accent/15 px-3 py-1.5 text-xs
                     font-medium text-accent transition-colors duration-150 hover:bg-accent/25
                     disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save profile"}
        </button>
      </header>

      <div className="grid gap-4 px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Full name">
          <input className={inputClass} {...text("full_name")} />
        </Field>
        <Field label="Headline">
          <input className={inputClass} {...text("headline")} />
        </Field>
        <Field label="Location">
          <input className={inputClass} {...text("location")} />
        </Field>

        <Field label="Email">
          <input className={inputClass} {...text("email")} />
        </Field>
        <Field label="Phone">
          <input className={inputClass} {...text("phone")} />
        </Field>
        <Field label="Seniority">
          <select className={inputClass} {...text("seniority")}>
            <option value="">not stated</option>
            {SENIORITY.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Years of experience">
          <input className={inputClass} inputMode="numeric" {...text("years_experience")} />
        </Field>
        <Field label="Salary floor (USD)" hint="Postings below this score worse; it never blocks.">
          <input className={inputClass} inputMode="numeric" {...text("salary_floor_usd")} />
        </Field>
        <Field label="Remote-ok regions" hint="Comma separated: WORLDWIDE, EMEA, APAC, PK">
          <input className={inputClass} {...text("regions")} />
        </Field>

        <Field label="Skills" hint="Comma separated. Only these may appear in a resume.">
          <input className={inputClass} {...text("skills")} />
        </Field>
        <Field label="GitHub">
          <input className={inputClass} {...text("github")} />
        </Field>
        <Field label="LinkedIn">
          <input className={inputClass} {...text("linkedin")} />
        </Field>

        <Field label="Portfolio">
          <input className={inputClass} {...text("portfolio")} />
        </Field>
        <Field label="Upwork">
          <input className={inputClass} {...text("upwork")} />
        </Field>
        <label className="flex items-center gap-2 self-end pb-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={draft.needs_sponsorship}
            onChange={(event) =>
              setDraft((current) => ({ ...current, needs_sponsorship: event.target.checked }))
            }
            className="h-3.5 w-3.5 rounded border-edge bg-ink accent-accent"
          />
          Needs visa sponsorship
        </label>
      </div>

      <div className="grid gap-4 border-t border-edge/60 px-4 py-4 lg:grid-cols-3">
        <Field label="Roles (JSON)" hint="role_context, title, company, location, dates">
          <textarea rows={7} className={monoInputClass} {...text("roles")} />
        </Field>
        <Field label="Education (JSON)" hint="degree, institution, dates">
          <textarea rows={7} className={monoInputClass} {...text("education")} />
        </Field>
        <Field label="Projects (JSON)" hint="Anything the resume may draw on verbatim.">
          <textarea rows={7} className={monoInputClass} {...text("projects")} />
        </Field>
      </div>

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </section>
  );
}
