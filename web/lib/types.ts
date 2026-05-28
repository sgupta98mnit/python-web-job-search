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
  query_text: string | null;
  rejection_reason: string | null;
};

export type JobDescriptionDebug = {
  id: number;
  url: string;
  normalized_url: string;
  status: string;
  http_status: number | null;
  ats: string | null;
  extractor: string;
  body_text: string | null;
  error: string | null;
  latency_ms: number | null;
  fetched_at: string;
};

export type LLMCallDebug = {
  id: number;
  provider: string;
  model: string;
  mode: string;
  attempt: number;
  system_prompt: string;
  user_prompt: string;
  raw_response: Record<string, unknown> | null;
  latency_ms: number | null;
  error: string | null;
};

export type JobEventDebug = {
  id: number;
  run_id: number | null;
  stage: string;
  level: string;
  message: string;
  details: Record<string, unknown> | null;
  created_at: string;
};

export type ApplicationDebug = {
  source: string;
  job_description: JobDescriptionDebug | null;
  llm_call: LLMCallDebug | null;
  events: JobEventDebug[];
};

export type ApplicationDetail = Application & {
  resume_count: number;
  debug?: ApplicationDebug | null;
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

export type SearchSourceExample = {
  url: string;
  score: number | null;
  query_text: string | null;
  application_id: number | null;
};

export type SearchSourceTopQuery = {
  query_text: string;
  count: number;
};

export type SearchSourceHost = {
  host: string;
  result_count: number;
  scored_count: number;
  avg_score: number | null;
  max_score: number | null;
  kept_count: number;
  top_queries: SearchSourceTopQuery[];
  examples: SearchSourceExample[];
};

export type SearchSourcesResponse = {
  total_hosts: number;
  hosts: SearchSourceHost[];
};
