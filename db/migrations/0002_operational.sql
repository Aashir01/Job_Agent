-- 0002_operational.sql — tables the spec implies but does not enumerate:
--   quota accounting (§8), the cost log (§10), hard daily caps (§10),
--   the sponsorship registers the Gatekeeper cross-references (§6),
--   and the extension hand-off queue (§3).

-- One row per batch run. §4 cadence: 02:00 UTC and 14:00 UTC.
create table batches (
  id uuid primary key default gen_random_uuid(),
  kind text not null default 'scheduled',      -- scheduled|manual|backfill
  started_at timestamptz default now(),
  finished_at timestamptz,
  status text default 'running',               -- running|ok|partial|failed
  stats jsonb default '{}'::jsonb,             -- per-stage counts
  error text
);

-- §10: "Log every LLM call with its cost so quota exhaustion is
-- diagnosable, not mysterious."
create table llm_calls (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid references batches,
  job_id uuid references jobs,
  agent text not null,                         -- analyst|scribe|tailor|connector
  provider text not null,                      -- gemini|groq
  model text not null,
  tier text not null,                          -- cheap|good
  prompt_tokens int, completion_tokens int,
  cost_usd numeric(10,6) default 0,            -- 0 on free tiers; still logged
  latency_ms int,
  ok bool default true,
  error text,
  created_at timestamptz default now()
);

-- §8 quota budget, enforced per batch and per UTC day.
create table quota_ledger (
  id uuid primary key default gen_random_uuid(),
  day date not null default (now() at time zone 'utc')::date,
  resource text not null,                      -- gemini_flash|groq|resend|extension_submit
  used int not null default 0,
  unique (day, resource)
);

-- §10 hard caps: 30 outbound emails/day, 20 extension submissions/day.
create table daily_counters (
  day date not null default (now() at time zone 'utc')::date,
  counter text not null,                       -- outbound_email|extension_submit
  count int not null default 0,
  primary key (day, counter)
);

-- §6 Gatekeeper relocation track. Refreshed weekly from the free sources:
--   UK  — Home Office Register of Licensed Sponsors (CSV)
--   NL  — IND Public Register of Recognised Sponsors
--   CA  — LMIA-exempt / Global Talent Stream employers
create table sponsor_registers (
  id uuid primary key default gen_random_uuid(),
  country text not null,                       -- UK|NL|CA
  org_name text not null,
  org_name_normalised text not null,           -- lowercased, punctuation removed
  org_name_stripped text,                      -- the same, minus ltd/bv/gmbh/inc/...
  route text,                                  -- 'Skilled Worker', 'Highly Skilled Migrant', ...
  rating text,
  refreshed_at timestamptz default now()
);

create table register_refreshes (
  id uuid primary key default gen_random_uuid(),
  country text not null,
  row_count int,
  source_url text,
  ok bool default true,
  error text,
  refreshed_at timestamptz default now()
);

-- §3: packages the Courier could not submit via an ATS API are pushed here
-- for the Chrome extension to pick up. The extension fills; the user submits.
create table extension_queue (
  id uuid primary key default gen_random_uuid(),
  package_id uuid references packages unique,
  target_url text not null,
  payload jsonb not null,                      -- field map the content script fills
  status text default 'pending',               -- pending|claimed|filled|submitted|abandoned
  claimed_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz default now()
);

-- The curated seed list Scout polls (§6, sources 1 and 2).
create table source_seeds (
  id uuid primary key default gen_random_uuid(),
  kind text not null,                          -- greenhouse|lever|ashby|workable|smartrecruiters
  slug text not null,                          -- board token, e.g. 'stripe'
  company_name text,
  enabled bool default true,
  last_polled_at timestamptz,
  last_error text,
  unique (kind, slug)
);

-- LinkedIn/Indeed are discovery-only and harvested passively by the extension
-- as the user browses (§6, source 4). Never scraped server-side.
create table passive_sightings (
  id uuid primary key default gen_random_uuid(),
  source text not null,                        -- linkedin|indeed
  source_url text unique,
  title text, company_name text, location_raw text,
  seen_at timestamptz default now(),
  promoted_job_id uuid references jobs
);

-- The Analyst's structured read of the JD (§6). Kept on the job so the
-- Gatekeeper, Tailor and Scribe all work from one parse.
alter table jobs add column if not exists analysis jsonb;
alter table jobs add column if not exists analysed_at timestamptz;
alter table jobs add column if not exists killed_reason text;

-- Cheap partial index for "what still needs analysing".
create index if not exists jobs_unanalysed_idx on jobs (discovered_at desc)
  where analysis is null;

-- §6 Chaser: the cadence is pre-approved but each send's content is not.
-- A follow-up sits here, drafted and due, until a human approves the body.
alter table outreach add column if not exists approved_at timestamptz;
alter table outreach add column if not exists due_at timestamptz;
alter table outreach add column if not exists send_error text;

-- §6 Chaser: the dossier generated the moment a reply lands.
create table if not exists dossiers (
  id uuid primary key default gen_random_uuid(),
  application_id uuid references applications unique,
  content jsonb not null,
  created_at timestamptz default now()
);

-- Gmail watch cursor, so reply polling is incremental.
create table if not exists mail_cursor (
  id int primary key default 1,
  history_id text,
  last_polled_at timestamptz,
  check (id = 1)
);

-- Connector output lives on the package while it waits for the human gate;
-- the Courier materialises it into `outreach` rows once an application exists.
alter table packages add column if not exists outreach_drafts jsonb;
alter table packages add column if not exists referral_plan jsonb;
alter table packages add column if not exists score_components jsonb;
alter table packages add column if not exists warnings text[];
