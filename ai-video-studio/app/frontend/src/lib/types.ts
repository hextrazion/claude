export type Health = {
  status: "ok" | "warning" | "error" | "not_configured" | "unavailable";
  message: string;
  detail?: string | null;
  info?: Record<string, unknown>;
  checked_at: string;
};

export type Idea = {
  id: number;
  title: string;
  niche: string;
  central_question: string;
  hook: string;
  description: string;
  appeal: string;
  visual_approach: string;
  est_duration_s: number | null;
  research_needs: string;
  accuracy_concerns: string;
  score: number | null;
  status: "new" | "favorite" | "rejected" | "approved" | "produced";
  duplicate_of: number | null;
  duplicate_score: number | null;
  project_id: number | null;
  source: string;
  notes: string;
  created_at: string;
};

export type Job = {
  id: number;
  project_id: number | null;
  scene_id: number | null;
  kind: string;
  label: string;
  lane: "gpu" | "api" | "cpu";
  status: "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";
  attempts: number;
  max_attempts: number;
  error_message: string | null;
  error_detail: string | null;
  error_kind: string | null;
  provider: string | null;
  progress: number | null;
  progress_message: string | null;
  next_attempt_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  project_title?: string | null;
  scene_number?: number | null;
};

export type ClipMeta = {
  provider: string;
  provider_label: string;
  is_ai: boolean;
  workflow: string;
  prompt: string;
  seed: number;
  width: number;
  height: number;
  frames: number;
  fps: number;
  duration: number | null;
};

export type Scene = {
  id: number;
  project_id: number;
  idx: number;
  narration: string;
  visual_objective: string;
  prompt: string;
  negative_prompt: string;
  camera: string;
  subject_motion: string;
  environment: string;
  style: string;
  duration_s: number;
  needs_image: number;
  image_prompt: string;
  transition: string;
  image_status: string;
  image_path: string | null;
  clip_status: string;
  clip_path: string | null;
  clip_meta: ClipMeta | null;
  flags: string[];
};

export type Segment = { text: string; purpose?: string; visual_idea?: string };

export type Script = {
  title: string;
  segments: Segment[];
  full_text: string;
  word_count: number;
  est_duration_s: number;
  target_duration_s?: number;
  uncertain_claims: string[];
  sources_used: string[];
  model?: string;
  edited?: boolean;
};

export type Source = { id: string; title: string; url: string; snippet: string; domain: string; provider: string };
export type Claim = {
  claim: string;
  status: "verified" | "needs_review" | "speculative" | "unverified" | "contradicted" | "not_checked";
  sources: { title: string; url: string }[];
  evidence: string;
  note: string;
};

export type QcCheck = { id: string; label: string; status: "pass" | "warn" | "fail"; detail: string };

export type NextStep = { action: string; message: string; gate: string | null };

export type Project = {
  id: number;
  idea_id: number | null;
  title: string;
  slug: string;
  folder: string;
  stage: string;
  status: string;
  status_message: string;
  overrides: Record<string, unknown>;
  research: { provider: string | null; sources: Source[]; facts: { fact: string; source_ids: string[] }[]; cautions: string[]; note?: string | null } | null;
  research_status: string;
  script: Script | null;
  script_status: string;
  factcheck: { claims: Claim[]; disclaimer: string } | null;
  scene_plan_status: string;
  narration: {
    path: string;
    duration: number;
    voice_name: string;
    voice_id: string;
    model: string;
    alignment_method: string;
    characters: number;
    cost_usd: number | null;
    generated_at: string;
  } | null;
  narration_status: string;
  export: { path: string; srt_path: string | null; duration: number | null; width: number; height: number; fps: number; created_at: string; library_path?: string } | null;
  export_status: string;
  qc: { checks: QcCheck[]; technical_ok: boolean; failures: number; warnings: number; note: string } | null;
  review_status: string;
  review_note: string;
  archived: number;
  created_at: string;
  updated_at: string;
  scenes: Scene[];
  jobs: Job[];
  next: NextStep;
  gates: { mode: string; auto: boolean; script: boolean; scene_plan: boolean; assembly: boolean };
  effective: Settings;
  idea: Idea | null;
  folder_exists: boolean;
};

export type ProjectSummary = Pick<Project, "id" | "title" | "stage" | "status" | "status_message" | "created_at" | "updated_at" | "export_status" | "review_status" | "archived" | "export"> & {
  scenes: number;
  clips_done: number;
};

// Settings mirror studio/settings.py. Kept loose: the backend validates.
export type Settings = Record<string, any>;

export type Integration = {
  name: string;
  label: string;
  kind: "api" | "local";
  purpose: string;
  docs?: string;
  keys_url?: string;
  health: Health | null;
  key?: { masked: string | null; source: string | null; env_var: string | null; backend: string };
  config?: Record<string, any>;
  rate_limits?: Record<string, string> | null;
};

export type Workflow = {
  name: string;
  label: string;
  kind: "video" | "image";
  mode: string;
  description: string;
  defaults: Record<string, number>;
  requirements: { vram_note?: string; models?: { file: string; folder: string; source: string }[] };
  bindings: Record<string, { node: string; input: string }[]>;
  user: boolean;
  overrides_bundled?: boolean;
  family?: string;
  priority?: number;
  model_slots?: { label: string; input: string }[];
  error?: string;
};

export type Activity = { id: number; ts: string; level: string; category: string; message: string; detail: string | null; project_id: number | null };

export type QueueState = {
  paused: boolean;
  lanes: Record<string, { allowed: boolean; reason: string; running: number; limit: number }>;
  session_gpu_jobs: number;
  counts: Record<string, number>;
  awaiting_approval?: { id: number; title: string; status_message: string; stage: string }[];
};

export type SystemInfo = {
  cpu_pct: number | null;
  ram_used_gb: number;
  ram_total_gb: number;
  gpus: { name: string; utilization_pct: number | null; memory_used_mb: number | null; memory_total_mb: number | null; temperature_c: number | null; power_w: number | null }[] | null;
  disk: { path: string; total_gb: number; free_gb: number; used_pct: number } | null;
  low_disk: boolean;
};
