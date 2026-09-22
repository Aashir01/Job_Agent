# Getting it running

Three pieces, all on free tiers. **Only the first is required** — the schedule
runs and messages your phone without any hosting at all.

| # | Piece | Where | Needed for |
|---|---|---|---|
| 1 | Database + the twice-daily run | Supabase + GitHub Actions | Everything. Jobs get found, scored and packaged, and you get a message. |
| 2 | API | Render free tier | The dashboard, the extension |
| 3 | Dashboard | Vercel hobby | Reviewing and approving in a browser |

---

## 1. Database and the scheduled run

### 1a. Supabase

1. Create a project at [supabase.com](https://supabase.com) (free tier).
2. **SQL Editor** → run each migration in order:
   `0001_init` → `0002_operational` → `0003_indexes_rpc_rls` →
   `0004_profile_fields` → `0005_run_settings`
3. **Storage** → create a **private** bucket called `packages` (rendered resumes).
4. **Project Settings → API** → copy the **Project URL** and the
   **`service_role`** key. The service role bypasses RLS; it belongs on servers
   and in Actions secrets, never in a browser or the extension.

### 1b. An LLM key

Any one of these is enough:

- **[OpenRouter](https://openrouter.ai/keys)** — has free models, tried first
- **[Google AI Studio](https://aistudio.google.com/apikey)** — Gemini Flash, generous free tier
- **[Groq](https://console.groq.com/keys)** — fast, rate-limited

### 1c. GitHub secrets

**Settings → Secrets and variables → Actions.** Either tab works:

- **Repository secrets** — simplest, nothing else to configure.
- **Environment secrets** — the scheduled workflows claim the environment named
  by the repository variable `SECRETS_ENVIRONMENT`, defaulting to **`env`**. If
  your environment has a different name, set that variable.

  > Check **Settings → Environments → your environment → Deployment protection
  > rules** and make sure there are **no required reviewers and no wait timer**.
  > A protected environment makes every scheduled run sit waiting for a human
  > click, which defeats the point of a cron.

| Secret | Required | What |
|---|---|---|
| `SUPABASE_URL` | yes | from 1a |
| `SUPABASE_SERVICE_KEY` | yes | the `service_role` key |
| `OPENROUTER_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` | one of | from 1b |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | recommended | see §4 |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | no | one extra job source |
| `RESEND_API_KEY`, `FROM_EMAIL`, `NOTIFY_EMAIL` | no | digest by email |

Under the **Variables** tab (not secrets — these are not sensitive):

| Variable | What |
|---|---|
| `DASHBOARD_URL` | so the digest links to your queue, e.g. `https://job-agent.vercel.app` |
| `LLM_CALLS_PER_BATCH` | defaults to 300 |

### 1d. Seed your profile and bullets

Locally, with `api/requirements.txt` installed and `.env` filled in:

```bash
python db/seeds/bootstrap_bullets.py ~/resume.docx > db/seeds/bullets.json
$EDITOR db/seeds/bullets.json          # set strength 1-5 — unrated ones are refused
cp db/seeds/profile.example.json db/seeds/profile.json && $EDITOR db/seeds/profile.json
python db/seeds/load.py --all
```

The bullet bank is the only thing a resume can be built from, so a thin bank
means thin packages. Ten to thirty real bullets is a good target.

### 1e. Check it

**Actions → doctor → Run workflow.** It changes nothing and applies for
nothing; it just reports which secrets the workflows can see, whether Supabase
answers, and how much seed data is loaded. Once it is green, run **batch**.

> **If a secret you added does not appear in doctor's list**, it is not a
> repository Actions secret, whatever page you added it on. GitHub keeps four
> separate stores and only one of them is readable here:
>
> | Store | Readable by these workflows? |
> |---|---|
> | Secrets and variables → Actions → **Repository secrets** | **yes** |
> | Secrets and variables → Actions → **Environment secrets** | only by a job declaring `environment:` |
> | Secrets and variables → **Dependabot** | no |
> | **Codespaces** secrets | no |
>
> The symptom is silent: an unreadable secret resolves to an empty string with
> no warning, so the job looks configured and behaves as though it is not.

Nothing needs deploying for this to work — the batch runs inside the runner and
talks to Supabase directly.

---

## 2. API on Render (free)

Needed only for the dashboard and the extension.

1. [dashboard.render.com/blueprint/new](https://dashboard.render.com/blueprint/new)
   → connect this repository. `render.yaml` is picked up automatically.
2. Fill in the same `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` and LLM key.
3. Render generates `AGENT_KEY` for you — **copy it**, it is needed twice more.
4. After the first deploy, set `CORS_ORIGINS` and `DASHBOARD_URL` to your
   Vercel URL from step 3.

The free instance sleeps after ~15 minutes idle and takes a few seconds to wake.
That does not affect the schedule, which never touches it.

> Fly.io (`api/fly.toml`) and any Procfile platform work too. Render is
> suggested because its free tier needs no card.

---

## 3. Dashboard on Vercel (free)

1. [vercel.com/new](https://vercel.com/new) → import this repository.
2. **Root Directory: `web`.** Everything else is auto-detected.
3. Environment variables:

   | Name | Value |
   |---|---|
   | `API_URL` | your Render URL, e.g. `https://job-agent-api.onrender.com` |
   | `AGENT_KEY` | the value Render generated |

   Both are server-side only. The key never reaches the browser — `lib/api.ts`
   is `server-only` and every call goes through a server action.
4. Deploy, then put that URL into Render's `CORS_ORIGINS` and `DASHBOARD_URL`,
   and into the repository variable `DASHBOARD_URL`.

---

## 4. Getting told what was found

After every run the system pushes a digest: how many packages were built, the
top matches with scores and links, and a link to the queue. Set up at least one
channel or you will have to remember to look, which is the habit this system
exists to replace.

### Telegram — recommended

Free, instant on a phone, two minutes:

1. Message **[@BotFather](https://t.me/BotFather)** → `/newbot` → copy the token
   → that is `TELEGRAM_BOT_TOKEN`.
2. **Send your new bot any message.** A bot cannot start a conversation with
   you, so skipping this makes every send fail with `chat not found`.
3. Message **[@userinfobot](https://t.me/userinfobot)** → it replies with your
   numeric id → that is `TELEGRAM_CHAT_ID`.

### Discord / Slack

Server Settings → Integrations → Webhooks → copy the URL into
`DISCORD_WEBHOOK_URL`. Slack: api.slack.com/apps → Incoming Webhooks →
`SLACK_WEBHOOK_URL`.

### Email

A [Resend](https://resend.com) account (3000/month free) and a verified sender:
`RESEND_API_KEY`, `FROM_EMAIL`, `NOTIFY_EMAIL`. The digest never spends the
daily outbound-application allowance — that cap exists to protect your sending
reputation with employers, and a note to yourself is not an application.

### WhatsApp

There is no free first-party WhatsApp API — Meta's Cloud API needs a business
account and approved templates. Use `NOTIFY_WEBHOOK_URL` with a relay instead;
[CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/) is free
for personal use. The digest is POSTed as JSON **and** passed as a `?text=`
query parameter, so relays of either shape work.

### Test it

```bash
cd api && python -m app.cli notify-test
```

or from the dashboard: **Settings → Notifications → Send test**.

---

## Where each secret goes

The same values are needed in up to three places. This is the part people get
wrong:

| Secret | GitHub Actions | Render (API) | Vercel (dashboard) |
|---|---|---|---|
| `SUPABASE_URL` | ✅ | ✅ | — |
| `SUPABASE_SERVICE_KEY` | ✅ | ✅ | — |
| LLM key | ✅ | ✅ | — |
| `AGENT_KEY` | — | ✅ (generated) | ✅ (same value) |
| `API_URL` | — | — | ✅ |
| Notification keys | ✅ | ✅ | — |
| `DASHBOARD_URL` | ✅ (variable) | ✅ | — |

The extension needs the API URL and `AGENT_KEY` too, pasted into its options page.

---

## When something is wrong

```bash
cd api && python -m app.cli doctor
```

It prints every setting, whether the database answers, and how many rows are in
the tables that matter. The `batch` workflow runs it as its first step, so a
misconfiguration shows up as a summary table rather than a stack trace.

| Symptom | Cause |
|---|---|
| Workflow fails in seconds | `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` not set |
| "I added the secrets and it still says unset" | Most likely an Environment whose name is not `env` (set `SECRETS_ENVIRONMENT`), or the Variables tab / Dependabot / Codespaces, or another repository. Run **doctor** — it lists what the job can actually see. |
| Scheduled runs sit "waiting" and never start | The environment holding the secrets has a deployment protection rule. Remove the required reviewer. |
| A secret name is right but still empty | Names are case-sensitive; a trailing space in the name creates a different secret |
| Runs fine, queue stays empty | Empty bullet bank, or filters too narrow — see the batch detail page |
| Digest never arrives | Never messaged the bot first (Telegram), or the run genuinely found nothing and `NOTIFY_ON_EMPTY` is off |
| Dashboard says "cannot reach the API" | `API_URL` wrong, `AGENT_KEY` mismatched, or Render still waking |
| Resume download 404s | The `packages` storage bucket does not exist |
| Seed loads but the profile is unchanged | A key the table has no column for — `load.py` reports which |
