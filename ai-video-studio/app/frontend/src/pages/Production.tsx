import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Clapperboard, Plus } from "lucide-react";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import type { ProjectSummary } from "../lib/types";
import { Card, Empty, ErrorNote, Field, Modal, PageHeader, Progress, StatusBadge, Toggle } from "../components/ui";
import { timeAgo, titleCase } from "../lib/format";

export default function Production() {
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(params.get("new") === "1");
  const { data, isLoading, error } = useQuery({ queryKey: ["projects"], queryFn: () => api.get<ProjectSummary[]>("/projects") });
  return (
    <div className="page">
      <PageHeader title="Production Studio" sub="Every active project, where it is, and what it needs next."
        actions={<button className="btn primary" onClick={() => setCreating(true)}><Plus size={15} /> New project</button>} />
      <ErrorNote error={error} />
      {isLoading ? <Progress /> : !data?.length ? (
        <Card><Empty icon={<Clapperboard size={28} />} title="No projects yet">Approve an idea in the Idea Studio or start a project from your own topic.</Empty></Card>
      ) : (
        <Card className="flush">
          <table className="table">
            <thead><tr><th>Project</th><th>Stage</th><th>Status</th><th>Clips</th><th>Updated</th></tr></thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.id} className="clickable">
                  <td style={{ maxWidth: 360 }}>
                    <Link to={`/production/${p.id}`} style={{ color: "var(--text)", fontWeight: 550 }}>{p.title}</Link>
                    <div className="small muted ellipsis">{p.status_message}</div>
                  </td>
                  <td>{titleCase(p.stage)}</td>
                  <td><StatusBadge status={p.status} /></td>
                  <td className="nowrap">{p.scenes ? `${p.clips_done}/${p.scenes}` : "—"}</td>
                  <td className="small muted nowrap">{timeAgo(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {creating && <NewProject onClose={() => { setCreating(false); setParams({}); }} />}
    </div>
  );
}

function NewProject({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [start, setStart] = useState(true);
  const create = useAction(() => api.post<{ id: number }>("/projects", { title, description, start }), { invalidate: [["projects"]], success: "Project created" });
  return (
    <Modal title="New project from your own topic" onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={title.trim().length < 3 || create.isPending} onClick={() => create.mutate(undefined, { onSuccess: (p) => nav(`/production/${p.id}`) })}>Create project</button>
      </>}>
      <Field label="Topic or working title"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Why do cats purr?" autoFocus /></Field>
      <Field label="What should the video explain?" hint="Optional, but helps the scriptwriter.">
        <textarea className="textarea" rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Toggle checked={start} onChange={setStart} label="Start research and script right away" />
    </Modal>
  );
}
