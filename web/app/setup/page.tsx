import { ApiError } from "@/components/ApiError";
import { ProfileForm } from "@/components/ProfileForm";
import { RunConsole } from "@/components/RunConsole";
import { getProfile, getRunSettings, getSources } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * The console: who the candidate is, where the agents look, what they keep,
 * and the button that starts them with all of it.
 *
 * Profile editing and the run controls degrade independently — a missing
 * run_settings table (migration 0005 not yet run) should not stop you fixing
 * your headline.
 */
export default async function SetupPage() {
  const [profile, sources, settings] = await Promise.allSettled([
    getProfile(),
    getSources(),
    getRunSettings(),
  ]);

  if (profile.status === "rejected") {
    return <ApiError error={profile.reason} />;
  }

  const ready = sources.status === "fulfilled" && settings.status === "fulfilled";
  const blocker =
    settings.status === "rejected"
      ? "Run settings are unavailable — apply db/migrations/0005_run_settings.sql, then reload."
      : sources.status === "rejected"
        ? "Platforms are unavailable — the API could not list its job sources."
        : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.02em] text-fg">Setup</h1>
          <p className="mt-0.5 text-sm text-muted">
            What the agents know about you, where they look, and what they keep.
          </p>
        </div>
        <p className="font-mono text-xs tabular-nums text-faint">
          {ready ? `${sources.value.platforms.length} platforms` : "—"}
        </p>
      </div>

      {blocker && (
        <p className="rounded-xl border border-standard/40 bg-standard/[0.06] px-4 py-3 text-sm text-muted">
          <span aria-hidden className="mr-2 text-standard">
            !
          </span>
          {blocker}
        </p>
      )}

      <ProfileForm initial={profile.value.profile} />

      {ready && (
        <RunConsole
          platforms={sources.value.platforms}
          boards={sources.value.boards}
          settings={settings.value}
        />
      )}
    </div>
  );
}
