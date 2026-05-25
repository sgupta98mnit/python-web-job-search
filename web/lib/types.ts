export const statuses = [
  "discovered",
  "saved",
  "applied",
  "interview",
  "offer",
  "rejected",
  "ghosted",
  "irrelevant",
] as const;

export type Status = (typeof statuses)[number];

export type Application = {
  id: number;
  run_id: number;
  search_result_id: number;
  llm_call_id: number;
  is_job: boolean;
  title: string;
  company: string;
  location: string;
  remote: boolean;
  score: number;
  reason: string;
  kept: boolean;
  status: Status;
  notes: string | null;
  applied_at: string | null;
  status_updated_at: string;
  created_at: string;
  url: string;
  search_title: string;
  snippet: string;
  engine: string;
};

export type ApplicationDetail = Application & {
  resume_count: number;
};

export type ResumeVersionSummary = {
  id: number;
  scored_result_id: number;
  llm_call_id: number | null;
  generated_at: string;
  model: string;
  prompt_hash: string;
};

export type ResumeVersion = ResumeVersionSummary & {
  tex_content: string;
};

export type OverviewStats = {
  total: number;
  statuses: Record<Status, number>;
  score_buckets: {
    "60-69": number;
    "70-79": number;
    "80-89": number;
    "90-100": number;
  };
};

export type FunnelDay = {
  day: string;
  applied: number;
  interview: number;
  offer: number;
};

export type ApplicationPatch = {
  status?: Status;
  notes?: string | null;
  applied_at?: string | null;
};

export type SerperEstimate = {
  query_count: number;
  page_request_count: number;
  results_per_query: number;
  pages_per_query: number;
};

export type SerperRunStarted = SerperEstimate & {
  run_id: number;
  status: "running";
};
