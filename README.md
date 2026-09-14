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
| `db/migrations/` | Schema. `0001` is the spec's DDL verbatim; `0002` adds operational tables; `0003` adds indexes, pgvector RPCs and RLS |
| `db/seeds/` | Curated company boards, the profile and bullet-bank seeds, and the loaders |
| `api/app/agents/` | Scout, Analyst, Gatekeeper, Tailor, Scribe, Connector, Courier, Chaser |
| `api/app/routes/` | The HTTP surface, including the approval gate |
| `api/tests/` | 126 tests, mostly about the things that must never happen |
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
The Scribe's output is separately audited for figures that appear nowhere in
the verified material.

## Setup

### 1. Database

```bash
psql "$SUPABASE_DB_URL" -f db/migrations/0001_init.sql
psql "$SUPABASE_DB_URL" -f db/migrations/0002_operational.sql
psql "$SUPABASE_DB_URL" -f db/migrations/0003_indexes_rpc_rls.sql
```

Create a private `packages` storage bucket for rendered resumes.

### 2. Configure

```bash
cp .env.example .env
openssl rand -hex 32     # this is your AGENT_KEY
```

Free tiers you need: Supabase, a Gemini API key, Fly.io, Vercel. Optional:
Groq (overflow), Resend (email), Hunter (address verification), Adzuna.

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
cd api && uvicorn app.main:app --reload

# dashboard locally
cd web && npm run dev

# fire a batch by hand
curl -X POST "$API_URL/batch/run?kind=manual&wait=true" -H "X-Agent-Key: $AGENT_KEY"
```

Review at `/`. `J`/`K` move, `A` approves, `X` then `1`–`5` rejects with a
reason, `E` edits. The whole fast lane approves with one button.

## Budget

| Resource | Free limit | Spent per batch |
|---|---|---|
| Gemini Flash | generous RPD | ≤ 300 calls, enforced in `LLMRouter` |
| Groq | rate-limited | overflow only |
| Fly.io | 3 shared VMs | one 256MB machine, asleep between batches |
| Supabase | 500MB | ~40k jobs before pruning |
| GitHub Actions | 2000 min/mo | 2 runs × ~8 min |
| Resend | 3000/mo | ≤ 30 emails/day, capped atomically in Postgres |

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
cd api && python -m pytest          # 126 tests
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
