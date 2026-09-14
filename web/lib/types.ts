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
