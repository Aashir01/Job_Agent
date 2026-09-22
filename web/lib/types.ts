export type Tier = "fast_lane" | "standard" | "marginal";
export type PackageStatus =
  | "draft" | "queued" | "approved" | "rejected" | "submitted" | "failed";

export interface Eligibility {
  verdict: "clear" | "uncertain" | "blocked";
  track: "remote_fte" | "relocation" | "contract";
  evidence: string[];
  blockers: string[];
  signals: Record<string, unknown>;
}

export interface DiffOp {
  op: "equal" | "insert" | "delete";
  text: string;
}

export interface DiffEntry {
  bullet_id: string;
  role_context: string | null;
  original: string;
  final: string;
  changed: boolean;
  rejected_rewrite: string | null;
  reject_reason: string | null;
  similarity: number | null;
  ops: DiffOp[];
}

export interface ResumeDiff {
  bullet_count: number;
  changed_count: number;
  verbatim_count: number;
  rejected_rewrites?: number;
  entries: DiffEntry[];
}

export interface ScreeningAnswer {
  question: string;
  answer: string;
  confidence: "high" | "medium" | "low";
}

export interface ReviewPackage {
  id: string;
  status: PackageStatus;
  tier: Tier | null;
  fit_score: number | null;
  fit_rationale: string | null;
  reasons_against: string | null;
  eligibility: Eligibility | null;
  resume_url: string | null;
  resume_diff: ResumeDiff | null;
  cover_letter: string | null;
  screening_answers: {
    answers?: ScreeningAnswer[];
    company_fact?: { text: string; source: string; url: string } | null;
    warnings?: string[];
  } | null;
  batch_id: string | null;
  created_at: string;

  job_id: string;
  title: string | null;
  source: string | null;
  source_url: string | null;
  location_raw: string | null;
  remote_policy: string | null;
  geo_restriction: string[] | null;
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  track: string | null;
  posted_at: string | null;

  company_id: string | null;
  company_name: string | null;
  domain: string | null;
  ats_type: string | null;
  hires_internationally: boolean | null;

  outreach_drafts?: Record<string, string> | null;
  referral_plan?: { kind: string; org: string; company: string; hint: string }[] | null;
  score_components?: Record<string, number> | null;
  warnings?: string[] | null;
}

export interface QueueResponse {
  packages: ReviewPackage[];
  counts: Record<string, number>;
  total: number;
}

export interface ApplicationRow {
  id: string;
  submitted_at: string | null;
  method: string | null;
  status: string;
  last_status_at: string | null;
  packages: {
    tier: Tier | null;
    fit_score: number | null;
    jobs: {
      title: string | null;
      source_url: string | null;
      track: string | null;
      companies: { name: string | null } | null;
    } | null;
  } | null;
}

// §7: `1-5` on the keyboard tags a rejection. Fixed codes so the Sprint 4
// feedback loop has something stable to learn from.
export const REJECT_REASONS = [
  { code: "stack", label: "Wrong stack" },
  { code: "seniority", label: "Wrong seniority" },
  { code: "eligibility", label: "Not actually eligible" },
  { code: "comp", label: "Pay too low" },
  { code: "company", label: "Not this company" },
] as const;

export type BatchStatus = "running" | "ok" | "partial" | "failed";
export type BatchKind = "scheduled" | "manual" | "backfill";

export interface ScoutStats {
  fetched?: number;
  kept?: number;
  duplicates_url?: number;
  duplicates_hash?: number;
  duplicates_embedding?: number;
  stale?: number;
  inserted?: number;
  /** Per-source yield, keyed by the platform (and board slug for ATS sources). */
  by_source?: Record<string, number>;
  /** What the run's filters dropped, by reason. */
  filtered?: Record<string, number>;
  source_errors?: Record<string, string>;
}

/** The Scout's own stats, as stored on a batch. */
export type BatchScoutStats = ScoutStats;

export interface BatchStats {
  /** What the run was asked to do. Empty platforms means "all". */
  platforms?: string[];
  filters?: RunFilters;
  max_jobs?: number;
  llm_budget?: number;
  scout?: ScoutStats;
  analysed?: number;
  killed_by_gatekeeper?: number;
  killed_by_score?: number;
  packages_built?: number;
  tiers?: Record<string, number>;
  rejected_rewrites?: number;
  llm_calls?: number;
  llm_cost_usd?: number;
  llm_by_provider?: Record<string, number>;
  quota_exhausted?: boolean;
  /** Channel → whether the digest reached it when the batch finished. */
  notifications?: Record<string, boolean>;
  errors?: string[];
}

export interface BatchRow {
  id: string;
  kind: BatchKind;
  started_at: string;
  finished_at: string | null;
  status: BatchStatus;
  stats: BatchStats;
  error: string | null;
}

export interface BatchDetail {
  batch: BatchRow;
  llm_by_agent: Record<string, { calls: number; cost_usd: number; failures: number }>;
}

export interface StatsOverview {
  day: string;
  queue: { total: number; by_tier: Record<string, number> };
  funnel: Record<string, number>;
  applications_total: number;
  outreach_due: number;
  extension_queue: Record<string, number>;
  latest_batch: BatchRow | null;
  llm_daily: { day: string; calls: number; cost_usd: number }[];
  decisions_30d: Record<string, number>;
}

export type OutreachKind = "pre_apply" | "follow_up_1" | "follow_up_2" | "thank_you";

export interface DueOutreach {
  id: string;
  application_id: string | null;
  contact_id: string | null;
  kind: OutreachKind | string;
  body: string | null;
  due_at: string | null;
  contacts: {
    name: string | null;
    email: string | null;
    email_confidence: string | null;
  } | null;
  applications: { package_id: string | null; status: string | null } | null;
}

export type ExtensionQueueStatus =
  | "pending" | "claimed" | "filled" | "submitted" | "abandoned";

export interface ExtensionQueueRow {
  id: string;
  package_id: string | null;
  target_url: string;
  status: ExtensionQueueStatus | string;
  claimed_at: string | null;
  completed_at: string | null;
  created_at: string;
  packages: {
    tier: Tier | null;
    jobs: { title: string | null; companies: { name: string | null } | null } | null;
  } | null;
}

/* ── Setup: the profile, the platforms, and the run's filters ───────────── */

export interface ProfileLinks {
  github?: string;
  linkedin?: string;
  portfolio?: string;
  upwork?: string;
  [key: string]: string | undefined;
}

export interface WorkAuth {
  passport?: string;
  current_visas?: string[];
  needs_sponsorship?: boolean;
  remote_ok_regions?: string[];
  [key: string]: unknown;
}

export interface ProfileRole {
  role_context?: string;
  title?: string;
  company?: string;
  location?: string;
  dates?: string;
  [key: string]: unknown;
}

export interface Profile {
  id: string;
  full_name: string | null;
  headline: string | null;
  location: string | null;
  email: string | null;
  phone: string | null;
  seniority: string | null;
  years_experience: number | null;
  salary_floor_usd: number | null;
  skills: string[] | null;
  roles: ProfileRole[] | null;
  education: Record<string, unknown>[] | null;
  projects: Record<string, unknown>[] | null;
  alumni_networks: string[] | null;
  links: ProfileLinks | null;
  work_auth: WorkAuth | null;
}

/** The columns the API accepts on PATCH /profile — the same allow-list. */
export type ProfilePatch = Partial<
  Pick<
    Profile,
    | "full_name"
    | "headline"
    | "location"
    | "email"
    | "phone"
    | "seniority"
    | "years_experience"
    | "salary_floor_usd"
    | "skills"
    | "roles"
    | "education"
    | "projects"
    | "alumni_networks"
    | "links"
    | "work_auth"
  >
>;

/** Everything the run console can ask of the Scout. All optional. */
export interface RunFilters {
  /** Keep postings matching any of these locations, or any remote posting. */
  locations?: string[];
  /** Keep postings whose title or description matches any of these. */
  keywords?: string[];
  /** Drop postings matching any of these. */
  exclude_keywords?: string[];
  remote_only?: boolean;
  salary_floor_usd?: number;
  /** intern | junior | mid | senior | staff | principal | lead | director */
  seniority?: string[];
  /** Overrides SCOUT_MAX_JOBS_PER_BATCH for this run. */
  max_jobs?: number;
  /** Overrides LLM_CALLS_PER_BATCH for this run. */
  llm_calls?: number;
}

export interface PlatformInfo {
  id: string;
  label: string;
  kind: "ats" | "aggregator";
}

export interface BoardInfo {
  id: string;
  kind: string;
  slug: string;
  company_name: string | null;
  enabled: boolean | null;
  last_polled_at: string | null;
  last_error: string | null;
  jobs_found: number | null;
}

export interface SourcesResponse {
  platforms: PlatformInfo[];
  boards: BoardInfo[];
}

export interface RunSettings {
  platforms: string[];
  filters: RunFilters;
  defaults: { max_jobs: number; llm_calls: number };
  ceilings: { max_jobs: number; llm_calls: number };
}

/* ── Notifications ─────────────────────────────────────────────────────── */

export interface NotifyChannel {
  id: "telegram" | "discord" | "slack" | "webhook" | "email";
  active: boolean;
  label: string;
  env: string[];
  how: string;
  /** Which of `env` is still unset — "not configured" is useless when you set
   *  one of two variables and cannot tell which half is missing. */
  missing: string[];
}

export interface NotifyStatus {
  configured: string[];
  any: boolean;
  dashboard_url: string | null;
  notify_on_empty: boolean;
  notify_top_n: number;
  channels: NotifyChannel[];
}

export interface NotifyTestResult {
  sent: boolean;
  reason?: string;
  results: { channel: string; ok: boolean; detail: string }[];
}
