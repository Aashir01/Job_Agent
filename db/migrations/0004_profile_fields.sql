-- 0004_profile_fields.sql — columns `profile` needs but 0001 does not define.
--
-- The seed (`db/seeds/profile.example.json`) and the agents both address these
-- fields directly: the Tailor reads skills/roles/education/projects, the
-- Scorer reads seniority and salary_floor_usd, the Scribe reads
-- years_experience, the Courier and docx_render read email/phone, and the
-- Connector reads education/alumni_networks. Without the columns PostgREST
-- rejects the seed row outright (PGRST204).

alter table profile add column if not exists email text;
alter table profile add column if not exists phone text;
alter table profile add column if not exists seniority text;
alter table profile add column if not exists years_experience int;
alter table profile add column if not exists salary_floor_usd int;
alter table profile add column if not exists skills text[];
alter table profile add column if not exists roles jsonb;
alter table profile add column if not exists education jsonb;
alter table profile add column if not exists projects jsonb;
alter table profile add column if not exists alumni_networks text[];
