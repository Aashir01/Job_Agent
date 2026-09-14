-- 0003_indexes_rpc_rls.sql — indexes, the RPCs the API calls through PostgREST,
-- and row-level security.

-- ── Indexes ────────────────────────────────────────────────────────────────
create index if not exists jobs_dedupe_hash_idx      on jobs (dedupe_hash);
create index if not exists jobs_discovered_at_idx    on jobs (discovered_at desc);
create index if not exists jobs_company_idx          on jobs (company_id);
create index if not exists jobs_track_idx            on jobs (track);
create index if not exists packages_status_idx       on packages (status);
create index if not exists packages_batch_idx        on packages (batch_id);
create index if not exists packages_tier_score_idx   on packages (tier, fit_score desc);
create index if not exists applications_status_idx   on applications (status);
create index if not exists applications_pkg_idx      on applications (package_id);
create index if not exists outreach_app_idx          on outreach (application_id);
create index if not exists contacts_company_idx      on contacts (company_id);
create index if not exists companies_domain_idx      on companies (lower(domain));
create index if not exists companies_name_idx        on companies (lower(name));
create index if not exists llm_calls_batch_idx       on llm_calls (batch_id, created_at desc);
create index if not exists sponsors_lookup_idx       on sponsor_registers (country, org_name_normalised);
create index if not exists extension_queue_status_idx on extension_queue (status, created_at);

-- HNSW works on an empty table; ivfflat would need data to train first.
create index if not exists jobs_embedding_idx
  on jobs using hnsw (embedding vector_cosine_ops);
create index if not exists bullet_bank_embedding_idx
  on bullet_bank using hnsw (embedding vector_cosine_ops);

-- ── Scout: dedupe by embedding cosine > 0.92 (§6) ──────────────────────────
create or replace function match_jobs(
  query_embedding vector(384),
  match_threshold float default 0.92,
  match_count int default 5
)
returns table (id uuid, source_url text, title text, similarity float)
language sql stable as $$
  select j.id, j.source_url, j.title, 1 - (j.embedding <=> query_embedding) as similarity
  from jobs j
  where j.embedding is not null
    and 1 - (j.embedding <=> query_embedding) > match_threshold
  order by j.embedding <=> query_embedding
  limit match_count;
$$;

-- ── Tailor: top-N bullets by similarity to the JD (§6) ─────────────────────
create or replace function match_bullets(
  query_embedding vector(384),
  match_count int default 12,
  min_strength int default 1
)
returns table (
  id uuid, role_context text, text text, metric text,
  tags text[], strength int, similarity float
)
language sql stable as $$
  select b.id, b.role_context, b.text, b.metric, b.tags, b.strength,
         1 - (b.embedding <=> query_embedding) as similarity
  from bullet_bank b
  where b.embedding is not null
    and coalesce(b.strength, 1) >= min_strength
  order by b.embedding <=> query_embedding
  limit match_count;
$$;

-- ── §10 hard daily caps, enforced atomically ───────────────────────────────
-- Returns the new count, or -1 when the cap would be exceeded (nothing written).
create or replace function bump_daily_counter(
  counter_name text,
  cap int,
  amount int default 1
)
returns int
language plpgsql volatile as $$
declare
  today date := (now() at time zone 'utc')::date;
  new_count int;
begin
  insert into daily_counters (day, counter, count)
  values (today, counter_name, 0)
  on conflict (day, counter) do nothing;

  update daily_counters
     set count = count + amount
   where day = today
     and counter = counter_name
     and count + amount <= cap
  returning count into new_count;

  return coalesce(new_count, -1);
end;
$$;

-- ── §8 quota accounting, advisory rather than hard-capped ──────────────────
create or replace function bump_quota(resource_name text, amount int default 1)
returns int
language plpgsql volatile as $$
declare
  today date := (now() at time zone 'utc')::date;
  new_used int;
begin
  insert into quota_ledger (day, resource, used)
  values (today, resource_name, amount)
  on conflict (day, resource)
    do update set used = quota_ledger.used + excluded.used
  returning used into new_used;
  return new_used;
end;
$$;

-- ── Company sponsorship lookup used by the Gatekeeper relocation track ─────
create or replace function normalise_org(name text)
returns text language sql immutable as $$
  select lower(regexp_replace(coalesce(name, ''), '[^a-z0-9]+', '', 'gi'));
$$;

-- Job boards write "Acme", registers write "Acme Ltd". Strip the one trailing
-- corporate suffix so the two keys meet.
create or replace function strip_org_suffix(key text)
returns text language sql immutable as $$
  -- The length guard mirrors normalise_name() in api/app/agents/scout/base.py:
  -- a company actually called "Ltd" keeps its name. The two must agree or the
  -- unique index below and the Gatekeeper's lookups disagree about identity.
  select case
    when coalesce(key, '') ~ '(incorporated|limited|gmbh|bv|ltd|llc|inc|plc|sa|ag)$'
     and length(key) > length((regexp_match(key,
           '(incorporated|limited|gmbh|bv|ltd|llc|inc|plc|sa|ag)$'))[1]) + 2
    then regexp_replace(key, '(incorporated|limited|gmbh|bv|ltd|llc|inc|plc|sa|ag)$', '')
    else coalesce(key, '')
  end;
$$;

create or replace function is_licensed_sponsor(country_code text, company_name text)
returns boolean
language sql stable as $$
  with key as (
    select normalise_org(company_name) as exact,
           strip_org_suffix(normalise_org(company_name)) as stripped
  )
  select exists (
    select 1 from sponsor_registers s, key k
    where s.country = country_code
      and k.exact <> ''
      and (
        s.org_name_normalised = k.exact
        or s.org_name_stripped = k.stripped
        or strip_org_suffix(s.org_name_normalised) = k.stripped
      )
  );
$$;

-- ── One row per company, enforced ──────────────────────────────────────────
-- Scout used to read the company table and compare names in Python, which both
-- re-read the table per job and silently created duplicates once the table grew
-- past the page size. A duplicate company splits `hires_internationally`, which
-- is the one asset the system accumulates, so identity belongs in the database.
-- nullif() rather than a partial index: PostgREST issues a bare
-- `on conflict (name_normalised)`, which Postgres cannot infer against a
-- partial index, so the upsert would fail at runtime. A null key is exempt
-- from a unique index anyway, which gives nameless rows the same escape.
alter table companies
  add column if not exists name_normalised text
  generated always as (nullif(strip_org_suffix(normalise_org(name)), '')) stored;

create unique index if not exists companies_name_normalised_key
  on companies (name_normalised);

-- ── Review queue: the dashboard's single read (§7) ─────────────────────────
create or replace view review_queue as
  select p.id, p.status, p.tier, p.fit_score, p.fit_rationale, p.reasons_against,
         p.eligibility, p.resume_url, p.resume_diff, p.cover_letter,
         p.screening_answers, p.batch_id, p.created_at,
         j.id as job_id, j.title, j.source, j.source_url, j.location_raw,
         j.remote_policy, j.geo_restriction, j.salary_min, j.salary_max,
         j.currency, j.track, j.posted_at,
         c.id as company_id, c.name as company_name, c.domain, c.ats_type,
         c.hires_internationally
  from packages p
  join jobs j on j.id = p.job_id
  left join companies c on c.id = j.company_id;

-- ── RLS ────────────────────────────────────────────────────────────────────
-- Single-operator system. The API holds the service_role key and bypasses RLS;
-- anon gets nothing; a signed-in owner may read and write through PostgREST.
-- Supabase ships the `authenticated` role; a vanilla Postgres does not, and
-- without this guard the whole RLS block aborts there.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
end $$;

do $$
declare t text;
begin
  foreach t in array array[
    'profile','bullet_bank','companies','jobs','packages','contacts',
    'applications','outreach','decisions','batches','llm_calls','quota_ledger',
    'daily_counters','sponsor_registers','register_refreshes','extension_queue',
    'source_seeds','passive_sightings'
  ] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists owner_all on %I', t);
    execute format(
      'create policy owner_all on %I for all to authenticated using (true) with check (true)', t);
  end loop;
end $$;
