# Runbook

## The two batches

| UTC | PKT | Why it exists |
|---|---|---|
| 02:00 | 07:00 | Overnight US postings, plus anything EU posted late the day before |
| 14:00 | 19:00 | **The important one.** EU/UK roles posted that same business morning reach your queue the same day, inside the 72-hour window where response rates are highest |

Both are `.github/workflows/batch.yml`. The job summary carries the counts, so
a batch that went wrong is visible without opening the database.

## Daily loop

1. Open the dashboard. Clear the fast lane first — one button, or `A` through
   the cards.
2. Work the standard tier with the diff visible. Sixty seconds each is the
   budget; if you are spending longer, the bullet bank is the thing to fix.
3. Marginal last, and only if the pipeline is thin.
4. Check `/outreach/due` for follow-ups that have come due. The cadence is
   pre-approved; each body still needs your read.

## When something looks wrong

**The queue is empty.**
Check the last batch: `GET /batch` shows `killed_by_gatekeeper` and
`killed_by_score`. A high gatekeeper number with a thin queue usually means the
seed boards have rotted — run `python db/seeds/verify_boards.py`. A high score
kill usually means the bullet bank is too small to match anything.

**Everything is scoring low.**
The score is 42% skills coverage, and coverage is measured against
`bullet_bank`. A bank of six bullets cannot cover a real job description. Add
bullets before touching the thresholds.

**The Gatekeeper is killing things it should not.**
`jobs.killed_reason` records why, verbatim. If it is a kill phrase that a
company with an EOR route posted anyway, set `companies.hires_internationally`
on that company — the override is exactly what the flag is for.

**The Gatekeeper is passing things it should not.**
Most likely the registers are stale or empty. `select country, count(*) from
sponsor_registers group by 1`. An empty register passes everything, which is
why a failed refresh keeps the previous rows rather than truncating. Check
`register_refreshes` for the last outcome.

**A batch stopped early.**
`stats.quota_exhausted` means the 300-call budget was spent. Unprocessed jobs
stay unanalysed and roll into the next batch on their own. If it happens every
run, the input volume is too high: tighten `scout_max_jobs_per_batch` or prune
the seed list.

**Submissions are failing.**
`GET /health/quota` shows today's counters against the caps. Once
`extension_submit` reaches 20 the Courier refuses rather than queueing, by
design.

**Resumes come out empty.**
`match_bullets` returns nothing for a row with a null `embedding`. Reload the
bank with `python db/seeds/load.py --bullets db/seeds/bullets.json
--replace-bullets`, which embeds on the way in.

**Changing the embedding provider.**
Vectors from `hashing` and `gemini` are not comparable. Switching means
re-embedding every `bullet_bank` and `jobs` row, or dedupe and retrieval both
silently degrade.

## Weekly

- `.github/workflows/registers.yml` refreshes UK, NL and CA on Mondays. Check
  `register_refreshes` afterwards.
- Skim `decisions`. It is what the scorer learns from, and a run of rejections
  for one reason usually means a rule needs changing, not a nudge.

## Monthly

- Re-run `verify_boards.py` and prune. Do it from a network that can reach the
  ATS hosts — behind a restrictive proxy every board looks dead, and the script
  refuses to prune when it cannot tell the difference.
- Prune `jobs` older than the retention you want; Supabase's free tier is 500MB
  and the `description` column is most of it.

## Panic switches

| Want | Do |
|---|---|
| Stop all outbound mail | `MAX_OUTBOUND_EMAILS_PER_DAY=0` |
| Stop all submissions | `MAX_EXTENSION_SUBMITS_PER_DAY=0` |
| Stop discovery, keep processing | `POST /batch/run?skip_scout=true` |
| Stop everything | Disable both workflows; nothing else initiates work |

Nothing in the system submits on a timer. If the dashboard is closed, nothing
goes out.
