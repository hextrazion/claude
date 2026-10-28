import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, Clapperboard, Film, HardDrive, Lightbulb, ListOrdered, Plus, RefreshCw, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import type { Activity, Health, QueueState, SystemInfo } from "../lib/types";
import { Card, Empty, Meter, PageHeader, StatusBadge } from "../components/ui";
import { timeAgo, titleCase } from "../lib/format";

type Dash = {
  counts: Record<string, number>;
  attention: { id: number; title: string; stage: string; status: string; status_message: string; updated_at: string }[];
  activity: Activity[];
  errors: Activity[];
  integrations: Record<string, Health>;
  queue: QueueState | null;
  usage_today: { provider: string; requests: number; ok: number; characters: number; tokens: number; cost_usd: number }[];
  mode: string;
};

const SERVICE_LABELS: Record<string, string> = {
  groq: "Groq", fish_audio: "Fish Audio", comfyui: "Video engine", research: "Research", ffmpeg: "FFmpeg", storage: "Storage",
};

export default function Dashboard() {
  const nav = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dash>("/dashboard"), refetchInterval: 15000 });
  const { data: sys } = useQuery({ queryKey: ["system"], queryFn: () => api.get<SystemInfo>("/system"), refetchInterval: 5000 });
  const testAll = useAction(() => api.post("/integrations/test-all"), { invalidate: [["dashboard"], ["integrations"]], success: "Checked all services" });
  const c = data?.counts;
  const stats = [
    { label: "Projects", value: c?.projects, icon: Clapperboard, to: "/production" },
    { label: "Ideas awaiting approval", value: c?.ideas_awaiting, icon: Lightbulb, to: "/ideas" },
    { label: "Processing", value: c?.processing, icon: ListOrdered, to: "/queue" },
    { label: "Awaiting review", value: c?.awaiting_review, icon: Film, to: "/library" },
    { label: "Failed jobs", value: c?.failed_jobs, icon: AlertTriangle, to: "/queue" },
  ];
  const gpu = sys?.gpus?.[0];
  return (
    <div className="page">
      <PageHeader
        title="Dashboard"
        sub={data ? <>Mode: <b>{titleCase(data.mode)}</b>{data.queue?.paused && <> · <span style={{ color: "var(--warn)" }}>queue paused</span></>}</> : " "}
        actions={
          <>
            <button className="btn" onClick={() => nav("/production?new=1")}><Plus size={15} /> New project</button>
            <button className="btn primary" onClick={() => nav("/ideas?generate=1")}><Sparkles size={15} /> Generate ideas</button>
          </>
        }
      />

      <div className="grid cols-5" style={{ marginBottom: 16 }}>
        {stats.map((s) => (
          <Link to={s.to} key={s.label} className="card selectable" style={{ color: "inherit", textDecoration: "none" }}>
            <div className="stat">
              <span className="stat-label"><s.icon size={14} /> {s.label}</span>
              {s.value == null ? <span className="stat-value unavailable">{isLoading ? "…" : "Unavailable"}</span> : <span className="stat-value">{s.value}</span>}
            </div>
          </Link>
        ))}
      </div>

      <div className="split-wide">
        <div className="stack">
          <Card title="Needs your attention" sub="Projects waiting for approval or with failed work">
            {!data?.attention.length ? (
              <Empty title="Nothing waiting">Approvals and failures show up here.</Empty>
            ) : (
              <div className="list">
                {data.attention.map((p) => (
                  <Link key={p.id} to={`/production/${p.id}`} className="list-item" style={{ color: "inherit" }}>
                    <StatusBadge status={p.status} />
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className="ellipsis" style={{ fontWeight: 550 }}>{p.title}</div>
                      <div className="small muted ellipsis">{p.status_message}</div>
                    </div>
                    <span className="tiny faint nowrap">{timeAgo(p.updated_at)}</span>
                  </Link>
                ))}
              </div>
            )}
          </Card>

          <Card title="Recent activity">
            {!data?.activity.length ? <Empty title="No activity yet" /> : (
              <div className="list">
                {data.activity.map((a) => (
                  <div className="list-item small" key={a.id}>
                    <span style={{ width: 8, height: 8, borderRadius: 4, flex: "none", background: a.level === "error" ? "var(--err)" : a.level === "warning" ? "var(--warn)" : "var(--border-strong)" }} />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      {a.project_id ? <Link to={`/production/${a.project_id}`} style={{ color: "inherit" }}>{a.message}</Link> : a.message}
                    </span>
                    <span className="tiny faint nowrap">{timeAgo(a.ts)}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="stack">
          <Card title="Services" actions={<button className="btn sm ghost" onClick={() => testAll.mutate()} disabled={testAll.isPending}><RefreshCw size={13} className={testAll.isPending ? "spin" : ""} /> Check</button>}>
            <div className="list">
              {Object.entries(SERVICE_LABELS).map(([k, label]) => {
                const h = data?.integrations?.[k];
                return (
                  <Link to="/integrations" className="list-item" key={k} style={{ color: "inherit" }}>
                    <span style={{ flex: 1 }}>{label}</span>
                    {h ? <StatusBadge status={h.status} /> : <span className="tiny faint">Not checked</span>}
                  </Link>
                );
              })}
            </div>
          </Card>

          <Card title="System">
            <div className="stack">
              {gpu ? <div className="small muted">{gpu.name}</div> : <div className="small faint">GPU metrics unavailable (nvidia-smi not found)</div>}
              <Meter label="GPU load" value={gpu?.utilization_pct} max={gpu ? 100 : null} unit="%" />
              <Meter label="VRAM" value={gpu?.memory_used_mb != null ? gpu.memory_used_mb / 1024 : null} max={gpu?.memory_total_mb ? gpu.memory_total_mb / 1024 : null} unit=" GB" />
              <div className="row between small"><span className="muted">GPU temperature</span><span>{gpu?.temperature_c != null ? `${gpu.temperature_c}°C` : "Unavailable"}</span></div>
              <Meter label="RAM" value={sys?.ram_used_gb} max={sys?.ram_total_gb} unit=" GB" />
              <Meter label="Project drive" value={sys?.disk ? sys.disk.total_gb - sys.disk.free_gb : null} max={sys?.disk?.total_gb} unit=" GB" warnAt={0.9} />
              {sys?.low_disk && <div className="note warn small"><HardDrive size={14} /> Low disk space: {sys.disk?.free_gb} GB free.</div>}
            </div>
          </Card>

          <Card title="API usage today">
            {!data?.usage_today.length ? <div className="small faint">No API calls today.</div> : (
              <table className="table small">
                <thead><tr><th>Provider</th><th className="right">Calls</th><th className="right">Est. cost</th></tr></thead>
                <tbody>
                  {data.usage_today.map((u) => (
                    <tr key={u.provider}>
                      <td>{SERVICE_LABELS[u.provider] ?? titleCase(u.provider)}</td>
                      <td className="right">{u.requests}{u.requests !== u.ok && <span style={{ color: "var(--err)" }}> ({u.requests - u.ok} failed)</span>}</td>
                      <td className="right">${(u.cost_usd ?? 0).toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {!!data?.errors.length && (
            <Card title="Recent errors">
              <div className="list">
                {data.errors.map((e) => (
                  <div className="list-item small" key={e.id} style={{ alignItems: "flex-start" }}>
                    <AlertTriangle size={14} color="var(--err)" style={{ flex: "none", marginTop: 3 }} />
                    <span style={{ flex: 1 }}>{e.message}</span>
                    <span className="tiny faint nowrap">{timeAgo(e.ts)}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
