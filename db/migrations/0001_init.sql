-- 0001_init.sql — core schema, verbatim from the build specification (§5).
-- Run against a Supabase project: psql "$SUPABASE_DB_URL" -f db/migrations/0001_init.sql

create extension if not exists vector;
create extension if not exists pgcrypto;

-- Verified source of truth. Nothing downstream may exceed this.
create table profile (
  id uuid primary key default gen_random_uuid(),
  full_name text, headline text, location text,
  work_auth jsonb,          -- {passport, current_visas, needs_sponsorship: true}
  links jsonb,              -- github, upwork, portfolio, linkedin
  updated_at timestamptz default now()
);

create table bullet_bank (
  id uuid primary key default gen_random_uuid(),
  role_context text,        -- which job/project this came from
  text text not null,       -- the verified achievement, as written by the user
  metric text,              -- the number in it, if any
  tags text[],              -- ['rag','langchain','fastapi','evaluation']
  embedding vector(384),
  strength int              -- 1-5, user-assigned
);

create table companies (
  id uuid primary key default gen_random_uuid(),
  name text, domain text, ats_type text,   -- greenhouse|lever|ashby|workable|other
  uk_sponsor_licensed bool,
  nl_recognised_sponsor bool,
  hires_internationally bool,
  email_pattern text,       -- '{first}.{last}@'
  notes text
);

create table jobs (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies,
  source text, source_url text unique,
  title text, description text,
  posted_at timestamptz, discovered_at timestamptz default now(),
  location_raw text, remote_policy text,   -- global|geo_restricted|hybrid|onsite
  geo_restriction text[],                  -- ['US','EU'] parsed from JD
  salary_min int, salary_max int, currency text,
  track text,                              -- remote_fte|relocation|contract
  dedupe_hash text, embedding vector(384)
);

create table packages (
  id uuid primary key default gen_random_uuid(),
  job_id uuid references jobs,
  status text,              -- draft|queued|approved|rejected|submitted|failed
  tier text,                -- fast_lane|standard|marginal
  fit_score int, fit_rationale text, reasons_against text,
  eligibility jsonb,        -- {verdict, evidence[], blockers[]}
  resume_url text, resume_diff jsonb,
  cover_letter text,
  screening_answers jsonb,
  batch_id uuid,
  created_at timestamptz default now()
);

create table contacts (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies,
  name text, role text, linkedin_url text,
  email text, email_confidence text,   -- verified|pattern_guess|unknown
  referral_path text                   -- how the user is connected, if at all
);

create table applications (
  id uuid primary key default gen_random_uuid(),
  package_id uuid references packages,
  submitted_at timestamptz, method text,   -- ats_api|extension|email
  status text,          -- submitted|acknowledged|replied|screen|interview|offer|rejected|ghosted
  last_status_at timestamptz
);

create table outreach (
  id uuid primary key default gen_random_uuid(),
  application_id uuid references applications,
  contact_id uuid references contacts,
  kind text,            -- pre_apply|follow_up_1|follow_up_2|thank_you
  body text, sent_at timestamptz, replied_at timestamptz
);

-- Every approve/reject trains the scorer.
create table decisions (
  id uuid primary key default gen_random_uuid(),
  package_id uuid references packages,
  verdict text, reason text, edited_fields text[],
  decided_at timestamptz default now()
);
