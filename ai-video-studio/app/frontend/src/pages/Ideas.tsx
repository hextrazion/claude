import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Check, Copy, Lightbulb, Plus, Search, Sparkles, Star, Trash2, X } from "lucide-react";
import { api } from "../lib/api";
import { useAction, useSettings } from "../lib/hooks";
import type { Idea, Job } from "../lib/types";
import { Badge, Card, ConfirmDialog, Empty, ErrorNote, Field, Modal, NumberInput, PageHeader, Progress, Segmented, StatusBadge } from "../components/ui";
import { timeAgo } from "../lib/format";

const FILTERS = [
  { value: "active", label: "To review" },
  { value: "favorite", label: "Favourites" },
  { value: "approved", label: "In production" },
  { value: "produced", label: "Produced" },
  { value: "rejected", label: "Rejected" },
  { value: "", label: "All" },
] as const;

export default function Ideas() {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<string>("active");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"new" | "score" | "title">("score");
  const [selected, setSelected] = useState<Idea | null>(null);
  const [creating, setCreating] = useState(false);
  const { data: ideas, isLoading, error } = useQuery({
    queryKey: ["ideas", filter, q, sort],
    queryFn: () => api.get<Idea[]>(`/ideas?status=${filter}&sort=${sort}&q=${encodeURIComponent(q)}`),
  });
  const { data: jobs } = useQuery({ queryKey: ["jobs", "ideas"], queryFn: () => api.get<Job[]>("/jobs?status=pending,running"), refetchInterval: 4000 });
  const ideaJobs = (jobs ?? []).filter((j) => j.kind === "ideas");
  const byId = useMemo(() => new Map((ideas ?? []).map((i) => [i.id, i])), [ideas]);

  return (
    <div className="page">
      <PageHeader title="Idea Studio" sub="Generate, refine and approve concepts. Approved ideas become projects."
        actions={<button className="btn" onClick={() => setCreating(true)}><Plus size={15} /> Add idea manually</button>} />
      <div className="split">
        <GeneratePanel autoFocus={params.get("generate") === "1"} onStarted={() => setParams({})} running={ideaJobs} />
        <div className="stack">
          <div className="row wrap">
            <Segmented value={filter} onChange={setFilter} options={FILTERS.map((f) => ({ value: f.value, label: f.label }))} />
            <div className="spacer" />
            <div className="row" style={{ position: "relative" }}>
              <Search size={14} style={{ position: "absolute", left: 10, color: "var(--faint)" }} />
              <input className="input" style={{ paddingLeft: 30, width: 220 }} placeholder="Search ideas" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <select className="select" style={{ width: 150 }} value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
              <option value="score">Best score</option>
              <option value="new">Newest</option>
              <option value="title">Title</option>
            </select>
          </div>
          <ErrorNote error={error} />
          {isLoading ? <Progress /> : !ideas?.length ? (
            <Card><Empty icon={<Lightbulb size={28} />} title="No ideas here yet">Use the panel on the left to generate a batch with Groq, or add one manually.</Empty></Card>
          ) : (
            <div className="grid cols-2">
              {ideas.map((idea) => <IdeaCard key={idea.id} idea={idea} dupe={idea.duplicate_of ? byId.get(idea.duplicate_of) : undefined} onOpen={() => setSelected(idea)} />)}
            </div>
          )}
        </div>
      </div>
      {selected && <IdeaModal idea={selected} onClose={() => setSelected(null)} />}
      {creating && <IdeaModal onClose={() => setCreating(false)} />}
    </div>
  );
}

function GeneratePanel({ autoFocus, onStarted, running }: { autoFocus: boolean; onStarted: () => void; running: Job[] }) {
  const { data: settings } = useSettings();
  const [form, setForm] = useState({ niche: "", exclusions: "", count: 8, duration_s: 35, tone: "", notes: "" });
  useEffect(() => {
    if (settings) setForm((f) => ({ ...f, niche: f.niche || settings.general.default_niche, duration_s: settings.video.duration_s, tone: f.tone || settings.general.tone }));
  }, [settings]);
  const gen = useAction(() => api.post<{ job_id: number }>("/ideas/generate", form), { invalidate: [["jobs"]], success: "Generating ideas…" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Card title="Generate ideas" sub="Uses your Groq quality model">
      <div className="stack">
        <Field label="Niche / themes"><textarea className="textarea" rows={2} value={form.niche} onChange={set("niche")} autoFocus={autoFocus} /></Field>
        <Field label="Exclude topics" hint="Comma-separated"><input className="input" value={form.exclusions} onChange={set("exclusions")} placeholder="e.g. dinosaurs, black holes" /></Field>
        <div className="grid cols-2">
          <Field label="How many"><NumberInput value={form.count} min={1} max={20} onChange={(v) => setForm({ ...form, count: v })} /></Field>
          <Field label="Length (s)"><NumberInput value={form.duration_s} min={5} max={180} onChange={(v) => setForm({ ...form, duration_s: v })} /></Field>
        </div>
        <Field label="Tone"><input className="input" value={form.tone} onChange={set("tone")} /></Field>
        <Field label="Extra direction" hint="Optional"><input className="input" value={form.notes} onChange={set("notes")} placeholder="e.g. focus on kitchen science" /></Field>
        <button className="btn primary big" disabled={gen.isPending || !!running.length} onClick={() => { gen.mutate(); onStarted(); }}>
          <Sparkles size={15} /> {running.length ? "Generating…" : "Generate ideas"}
        </button>
        {running.map((j) => (
          <div key={j.id} className="stack tight">
            <div className="small muted">{j.progress_message || "Waiting in queue"}</div>
            <Progress value={j.status === "running" ? j.progress : null} />
          </div>
        ))}
        <div className="tiny faint">Ideas you have already produced or rejected are sent as "do not repeat" examples.</div>
      </div>
    </Card>
  );
}

function IdeaCard({ idea, dupe, onOpen }: { idea: Idea; dupe?: Idea; onOpen: () => void }) {
  const fav = useAction(() => api.patch(`/ideas/${idea.id}`, { status: idea.status === "favorite" ? "new" : "favorite" }), { invalidate: [["ideas"]] });
  const reject = useAction(() => api.patch(`/ideas/${idea.id}`, { status: "rejected" }), { invalidate: [["ideas"], ["dashboard"]] });
  const editable = idea.status === "new" || idea.status === "favorite";
  return (
    <div className="card selectable idea-card" onClick={onOpen}>
      <div className="stack tight">
        <div className="row between" style={{ alignItems: "flex-start" }}>
          <h3>{idea.title}</h3>
          {idea.score != null && <span className="score" style={{ color: idea.score >= 8 ? "var(--ok)" : idea.score >= 6.5 ? "var(--text)" : "var(--faint)" }}>{idea.score.toFixed(1)}</span>}
        </div>
        {idea.hook && <div className="small hook">“{idea.hook}”</div>}
        <div className="small muted" style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{idea.description || idea.central_question}</div>
        <div className="row wrap" style={{ marginTop: 6 }}>
          {idea.niche && <Badge>{idea.niche}</Badge>}
          {idea.status !== "new" && <StatusBadge status={idea.status} />}
          {dupe && <Badge tone="warn"><Copy size={11} /> Similar to “{dupe.title.slice(0, 28)}…”</Badge>}
          {!dupe && idea.duplicate_of && <Badge tone="warn"><Copy size={11} /> Possible duplicate</Badge>}
          <span className="spacer" />
          <span className="tiny faint">{timeAgo(idea.created_at)}</span>
          {editable && (
            <span className="row" onClick={(e) => e.stopPropagation()}>
              <button className="btn icon ghost" title="Favourite" onClick={() => fav.mutate()}><Star size={15} fill={idea.status === "favorite" ? "var(--warn)" : "none"} color={idea.status === "favorite" ? "var(--warn)" : undefined} /></button>
              <button className="btn icon ghost" title="Reject" onClick={() => reject.mutate()}><X size={15} /></button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

const FIELDS: [keyof Idea, string, number][] = [
  ["title", "Working title", 1],
  ["central_question", "Central question or surprising idea", 2],
  ["hook", "Opening hook", 2],
  ["description", "Description", 3],
  ["appeal", "Why viewers will care", 2],
  ["visual_approach", "Visual approach", 2],
  ["research_needs", "Research requirements", 2],
  ["accuracy_concerns", "Accuracy concerns", 2],
  ["niche", "Niche", 1],
  ["notes", "Your notes", 2],
];

function IdeaModal({ idea, onClose }: { idea?: Idea; onClose: () => void }) {
  const nav = useNavigate();
  const [form, setForm] = useState<Partial<Idea>>(idea ?? { title: "" });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const editable = !idea || idea.status === "new" || idea.status === "favorite" || idea.status === "rejected";
  const save = useAction(
    () => {
      const body = Object.fromEntries(FIELDS.map(([k]) => [k, form[k] ?? ""]));
      return idea ? api.patch<Idea>(`/ideas/${idea.id}`, body) : api.post<Idea>("/ideas", body);
    },
    { invalidate: [["ideas"]], success: idea ? "Idea saved" : "Idea added" },
  );
  const approve = useAction(
    async (start: boolean) => {
      const saved = idea ? await api.patch<Idea>(`/ideas/${idea.id}`, Object.fromEntries(FIELDS.map(([k]) => [k, form[k] ?? ""]))) : await api.post<Idea>("/ideas", form);
      return api.post<{ id: number }>(`/ideas/${saved.id}/approve`, { start });
    },
    { invalidate: [["ideas"], ["projects"], ["dashboard"]], success: "Project created" },
  );
  const del = useAction(() => api.del(`/ideas/${idea!.id}`), { invalidate: [["ideas"]], success: "Idea deleted" });
  return (
    <Modal wide title={idea ? "Idea details" : "New idea"} onClose={onClose}
      footer={
        <>
          {idea && !idea.project_id && <button className="btn danger" onClick={() => setConfirmDelete(true)}><Trash2 size={14} /> Delete</button>}
          <div className="spacer" />
          {idea?.project_id ? (
            <button className="btn primary" onClick={() => nav(`/production/${idea.project_id}`)}>Open project</button>
          ) : (
            <>
              {editable && <button className="btn" disabled={save.isPending || !form.title} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>Save</button>}
              <button className="btn" disabled={approve.isPending || !form.title} onClick={() => approve.mutate(false, { onSuccess: (p) => nav(`/production/${p.id}`) })}>Approve only</button>
              <button className="btn primary" disabled={approve.isPending || !form.title} onClick={() => approve.mutate(true, { onSuccess: (p) => nav(`/production/${p.id}`) })}>
                <Check size={15} /> Approve & start
              </button>
            </>
          )}
        </>
      }>
      {idea?.duplicate_of && <div className="note warn small">This looks similar to idea #{idea.duplicate_of} ({Math.round((idea.duplicate_score ?? 0) * 100)}% overlap). Make sure it is genuinely different.</div>}
      <div className="grid cols-2">
        {FIELDS.map(([k, label, rows]) => (
          <div key={k} style={rows >= 3 || k === "title" ? { gridColumn: "1 / -1" } : undefined}>
            <Field label={label}>
              {rows === 1 ? (
                <input className="input" value={(form[k] as string) ?? ""} disabled={!editable} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
              ) : (
                <textarea className="textarea" rows={rows} value={(form[k] as string) ?? ""} disabled={!editable} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
              )}
            </Field>
          </div>
        ))}
      </div>
      <div className="tiny faint">“Approve & start” follows your automation mode: in Supervised mode it researches and writes the script, then waits for you.</div>
      {confirmDelete && idea && (
        <ConfirmDialog title="Delete this idea?" danger confirmLabel="Delete" busy={del.isPending} onClose={() => setConfirmDelete(false)}
          onConfirm={() => del.mutate(undefined, { onSuccess: () => { setConfirmDelete(false); onClose(); } })}>
          <p className="muted">“{idea.title}” will be removed. Rejecting keeps it as a do-not-repeat example instead.</p>
        </ConfirmDialog>
      )}
    </Modal>
  );
}
