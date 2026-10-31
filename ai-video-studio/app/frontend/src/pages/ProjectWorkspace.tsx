import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle, ArrowLeft, Check, CheckCircle2, ExternalLink, FileText, Film, FolderOpen, ImagePlus, ListOrdered, Mic,
  Play, Plus, RefreshCw, Search, Settings2, Sparkles, Square, Trash2, Upload, Wand2, XCircle,
} from "lucide-react";
import { api, fileUrl } from "../lib/api";
import { useAction } from "../lib/hooks";
import type { Claim, Project, Scene, Segment } from "../lib/types";
import { Badge, Card, ConfirmDialog, Details, Empty, ErrorNote, Field, Note, NumberInput, Progress, Spinner, StatusBadge, Toggle } from "../components/ui";
import { JobTable } from "../components/JobTable";
import { dateTime, duration, timeAgo, titleCase, voiceLabel } from "../lib/format";

const STAGES = [
  ["research", "Research"], ["script", "Script"], ["scene_plan", "Scenes"], ["production", "Footage"],
  ["assembly", "Assembly"], ["review", "Review"], ["complete", "Done"],
] as const;

type Tab = "script" | "scenes" | "narration" | "review" | "research" | "jobs" | "settings";

export default function ProjectWorkspace() {
  const id = Number(useParams().id);
  const { data: p, error, isLoading } = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.get<Project>(`/projects/${id}`),
    refetchInterval: (q) => (q.state.data && ["running", "queued"].includes(q.state.data.status) ? 3000 : 15000),
  });
  const [tab, setTab] = useState<Tab>("script");
  const [chosen, setChosen] = useState(false);
  useEffect(() => {
    if (!p || chosen) return;
    const s = p.stage;
    setTab(s === "review" || s === "complete" ? "review" : s === "production" || s === "assembly" || s === "scene_plan" ? "scenes" : "script");
  }, [p, chosen]);
  const pick = (t: Tab) => { setTab(t); setChosen(true); };

  if (isLoading) return <div className="page"><Progress /></div>;
  if (error || !p) return <div className="page"><ErrorNote error={error ?? new Error("Project not found")} /></div>;
  const failedJobs = p.jobs.filter((j) => j.status === "failed").length;
  const tabs: [Tab, string, typeof FileText, number?][] = [
    ["script", "Script", FileText], ["scenes", "Scenes", Film, p.scenes.length], ["narration", "Narration", Mic],
    ["review", "Video & review", CheckCircle2], ["research", "Research & claims", Search, p.factcheck?.claims.length],
    ["jobs", "Jobs", ListOrdered, failedJobs || undefined], ["settings", "Project settings", Settings2],
  ];
  return (
    <div className="page">
      <Link to="/production" className="small muted row" style={{ marginBottom: 10 }}><ArrowLeft size={14} /> All projects</Link>
      <Header p={p} />
      <Stepper stage={p.stage} />
      <NextBanner p={p} onGo={pick} />
      <div className="tabs">
        {tabs.map(([t, label, Icon, n]) => (
          <button key={t} className={`tab ${tab === t ? "on" : ""}`} onClick={() => pick(t)}>
            <Icon size={15} /> {label}{n ? <Badge tone={t === "jobs" ? "err" : ""}>{n}</Badge> : null}
          </button>
        ))}
      </div>
      {tab === "script" && <ScriptTab p={p} />}
      {tab === "scenes" && <ScenesTab p={p} />}
      {tab === "narration" && <NarrationTab p={p} />}
      {tab === "review" && <ReviewTab p={p} />}
      {tab === "research" && <ResearchTab p={p} />}
      {tab === "jobs" && <Card className="flush">{p.jobs.length ? <JobTable jobs={p.jobs} showProject={false} /> : <Empty title="No jobs yet" />}</Card>}
      {tab === "settings" && <ProjectSettings p={p} />}
    </div>
  );
}

function Header({ p }: { p: Project }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(p.title);
  const rename = useAction(() => api.patch(`/projects/${p.id}`, { title }), { invalidate: [["project", p.id], ["projects"]] });
  const open = useAction(() => api.post(`/projects/${p.id}/open-folder`), { success: "Opened in your file manager" });
  const cancel = useAction(() => api.post<{ cancelled: number }>(`/projects/${p.id}/cancel`), { invalidate: [["project", p.id]], success: (r) => `Cancelling ${r.cancelled} job(s)` });
  const active = p.jobs.some((j) => ["pending", "running", "paused"].includes(j.status));
  return (
    <div className="page-header" style={{ marginBottom: 8 }}>
      <div style={{ minWidth: 0 }}>
        {editing ? (
          <div className="row">
            <input className="input" style={{ fontSize: 18, width: 480 }} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
            <button className="btn primary sm" onClick={() => rename.mutate(undefined, { onSuccess: () => setEditing(false) })}>Save</button>
            <button className="btn sm" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        ) : (
          <h1 onDoubleClick={() => setEditing(true)} title="Double-click to rename">{p.title}</h1>
        )}
        <p className="small">Created {dateTime(p.created_at)} · <span className="mono">{p.folder}</span></p>
      </div>
      <div className="header-actions">
        {active && <button className="btn" onClick={() => cancel.mutate()}><Square size={13} /> Stop project jobs</button>}
        <button className="btn" onClick={() => open.mutate()} disabled={!p.folder_exists}><FolderOpen size={15} /> Open folder</button>
      </div>
    </div>
  );
}

function Stepper({ stage }: { stage: string }) {
  const idx = STAGES.findIndex(([s]) => s === stage);
  return (
    <div className="stepper">
      {STAGES.map(([s, label], i) => (
        <div className="row" key={s} style={{ gap: 0 }}>
          {i > 0 && <span className="step-line" />}
          <span className={`step ${i < idx ? "done" : i === idx ? "current" : ""}`}>
            <span className="num">{i < idx ? <Check size={12} /> : i + 1}</span>{label}
          </span>
        </div>
      ))}
    </div>
  );
}

const ACTION_LABEL: Record<string, string> = {
  research: "Start research", script: "Write script", scene_plan: "Plan scenes", production: "Generate footage & narration",
  assemble: "Assemble video",
};

function NextBanner({ p, onGo }: { p: Project; onGo: (t: Tab) => void }) {
  const inv = { invalidate: [["project", p.id], ["projects"], ["dashboard"], ["jobs"]] };
  const cont = useAction(() => api.post(`/projects/${p.id}/continue`), inv);
  const approve = useAction((gate: string) => api.post(`/projects/${p.id}/approve/${gate}`), { ...inv, success: "Approved" });
  const n = p.next;
  let button = null;
  if (n.action === "approve_script") button = <><button className="btn" onClick={() => onGo("script")}>Review script</button><button className="btn primary" onClick={() => approve.mutate("script")}><Check size={15} /> Approve script</button></>;
  else if (n.action === "approve_scene_plan") button = <><button className="btn" onClick={() => onGo("scenes")}>Review scenes</button><button className="btn primary" onClick={() => approve.mutate("scene_plan")}><Check size={15} /> Approve scene plan</button></>;
  else if (n.action === "approve_assembly") button = <button className="btn primary" onClick={() => approve.mutate("assembly")}><Wand2 size={15} /> Assemble video</button>;
  else if (n.action === "review") button = <button className="btn primary" onClick={() => onGo("review")}>Open review</button>;
  else if (n.action === "fix_failed") button = <button className="btn" onClick={() => onGo("jobs")}>See what failed</button>;
  else if (ACTION_LABEL[n.action] && !["running", "queued"].includes(p.status)) button = <button className="btn primary" disabled={cont.isPending} onClick={() => cont.mutate()}><Play size={14} /> {ACTION_LABEL[n.action]}</button>;
  const Icon = p.status === "failed" ? XCircle : p.status === "completed" ? CheckCircle2 : p.status === "waiting_approval" ? AlertTriangle : null;
  return (
    <div className={`banner ${p.status}`}>
      {["running", "queued"].includes(p.status) ? <Spinner /> : Icon ? <Icon size={18} /> : null}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>{p.status === "waiting_approval" ? "Waiting for you" : titleCase(p.status)} · {titleCase(p.stage)}</div>
        <div className="small muted">{p.status_message || n.message}</div>
        {!p.gates.auto && <div className="tiny faint">Manual mode: each stage starts only when you click.</div>}
      </div>
      <div className="row">{button}</div>
    </div>
  );
}

// ---------------------------------------------------------------- script
function ScriptTab({ p }: { p: Project }) {
  const [segments, setSegments] = useState<Segment[]>(p.script?.segments ?? []);
  const [title, setTitle] = useState(p.script?.title ?? p.title);
  const [feedback, setFeedback] = useState("");
  useEffect(() => { setSegments(p.script?.segments ?? []); setTitle(p.script?.title ?? p.title); }, [p.script]);
  const inv = { invalidate: [["project", p.id]] };
  const save = useAction(() => api.put(`/projects/${p.id}/script`, { title, segments }), { ...inv, success: "Script saved (needs approval again)" });
  const regen = useAction(() => api.post(`/projects/${p.id}/actions/script`, { payload: feedback ? { feedback } : {} }), { ...inv, success: "Rewriting script…" });
  const approve = useAction(() => api.post(`/projects/${p.id}/approve/script`), { ...inv, success: "Script approved" });
  const writing = p.jobs.some((j) => j.kind === "script" && ["pending", "running"].includes(j.status));
  const dirty = JSON.stringify(segments) !== JSON.stringify(p.script?.segments ?? []) || title !== (p.script?.title ?? p.title);
  const words = segments.reduce((a, s) => a + s.text.split(/\s+/).filter(Boolean).length, 0);
  const target = p.script?.target_duration_s ?? p.effective.video.duration_s;

  if (!p.script) {
    return (
      <Card>
        {writing ? <Empty icon={<Spinner size={24} />} title="Writing the script…" /> : (
          <Empty icon={<FileText size={28} />} title="No script yet">
            <button className="btn primary" style={{ marginTop: 8 }} onClick={() => regen.mutate()}><Sparkles size={14} /> Write script</button>
          </Empty>
        )}
      </Card>
    );
  }
  return (
    <div className="split-wide">
      <Card title={<input className="input" style={{ fontSize: 15, fontWeight: 600 }} value={title} onChange={(e) => setTitle(e.target.value)} />}
        actions={<StatusBadge status={p.script_status} label={p.script_status === "approved" ? "Approved" : "Draft"} />}>
        <div className="stack">
          {segments.map((s, i) => (
            <div key={i} className="stack tight">
              <div className="row between">
                <span className="tiny faint">{s.purpose ? titleCase(s.purpose) : `Segment ${i + 1}`}{s.visual_idea && <> · visual: {s.visual_idea}</>}</span>
                <button className="btn icon ghost" title="Remove segment" onClick={() => setSegments(segments.filter((_, k) => k !== i))}><Trash2 size={13} /></button>
              </div>
              <textarea className="textarea" rows={2} value={s.text} onChange={(e) => setSegments(segments.map((x, k) => (k === i ? { ...x, text: e.target.value } : x)))} />
            </div>
          ))}
          <div className="row">
            <button className="btn sm" onClick={() => setSegments([...segments, { text: "", purpose: "explanation" }])}><Plus size={13} /> Add segment</button>
            <div className="spacer" />
            <span className="small muted">{words} words · ~{duration(words / 2.6)} (target {target}s)</span>
          </div>
          <div className="row">
            <button className="btn" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>Save edits</button>
            <button className="btn primary" disabled={dirty || p.script_status === "approved" || approve.isPending} onClick={() => approve.mutate()}><Check size={15} /> Approve script</button>
            {dirty && <span className="tiny faint">Save before approving</span>}
          </div>
        </div>
      </Card>
      <div className="stack">
        <Card title="Rewrite with AI">
          <div className="stack">
            <textarea className="textarea" rows={3} placeholder="Optional feedback, e.g. 'stronger hook, less jargon'" value={feedback} onChange={(e) => setFeedback(e.target.value)} />
            <button className="btn" disabled={writing || regen.isPending} onClick={() => regen.mutate()}>{writing ? <Spinner size={14} /> : <RefreshCw size={14} />} Regenerate script</button>
            <div className="tiny faint">Regenerating replaces this draft. The scene plan will need to be redone.</div>
          </div>
        </Card>
        <Card title="Claims to double-check">
          {p.script.uncertain_claims?.length ? (
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{p.script.uncertain_claims.map((c, i) => <li key={i}>{c}</li>)}</ul>
          ) : <div className="small faint">The writer flagged nothing. See Research & claims for the automatic check.</div>}
        </Card>
        <Card title="Details">
          <dl className="kv">
            <dt>Model</dt><dd>{p.script.model ?? "—"}</dd>
            <dt>Edited by you</dt><dd>{p.script.edited ? "Yes" : "No"}</dd>
            <dt>Research</dt><dd>{p.research_status === "completed" ? `${p.research?.sources.length ?? 0} sources` : titleCase(p.research_status)}</dd>
          </dl>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- scenes
function ScenesTab({ p }: { p: Project }) {
  const inv = { invalidate: [["project", p.id]] };
  const plan = useAction(() => api.post(`/projects/${p.id}/actions/scene_plan`), { ...inv, success: "Planning scenes…" });
  const approve = useAction(() => api.post(`/projects/${p.id}/approve/scene_plan`), { ...inv, success: "Scene plan approved" });
  const clips = useAction(() => api.post<{ job_ids: number[] }>(`/projects/${p.id}/actions/clips`), { ...inv, success: (r) => `${r.job_ids.length} clip job(s) queued` });
  const add = useAction(() => api.post(`/projects/${p.id}/scenes`), inv);
  const planning = p.jobs.some((j) => j.kind === "scene_plan" && ["pending", "running"].includes(j.status));
  const approved = p.scene_plan_status === "approved";
  const totalEst = p.scenes.reduce((a, s) => a + s.duration_s, 0);
  if (!p.scenes.length) {
    return (
      <Card>
        {planning ? <Empty icon={<Spinner size={24} />} title="Planning scenes…" /> : (
          <Empty icon={<Film size={28} />} title="No scene plan yet">
            {p.script_status === "approved"
              ? <button className="btn primary" style={{ marginTop: 8 }} onClick={() => plan.mutate()}><Sparkles size={14} /> Plan scenes</button>
              : "Approve the script first."}
          </Empty>
        )}
      </Card>
    );
  }
  const provider = p.effective.generation.video_provider;
  return (
    <div className="stack">
      <div className="row wrap">
        <StatusBadge status={p.scene_plan_status} label={approved ? "Plan approved" : p.scene_plan_status === "stale" ? "Script changed — re-plan" : "Draft plan"} />
        <span className="small muted">{p.scenes.length} scenes · ~{duration(totalEst)} estimated</span>
        {provider === "draft" && <Badge tone="warn">Video provider: draft cards (no AI)</Badge>}
        <div className="spacer" />
        <button className="btn" disabled={planning} onClick={() => plan.mutate()}>{planning ? <Spinner size={14} /> : <RefreshCw size={14} />} Re-plan</button>
        <button className="btn" onClick={() => add.mutate()}><Plus size={14} /> Add scene</button>
        {!approved && <button className="btn primary" onClick={() => approve.mutate()}><Check size={15} /> Approve scene plan</button>}
        {approved && <button className="btn primary" onClick={() => clips.mutate()}><Wand2 size={15} /> Generate missing clips</button>}
      </div>
      {p.scenes.map((s) => <SceneCard key={s.id} p={p} s={s} approved={approved} />)}
    </div>
  );
}

const SCENE_TEXT: [keyof Scene, string, number][] = [
  ["narration", "Narration", 2], ["visual_objective", "What the viewer must understand", 1], ["prompt", "Video prompt", 4],
  ["camera", "Camera", 1], ["subject_motion", "Motion", 1], ["environment", "Environment & lighting", 1],
  ["style", "Scene style", 1], ["negative_prompt", "Negative prompt", 1], ["image_prompt", "Still image prompt (optional)", 2],
];

function SceneCard({ p, s, approved }: { p: Project; s: Scene; approved: boolean }) {
  const [form, setForm] = useState<Partial<Scene>>(s);
  const [confirmDel, setConfirmDel] = useState(false);
  const [showMeta, setShowMeta] = useState(false);
  useEffect(() => setForm(s), [s]);
  const inv = { invalidate: [["project", p.id]] };
  const dirty = SCENE_TEXT.some(([k]) => form[k] !== s[k]) || form.duration_s !== s.duration_s || form.transition !== s.transition;
  const save = useAction(() => api.patch(`/scenes/${s.id}`, Object.fromEntries([...SCENE_TEXT.map(([k]) => [k, form[k]]), ["duration_s", form.duration_s], ["transition", form.transition]])), { ...inv, success: "Scene saved" });
  const gen = useAction((provider?: string) => api.post(`/scenes/${s.id}/generate`, provider ? { provider } : {}), { ...inv, success: "Clip queued" });
  const genImg = useAction(() => api.post(`/scenes/${s.id}/generate-image`), { ...inv, success: "Still queued" });
  const upload = useAction((f: File) => api.upload(`/scenes/${s.id}/image`, f), { ...inv, success: "Source image attached" });
  const del = useAction(() => api.del(`/scenes/${s.id}`), inv);
  const job = p.jobs.find((j) => j.scene_id === s.id && ["running", "pending"].includes(j.status));
  const failed = p.jobs.find((j) => j.scene_id === s.id && j.status === "failed" && s.clip_status === "failed");
  const clip = fileUrl(p.id, s.clip_path);
  const image = fileUrl(p.id, s.image_path);
  const imageStage = p.effective.generation.use_image_stage;
  return (
    <Card>
      <div className="scene">
        <div className="stack tight">
          <div className="row between"><span className="scene-index">Scene {s.idx + 1}</span><StatusBadge status={s.clip_status} label={s.clip_status === "none" ? "No clip" : undefined} /></div>
          {clip ? (
            <div className="video-frame vertical"><video src={clip} controls loop muted preload="metadata" /></div>
          ) : image ? (
            <img src={image} alt="" style={{ width: "100%", borderRadius: 7 }} />
          ) : (
            <div className="thumb-placeholder">{job ? <Spinner size={22} /> : <Film size={22} />}</div>
          )}
          {job && <><Progress value={job.status === "running" ? job.progress : null} /><span className="tiny muted">{job.status === "pending" ? "Queued" : job.progress_message}</span></>}
          {s.clip_meta && (
            <div className="tiny faint">
              {s.clip_meta.is_ai ? s.clip_meta.workflow : "Draft card (not AI)"} · {duration(s.clip_meta.duration)} · seed {s.clip_meta.seed}{" "}
              <button className="details-toggle" onClick={() => setShowMeta(!showMeta)}>{showMeta ? "hide" : "details"}</button>
            </div>
          )}
          {showMeta && s.clip_meta && <pre className="detail-box mono tiny">{JSON.stringify(s.clip_meta, null, 2)}</pre>}
        </div>
        <div className="stack">
          {failed && <Note tone="err" title={failed.error_message ?? "Generation failed"} detail={failed.error_detail} />}
          {s.flags?.map((f, i) => <Note key={i} tone="warn">{f}</Note>)}
          <div className="grid cols-2">
            {SCENE_TEXT.filter(([k]) => k !== "image_prompt" || imageStage || s.needs_image).map(([k, label, rows]) => (
              <div key={k} style={rows >= 2 ? { gridColumn: "1 / -1" } : undefined}>
                <Field label={label}>
                  {rows === 1 ? <input className="input" value={(form[k] as string) ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                    : <textarea className="textarea" rows={rows} value={(form[k] as string) ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />}
                </Field>
              </div>
            ))}
            <Field label="Estimated seconds"><NumberInput value={form.duration_s ?? 3} step={0.5} min={0.5} max={60} onChange={(v) => setForm({ ...form, duration_s: v })} /></Field>
            <Field label="Transition in">
              <select className="select" value={form.transition} onChange={(e) => setForm({ ...form, transition: e.target.value })}>
                <option value="cut">Cut</option><option value="fade">Fade</option><option value="dissolve">Dissolve</option>
              </select>
            </Field>
          </div>
          <div className="row wrap">
            <button className="btn" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>Save scene</button>
            <button className="btn primary" disabled={!approved || dirty || !!job} title={!approved ? "Approve the scene plan first" : dirty ? "Save first" : ""} onClick={() => gen.mutate(undefined)}>
              <Wand2 size={14} /> {s.clip_path ? "Regenerate clip" : "Generate clip"}
            </button>
            <button className="btn ghost sm" disabled={!approved || dirty || !!job} onClick={() => gen.mutate("draft")} title="Quick placeholder card via FFmpeg — not AI footage">Draft card</button>
            {imageStage && <button className="btn sm" disabled={!!job} onClick={() => genImg.mutate()}><ImagePlus size={14} /> Generate still</button>}
            <label className="btn sm ghost" title="Use your own image as the first frame (image-to-video)">
              <Upload size={14} /> Source image
              <input type="file" accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            </label>
            <div className="spacer" />
            <button className="btn icon ghost" title="Delete scene" onClick={() => setConfirmDel(true)}><Trash2 size={14} /></button>
          </div>
        </div>
      </div>
      {confirmDel && (
        <ConfirmDialog title={`Delete scene ${s.idx + 1}?`} danger confirmLabel="Delete scene" onClose={() => setConfirmDel(false)}
          onConfirm={() => del.mutate(undefined, { onSuccess: () => setConfirmDel(false) })}>
          <p className="muted">Its narration is removed from the video, so narration will need regenerating. Clip files stay on disk.</p>
        </ConfirmDialog>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- narration
function NarrationTab({ p }: { p: Project }) {
  const gen = useAction(() => api.post(`/projects/${p.id}/actions/narration`), { invalidate: [["project", p.id]], success: "Narration queued" });
  const n = p.narration;
  const job = p.jobs.find((j) => j.kind === "narration" && ["pending", "running"].includes(j.status));
  const failed = p.narration_status === "failed" ? p.jobs.find((j) => j.kind === "narration" && j.status === "failed") : null;
  const voice = p.effective.narration;
  return (
    <div className="split-wide">
      <Card title="Narration" actions={<StatusBadge status={p.narration_status} />}>
        <div className="stack">
          {failed && <Note tone="err" title={failed.error_message ?? "Narration failed"} detail={failed.error_detail}>Your script and footage are kept. Fix the problem and generate again.</Note>}
          {p.narration_status === "stale" && <Note tone="warn">The scene narration changed since this audio was made. Regenerate before assembling.</Note>}
          {n ? (
            <>
              <audio controls src={fileUrl(p.id, n.path)} style={{ width: "100%" }} />
              <dl className="kv">
                <dt>Length</dt><dd>{duration(n.duration)}</dd>
                <dt>Voice</dt><dd>{n.voice_name || n.voice_id}</dd>
                <dt>Model</dt><dd>{n.model}</dd>
                <dt>Characters</dt><dd>{n.characters}{n.cost_usd != null && <> · est. ${n.cost_usd.toFixed(4)}</>}</dd>
                <dt>Caption timing</dt><dd>{n.alignment_method === "whisper" ? "Speech recognition (faster-whisper)" : "Estimated + snapped to pauses"}</dd>
                <dt>Generated</dt><dd>{timeAgo(n.generated_at)}</dd>
              </dl>
            </>
          ) : job ? <Empty icon={<Spinner size={22} />} title="Generating narration…" /> : <Empty icon={<Mic size={26} />} title="No narration yet" />}
          <div className="row">
            <button className="btn primary" disabled={!!job || !p.script} onClick={() => gen.mutate()}><Mic size={14} /> {n ? "Regenerate narration" : "Generate narration"}</button>
            {voice.provider === "fish_audio" && !voice.voice_id && <span className="small" style={{ color: "var(--warn)" }}>No Fish Audio voice selected — choose one in Integrations or Project settings.</span>}
          </div>
        </div>
      </Card>
      <Card title="Voice for this project">
        <dl className="kv">
          {voice.provider === "kokoro" ? (
            <><dt>Voice</dt><dd>{voiceLabel(voice.kokoro_voice)}</dd><dt>Engine</dt><dd>Free local voice (Kokoro)</dd></>
          ) : (
            <><dt>Voice</dt><dd>{voice.voice_name || voice.voice_id || "Not set"}</dd><dt>Engine</dt><dd>Fish Audio ({voice.model})</dd></>
          )}
          <dt>Speed</dt><dd>{voice.speed}×</dd>
        </dl>
        <div className="tiny faint" style={{ marginTop: 10 }}>Change it under Project settings. Narration always uses the scenes' narration text, in order.</div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- review
function ReviewTab({ p }: { p: Project }) {
  const inv = { invalidate: [["project", p.id], ["library"], ["dashboard"]] };
  const [note, setNote] = useState("");
  const assemble = useAction(() => api.post(`/projects/${p.id}/actions/assemble`), { ...inv, success: "Assembly queued" });
  const review = useAction((decision: string) => api.post(`/projects/${p.id}/review`, { decision, note }), { ...inv, success: "Review saved" });
  const exp = useAction(() => api.post<{ path: string }>(`/projects/${p.id}/export`), { ...inv, success: (r) => `Copied to ${r.path}` });
  const open = useAction(() => api.post(`/projects/${p.id}/open-folder?sub=exports`));
  const job = p.jobs.find((j) => j.kind === "assemble" && ["pending", "running"].includes(j.status));
  const ready = p.scenes.length > 0 && p.scenes.every((s) => s.clip_status === "completed") && p.narration_status === "completed";
  const video = fileUrl(p.id, p.export?.path);
  return (
    <div className="split">
      <Card>
        {video && p.export_status !== "running" ? (
          <div className="video-frame vertical" style={{ maxHeight: "72vh" }}><video key={video} src={video} controls preload="metadata" /></div>
        ) : (
          <div className="thumb-placeholder">{job ? <div className="stack" style={{ alignItems: "center" }}><Spinner size={24} /><span className="small">{job.progress_message}</span></div> : <Film size={26} />}</div>
        )}
        {job && <div style={{ marginTop: 10 }}><Progress value={job.status === "running" ? job.progress : null} /></div>}
      </Card>
      <div className="stack">
        {p.export_status === "stale" && <Note tone="warn">Footage or narration changed since this export. Re-assemble to include the changes.</Note>}
        {p.export_status === "failed" && <Note tone="err" title="Assembly failed" detail={p.jobs.find((j) => j.kind === "assemble" && j.status === "failed")?.error_detail}>{p.jobs.find((j) => j.kind === "assemble" && j.status === "failed")?.error_message}</Note>}
        <Card title="Final review" actions={p.export_status === "completed" && <StatusBadge status={p.review_status === "none" ? "waiting_approval" : p.review_status} label={p.review_status === "none" ? "Awaiting review" : undefined} />}>
          <div className="stack">
            <div className="row wrap">
              <button className="btn" disabled={!ready || !!job} onClick={() => assemble.mutate()}><Wand2 size={14} /> {p.export ? "Re-assemble" : "Assemble video"}</button>
              <button className="btn" disabled={!p.export} onClick={() => exp.mutate()}><ExternalLink size={14} /> Copy to library folder</button>
              <button className="btn" disabled={!p.export} onClick={() => open.mutate()}><FolderOpen size={14} /> Open exports</button>
            </div>
            {!ready && !p.export && <div className="small faint">Needs every scene clip and the narration before assembly.</div>}
            {p.export_status === "completed" && (
              <>
                <textarea className="textarea" rows={2} placeholder="Notes (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
                <div className="row">
                  <button className="btn primary" onClick={() => review.mutate("approved")}><Check size={15} /> Approve as finished</button>
                  <button className="btn" onClick={() => review.mutate("rejected")}>Needs changes</button>
                </div>
                {p.review_note && <div className="small muted">Last note: {p.review_note}</div>}
              </>
            )}
          </div>
        </Card>
        {p.qc && (
          <Card title="Automated checks" sub={p.qc.note}>
            <div className="list">
              {p.qc.checks.map((c, i) => (
                <div className="list-item small" key={i} style={{ alignItems: "flex-start" }}>
                  {c.status === "pass" ? <CheckCircle2 size={15} color="var(--ok)" /> : c.status === "warn" ? <AlertTriangle size={15} color="var(--warn)" /> : <XCircle size={15} color="var(--err)" />}
                  <div style={{ flex: 1 }}><div>{c.label}</div>{c.detail && <div className="tiny muted">{c.detail}</div>}</div>
                </div>
              ))}
            </div>
          </Card>
        )}
        {p.export && (
          <Card title="Export">
            <dl className="kv">
              <dt>File</dt><dd className="mono tiny">{p.export.path}</dd>
              <dt>Duration</dt><dd>{duration(p.export.duration)}</dd>
              <dt>Format</dt><dd>{p.export.width}×{p.export.height} · {p.export.fps} fps · H.264/AAC</dd>
              <dt>Captions</dt><dd>{p.export.srt_path ? <a href={fileUrl(p.id, p.export.srt_path)} download>captions.srt</a> : "Burned in only"}</dd>
              {p.export.library_path && <><dt>Library copy</dt><dd className="mono tiny">{p.export.library_path}</dd></>}
              <dt>Created</dt><dd>{dateTime(p.export.created_at)}</dd>
            </dl>
          </Card>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- research
const CLAIM_LABEL: Record<Claim["status"], string> = {
  verified: "Verified (2+ sources)", needs_review: "Supported — review", speculative: "Creative / framing",
  unverified: "Not found in sources", contradicted: "Contradicted", not_checked: "Not checked",
};

function ResearchTab({ p }: { p: Project }) {
  const inv = { invalidate: [["project", p.id]] };
  const research = useAction(() => api.post(`/projects/${p.id}/actions/research`), { ...inv, success: "Research queued" });
  const check = useAction(() => api.post(`/projects/${p.id}/actions/factcheck`), { ...inv, success: "Claim check queued" });
  const r = p.research;
  return (
    <div className="split-wide">
      <div className="stack">
        <Card title="Claims in the script" actions={<button className="btn sm" disabled={!p.script} onClick={() => check.mutate()}><RefreshCw size={13} /> Re-check</button>}>
          {p.factcheck ? (
            <div className="stack">
              <Note tone={r?.sources?.length ? "info" : "warn"}>{p.factcheck.disclaimer}</Note>
              <table className="table small">
                <thead><tr><th>Claim</th><th>Status</th><th>Evidence</th></tr></thead>
                <tbody>
                  {p.factcheck.claims.map((c, i) => (
                    <tr key={i}>
                      <td style={{ width: "45%" }}>{c.claim}{c.note && <div className="tiny faint">{c.note}</div>}</td>
                      <td><StatusBadge status={c.status} label={CLAIM_LABEL[c.status]} /></td>
                      <td>
                        {c.evidence && <div className="tiny muted">“{c.evidence}”</div>}
                        {c.sources.map((s, k) => <div key={k}><a className="tiny" href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a></div>)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty title="No claim check yet">It runs automatically after each script.</Empty>}
        </Card>
        {r?.facts?.length ? (
          <Card title="Sourced facts given to the writer">
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{r.facts.map((f, i) => <li key={i}>{f.fact} <span className="faint">[{f.source_ids.join(", ")}]</span></li>)}</ul>
            {!!r.cautions?.length && <><div className="section-title" style={{ marginTop: 12 }}>Cautions</div><ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>{r.cautions.map((c, i) => <li key={i}>{c}</li>)}</ul></>}
          </Card>
        ) : null}
      </div>
      <Card title="Sources" sub={r?.provider ? `via ${titleCase(r.provider)}` : undefined}
        actions={<button className="btn sm" onClick={() => research.mutate()}><Search size={13} /> {r ? "Research again" : "Run research"}</button>}>
        {p.research_status === "skipped" && <Note tone="warn">{r?.note ?? "Research was skipped."}</Note>}
        {r?.note && p.research_status !== "skipped" && <Note tone="warn">{r.note}</Note>}
        {r?.sources?.length ? (
          <div className="list">
            {r.sources.map((s) => (
              <div className="list-item" key={s.id} style={{ alignItems: "flex-start" }}>
                <Badge>{s.id}</Badge>
                <div style={{ minWidth: 0 }}>
                  <a href={s.url} target="_blank" rel="noreferrer noopener" className="small">{s.title}</a>
                  <div className="tiny faint">{s.domain}</div>
                  <Details text={s.snippet} label="Excerpt" />
                </div>
              </div>
            ))}
          </div>
        ) : p.research_status !== "skipped" && <div className="small faint">No sources yet.</div>}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- project settings
function ProjectSettings({ p }: { p: Project }) {
  const e = p.effective;
  const { data: voices } = useQuery({ queryKey: ["kokoro-voices"], queryFn: () => api.get<{ voices: { id: string; label: string }[] }>("/integrations/kokoro/voices") });
  const [o, setO] = useState({
    duration_s: e.video.duration_s, voice_id: e.narration.voice_id, voice_name: e.narration.voice_name, speed: e.narration.speed,
    narrator: e.narration.provider as string, kokoro_voice: e.narration.kokoro_voice as string,
    captions: e.captions.enabled, provider: e.generation.video_provider, transition: e.video.transition, music: e.music.enabled,
  });
  const save = useAction(() => api.patch(`/projects/${p.id}`, {
    overrides: {
      video: { duration_s: o.duration_s, transition: o.transition },
      narration: { provider: o.narrator, kokoro_voice: o.kokoro_voice, voice_id: o.voice_id, voice_name: o.voice_name, speed: o.speed },
      captions: { enabled: o.captions },
      generation: { video_provider: o.provider },
      music: { enabled: o.music },
    },
  }), { invalidate: [["project", p.id]], success: "Project settings saved" });
  return (
    <Card title="Overrides for this project" sub="Everything else follows the global Settings page.">
      <div className="form-grid">
        <Field label="Target length (s)"><NumberInput value={o.duration_s} min={5} max={180} onChange={(v) => setO({ ...o, duration_s: v })} /></Field>
        <Field label="Video provider">
          <select className="select" value={o.provider} onChange={(ev) => setO({ ...o, provider: ev.target.value })}>
            <option value="comfyui">ComfyUI (AI video)</option><option value="draft">Draft cards (no AI)</option>
          </select>
        </Field>
        <Field label="Transitions">
          <select className="select" value={o.transition} onChange={(ev) => setO({ ...o, transition: ev.target.value })}>
            <option value="cut">Cut</option><option value="fade">Fade</option><option value="dissolve">Dissolve</option><option value="slideup">Slide up</option>
          </select>
        </Field>
        <Field label="Narration">
          <select className="select" value={o.narrator} onChange={(ev) => setO({ ...o, narrator: ev.target.value })}>
            <option value="kokoro">Free voice on this PC</option><option value="fish_audio">Fish Audio (paid)</option>
          </select>
        </Field>
        {o.narrator === "kokoro" ? (
          <Field label="Voice">
            <select className="select" value={o.kokoro_voice} onChange={(ev) => setO({ ...o, kokoro_voice: ev.target.value })}>
              {(voices?.voices ?? [{ id: o.kokoro_voice, label: voiceLabel(o.kokoro_voice) }]).map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </Field>
        ) : (
          <>
            <Field label="Voice ID (Fish Audio)"><input className="input mono" value={o.voice_id} onChange={(ev) => setO({ ...o, voice_id: ev.target.value })} /></Field>
            <Field label="Voice name"><input className="input" value={o.voice_name} onChange={(ev) => setO({ ...o, voice_name: ev.target.value })} /></Field>
          </>
        )}
        <Field label="Speech speed"><NumberInput value={o.speed} step={0.05} min={0.5} max={2} onChange={(v) => setO({ ...o, speed: v })} /></Field>
        <Field label="Captions"><Toggle checked={o.captions} onChange={(v) => setO({ ...o, captions: v })} label={o.captions ? "On" : "Off"} /></Field>
        <Field label="Background music"><Toggle checked={o.music} onChange={(v) => setO({ ...o, music: v })} label={o.music ? "On" : "Off"} /></Field>
      </div>
      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn primary" onClick={() => save.mutate()} disabled={save.isPending}>Save project settings</button>
        <span className="tiny faint">Changes apply to stages generated after saving.</span>
      </div>
    </Card>
  );
}
