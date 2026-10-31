import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, KeyRound, Play, RefreshCw, RotateCcw, Search, SlidersHorizontal, Trash2, Upload } from "lucide-react";
import { api } from "../lib/api";
import { useAction, useSaveSettings, useSettings } from "../lib/hooks";
import type { Health, Integration, Workflow } from "../lib/types";
import { Badge, Card, ConfirmDialog, Details, ErrorNote, Field, Modal, Note, NumberInput, PageHeader, Progress, Spinner, StatusBadge } from "../components/ui";
import { timeAgo } from "../lib/format";

export default function Integrations() {
  const { data, isLoading, error } = useQuery({ queryKey: ["integrations"], queryFn: () => api.get<Integration[]>("/integrations") });
  const testAll = useAction(() => api.post("/integrations/test-all"), { invalidate: [["integrations"], ["dashboard"]], success: "All services checked" });
  const by = Object.fromEntries((data ?? []).map((i) => [i.name, i]));
  return (
    <div className="page">
      <PageHeader title="Integrations" sub="API keys are stored by the backend in your OS credential store and never sent to the browser."
        actions={<button className="btn" onClick={() => testAll.mutate()} disabled={testAll.isPending}>{testAll.isPending ? <Spinner size={14} /> : <RefreshCw size={14} />} Test all</button>} />
      <ErrorNote error={error} />
      {isLoading ? <Progress /> : (
        <div className="grid cols-2">
          {by.groq && <IntegrationCard i={by.groq}><GroqModels /></IntegrationCard>}
          {by.kokoro && <IntegrationCard i={by.kokoro}><FreeVoice /></IntegrationCard>}
          {by.comfyui && <div style={{ gridColumn: "1 / -1" }}><IntegrationCard i={by.comfyui}><ComfySection /></IntegrationCard></div>}
          {by.fish_audio && <IntegrationCard i={by.fish_audio}><FishVoices /></IntegrationCard>}
          {by.research && <IntegrationCard i={by.research}><ResearchSection /></IntegrationCard>}
          {by.ffmpeg && <IntegrationCard i={by.ffmpeg}><FfmpegHelp /></IntegrationCard>}
          {by.storage && <IntegrationCard i={by.storage}><StorageSection i={by.storage} /></IntegrationCard>}
        </div>
      )}
    </div>
  );
}

function HealthLine({ h }: { h: Health | null }) {
  if (!h) return <div className="small faint">Not tested yet.</div>;
  const tone = h.status === "ok" ? "ok" : h.status === "warning" ? "warn" : h.status === "not_configured" ? "info" : "err";
  return <Note tone={tone} title={h.message} detail={h.detail}><span className="tiny faint">Checked {timeAgo(h.checked_at)}</span></Note>;
}

function IntegrationCard({ i, children }: { i: Integration; children?: ReactNode }) {
  const test = useAction(() => api.post(`/integrations/${i.name}/test`), { invalidate: [["integrations"], ["dashboard"]] });
  return (
    <Card title={i.label} sub={i.purpose}
      actions={<>
        {i.health && <StatusBadge status={i.health.status} />}
        <button className="btn sm" onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? <Spinner size={13} /> : <RefreshCw size={13} />} Test</button>
      </>}>
      <div className="stack">
        <HealthLine h={i.health} />
        {i.key && <KeyField i={i} />}
        {children}
        <div className="row small">
          {i.docs && <a href={i.docs} target="_blank" rel="noreferrer noopener" className="row"><BookOpen size={13} /> Documentation</a>}
          {i.keys_url && <a href={i.keys_url} target="_blank" rel="noreferrer noopener" className="row"><KeyRound size={13} /> Get an API key</a>}
        </div>
      </div>
    </Card>
  );
}

function KeyField({ i }: { i: Integration }) {
  const [value, setValue] = useState("");
  const [confirm, setConfirm] = useState(false);
  const inv = { invalidate: [["integrations"], ["dashboard"]] };
  const save = useAction(() => api.put(`/integrations/${i.name}/key`, { api_key: value }), { ...inv, success: "Key saved and tested" });
  const remove = useAction(() => api.del(`/integrations/${i.name}/key`), { ...inv, success: "Key removed" });
  const k = i.key!;
  return (
    <div className="stack tight">
      <div className="label">API key</div>
      {k.masked && (
        <div className="row small">
          <span className="mono">{k.masked}</span>
          <Badge>{k.source}</Badge>
          <div className="spacer" />
          {k.source !== `environment variable ${k.env_var}` && <button className="btn icon ghost" title="Remove key" onClick={() => setConfirm(true)}><Trash2 size={13} /></button>}
        </div>
      )}
      <div className="row">
        <input className="input mono" type="password" autoComplete="off" placeholder={k.masked ? "Paste a new key to replace it" : "Paste your API key"} value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn primary" disabled={value.trim().length < 8 || save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => setValue("") })}>Save</button>
      </div>
      <div className="tiny faint">Stored in: {k.backend}. You can also set {k.env_var} in config/studio.env.</div>
      {confirm && <ConfirmDialog title={`Remove the ${i.label} key?`} danger confirmLabel="Remove" onClose={() => setConfirm(false)} onConfirm={() => remove.mutate(undefined, { onSuccess: () => setConfirm(false) })} />}
    </div>
  );
}

function GroqModels() {
  const { data: s } = useSettings();
  const save = useSaveSettings();
  const [load, setLoad] = useState(false);
  const { data: models, error, isFetching } = useQuery({ queryKey: ["groq-models"], queryFn: () => api.get<{ id: string; context_window: number }[]>("/integrations/groq/models"), enabled: load });
  if (!s) return null;
  const options = models?.map((m) => m.id) ?? [];
  const pick = (key: string, value: string) => save.mutate({ text: { [key]: value } });
  const sel = (key: "model_quality" | "model_fast", label: string, hint: string) => (
    <Field label={label} hint={hint}>
      {options.length ? (
        <select className="select" value={s.text[key]} onChange={(e) => pick(key, e.target.value)}>
          {!options.includes(s.text[key]) && <option value={s.text[key]}>{s.text[key]} (not available)</option>}
          {options.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      ) : <input className="input mono" defaultValue={s.text[key]} onBlur={(e) => e.target.value !== s.text[key] && pick(key, e.target.value)} />}
    </Field>
  );
  return (
    <div className="stack">
      <div className="grid cols-2">
        {sel("model_quality", "Writing model", "Ideas, scripts, scene plans")}
        {sel("model_fast", "Fast model", "Search queries, claim listing")}
      </div>
      {!models && <button className="btn sm" onClick={() => setLoad(true)} disabled={isFetching}>{isFetching ? <Spinner size={13} /> : <Search size={13} />} Load available models</button>}
      <ErrorNote error={error} />
      <div className="tiny faint">Free-tier limits change over time; the app tracks rate-limit headers and backs off automatically.</div>
    </div>
  );
}

type LocalVoice = { id: string; name: string; accent: string; gender: string; label: string; recommended: boolean };
type VoiceStatus = { installed: boolean; download_mb: number; download: { status: string; received: number; total: number; error: string | null } };

function FreeVoice() {
  const { data: s } = useSettings();
  const save = useSaveSettings();
  const qc = useQueryClient();
  const { data: st } = useQuery({
    queryKey: ["kokoro-status"],
    queryFn: () => api.get<VoiceStatus>("/integrations/kokoro/status"),
    refetchInterval: (q) => (q.state.data?.download.status === "downloading" ? 1000 : false),
  });
  const { data: voices } = useQuery({ queryKey: ["kokoro-voices", st?.installed], queryFn: () => api.get<{ voices: LocalVoice[] }>("/integrations/kokoro/voices") });
  const download = useAction(() => api.post<VoiceStatus>("/integrations/kokoro/download"), { invalidate: [["kokoro-status"]] });
  const [preview, setPreview] = useState<string | null>(null);
  const previewMut = useAction((voice: string) => api.post<{ url: string }>("/integrations/kokoro/preview", { voice, speed: s?.narration.speed ?? 1 }));
  useEffect(() => {
    if (st?.installed) qc.invalidateQueries({ queryKey: ["integrations"] });
  }, [st?.installed, qc]);
  if (!s) return null;
  const n = s.narration;
  const active = n.provider === "kokoro";
  const dl = st?.download;
  const frac = dl && dl.total ? Math.min(1, dl.received / dl.total) : null;
  return (
    <div className="stack">
      {!active && (
        <Note tone="warn" title="Narration currently uses Fish Audio (paid).">
          <button className="btn sm primary" style={{ marginTop: 6 }} onClick={() => save.mutate({ narration: { provider: "kokoro" } })}>Use the free voice instead</button>
        </Note>
      )}
      {st && !st.installed && (
        dl?.status === "downloading" ? (
          <div className="stack tight">
            <div className="small">Downloading the voice model… {frac != null ? `${Math.round(frac * 100)}%` : ""}</div>
            <Progress value={frac} />
          </div>
        ) : (
          <div className="stack tight">
            {dl?.status === "error" && <Note tone="err">{dl.error}</Note>}
            <button className="btn primary" onClick={() => download.mutate()}>Download free voice ({st.download_mb} MB, one time)</button>
            <div className="tiny faint">Or just start a video: it downloads automatically the first time narration is needed.</div>
          </div>
        )
      )}
      <div className="grid cols-2">
        <Field label="Voice">
          <select className="select" value={n.kokoro_voice} onChange={(e) => { setPreview(null); save.mutate({ narration: { kokoro_voice: e.target.value } }); }}>
            {(voices?.voices ?? []).map((v) => <option key={v.id} value={v.id}>{v.label}{v.recommended ? " ★" : ""}</option>)}
          </select>
        </Field>
        <Field label="Speed">
          <select className="select" value={String(n.speed)} onChange={(e) => { setPreview(null); save.mutate({ narration: { speed: Number(e.target.value) } }); }}>
            {[0.9, 0.95, 1, 1.05, 1.1, 1.15, 1.2].map((x) => <option key={x} value={String(x)}>{x === 1 ? "Normal" : `${x}×`}</option>)}
          </select>
        </Field>
      </div>
      <div className="row wrap">
        <button className="btn sm" disabled={!st?.installed || previewMut.isPending} onClick={() => previewMut.mutate(n.kokoro_voice, { onSuccess: (r) => setPreview(r.url) })}>
          {previewMut.isPending ? <Spinner size={13} /> : <Play size={13} />} Preview voice
        </button>
        {preview && <audio key={preview} src={preview} controls autoPlay style={{ height: 32 }} />}
      </div>
      <div className="tiny faint">★ = clearest voices. Free and private: generated on your CPU, so it never slows video generation on the GPU.</div>
    </div>
  );
}

type Voice = { id: string; title: string; description: string; languages: string[]; tags: string[]; samples: string[] };

function FishVoices() {
  const { data: s } = useSettings();
  const save = useSaveSettings();
  const [open, setOpen] = useState(false);
  if (!s) return null;
  return (
    <div className="stack">
      {s.narration.provider !== "fish_audio" ? (
        <div className="small muted">Not in use. Fish Audio's API needs paid API credit; the free voice above is used instead.
          {" "}<button className="details-toggle" onClick={() => save.mutate({ narration: { provider: "fish_audio" } })}>Use Fish Audio</button></div>
      ) : <Note tone="info">Narration uses Fish Audio (paid API credit).</Note>}
      <div className="grid cols-2">
        <Field label="Narration voice">
          <div className="row">
            <span className="small ellipsis" style={{ flex: 1 }}>{s.narration.voice_name || s.narration.voice_id || <span style={{ color: "var(--warn)" }}>None selected</span>}</span>
            <button className="btn sm" onClick={() => setOpen(true)}>Choose</button>
          </div>
        </Field>
        <Field label="TTS model" hint="Sent as the 'model' header. Availability depends on your plan.">
          <input className="input mono" defaultValue={s.narration.model} onBlur={(e) => e.target.value !== s.narration.model && save.mutate({ narration: { model: e.target.value.trim() } })} list="fish-models" />
          <datalist id="fish-models"><option value="s2-pro" /><option value="s1" /></datalist>
        </Field>
      </div>
      {open && <VoicePicker onClose={() => setOpen(false)} onPick={(v) => save.mutate({ narration: { voice_id: v.id, voice_name: v.title } }, { onSuccess: () => setOpen(false) })} />}
    </div>
  );
}

function VoicePicker({ onClose, onPick }: { onClose: () => void; onPick: (v: Voice) => void }) {
  const [mine, setMine] = useState(false);
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [manual, setManual] = useState("");
  const { data, error, isFetching } = useQuery({
    queryKey: ["fish-voices", mine, term],
    queryFn: () => api.get<{ total: number; items: Voice[] }>(`/integrations/fish_audio/voices?mine=${mine}&q=${encodeURIComponent(term)}`),
  });
  return (
    <Modal wide title="Choose a narration voice" onClose={onClose}>
      <div className="row">
        <div className="segmented"><button className={!mine ? "on" : ""} onClick={() => setMine(false)}>Public voices</button><button className={mine ? "on" : ""} onClick={() => setMine(true)}>My voices</button></div>
        <input className="input" placeholder="Search by name" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setTerm(q)} />
        <button className="btn" onClick={() => setTerm(q)}><Search size={14} /></button>
      </div>
      <ErrorNote error={error} />
      {isFetching ? <Progress /> : (
        <div className="list" style={{ maxHeight: 420, overflowY: "auto" }}>
          {data?.items.map((v) => (
            <div className="list-item" key={v.id}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 550 }}>{v.title}</div>
                <div className="tiny muted ellipsis">{v.description}</div>
                <div className="chips" style={{ marginTop: 4 }}>{v.languages.map((l) => <Badge key={l}>{l}</Badge>)}{v.tags.map((t) => <Badge key={t}>{t}</Badge>)}</div>
              </div>
              {v.samples[0] && <audio controls preload="none" src={v.samples[0]} style={{ height: 32, width: 200 }} />}
              <button className="btn sm primary" onClick={() => onPick(v)}><Check size={13} /> Use</button>
            </div>
          ))}
          {data && !data.items.length && <div className="small faint">No voices found.</div>}
        </div>
      )}
      <hr className="sep" />
      <Field label="Or paste a voice (model) ID" hint="From the Fish Audio website, e.g. a voice you cloned.">
        <div className="row">
          <input className="input mono" value={manual} onChange={(e) => setManual(e.target.value)} />
          <button className="btn" disabled={manual.trim().length < 6} onClick={() => onPick({ id: manual.trim(), title: manual.trim(), description: "", languages: [], tags: [], samples: [] })}>Use ID</button>
        </div>
      </Field>
    </Modal>
  );
}

function ComfySection() {
  const { data: s } = useSettings();
  const save = useSaveSettings();
  const { data: wf } = useQuery({ queryKey: ["workflows"], queryFn: () => api.get<{ workflows: Workflow[] }>("/workflows") });
  const [url, setUrl] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [detected, setDetected] = useState<{ changed: boolean; reason: string | null; video_workflow: string } | null>(null);
  const detect = useAction(() => api.post<{ changed: boolean; reason: string | null; video_workflow: string }>("/integrations/comfyui/autodetect"),
    { invalidate: [["settings"], ["integrations"], ["workflows"]] });
  if (!s) return null;
  const g = s.generation;
  const workflows = wf?.workflows ?? [];
  const videoWfs = workflows.filter((w) => w.kind === "video").sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100));
  const imageWfs = workflows.filter((w) => w.kind === "image");
  return (
    <div className="stack">
      <div className="form-grid">
        <Field label="Video provider">
          <select className="select" value={g.video_provider} onChange={(e) => save.mutate({ generation: { video_provider: e.target.value } })}>
            <option value="comfyui">ComfyUI — AI video on your GPU</option>
            <option value="draft">Draft cards — FFmpeg placeholders, no AI</option>
          </select>
        </Field>
        <Field label="ComfyUI address" hint="Default http://127.0.0.1:8188. A homelab worker can be used later.">
          <div className="row">
            <input className="input mono" value={url ?? g.comfyui_url} onChange={(e) => setUrl(e.target.value)} />
            {url !== null && url !== g.comfyui_url && <button className="btn sm primary" onClick={() => save.mutate({ generation: { comfyui_url: url } }, { onSuccess: () => setUrl(null) })}>Save</button>}
          </div>
        </Field>
        <Field label="Text-to-video workflow">
          <select className="select" value={g.video_workflow} onChange={(e) => save.mutate({ generation: { video_workflow: e.target.value } })}>
            {videoWfs.filter((w) => w.mode !== "i2v").map((w) => <option key={w.name} value={w.name}>{w.label}</option>)}
          </select>
        </Field>
        <Field label="Image-to-video workflow">
          <select className="select" value={g.i2v_workflow} onChange={(e) => save.mutate({ generation: { i2v_workflow: e.target.value } })}>
            {videoWfs.filter((w) => w.mode === "i2v").map((w) => <option key={w.name} value={w.name}>{w.label}</option>)}
          </select>
        </Field>
        <Field label="Still image workflow (optional)">
          <select className="select" value={g.image_workflow} onChange={(e) => save.mutate({ generation: { image_workflow: e.target.value } })}>
            <option value="">None</option>
            {imageWfs.map((w) => <option key={w.name} value={w.name}>{w.label}</option>)}
          </select>
        </Field>
      </div>
      <div className="row wrap">
        <button className="btn primary" disabled={detect.isPending} onClick={() => detect.mutate(undefined, { onSuccess: setDetected })}>
          {detect.isPending ? <Spinner size={14} /> : <Search size={14} />} Auto-detect my model
        </button>
        <span className="small muted">Checks which models (MiniMax H3, Wan…) your ComfyUI has, finds their files, and selects the best one.</span>
      </div>
      {detected && (detected.reason
        ? <Note tone="warn">{detected.reason}</Note>
        : <Note tone="ok">Using {workflows.find((w) => w.name === detected.video_workflow)?.label ?? detected.video_workflow}.</Note>)}
      <div className="row between">
        <div className="section-title">Workflows</div>
        <button className="btn sm" onClick={() => setImporting(true)}><Upload size={13} /> Import from ComfyUI</button>
      </div>
      <div className="list">
        {workflows.map((w) => <WorkflowRow key={w.name} w={w} active={[g.video_workflow, g.i2v_workflow, g.image_workflow].includes(w.name)} />)}
      </div>
      {importing && <ImportWorkflow onClose={() => setImporting(false)} />}
    </div>
  );
}

function frameRule(m?: number, offset = 1) {
  return m && m > 1 ? `${m}n+${offset} frames` : "any frame count";
}

const FRAME_RULES: { label: string; m: number; offset: number }[] = [
  { label: "Any frame count", m: 1, offset: 1 },
  { label: "4n+1 (Wan)", m: 4, offset: 1 },
  { label: "8n+1 (LTX)", m: 8, offset: 1 },
  { label: "17n+5 (MiniMax H3)", m: 17, offset: 5 },
  { label: "2n+1", m: 2, offset: 1 },
  { label: "16n+1", m: 16, offset: 1 },
];

function WorkflowRow({ w, active }: { w: Workflow; active: boolean }) {
  const [result, setResult] = useState<Health | null>(null);
  const [editing, setEditing] = useState(false);
  const check = useAction(() => api.post<Health>(`/workflows/${w.name}/check`));
  const del = useAction(() => api.del(`/workflows/${w.name}`), {
    invalidate: [["workflows"]], success: w.overrides_bundled ? "Restored the bundled version" : "Workflow removed",
  });
  const d = w.defaults ?? {};
  const bySeconds = !!w.bindings?.seconds?.length && !w.bindings?.frames?.length;
  return (
    <div className="list-item" style={{ alignItems: "flex-start" }}>
      <div style={{ flex: 1, minWidth: 0 }} className="stack tight">
        <div className="row wrap">
          <b>{w.label}</b>
          <Badge>{w.mode.toUpperCase()}</Badge>
          {active && <Badge tone="accent">In use</Badge>}
          {w.overrides_bundled ? <Badge tone="warn">Customised</Badge> : w.user && <Badge>Imported</Badge>}
          {d.width && (
            <span className="tiny faint">
              {d.width}×{d.height} · {d.fps} fps · up to {d.max_frames} frames
              {w.kind === "video" && <> · {bySeconds ? "length set in seconds" : frameRule(d.frame_multiple, d.frame_offset ?? 1)}</>}
            </span>
          )}
        </div>
        {w.description && <div className="small muted">{w.description}</div>}
        {w.requirements?.vram_note && <div className="tiny faint">{w.requirements.vram_note}</div>}
        {!!w.requirements?.models?.length && (
          <Details label="Required model files" text={w.requirements.models.map((m) => `${m.file}\n  → ${m.folder}\n  from ${m.source}`).join("\n")} />
        )}
        {result && <HealthLine h={result} />}
      </div>
      <div className="row">
        <button className="btn sm" disabled={check.isPending} onClick={() => check.mutate(undefined, { onSuccess: (r) => setResult(r) })}>{check.isPending ? <Spinner size={13} /> : null} Check</button>
        {w.kind === "video" && <button className="btn sm ghost" onClick={() => setEditing(true)}><SlidersHorizontal size={13} /> Edit frames</button>}
        {w.user && (
          <button className="btn icon ghost" onClick={() => del.mutate()} title={w.overrides_bundled ? "Reset to the bundled version" : "Delete imported workflow"}>
            {w.overrides_bundled ? <RotateCcw size={13} /> : <Trash2 size={13} />}
          </button>
        )}
      </div>
      {editing && <FrameSettings w={w} onClose={() => setEditing(false)} />}
    </div>
  );
}

function FrameSettings({ w, onClose }: { w: Workflow; onClose: () => void }) {
  const d = w.defaults ?? {};
  const [v, setV] = useState({
    width: d.width ?? 704, height: d.height ?? 1280, fps: d.fps ?? 24, max_frames: d.max_frames ?? 121, frame_multiple: d.frame_multiple ?? 1,
    frame_offset: d.frame_offset ?? 1,
  });
  const save = useAction(() => api.patch(`/workflows/${w.name}`, { defaults: v }), { invalidate: [["workflows"]], success: "Frame settings saved" });
  const set = (k: keyof typeof v) => (n: number) => setV({ ...v, [k]: Math.max(1, Math.round(n)) });
  const validMax = v.frame_multiple <= 1 || (v.max_frames - v.frame_offset) % v.frame_multiple === 0;
  const capped = v.max_frames - ((((v.max_frames - v.frame_offset) % v.frame_multiple) + v.frame_multiple) % v.frame_multiple);
  return (
    <Modal title={`Frame settings · ${w.label}`} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn primary" disabled={save.isPending || v.width % 2 !== 0 || v.height % 2 !== 0} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>Save</button>
    </>}>
      <Note>
        These values are sent to ComfyUI for every clip. Use what the model supports: the scene planner keeps each scene within
        <b> max frames ÷ fps</b> seconds{v.fps ? ` (currently ${(v.max_frames / v.fps).toFixed(1)} s)` : ""}.
        {w.overrides_bundled === false && !w.user && " Saving creates a customised copy; you can reset it later."}
      </Note>
      <div className="grid cols-2">
        <Field label="Width" hint="Even number"><NumberInput value={v.width} min={64} max={4096} step={2} onChange={set("width")} /></Field>
        <Field label="Height" hint="Even number"><NumberInput value={v.height} min={64} max={4096} step={2} onChange={set("height")} /></Field>
        <Field label="Frames per second"><NumberInput value={v.fps} min={1} max={60} onChange={set("fps")} /></Field>
        <Field label="Max frames per clip"><NumberInput value={v.max_frames} min={1} max={2000} onChange={set("max_frames")} /></Field>
        <Field label="Frame-count rule" hint="Use the rule your model needs; “any” if it accepts any count.">
          <select className="select" value={`${v.frame_multiple}:${v.frame_offset}`}
            onChange={(e) => { const [m, o] = e.target.value.split(":").map(Number); setV({ ...v, frame_multiple: m, frame_offset: o }); }}>
            {FRAME_RULES.map((r) => <option key={r.label} value={`${r.m}:${r.offset}`}>{r.label}</option>)}
            {!FRAME_RULES.some((r) => r.m === v.frame_multiple && r.offset === v.frame_offset) && (
              <option value={`${v.frame_multiple}:${v.frame_offset}`}>{frameRule(v.frame_multiple, v.frame_offset)}</option>
            )}
          </select>
        </Field>
      </div>
      {!validMax && <Note tone="warn">{v.max_frames} doesn't fit {frameRule(v.frame_multiple, v.frame_offset)}; clips will be capped at {capped} frames.</Note>}
    </Modal>
  );
}

function ImportWorkflow({ onClose }: { onClose: () => void }) {
  const [graph, setGraph] = useState<Record<string, unknown> | null>(null);
  const [fileErr, setFileErr] = useState("");
  const [form, setForm] = useState({ name: "", label: "", kind: "video", mode: "t2v" });
  const [result, setResult] = useState<{ name: string; warnings: string[]; bindings: Record<string, unknown> } | null>(null);
  const imp = useAction(() => api.post<{ name: string; warnings: string[]; bindings: Record<string, unknown> }>("/workflows/import", { ...form, graph }), { invalidate: [["workflows"]] });
  const onFile = async (f: File) => {
    setFileErr("");
    try {
      const data = JSON.parse(await f.text());
      setGraph(data);
      const base = f.name.replace(/\.json$/i, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 50);
      setForm((x) => ({ ...x, name: x.name || base, label: x.label || f.name.replace(/\.json$/i, "") }));
    } catch {
      setFileErr("That file is not valid JSON.");
    }
  };
  return (
    <Modal title="Import a ComfyUI workflow" onClose={onClose} footer={result ? <button className="btn primary" onClick={onClose}>Done</button> : <>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn primary" disabled={!graph || !form.name || imp.isPending} onClick={() => imp.mutate(undefined, { onSuccess: setResult })}>Import</button>
    </>}>
      <Note>In ComfyUI, load a working workflow (for example a built-in Wan 2.2 or LTX-2 template), then use <b>Workflow → Export (API)</b> and choose that file here. The studio detects where the prompt, size, frame count, seed and image go.</Note>
      {!result ? (
        <>
          <input type="file" accept="application/json,.json" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
          {fileErr && <Note tone="err">{fileErr}</Note>}
          <div className="grid cols-2">
            <Field label="Name (id)"><input className="input mono" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Label"><input className="input" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></Field>
            <Field label="Produces"><select className="select" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value, mode: e.target.value === "image" ? "t2i" : "t2v" })}><option value="video">Video</option><option value="image">Still image</option></select></Field>
            <Field label="Input"><select className="select" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
              {form.kind === "video" ? <><option value="t2v">Text → video</option><option value="i2v">Image → video</option></> : <option value="t2i">Text → image</option>}
            </select></Field>
          </div>
        </>
      ) : (
        <div className="stack">
          <Note tone={result.warnings.length ? "warn" : "ok"} title={`Imported as '${result.name}'`}>
            {result.warnings.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul> : "All inputs were detected."}
          </Note>
          <Details label="Detected bindings" text={JSON.stringify(result.bindings, null, 2)} />
          <div className="small muted">Select it as the active workflow above, then press Check to confirm all nodes and model files are installed.</div>
        </div>
      )}
    </Modal>
  );
}

function ResearchSection() {
  const { data: s } = useSettings();
  const save = useSaveSettings();
  if (!s) return null;
  return (
    <Field label="Research source" hint="Wikipedia needs no key. Tavily searches the web (free tier available) and needs the key above.">
      <select className="select" value={s.text.research_enabled ? s.text.research_provider : "none"}
        onChange={(e) => save.mutate({ text: e.target.value === "none" ? { research_enabled: false } : { research_enabled: true, research_provider: e.target.value } })}>
        <option value="none">Off — scripts are not checked against sources</option>
        <option value="wikipedia">Wikipedia</option>
        <option value="tavily">Tavily web search</option>
      </select>
    </Field>
  );
}

function FfmpegHelp() {
  return (
    <div className="small muted stack tight">
      <div>Windows: download a “full” build from gyan.dev, unzip it to <span className="mono">tools/ffmpeg</span> inside the studio folder (so <span className="mono">tools/ffmpeg/bin/ffmpeg.exe</span> exists), or add it to PATH, or set <span className="mono">FFMPEG_PATH</span>. Then press Test.</div>
    </div>
  );
}

function StorageSection({ i }: { i: Integration }) {
  const { data } = useQuery({ queryKey: ["storage"], queryFn: () => api.get<{ projects_bytes: number; library_bytes: number; cache_bytes: number }>("/storage") });
  const gb = (b?: number) => (b == null ? "—" : `${(b / 1024 ** 3).toFixed(2)} GB`);
  return (
    <dl className="kv small">
      <dt>Projects folder</dt><dd className="mono tiny">{i.config?.projects_dir}</dd>
      <dt>Library folder</dt><dd className="mono tiny">{i.config?.export_dir}</dd>
      <dt>Projects use</dt><dd>{gb(data?.projects_bytes)}</dd>
      <dt>Library uses</dt><dd>{gb(data?.library_bytes)}</dd>
    </dl>
  );
}
