/**
 * The API-unreachable panel. Every page renders this instead of its content
 * when the backend cannot be reached, so the failure looks the same everywhere.
 */
export function ApiError({ error }: { error: unknown }) {
  return (
    <div className="animate-fade-in mx-auto max-w-lg rounded-2xl border border-marginal/40 bg-marginal/[0.06] p-6">
      <h1 className="flex items-center gap-2 text-sm font-medium text-marginal">
        <span aria-hidden>!</span> Cannot reach the API
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        {error instanceof Error ? error.message : "unknown error"}
      </p>
      <p className="mt-4 border-t border-marginal/20 pt-3 text-xs text-faint">
        Check <code className="font-mono text-muted">API_URL</code> and{" "}
        <code className="font-mono text-muted">AGENT_KEY</code> in the dashboard environment.
      </p>
    </div>
  );
}
