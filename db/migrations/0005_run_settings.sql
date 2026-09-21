-- 0005_run_settings.sql — the run console's configuration.
--
-- One row holds what the dashboard's Setup page selects: which Scout platforms
-- to poll, and the filters applied to what they return. The scheduled batches
-- read the same row, so the 02:00/14:00 UTC runs use what the user last chose
-- rather than a compile-time default.
--
-- An empty `platforms` array means "all platforms" — an install that never
-- opens the Setup page behaves exactly as it did before this table existed.

create table if not exists run_settings (
  id uuid primary key default gen_random_uuid(),
  platforms text[] not null default '{}'::text[],
  filters jsonb not null default '{}'::jsonb,
  updated_at timestamptz default now()
);

-- Per-board yield, so a board that returns nothing for weeks is visible next to
-- one that is working, instead of both looking identical in the picker.
alter table source_seeds add column if not exists jobs_found int default 0;
