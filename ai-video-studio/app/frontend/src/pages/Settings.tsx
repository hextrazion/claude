import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Upload } from "lucide-react";
import { api } from "../lib/api";
import { useAction, useSaveSettings, useSettings } from "../lib/hooks";
import type { Settings } from "../lib/types";
import { Card, Field, ListInput, Note, NumberInput, PageHeader, Progress, Spinner, Toggle } from "../components/ui";

type Opt = { value: string; label: string };
type Def =
  | { k: string; label: string; type: "number"; min?: number; max?: number; step?: number; hint?: string }
  | { k: string; label: string; type: "text" | "textarea" | "color" | "time"; hint?: string }
  | { k: string; label: string; type: "bool"; hint?: string }
  | { k: string; label: string; type: "select"; options: Opt[]; hint?: string }
  | { k: string; label: string; type: "list"; hint?: string };

const SECTIONS: { id: string; title: string; sub?: string; fields: Def[] }[] = [
  { id: "video", title: "Video format", fields: [
    { k: "duration_s", label: "Default length (s)", type: "number", min: 5, max: 180 },
    { k: "min_duration_s", label: "Minimum length (s)", type: "number", min: 3 },
    { k: "max_duration_s", label: "Maximum length (s)", type: "number", min: 5 },
    { k: "aspect_ratio", label: "Aspect ratio", type: "select", options: ["9:16", "16:9", "1:1", "4:5"].map((v) => ({ value: v, label: v })) },
    { k: "width", label: "Export width", type: "number", min: 240, max: 3840, step: 2 },
    { k: "height", label: "Export height", type: "number", min: 240, max: 3840, step: 2 },
    { k: "fps", label: "Frame rate", type: "number", min: 12, max: 60 },
    { k: "fit_mode", label: "Fit footage to frame", type: "select", options: [{ value: "crop", label: "Fill & crop" }, { value: "blur_pad", label: "Fit with blurred background" }, { value: "black_pad", label: "Fit with black bars" }] },
    { k: "transition", label: "Transition", type: "select", options: [{ value: "cut", label: "Cut" }, { value: "fade", label: "Fade" }, { value: "dissolve", label: "Dissolve" }, { value: "slideup", label: "Slide up" }] },
    { k: "transition_s", label: "Transition length (s)", type: "number", min: 0, max: 1.5, step: 0.05 },
    { k: "tail_padding_s", label: "Hold after narration (s)", type: "number", min: 0, max: 3, step: 0.1 },
    { k: "max_stretch", label: "Max slow-down for short clips", type: "number", min: 1, max: 2, step: 0.05, hint: "Beyond this the last frame is held and the scene is flagged" },
    { k: "crf", label: "Quality (CRF, lower = better)", type: "number", min: 12, max: 30 },
  ] },
  { id: "captions", title: "Captions", fields: [
    { k: "enabled", label: "Captions", type: "bool" },
    { k: "burn_in", label: "Burn into video", type: "bool" },
    { k: "save_srt", label: "Also save .srt file", type: "bool" },
    { k: "uppercase", label: "Uppercase", type: "bool" },
    { k: "font", label: "Font (installed on this PC)", type: "text" },
    { k: "size_pct", label: "Size (% of height)", type: "number", min: 2, max: 15, step: 0.5 },
    { k: "position_pct", label: "Distance from bottom (%)", type: "number", min: 3, max: 80, hint: "~25–35% keeps clear of app buttons and descriptions" },
    { k: "max_words", label: "Words per caption", type: "number", min: 1, max: 8 },
    { k: "max_chars_per_line", label: "Max characters per line", type: "number", min: 8, max: 60 },
    { k: "primary_color", label: "Text colour", type: "color" },
    { k: "highlight_color", label: "Spoken-word colour", type: "color" },
    { k: "outline_color", label: "Outline colour", type: "color" },
    { k: "outline_px", label: "Outline (px)", type: "number", min: 0, max: 20 },
  ] },
  { id: "narration", title: "Narration", sub: "Pick and preview voices on the Integrations page.", fields: [
    { k: "provider", label: "Narration engine", type: "select", options: [{ value: "kokoro", label: "Free voice on this PC (Kokoro)" }, { value: "fish_audio", label: "Fish Audio (paid API)" }] },
    { k: "kokoro_voice", label: "Free voice", type: "text", hint: "e.g. af_heart, am_michael, bf_emma" },
    { k: "voice_id", label: "Fish Audio voice ID", type: "text" },
    { k: "voice_name", label: "Fish Audio voice name", type: "text" },
    { k: "model", label: "Fish Audio model", type: "text" },
    { k: "speed", label: "Speed", type: "number", min: 0.5, max: 2, step: 0.05 },
    { k: "volume", label: "Volume adjustment", type: "number", min: -20, max: 20 },
    { k: "format", label: "Audio format (Fish Audio)", type: "select", options: [{ value: "mp3", label: "MP3" }, { value: "wav", label: "WAV" }] },
    { k: "alignment", label: "Caption timing", type: "select", options: [{ value: "auto", label: "Auto (speech recognition if installed)" }, { value: "whisper", label: "Speech recognition (faster-whisper)" }, { value: "heuristic", label: "Estimate + pause detection" }] },
    { k: "target_lufs", label: "Loudness target (LUFS)", type: "number", min: -30, max: -6 },
    { k: "normalize", label: "Normalise text (numbers, etc.)", type: "bool" },
  ] },
  { id: "generation", title: "Video generation", fields: [
    { k: "style_preset", label: "Global visual style", type: "textarea", hint: "Added to every scene prompt for a consistent look" },
    { k: "negative_prompt", label: "Global negative prompt", type: "textarea" },
    { k: "use_image_stage", label: "Generate stills first for scenes that need them (image → video)", type: "bool" },
    { k: "seed_mode", label: "Seeds", type: "select", options: [{ value: "random", label: "Random each time" }, { value: "fixed", label: "Fixed (reproducible)" }] },
    { k: "fixed_seed", label: "Fixed seed", type: "number", min: 0 },
    { k: "max_retries", label: "Automatic retries per clip", type: "number", min: 0, max: 10, hint: "Only for temporary errors; out-of-memory and invalid workflows are not retried" },
    { k: "job_timeout_s", label: "Clip timeout (s)", type: "number", min: 60 },
  ] },
  { id: "text", title: "Text & research", fields: [
    { k: "model_quality", label: "Groq writing model", type: "text" },
    { k: "model_fast", label: "Groq fast model", type: "text" },
    { k: "temperature", label: "Creativity (temperature)", type: "number", min: 0, max: 2, step: 0.1 },
    { k: "research_enabled", label: "Research before writing", type: "bool" },
    { k: "research_provider", label: "Research provider", type: "select", options: [{ value: "wikipedia", label: "Wikipedia" }, { value: "tavily", label: "Tavily" }, { value: "none", label: "None" }] },
  ] },
  { id: "gates", title: "Approval gates", sub: "Where Supervised and Automated modes stop for you. Supervised always stops before footage.", fields: [
    { k: "script", label: "Approve scripts", type: "bool" },
    { k: "scene_plan", label: "Approve scene plans (Automated mode)", type: "bool" },
    { k: "assembly", label: "Approve before assembly", type: "bool" },
  ] },
  { id: "automation", title: "Automation (Automated mode only)", fields: [
    { k: "auto_generate_ideas", label: "Keep an idea pool topped up", type: "bool" },
    { k: "idea_pool_min", label: "Minimum good ideas in pool", type: "number", min: 0, max: 100 },
    { k: "auto_select_ideas", label: "Start projects from the best ideas", type: "bool" },
    { k: "min_idea_score", label: "Minimum idea score", type: "number", min: 0, max: 10, step: 0.5 },
    { k: "max_active_projects", label: "Max projects in progress", type: "number", min: 1, max: 20 },
  ] },
  { id: "limits", title: "Daily limits", sub: "Protect free tiers and credit. Reset at local midnight.", fields: [
    { k: "max_idea_batches_per_day", label: "Idea batches", type: "number", min: 0 },
    { k: "max_scripts_per_day", label: "Scripts", type: "number", min: 0 },
    { k: "max_tts_chars_per_day", label: "Narration characters", type: "number", min: 0 },
    { k: "max_auto_projects_per_day", label: "Automatic projects", type: "number", min: 0 },
  ] },
  { id: "queue", title: "Queue & resources", fields: [
    { k: "max_gpu_jobs", label: "Concurrent GPU jobs", type: "number", min: 1, max: 4, hint: "1 recommended for 12 GB VRAM" },
    { k: "max_api_jobs", label: "Concurrent API jobs", type: "number", min: 1, max: 8 },
    { k: "max_cpu_jobs", label: "Concurrent FFmpeg jobs", type: "number", min: 1, max: 4 },
    { k: "max_jobs_per_session", label: "GPU jobs per session (0 = no limit)", type: "number", min: 0 },
    { k: "defer_when_gpu_busy", label: "Wait while another app uses the GPU", type: "bool" },
    { k: "gpu_busy_threshold_pct", label: "“Busy” GPU load (%)", type: "number", min: 5, max: 100 },
    { k: "pause_when_processes", label: "Hold GPU jobs while these programs run", type: "list", hint: "Comma-separated process names, e.g. a game .exe" },
    { k: "window_applies_to_api", label: "Processing hours also apply to API jobs", type: "bool" },
    { k: "min_free_disk_gb", label: "Stop generating below free disk (GB)", type: "number", min: 0 },
  ] },
  { id: "storage", title: "Disk space", sub: "Choose the drive itself at the top of this page.", fields: [
    { k: "low_disk_warning_gb", label: "Warn below free space (GB)", type: "number", min: 0 },
    { k: "keep_work_files_days", label: "Keep intermediate files (days)", type: "number", min: 0 },
  ] },
  { id: "pricing", title: "Cost estimates", sub: "Used only for estimates. Check current prices on the providers' websites.", fields: [
    { k: "groq_free_tier", label: "I'm on Groq's free tier (cost $0)", type: "bool" },
    { k: "fish_usd_per_m_chars", label: "Fish Audio $ per million characters", type: "number", min: 0, step: 0.5 },
  ] },
];

const MODES = [
  { value: "manual", title: "Manual", text: "You start every stage. Best while testing." },
  { value: "supervised", title: "Supervised (recommended)", text: "Writes ideas and scripts, then waits for your approval before spending GPU time." },
  { value: "automated", title: "Automated", text: "Works through the queue on its own within your limits, gates and processing hours." },
];

export default function SettingsPage() {
  const { data: s, isLoading } = useSettings();
  if (isLoading || !s) return <div className="page"><Progress /></div>;
  return (
    <div className="page">
      <PageHeader title="Settings" sub="Saved to the local database and kept across restarts." />
      <div className="stack">
        <General s={s} />
        <StorageLocation />
        <div className="grid cols-2">
          {SECTIONS.map((sec) => <Section key={sec.id} id={sec.id} title={sec.title} sub={sec.sub} fields={sec.fields} value={s[sec.id]} />)}
          <MusicSection s={s} />
          <WindowSection s={s} />
        </div>
      </div>
    </div>
  );
}

function General({ s }: { s: Settings }) {
  const save = useSaveSettings();
  const [g, setG] = useState(s.general);
  useEffect(() => setG(s.general), [s.general]);
  const dirty = JSON.stringify(g) !== JSON.stringify(s.general);
  return (
    <Card title="Automation mode & content">
      <div className="grid cols-3">
        {MODES.map((m) => (
          <div key={m.value} className={`mode-card ${g.automation_mode === m.value ? "on" : ""}`} onClick={() => setG({ ...g, automation_mode: m.value })}>
            <h3>{m.title}</h3><div className="small muted">{m.text}</div>
          </div>
        ))}
      </div>
      <div className="form-grid" style={{ marginTop: 16 }}>
        <Field label="Default content niche"><input className="input" value={g.default_niche} onChange={(e) => setG({ ...g, default_niche: e.target.value })} /></Field>
        <Field label="Tone"><input className="input" value={g.tone} onChange={(e) => setG({ ...g, tone: e.target.value })} /></Field>
        <Field label="Log level">
          <select className="select" value={g.log_level} onChange={(e) => setG({ ...g, log_level: e.target.value })}>{["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => <option key={l}>{l}</option>)}</select>
        </Field>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate({ general: g })}>Save</button>
        <span className="tiny faint">Logs are written to logs/studio.log with API keys removed.</span>
      </div>
    </Card>
  );
}

function Section({ id, title, sub, fields, value }: { id: string; title: string; sub?: string; fields: Def[]; value: Record<string, unknown> }) {
  const save = useSaveSettings();
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const dirty = JSON.stringify(v) !== JSON.stringify(value);
  const set = (k: string, x: unknown) => setV({ ...v, [k]: x });
  return (
    <Card title={title} sub={sub}>
      <div className="form-grid">
        {fields.map((f) => (
          <div key={f.k} style={f.type === "textarea" || f.type === "list" ? { gridColumn: "1 / -1" } : undefined}>
            <Field label={f.type === "bool" ? "" : f.label} hint={f.hint}>
              <Control def={f} value={v[f.k]} onChange={(x) => set(f.k, x)} />
            </Field>
          </div>
        ))}
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate({ [id]: v })}>Save</button>
        {dirty && <button className="btn ghost" onClick={() => setV(value)}>Discard</button>}
      </div>
    </Card>
  );
}

function Control({ def, value, onChange }: { def: Def; value: unknown; onChange: (v: unknown) => void }) {
  switch (def.type) {
    case "number":
      return <NumberInput value={value as number} min={def.min} max={def.max} step={def.step} onChange={onChange} />;
    case "bool":
      return <Toggle checked={!!value} onChange={onChange} label={def.label} />;
    case "select":
      return <select className="select" value={value as string} onChange={(e) => onChange(e.target.value)}>{def.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>;
    case "textarea":
      return <textarea className="textarea" rows={3} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "color":
      return <div className="row"><input type="color" value={value as string} onChange={(e) => onChange(e.target.value.toUpperCase())} style={{ width: 40, height: 32, background: "none", border: 0 }} /><input className="input mono" value={value as string} onChange={(e) => onChange(e.target.value)} /></div>;
    case "list":
      return <ListInput value={(value as string[]) ?? []} onChange={onChange} />;
    default:
      return <input className="input" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
}

function MusicSection({ s }: { s: Settings }) {
  const save = useSaveSettings();
  const { data: files } = useQuery({ queryKey: ["music"], queryFn: () => api.get<{ name: string; bytes: number }[]>("/music") });
  const upload = useAction((f: File) => api.upload<{ name: string }>("/music", f), { invalidate: [["music"]], success: "Music added — only use tracks you have rights to" });
  const [m, setM] = useState(s.music);
  useEffect(() => setM(s.music), [s.music]);
  const dirty = JSON.stringify(m) !== JSON.stringify(s.music);
  return (
    <Card title="Background music" sub="Optional. Tracks are read from data/music; the studio never downloads music.">
      <div className="form-grid">
        <Field label=""><Toggle checked={m.enabled} onChange={(x) => setM({ ...m, enabled: x })} label="Add background music" /></Field>
        <Field label="Track">
          <select className="select" value={m.file} onChange={(e) => setM({ ...m, file: e.target.value })}>
            <option value="">None</option>
            {files?.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>
        </Field>
        <Field label="Music volume (dB)"><NumberInput value={m.volume_db} min={-40} max={0} onChange={(x) => setM({ ...m, volume_db: x })} /></Field>
        <Field label=""><Toggle checked={m.ducking} onChange={(x) => setM({ ...m, ducking: x })} label="Duck under narration" /></Field>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate({ music: m })}>Save</button>
        <label className="btn"><Upload size={14} /> Add track<input type="file" accept="audio/*" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} /></label>
      </div>
    </Card>
  );
}

function WindowSection({ s }: { s: Settings }) {
  const save = useSaveSettings();
  const [w, setW] = useState(s.queue.processing_window);
  useEffect(() => setW(s.queue.processing_window), [s.queue.processing_window]);
  const dirty = JSON.stringify(w) !== JSON.stringify(s.queue.processing_window);
  return (
    <Card title="Processing hours" sub="GPU and FFmpeg jobs only start inside this window. Running jobs are never interrupted.">
      <div className="form-grid">
        <Field label=""><Toggle checked={w.enabled} onChange={(x) => setW({ ...w, enabled: x })} label="Limit processing hours" /></Field>
        <Field label="From"><input className="input" type="time" value={w.start} onChange={(e) => setW({ ...w, start: e.target.value })} /></Field>
        <Field label="Until"><input className="input" type="time" value={w.end} onChange={(e) => setW({ ...w, end: e.target.value })} /></Field>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate({ queue: { processing_window: w } })}>Save</button>
      </div>
    </Card>
  );
}

type StorageInfo = {
  location: string;
  projects_dir: string;
  available: boolean;
  export_dir: string;
  default_location: string;
  disk: { free_gb: number; total_gb: number } | null;
  projects: number;
  projects_elsewhere: number;
  move: { status: string; done: number; total: number; current: string; errors: string[] };
};

function StorageLocation() {
  const qc = useQueryClient();
  const { data: info } = useQuery({
    queryKey: ["storage-location"],
    queryFn: () => api.get<StorageInfo>("/storage/location"),
    refetchInterval: (q) => (q.state.data?.move.status === "moving" ? 1000 : false),
  });
  const [path, setPath] = useState("");
  const [move, setMove] = useState(true);
  useEffect(() => {
    if (info && !path) setPath(info.location || "");
  }, [info, path]);
  const pick = useAction(() => api.post<{ path: string | null }>("/storage/choose-folder"));
  const apply = useAction(() => api.post<StorageInfo>("/storage/location", { path, move_existing: move }), {
    invalidate: [["storage-location"], ["settings"], ["system"], ["integrations"]],
    success: move ? "Storage folder set — moving your projects" : "Storage folder set",
  });
  const moveNow = useAction(() => api.post<StorageInfo>("/storage/move"), { invalidate: [["storage-location"]] });
  useEffect(() => {
    if (info?.move.status && info.move.status !== "moving") qc.invalidateQueries({ queryKey: ["projects"] });
  }, [info?.move.status, qc]);
  if (!info) return null;
  const m = info.move;
  const moving = m.status === "moving";
  return (
    <Card title="Where your videos are saved" sub="Projects and finished videos can live on any drive, such as an external SSD.">
      <div className="stack">
        <div className="row wrap">
          <span className="small muted">Current folder:</span>
          <span className="mono small">{info.projects_dir}</span>
          {info.available
            ? info.disk && <span className="small muted">· {info.disk.free_gb} GB free of {info.disk.total_gb} GB</span>
            : <span className="small" style={{ color: "var(--err)" }}>· not available — plug in the drive or choose another folder</span>}
        </div>
        <div className="row">
          <input className="input mono" placeholder="E:\AI Video Studio" value={path} onChange={(e) => setPath(e.target.value)} />
          <button className="btn" disabled={pick.isPending} onClick={() => pick.mutate(undefined, { onSuccess: (r) => r.path && setPath(r.path) })}>
            {pick.isPending ? <Spinner size={14} /> : <FolderOpen size={14} />} Choose folder…
          </button>
        </div>
        {info.projects > 0 && (
          <Toggle checked={move} onChange={setMove} label={`Also move my ${info.projects} existing project${info.projects === 1 ? "" : "s"} there`} />
        )}
        <div className="row wrap">
          <button className="btn primary" disabled={!path.trim() || moving || apply.isPending} onClick={() => apply.mutate()}>Use this folder</button>
          <span className="tiny faint">The studio creates <b>Projects</b> and <b>Library</b> folders inside it. Its small database and the voice model stay on C:.</span>
        </div>
        {moving && (
          <div className="stack tight">
            <div className="small">Moving {m.current}… ({m.done}/{m.total}) — new generations wait until this finishes.</div>
            <Progress value={m.total ? m.done / m.total : null} />
          </div>
        )}
        {m.status === "done" && <Note tone="ok">All projects moved. Each one was copied and checked before the old copy was removed.</Note>}
        {m.status === "done_with_errors" && (
          <Note tone="warn" title="Some projects could not be moved; they are still in their old place and work normally.">
            <ul style={{ margin: 0, paddingLeft: 18 }}>{m.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
          </Note>
        )}
        {m.status === "error" && <Note tone="err">{m.errors.join(" ")}</Note>}
        {!moving && info.projects_elsewhere > 0 && info.location && m.status !== "idle" && (
          <button className="btn sm" onClick={() => moveNow.mutate()}>Try moving the remaining {info.projects_elsewhere} project(s) again</button>
        )}
      </div>
    </Card>
  );
}
