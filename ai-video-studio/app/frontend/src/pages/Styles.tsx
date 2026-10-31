import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Check, Film, ImagePlus, Palette, Plus, Sparkles, Star, Trash2, Upload, Wand2, X } from "lucide-react";
import { api } from "../lib/api";
import { useAction, useSettings } from "../lib/hooks";
import { Badge, Card, ConfirmDialog, Empty, ErrorNote, Field, Modal, Note, PageHeader, Progress, StatusBadge } from "../components/ui";
import { timeAgo } from "../lib/format";

type Ref = { file: string; kind: "image" | "video"; key: boolean; frames: string[]; facts?: { duration: number; cuts: number; avg_shot_s: number } };
type Profile = {
  name?: string; summary?: string; style_prompt?: string; avoid?: string; camera?: string; motion?: string; mood?: string;
  palette?: string[]; pacing?: { avg_shot_s: number; cuts_per_10s: number | null; videos: number } | null;
  vision_model?: string | null; stale?: boolean; edited?: boolean; analyzed_at?: string;
};
type Job = { id: number; status: string; progress: number | null; progress_message: string | null };
export type Style = {
  id: number; name: string; notes: string; status: "new" | "analyzing" | "ready" | "failed"; profile: Profile | null; refs: Ref[];
  error: string | null; is_default: boolean; job: Job | null; updated_at: string;
};

const fileUrl = (id: number, rel: string) => `/api/style-files/${id}/${rel.split("/").map(encodeURIComponent).join("/")}`;

function thumbOf(st: Style): string | null {
  const img = st.refs.find((r) => r.kind === "image") ?? st.refs.find((r) => r.frames.length);
  if (!img) return null;
  return fileUrl(st.id, img.kind === "image" ? img.file : img.frames[Math.floor(img.frames.length / 2)]);
}

const STATUS_LABEL: Record<string, string> = { new: "Not analysed", analyzing: "Analysing", ready: "Ready", failed: "Failed" };

export default function Styles() {
  const nav = useNavigate();
  const [creating, setCreating] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["styles"], queryFn: () => api.get<Style[]>("/styles") });
  return (
    <div className="page">
      <PageHeader title="Style library" sub="Show the studio what your videos should look like. Every scene is then generated in that style."
        actions={<button className="btn primary" onClick={() => setCreating(true)}><Plus size={15} /> New style</button>} />
      <ErrorNote error={error} />
      <Note title="How references work">
        Upload example images or short clips in the look you want. The studio measures their colours and how fast they cut,
        and an image-reading AI writes a detailed style description that is added to every scene. If the MiniMax H3 reference
        model is installed in ComfyUI, your starred images are also shown to the video model directly. This does not retrain the model
        (that needs a much bigger GPU), but it steers every clip toward your style.
      </Note>
      <div style={{ height: 16 }} />
      {isLoading ? <Progress /> : !data?.length ? (
        <Card><Empty icon={<Palette size={28} />} title="No styles yet">Create one and drop in a few reference images or clips.</Empty></Card>
      ) : (
        <div className="grid cols-4">
          {data.map((st) => {
            const thumb = thumbOf(st);
            return (
              <Link key={st.id} to={`/styles/${st.id}`} className="card selectable" style={{ color: "inherit", textDecoration: "none" }}>
                <div className="stack tight">
                  {thumb ? <img src={thumb} alt="" style={{ width: "100%", aspectRatio: "16/10", objectFit: "cover", borderRadius: 7 }} />
                    : <div className="thumb-placeholder" style={{ aspectRatio: "16/10" }}><Palette size={22} /></div>}
                  <div className="row between"><b className="ellipsis">{st.name}</b>{st.is_default && <Badge tone="accent">Default</Badge>}</div>
                  <div className="row"><StatusBadge status={st.status === "new" ? "none" : st.status === "analyzing" ? "running" : st.status === "ready" ? "ok" : "failed"} label={STATUS_LABEL[st.status]} />
                    <span className="tiny faint">{st.refs.length} reference{st.refs.length === 1 ? "" : "s"}</span></div>
                  {st.profile?.palette && <Swatches colours={st.profile.palette} />}
                </div>
              </Link>
            );
          })}
        </div>
      )}
      {creating && <NewStyle onClose={() => setCreating(false)} onCreated={(id) => nav(`/styles/${id}`)} />}
    </div>
  );
}

function Swatches({ colours }: { colours: string[] }) {
  return (
    <div className="row" style={{ gap: 4 }}>
      {colours.map((c) => <span key={c} title={c} style={{ width: 22, height: 14, borderRadius: 3, background: c, border: "1px solid var(--border)" }} />)}
    </div>
  );
}

function NewStyle({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const create = useAction(() => api.post<Style>("/styles", { name: name || "New style", notes }), { invalidate: [["styles"]] });
  return (
    <Modal title="New style" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn primary" disabled={create.isPending} onClick={() => create.mutate(undefined, { onSuccess: (s) => onCreated(s.id) })}>Create</button>
    </>}>
      <Field label="Name" hint="You can rename it later; the analysis can suggest one."><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Kurzgesagt-like flat animation" autoFocus /></Field>
      <Field label="Describe the look in your own words (optional)" hint="Helps the analysis, and is used on its own if no image-reading AI is available.">
        <textarea className="textarea" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="bright flat 2D animation, thick outlines, bouncy motion, lots of quick cuts" />
      </Field>
    </Modal>
  );
}

export function StyleDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const { data: st, error } = useQuery({
    queryKey: ["style", id],
    queryFn: () => api.get<Style>(`/styles/${id}`),
    refetchInterval: (q) => (q.state.data?.status === "analyzing" ? 1500 : false),
  });
  const { data: settings } = useSettings();
  const qc = useQueryClient();
  const inv = { invalidate: [["style", id], ["styles"], ["settings"]] };
  const [uploading, setUploading] = useState<{ done: number; total: number } | null>(null);
  const [uploadErr, setUploadErr] = useState<unknown>(null);
  const [deleting, setDeleting] = useState(false);
  const [notes, setNotes] = useState("");
  const [prompt, setPrompt] = useState("");
  const [avoid, setAvoid] = useState("");
  const [name, setName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!st) return;
    setNotes(st.notes);
    setPrompt(st.profile?.style_prompt ?? "");
    setAvoid(st.profile?.avoid ?? "");
    setName(st.name);
  }, [st?.updated_at, st?.status]);
  const analyze = useAction(() => api.post(`/styles/${id}/analyze`), { ...inv, success: "Analysing your references…" });
  const save = useAction((body: Record<string, string>) => api.patch(`/styles/${id}`, body), { ...inv, success: "Saved" });
  const star = useAction((r: Ref) => api.post(`/styles/${id}/key`, { file: r.file, key: !r.key }), inv);
  const remove = useAction((r: Ref) => api.del(`/styles/${id}/references?file=${encodeURIComponent(r.file)}`), inv);
  const makeDefault = useAction((on: boolean) => api.post(`/styles/${id}/default?on=${on}`), { ...inv, success: "Default style updated" });
  const del = useAction(() => api.del(`/styles/${id}`, { confirm: st?.name ?? "" }), { invalidate: [["styles"], ["settings"]] });

  async function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    setUploadErr(null);
    setUploading({ done: 0, total: list.length });
    for (const [i, f] of list.entries()) {
      try {
        await api.upload(`/styles/${id}/references`, f);
      } catch (e) {
        setUploadErr(e);
      }
      setUploading({ done: i + 1, total: list.length });
      qc.invalidateQueries({ queryKey: ["style", id] });
    }
    setUploading(null);
    qc.invalidateQueries({ queryKey: ["styles"] });
  }

  if (error) return <div className="page"><ErrorNote error={error} /></div>;
  if (!st) return <div className="page"><Progress /></div>;
  const p = st.profile;
  const job = st.job;
  const keys = st.refs.filter((r) => r.key).length;
  const isDefault = settings?.generation.style_id === st.id;
  return (
    <div className="page">
      <Link to="/styles" className="small muted row" style={{ marginBottom: 10 }}><ArrowLeft size={14} /> All styles</Link>
      <PageHeader
        title={<input className="input" style={{ fontSize: 20, fontWeight: 600, width: 420 }} value={name} onChange={(e) => setName(e.target.value)}
          onBlur={() => name.trim() && name !== st.name && save.mutate({ name })} />}
        sub={<>{STATUS_LABEL[st.status]}{p?.analyzed_at && <> · analysed {timeAgo(p.analyzed_at)}</>}</>}
        actions={<>
          {isDefault ? <button className="btn" onClick={() => makeDefault.mutate(false)}><X size={14} /> Stop using by default</button>
            : <button className="btn primary" disabled={st.status !== "ready"} onClick={() => makeDefault.mutate(true)}><Check size={15} /> Use for all new videos</button>}
          <button className="btn icon ghost" title="Delete style" onClick={() => setDeleting(true)}><Trash2 size={15} /></button>
        </>} />

      <div className="split-wide">
        <div className="stack">
          <Card title="1 · References" sub={`${st.refs.length} added · ${keys}/4 starred for H3's reference mode`}
            actions={<button className="btn" onClick={() => inputRef.current?.click()} disabled={!!uploading}><Upload size={14} /> Add images or clips</button>}>
            <input ref={inputRef} type="file" multiple accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm"
              style={{ display: "none" }} onChange={(e) => e.target.files && uploadFiles(e.target.files).then(() => (e.target.value = ""))} />
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files); }}
              style={{ border: "1px dashed var(--border-strong)", borderRadius: 10, padding: 12 }}
            >
              {!st.refs.length ? (
                <Empty icon={<ImagePlus size={26} />} title="Drop images or video clips here">3–10 references work best: frames or short clips (5–30 s) of videos in the style you want.</Empty>
              ) : (
                <div className="grid cols-4">
                  {st.refs.map((r) => {
                    const thumb = r.kind === "image" ? fileUrl(st.id, r.file) : r.frames.length ? fileUrl(st.id, r.frames[Math.floor(r.frames.length / 2)]) : null;
                    return (
                      <div key={r.file} className="stack tight" style={{ position: "relative" }}>
                        {thumb ? <img src={thumb} alt="" style={{ width: "100%", aspectRatio: "16/10", objectFit: "cover", borderRadius: 7 }} />
                          : <div className="thumb-placeholder" style={{ aspectRatio: "16/10" }}><Film size={20} /></div>}
                        <div className="row" style={{ gap: 4 }}>
                          {r.kind === "video" ? <Badge><Film size={11} /> {r.facts ? `${r.facts.duration.toFixed(0)}s · ${r.facts.cuts} cuts` : "clip"}</Badge> : <Badge>image</Badge>}
                          <span className="spacer" />
                          {(r.kind === "image" || r.frames.length > 0) && (
                            <button className="btn icon ghost" title={r.key ? "Starred: shown to the video model directly" : "Star: show this image to the video model directly"} onClick={() => star.mutate(r)}>
                              <Star size={14} fill={r.key ? "var(--warn)" : "none"} color={r.key ? "var(--warn)" : undefined} />
                            </button>
                          )}
                          <button className="btn icon ghost" title="Remove" onClick={() => remove.mutate(r)}><X size={14} /></button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            {uploading && <div className="stack tight" style={{ marginTop: 10 }}><span className="small">Uploading {uploading.done}/{uploading.total}…</span><Progress value={uploading.done / uploading.total} /></div>}
            <div style={{ marginTop: 10 }}><ErrorNote error={uploadErr} /></div>
          </Card>

          <Card title="2 · Describe it (optional)" sub="Your own words are combined with what the AI sees.">
            <div className="stack">
              <textarea className="textarea" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. playful 2D animation, thick black outlines, pastel colours, snappy cuts on every sentence" />
              <div className="row">
                <button className="btn" disabled={notes === st.notes} onClick={() => save.mutate({ notes })}>Save description</button>
              </div>
            </div>
          </Card>

          <Card title="3 · Analyse">
            <div className="stack">
              {st.status === "analyzing" || job ? (
                <div className="stack tight"><span className="small">{job?.progress_message || "Waiting in the queue…"}</span><Progress value={job?.status === "running" ? job.progress : null} /></div>
              ) : (
                <div className="row wrap">
                  <button className="btn primary" disabled={!st.refs.length} onClick={() => analyze.mutate()}><Sparkles size={15} /> {p ? "Analyse again" : "Analyse references"}</button>
                  <span className="small muted">Takes under a minute. Uses your Groq key; images never leave your PC except to that analysis.</span>
                </div>
              )}
              {st.status === "failed" && <Note tone="err" title="Analysis failed">{st.error}</Note>}
              {p?.stale && st.status === "ready" && <Note tone="warn">References changed since the last analysis. The style still works; analyse again to include the new ones.</Note>}
            </div>
          </Card>
        </div>

        <div className="stack">
          <Card title="The style" sub={p ? (p.vision_model ? `Written by ${p.vision_model}` : "Written from your description (no image-reading AI available)") : "Appears after analysis, or write it yourself"}>
            <div className="stack">
              {p?.summary && <div className="small">{p.summary}</div>}
              {p?.palette && <Field label="Colours"><Swatches colours={p.palette} /></Field>}
              {p?.pacing && (
                <div className="small muted">Pacing: a cut every <b>{p.pacing.avg_shot_s}s</b> on average — scenes are planned to match.</div>
              )}
              {(p?.camera || p?.motion || p?.mood) && (
                <dl className="kv small">
                  {p.camera && <><dt>Camera</dt><dd>{p.camera}</dd></>}
                  {p.motion && <><dt>Motion</dt><dd>{p.motion}</dd></>}
                  {p.mood && <><dt>Mood</dt><dd>{p.mood}</dd></>}
                </dl>
              )}
              <Field label="Style description given to the video model" hint="Added to every scene's prompt. Edit freely.">
                <textarea className="textarea" rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. hand-painted watercolour animation, soft paper texture, warm afternoon light…" />
              </Field>
              <Field label="Avoid"><input className="input" value={avoid} onChange={(e) => setAvoid(e.target.value)} placeholder="photorealism, neon colours" /></Field>
              <div className="row">
                <button className="btn primary" disabled={prompt === (p?.style_prompt ?? "") && avoid === (p?.avoid ?? "")} onClick={() => save.mutate({ style_prompt: prompt, avoid })}><Wand2 size={14} /> Save style</button>
              </div>
            </div>
          </Card>
          <Card title="Using it">
            <div className="stack small">
              <div>{isDefault ? <><Check size={13} color="var(--ok)" /> Used for all new videos.</> : "Not the default. Make it the default above, or pick it per project under Project settings → Style."}</div>
              <div className="muted">Starred images go to MiniMax H3's reference mode when its Ref2VA model is installed in ComfyUI (Integrations → Auto-detect). Without it, the written style is used.</div>
            </div>
          </Card>
        </div>
      </div>
      {deleting && (
        <ConfirmDialog title="Delete this style?" danger requireText={st.name} confirmLabel="Delete style" busy={del.isPending}
          onClose={() => setDeleting(false)} onConfirm={() => del.mutate(undefined, { onSuccess: () => nav("/styles") })}>
          <p className="muted small">Its reference files are removed from the studio. Videos already made are not affected.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
