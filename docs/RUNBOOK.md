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

**Every scheduled run fails within seconds.**
`batch`, `chaser` and `refresh-sponsor-registers` reach the deployed API with
`API_URL` and `AGENT_KEY`, which they read from repository secrets. With the
secrets unset the guard at the top of each job exits in about two seconds —
long before any network call — and the run annotation reads
`API_URL and AGENT_KEY repository secrets must be set`. Set them once, using
the same values the API machine has:

```bash
gh secret set API_URL --body "https://your-app.fly.dev"
gh secret set AGENT_KEY --body "<the same AGENT_KEY the API runs with>"
```

`ci` needs no secrets and passes on its own, so a green `ci` beside red
scheduled runs is this and not a code failure.

**Everything in a package mentions a company I never worked for.**
The database is still holding the `.example` seed, so the agents are writing
about a fictional candidate — the agents read the database, not the files in
`db/seeds/`. Check what they can actually see:

```sql
select role_context, strength from bullet_bank;
```

If that shows the example rows (or nothing), the real seed never landed. Two
things stop it silently:

- `profile.json` carrying a key the `profile` table does not define. PostgREST
  rejects the whole row (PGRST204), so nothing is written and the example row
  survives. `load.py` now drops the unknown field and says so.
- `bullets.json` with `strength: null` on every line. `load.py` refuses an
  unrated bullet by design, so the seed loads zero rows and the previously
  loaded example bullets stay behind. Rate each bullet 1-5, then reload with
  `--replace-bullets` so the demo rows are cleared rather than appended to.

```bash
python db/seeds/load.py --all --replace-bullets
```

**The letter claims something I never did.**
Read the card's *Check before sending* warnings first: the audit flags figures
and technologies that appear nowhere in your profile or bullet bank. It is a
net, not a guarantee — a claim carrying neither a name nor a number ("I
contributed to open-source tooling") still gets through. The letter is a draft
to edit; that is what the human gate is for.

**The queue is empty.**
Check the last batch: `GET /batch` shows `killed_by_gatekeeper` and
`killed_by_score`. A high gatekeeper number with a thin queue usually means the
seed boards have rotted — run `python db/seeds/verify_boards.py`. A high score
kill usually means the bullet bank is too small to match anything.

**Only one platform is contributing.**
Read *Jobs by platform* on the batch detail page. Sources are polled in code
order and the seeds sort `kind.asc`, so a cap applied by arrival order lets
whichever platform sorts first spend the whole allowance on its own — every
stored job can come from one ATS while Greenhouse and the aggregators, all
healthy, are never reached. `_balanced_take` in the Scout interleaves by source
so every platform gets a turn before any gets a second one.

If that is already in place and the queue is still thin, the cap itself is the
problem: a single large board (Databricks alone returns ~876 postings) can
exceed `SCOUT_MAX_JOBS_PER_BATCH` on its own. Raise **max jobs** from the Setup
page rather than editing `.env` — the per-run value overrides the setting and is
recorded on the batch, so the next run is explicable.

**Every source shows zero.**
The platform picker saved a selection and the board you want is not in it. An
empty selection means *all platforms*; a non-empty one means exactly those
listed on the batch detail page under "asked for".

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
