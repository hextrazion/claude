import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Clapperboard, Film, Gauge, Lightbulb, ListOrdered, Palette, Pause, Play, Plug, Settings as SettingsIcon, WifiOff } from "lucide-react";
import { api } from "./lib/api";
import { useAction, useLiveEvents } from "./lib/hooks";
import type { QueueState, SystemInfo } from "./lib/types";
import { Meter } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Ideas from "./pages/Ideas";
import Production from "./pages/Production";
import ProjectWorkspace from "./pages/ProjectWorkspace";
import Queue from "./pages/Queue";
import Styles, { StyleDetail } from "./pages/Styles";
import Library from "./pages/Library";
import Integrations from "./pages/Integrations";
import SettingsPage from "./pages/Settings";

export default function App() {
  const connected = useLiveEvents();
  const { data: dash } = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<{ counts: Record<string, number> }>("/dashboard"), refetchInterval: 15000 });
  const counts = dash?.counts;
  const nav = [
    { to: "/", label: "Dashboard", icon: Gauge, end: true },
    { to: "/ideas", label: "Idea Studio", icon: Lightbulb, count: counts?.ideas_awaiting },
    { to: "/production", label: "Production", icon: Clapperboard, count: counts?.waiting_approval, alert: !!counts?.waiting_approval },
    { to: "/styles", label: "Styles", icon: Palette },
    { to: "/queue", label: "Queue", icon: ListOrdered, count: counts?.failed_jobs, alert: !!counts?.failed_jobs },
    { to: "/library", label: "Library", icon: Film, count: counts?.awaiting_review },
    { to: "/integrations", label: "Integrations", icon: Plug },
    { to: "/settings", label: "Settings", icon: SettingsIcon },
  ];
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Play size={14} fill="white" /></div>
          AI Video Studio
        </div>
        {nav.map(({ to, label, icon: Icon, end, count, alert }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            <Icon size={17} />
            {label}
            {!!count && <span className={`nav-count ${alert ? "alert" : ""}`}>{count}</span>}
          </NavLink>
        ))}
        <SidebarFooter connected={connected} />
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/ideas" element={<Ideas />} />
          <Route path="/production" element={<Production />} />
          <Route path="/production/:id" element={<ProjectWorkspace />} />
          <Route path="/styles" element={<Styles />} />
          <Route path="/styles/:id" element={<StyleDetail />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/library" element={<Library />} />
          <Route path="/integrations" element={<Integrations />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function SidebarFooter({ connected }: { connected: boolean }) {
  const { data: q } = useQuery({ queryKey: ["queue"], queryFn: () => api.get<QueueState>("/queue"), refetchInterval: 10000 });
  const { data: sys } = useQuery({ queryKey: ["system"], queryFn: () => api.get<SystemInfo>("/system"), refetchInterval: 5000 });
  const toggle = useAction(() => api.post<QueueState>(q?.paused ? "/queue/resume" : "/queue/pause"), { invalidate: [["queue"], ["settings"]] });
  const gpu = sys?.gpus?.[0];
  const running = q ? Object.values(q.lanes).reduce((a, l) => a + l.running, 0) : 0;
  return (
    <div className="sidebar-footer">
      {!connected && (
        <div className="note warn small"><WifiOff size={14} /> Live updates disconnected — retrying</div>
      )}
      <div className="row between small">
        <span className="muted">Queue</span>
        <span>{q ? (q.paused ? "Paused" : running ? `${running} running` : "Idle") : "—"}</span>
      </div>
      <button className={`btn sm ${q?.paused ? "primary" : ""}`} onClick={() => toggle.mutate()} disabled={!q || toggle.isPending}
        title={q?.paused ? "Start launching jobs again" : "Stop launching new jobs; running jobs finish"}>
        {q?.paused ? <><Play size={13} /> Resume queue</> : <><Pause size={13} /> Pause new jobs</>}
      </button>
      <Meter label="GPU" value={gpu?.utilization_pct} max={gpu ? 100 : null} unit="%" />
      <Meter label="VRAM" value={gpu?.memory_used_mb != null ? gpu.memory_used_mb / 1024 : null} max={gpu?.memory_total_mb ? gpu.memory_total_mb / 1024 : null} unit=" GB" />
    </div>
  );
}
