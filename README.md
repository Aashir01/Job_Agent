# job-agent

Autonomous job search with one hard rule: **agents draft, a human approves.**
Nothing carrying your name leaves the system without a click.

Runs on free tiers only, and on a laptop that never has to do more than run
Chrome and VS Code.

---

## What it does

Twice a day it discovers postings, reads them, throws away the ones you cannot
actually apply to, and builds a complete application package for the rest —
tailored resume, cover letter, drafted screening answers, and outreach notes.
Then it stops and waits for you.

The scarce resource is not discovery. It is your review time, so the queue is
tiered: a fast-lane package should take ten seconds to clear, a marginal one
two or three minutes.

```
GitHub Actions cron ──HTTP──▶ FastAPI on Fly.io (one 256MB machine)
   02:00 / 14:00 UTC             Scout → Analyst → Gatekeeper
                                     → Tailor → Scribe → Connector
                                     ↓
                              Supabase (Postgres + pgvector + storage)
                                 ↙                        ↘
                   Next.js on Vercel            Chrome extension (MV3)
                   review dashboard             fills forms in your own
                   approve / edit / reject      session; you click Submit
                                 ↓
                         ── HUMAN GATE ──
                                 ↓
                    Courier submits · Chaser follows up
```

## Repository layout

| Path | What lives there |
|---|---|
| `db/migrations/` | Schema. `0001` is the spec's DDL verbatim; `0002` adds operational tables; `0003` adds indexes, pgvector RPCs and RLS; `0004` adds the profile columns the agents read |
| `db/seeds/` | Curated company boards, the profile and bullet-bank seeds, and the loaders |
| `api/app/agents/` | Scout, Analyst, Gatekeeper, Tailor, Scribe, Connector, Courier, Chaser |
| `api/app/llm/` | Providers behind one interface: OpenRouter, Gemini, Groq, and the router that budgets and logs every call |
| `api/app/routes/` | The HTTP surface, including the approval gate and the resume download |
| `api/tests/` | 163 tests, mostly about the things that must never happen |
| `web/` | Next.js review dashboard, keyboard-driven |
| `extension/` | MV3 extension and the tests that enforce its limits |

## The agents

| Agent | Approval | What it does |
|---|---|---|
| **Scout** | none | Polls Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Remotive, RemoteOK, Arbeitnow, Himalayas, WeWorkRemotely, Adzuna and HN "Who is hiring". Dedupes on URL, then a normalised hash, then embedding cosine > 0.92 |
| **Analyst** | none | One cheap strict-JSON call per job: requirements, seniority, salary band, **geo restriction**, sponsorship language, screening questions, and the keywords a resume should mirror |
| **Gatekeeper** | none | Pure rules, no LLM. Kills what you cannot apply to before anything expensive runs |
| **Tailor** | none | Retrieves bullets by similarity, reorders, rewords lightly — and mechanically rejects any rewrite it cannot trace back to the bank |
| **Scribe** | none | Cover letter and screening answers. The one good-model call per package |
| **Connector** | drafts only | Finds the human, guesses and MX-verifies the address, drafts the pre-apply note and both follow-ups |
| — | **human gate** | |
| **Courier** | required | The only agent that submits. Re-reads status from the database first |
| **Chaser** | cadence pre-approved, content per send | Day 3 and day 10 follow-ups, Gmail reply detection, interview dossier |

### The Gatekeeper is where the money is

Killing a package costs one cheap call. Building one costs five. So the
Gatekeeper — and the score — run *before* the Tailor and the Scribe, and both
are free.

Most "remote" jobs are geo-restricted and never say so in the title, so the
remote rules read the body for `Remote (US only)`, `must reside in`,
`EU timezone`, `eligible to work in`. Against that sits the most valuable
signal in the system: a company already running payroll through Deel, Remote.com,
Oyster or Velocity Global can hire from Pakistan with no visa involved. That
evidence sets `companies.hires_internationally`, which is only ever set true
and never cleared by a later silent posting — the asset compounds.

The relocation rules are register lookups, refreshed weekly: the Home Office
Register of Licensed Sponsors, the IND recognised sponsors list, the EU Blue
Card shortage-occupation floor for Germany, and LMIA-exempt employers for
Canada. Not on the register, not eligible.

### No fabricated experience, enforced not requested

The Tailor's rewrite is checked *after* the model speaks:

1. every figure in a rewritten bullet must already exist in its source bullet
2. every content word must come from that bullet or the job description
3. the rewrite may not balloon in length

A rewrite that fails is discarded and your own wording is used verbatim, with
the rejection recorded in the diff so you can see the model tried to drift.

The Scribe's cover letter and screening answers are audited the same way, and the
audit does not stop at figures. A number that appears nowhere in the verified
material is flagged, and so is a technology the letter names that the profile and
the bullet bank cannot evidence — "gained hands-on experience with Kubernetes"
carries no number for a figure check to catch. The job description is deliberately
not part of that allow-list: naming a requirement is not the same as having done it.
Warnings are advisory; they appear on the card under *Check before sending*.

## Setup

### 1. Database

```bash
psql "$SUPABASE_DB_URL" -f db/migrations/0001_init.sql
psql "$SUPABASE_DB_URL" -f db/migrations/0002_operational.sql
psql "$SUPABASE_DB_URL" -f db/migrations/0003_indexes_rpc_rls.sql
psql "$SUPABASE_DB_URL" -f db/migrations/0004_profile_fields.sql
psql "$SUPABASE_DB_URL" -f db/migrations/0005_run_settings.sql
```

No `psql` to hand? Pasting each file into the Supabase SQL Editor in that order
does the same thing. `0004` is not optional: the profile seed and the agents
both address `skills`, `roles`, `education`, `projects`, `seniority`,
`years_experience`, `salary_floor_usd`, `email`, `phone` and `alumni_networks`
directly, and PostgREST rejects a row containing a column that does not exist
(`PGRST204`).

Create a private `packages` storage bucket for rendered resumes. With the
service key it can be made from the command line:

```bash
curl -X POST "$SUPABASE_URL/storage/v1/bucket" \
  -H "apikey: $SUPABASE_SERVICE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"id":"packages","name":"packages","public":false}'
```

Use the **secret** key (`sb_secret_...`) or the legacy `service_role` JWT, not
the publishable/anon key. `0003` enables RLS with a policy for `authenticated`
only, so an anon key reads and writes nothing — and the API is built to bypass
RLS rather than to authenticate as a user.

### 2. Configure

```bash
cp .env.example .env
openssl rand -hex 32     # this is your AGENT_KEY
```

Free tiers you need: Supabase, one LLM key, Fly.io, Vercel. Optional: Resend
(email), Hunter (address verification), Adzuna.

### LLM providers

Three providers sit behind one interface and the router walks them in order,
consuming the per-batch budget once per attempt:

| Order | Provider | Notes |
|---|---|---|
| 1 | **OpenRouter** | One key, many models. Set `OPENROUTER_API_KEY`. Free models work. |
| 2 | Gemini | `GEMINI_API_KEY`. Enforces the response schema server-side. |
| 3 | Groq | `GROQ_API_KEY`. Overflow only. |

Any one of them is enough to run a batch. Two OpenRouter quirks are handled in
`api/app/llm/openrouter.py` and are worth knowing before you change the models:

- **Reasoning is disabled by default** (`OPENROUTER_DISABLE_REASONING=true`).
  Reasoning models otherwise spend the entire token budget on hidden thinking
  and never emit an answer: `nemotron-3.5-lightning` was observed burning 1,586
  of 1,600 tokens on thinking and returning prose instead of JSON.
- **`response_format: json_object` is deliberately not sent.** It is not
  universally supported behind OpenRouter — `ling-3.0-flash-fin` rejects the
  whole request with a 400 and `nemotron-3-ultra` answers with empty content.

Because the schema cannot be enforced server-side over OpenRouter, `LLMRouter`
restates the expected keys in the prompt whenever a `schema` is supplied. That
restatement matters: without it the model invents its own key set and silently
omits `required_skills` and `seniority`, which looks like a thin posting rather
than a bug. Point `OPENROUTER_CHEAP_MODEL` / `OPENROUTER_GOOD_MODEL` at models
you have checked return parseable JSON, and list spares in
`OPENROUTER_FALLBACK_MODELS` — free models rate-limit without warning.

### 3. Seed

```bash
# Verify the board tokens first — they rot, and a dead one is a silent gap.
python db/seeds/verify_boards.py

# Turn your master resume into a bullet-bank draft, then rate every line.
python db/seeds/bootstrap_bullets.py ~/resume.docx > db/seeds/bullets.json
$EDITOR db/seeds/bullets.json     # set strength 1-5; unrated bullets are refused

cp db/seeds/profile.example.json db/seeds/profile.json && $EDITOR db/seeds/profile.json
python db/seeds/load.py --all
```

### 4. Deploy

```bash
cd api && fly launch --no-deploy && fly secrets set $(grep -v '^#' ../.env | xargs) && fly deploy
cd ../web && vercel --prod     # set API_URL and AGENT_KEY as server-side env vars
```

Set `API_URL` and `AGENT_KEY` as GitHub Actions repository secrets so the cron
can reach the API.

### 5. Extension

`chrome://extensions` → Developer mode → Load unpacked → `extension/`. Open its
options and paste the same API URL and agent key.

## Running it

```bash
# API locally
cd api && python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload

# dashboard locally — needs API_URL and AGENT_KEY in web/.env.local
cd web && npm install && npm run dev

# fire a batch by hand
curl -X POST "$API_URL/batch/run?kind=manual&wait=true" -H "X-Agent-Key: $AGENT_KEY"

# skip discovery and only process jobs already stored
curl -X POST "$API_URL/batch/run?kind=manual&skip_scout=true&wait=true" -H "X-Agent-Key: $AGENT_KEY"
```

### The Setup page

Everything the agents hunt with is set at `/setup`, not in a seed file or an
`.env`: your profile, the platforms to poll, the filters applied to what they
return, and the button that starts a run with all of it.

- **Profile** — the facts the Tailor, Scribe and Connector may cite. The API
  rejects an unknown field with a 400 rather than letting PostgREST reject the
  whole row (PGRST204), which is how a real profile once failed to load at all.
- **Platforms** — the twelve fetchable ones, plus the seeded company boards with
  their per-board switch, last-polled time and yield. LinkedIn and Indeed are
  deliberately absent: the extension harvests those from pages you are already
  on, and nothing is scraped server-side.
- **Filters** — `keywords`, `locations`, `exclude_keywords`, `remote_only`,
  `salary_floor_usd`, `seniority`, and per-run overrides for `max_jobs` and the
  LLM budget. All optional, all deterministic, and applied *during discovery*:
  a filtered posting never spends an Analyst call. An undisclosed salary is
  never a reason to drop a posting, and an unlevelled title is ambiguous rather
  than a mismatch.
- **Run** — *Save and run* persists the choices and starts the batch in one
  call, so a run can never go out with a configuration you did not just
  confirm. The scheduled batches read the same row, so the cron inherits it.

An empty platform selection means *all platforms*, so an install that never
opens this page behaves exactly as it did before it existed.

```bash
# the same thing over HTTP, for scripts
curl -X PATCH "$API_URL/run-settings" -H "X-Agent-Key: $AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{"platforms":["greenhouse","remoteok"],"filters":{"keywords":["python"],"max_jobs":200}}'
```

Review at `/`. `J`/`K` move, `A` approves, `X` then `1`–`5` rejects with a
reason, `E` edits. The whole fast lane approves with one button. Each package
carries its posting link and a **Resume .docx** download. That download is
proxied through the API (`GET /packages/{id}/resume`) and then through the
dashboard's `/api/resume/[id]` route, because the storage bucket is private and
the service key must never reach the browser.

A batch that produces nothing is usually not a bug. Watch the two counters it
reports: `killed_by_gatekeeper` means you could not have applied, and
`killed_by_score` means the bullet bank was too thin to evidence the posting.
The score is 42% skills coverage, so a bank of two bullets kills almost
everything. `GET /batch` shows the breakdown for the last runs, and the batch
page now also carries **jobs by platform** — because a cap applied in source
order is the other way a batch comes back empty, however healthy the boards are.

### Windows

Two environment details bite on Windows:

```powershell
# `next dev` fails to compile Tailwind when NODE_ENV=production is inherited
$env:NODE_ENV = "development"; npm run dev

# the same variable makes `npm install` silently skip devDependencies,
# so tsc/tailwind/@types never get installed
npm install --include=dev
```

Set them per-shell rather than globally. Nothing else in the repo is
platform-specific.

## Budget

| Resource | Free limit | Spent per batch |
|---|---|---|
| OpenRouter | free model tier | primary; `:free` models are rate-limited and slow, so the fallback list earns its keep |
| Gemini Flash | generous RPD | fallback, when configured |
| Groq | rate-limited | fallback only |
| Fly.io | 3 shared VMs | one 256MB machine, asleep between batches |
| Supabase | 500MB | ~40k jobs before pruning |
| GitHub Actions | 2000 min/mo | 2 runs × ~8 min |
| Resend | 3000/mo | ≤ 30 emails/day, capped atomically in Postgres |

`LLM_CALLS_PER_BATCH` (default 300) is the hard per-batch ceiling. For a first
run set it low, around 25, and pair it with a low `SCOUT_MAX_JOBS_PER_BATCH` so
a batch finishes in minutes while you watch it. `quota_exhausted: true` in the
batch stats means the ceiling was hit, not that anything failed.

Every LLM call is logged to `llm_calls` with its token counts and cost, so
running out of quota is diagnosable rather than mysterious.

## The limits, kept deliberately

- Resume output traces to `bullet_bank`. No exceptions, no reasonable inference.
- 30 outbound emails and 20 extension submissions a day, enforced with an
  atomic Postgres counter rather than in process memory, so two concurrent
  batches cannot each think they have the full allowance.
- No hidden keyword stuffing. The skills section only lists what the bank can
  evidence.
- The extension never clicks a site's Submit button. `extension/test/` fails
  the build if a `.click()` ever appears in it.
- LinkedIn and Indeed are discovery only, harvested from pages you are already
  looking at. Nothing is scraped server-side.

## Tests

```bash
cd api && python -m pytest          # 163 tests
cd web && npm run typecheck && npm run build
cd extension && npm test            # the invariants above, enforced
```

The API tests are mostly about things that must never happen: no package is
created pre-approved, the Courier refuses anything not approved, a fabricated
bullet never reaches the document, a blocked job never reaches the Tailor, and
the track multipliers are exactly 1.00 / 0.70 / 0.40.

## Build order

1. **Sprint 1 — see the pipeline.** Schema, Scout, Analyst, Gatekeeper, a
   dashboard listing scored jobs. ✅
2. **Sprint 2 — package assembly.** Bullet bank, Tailor, docx template, Scribe,
   resume diff, three-tier review UI. ✅
3. **Sprint 3 — fire.** Courier, the extension, approval end to end,
   applications tracking. ✅
4. **Sprint 4 — compound.** Connector, outreach, Chaser, Gmail replies,
   decisions feeding back into scoring, sponsorship registers. ✅

See [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for operating it day to day and
[`docs/DECISIONS.md`](docs/DECISIONS.md) for why the awkward parts are the way
they are.
