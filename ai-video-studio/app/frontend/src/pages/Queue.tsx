import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Cpu, ListOrdered, Pause, Play, RotateCcw, Trash2, Zap } from "lucide-react";
import { api } from "../lib/api";
import { useAction, useSaveSettings, useSettings } from "../lib/hooks";
import type { Job, QueueState } from "../lib/types";
import { Card, Empty, ErrorNote, Field, ListInput, NumberInput, PageHeader, Progress, Segmented, StatusBadge, Toggle } from "../components/ui";
import { JobTable } from "../components/JobTable";

const LANES = [
  { key: "gpu", label: "GPU generation", icon: Zap, hint: "Video and still generation" },
  { key: "api", label: "API calls", icon: ListOrdered, hint: "Groq, Fish Audio, research" },
  { key: "cpu", label: "FFmpeg", icon: Cpu, hint: "Assembly and checks" },
];

export default function Queue() {
  const [filter, setFilter] = useState<"active" | "failed" | "done" | "all">("active");
  const statuses = { active: "pending,running,paused", failed: "failed", done: "completed,cancelled", all: "" }[filter];
  const { data: q } = useQuery({ queryKey: ["queue"], queryFn: () => api.get<QueueState>("/queue"), refetchInterval: 5000 });
  const { data: jobs, isLoading, error } = useQuery({ queryKey: ["jobs", filter], queryFn: () => api.get<Job[]>(`/jobs?status=${statuses}`), refetchInterval: 5000 });
  const inv = { invalidate: [["queue"], ["jobs"], ["settings"], ["dashboard"]] };
  const pause = useAction(() => api.post("/queue/pause"), { ...inv, success: "Queue paused — running jobs will finish" });
  const resume = useAction((reset: boolean) => api.post(`/queue/resume${reset ? "?reset_session=true" : ""}`), { ...inv, success: "Queue resumed" });
  const clear = useAction(() => api.post<{ removed: number }>("/jobs/clear-finished"), { ...inv, success: (r) => `Removed ${r.removed} finished jobs` });
  const retryAll = useAction(async () => {
    const failed = (jobs ?? []).filter((j) => j.status === "failed");
    for (const j of failed) await api.post(`/jobs/${j.id}/retry`);
    return failed.length;
  }, { ...inv, success: (n) => `Retrying ${n} job(s)` });

  return (
    <div className="page">
      <PageHeader title="Queue Manager" sub="Persistent job queue. Pausing stops new jobs from starting; running jobs finish (or cancel them safely)."
        actions={q?.paused
          ? <button className="btn primary big" onClick={() => resume.mutate(false)}><Play size={16} /> Resume queue</button>
          : <button className="btn big" onClick={() => pause.mutate()}><Pause size={16} /> Pause new jobs</button>} />

      <div className="grid cols-3" style={{ marginBottom: 16 }}>
        {LANES.map(({ key, label, icon: Icon, hint }) => {
          const lane = q?.lanes[key];
          return (
            <Card key={key}>
              <div className="row between">
                <span className="row"><Icon size={16} /> <b>{label}</b></span>
                {lane && <StatusBadge status={lane.allowed ? (lane.running ? "running" : "ok") : "paused"} label={lane.allowed ? (lane.running ? "Working" : "Ready") : "On hold"} />}
              </div>
              <div className="small muted" style={{ marginTop: 6 }}>{hint}</div>
              <div style={{ marginTop: 10 }} className="row between small">
                <span>{lane ? `${lane.running} running / ${lane.limit} max` : "—"}</span>
                {key === "gpu" && q && <span className="muted">{q.session_gpu_jobs} this session</span>}
              </div>
              {lane && !lane.allowed && <div className="small" style={{ color: "var(--warn)", marginTop: 6 }}>{lane.reason}</div>}
              {key === "gpu" && lane?.reason.startsWith("Session limit") && (
                <button className="btn sm" style={{ marginTop: 8 }} onClick={() => resume.mutate(true)}><RotateCcw size={13} /> Reset session count</button>
              )}
            </Card>
          );
        })}
      </div>

      <div className="split-wide">
        <div className="stack">
          <div className="row">
            <Segmented value={filter} onChange={setFilter} options={[
              { value: "active", label: "Active" }, { value: "failed", label: `Failed${q?.counts.failed ? ` (${q.counts.failed})` : ""}` },
              { value: "done", label: "Finished" }, { value: "all", label: "All" },
            ]} />
            <div className="spacer" />
            {filter === "failed" && !!jobs?.length && <button className="btn sm" onClick={() => retryAll.mutate()}><RotateCcw size={13} /> Retry all</button>}
            {filter === "done" && !!jobs?.length && <button className="btn sm" onClick={() => clear.mutate()}><Trash2 size={13} /> Clear finished</button>}
          </div>
          <ErrorNote error={error} />
          <Card className="flush">
            {isLoading ? <div style={{ padding: 18 }}><Progress /></div> : !jobs?.length ? (
              <Empty icon={<ListOrdered size={26} />} title={filter === "active" ? "Nothing queued" : "No jobs"}>Jobs appear here as projects move through the pipeline.</Empty>
            ) : <JobTable jobs={jobs} reorder={filter === "active"} />}
          </Card>
        </div>
        <div className="stack">
          {!!q?.awaiting_approval?.length && (
            <Card title="Waiting for approval">
              <div className="list">
                {q.awaiting_approval.map((p) => (
                  <Link key={p.id} to={`/production/${p.id}`} className="list-item" style={{ color: "inherit" }}>
                    <div style={{ minWidth: 0 }}>
                      <div className="ellipsis" style={{ fontWeight: 550 }}>{p.title}</div>
                      <div className="small muted">{p.status_message}</div>
                    </div>
                  </Link>
                ))}
              </div>
            </Card>
          )}
          <QueueLimits />
        </div>
      </div>
    </div>
  );
}

function QueueLimits() {
  const { data: s } = useSettings();
  const save = useSaveSettings();
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  if (!s) return null;
  const q = { ...s.queue, ...(draft ?? {}) };
  const set = (k: string, v: unknown) => setDraft({ ...(draft ?? {}), [k]: v });
  return (
    <Card title="Limits & schedule">
      <div className="stack">
        <Field label="Concurrent GPU jobs" hint="Keep at 1 on a 12 GB card: two video models rarely fit in VRAM together.">
          <NumberInput value={q.max_gpu_jobs} min={1} max={4} onChange={(v) => set("max_gpu_jobs", v)} />
        </Field>
        <div className="grid cols-2">
          <Field label="Concurrent API jobs"><NumberInput value={q.max_api_jobs} min={1} max={8} onChange={(v) => set("max_api_jobs", v)} /></Field>
          <Field label="GPU jobs per session" hint="0 = unlimited"><NumberInput value={q.max_jobs_per_session} min={0} onChange={(v) => set("max_jobs_per_session", v)} /></Field>
        </div>
        <Toggle checked={q.processing_window.enabled} onChange={(v) => set("processing_window", { ...q.processing_window, enabled: v })} label="Only generate during set hours" />
        {q.processing_window.enabled && (
          <div className="grid cols-2">
            <Field label="From"><input className="input" type="time" value={q.processing_window.start} onChange={(e) => set("processing_window", { ...q.processing_window, start: e.target.value })} /></Field>
            <Field label="Until"><input className="input" type="time" value={q.processing_window.end} onChange={(e) => set("processing_window", { ...q.processing_window, end: e.target.value })} /></Field>
          </div>
        )}
        <Toggle checked={q.defer_when_gpu_busy} onChange={(v) => set("defer_when_gpu_busy", v)} label="Wait while another app is using the GPU" />
        <Field label="Hold GPU jobs while these programs run" hint="Process names, comma-separated (e.g. a game's .exe).">
          <ListInput value={q.pause_when_processes as string[]} onChange={(v) => set("pause_when_processes", v)} placeholder="e.g. eldenring.exe" />
        </Field>
        <button className="btn primary" disabled={!draft || save.isPending} onClick={() => save.mutate({ queue: draft! }, { onSuccess: () => setDraft(null) })}>Save limits</button>
      </div>
    </Card>
  );
}
