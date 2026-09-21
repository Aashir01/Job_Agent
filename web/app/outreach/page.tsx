import { ApiError } from "@/components/ApiError";
import { OutreachQueue } from "@/components/OutreachQueue";
import { getDueOutreach } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "job-agent — outreach",
};

export default async function OutreachPage() {
  const result = await getDueOutreach().catch((error: unknown) => error as Error);

  if (result instanceof Error) {
    return <ApiError error={result} />;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.02em] text-fg">Outreach</h1>
          <p className="mt-0.5 text-sm text-muted">
            Follow-ups the chaser drafted. The cadence is pre-approved; the words are not.
          </p>
        </div>
        <p className="font-mono text-xs tabular-nums text-faint">
          {result.total} due
        </p>
      </div>

      <OutreachQueue initial={result.due} />
    </div>
  );
}
