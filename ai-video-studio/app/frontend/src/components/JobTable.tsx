import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, ChevronsUp, Pause, Play, RotateCcw, Square, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { useAction } from "../lib/hooks";
import type { Job } from "../lib/types";
import { Badge, Details, Progress, StatusBadge } from "./ui";
import { dateTime, elapsed, timeAgo } from "../lib/format";

const LANE_LABEL: Record<string, string> = { gpu: "GPU", api: "API", cpu: "FFmpeg" };

export function JobTable({ jobs, showProject = true, reorder = false }: { jobs: Job[]; showProject?: boolean; reorder?: boolean }) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Job</th>
          <th>Status</th>
          <th style={{ width: "28%" }}>Progress</th>
          <th>Submitted</th>
          <th>Elapsed</th>
          <th>Tries</th>
          <th className="right">Actions</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => <JobRow key={j.id} job={j} showProject={showProject} reorder={reorder} />)}
      </tbody>
    </table>
  );
}

function JobRow({ job: j, showProject, reorder }: { job: Job; showProject: boolean; reorder: boolean }) {
  const [open, setOpen] = useState(false);
  const inv = { invalidate: [["jobs"], ["queue"], ["project"], ["dashboard"]] };
  const act = useAction((path: string) => api.post(`/jobs/${j.id}/${path}`), inv);
  const move = useAction((direction: string) => api.post(`/jobs/${j.id}/move`, { direction }), inv);
  const remove = useAction(() => api.del(`/jobs/${j.id}`), inv);
  const waiting = j.status === "pending" && j.next_attempt_at && new Date(j.next_attempt_at) > new Date();
  return (
    <>
      <tr>
        <td style={{ maxWidth: 320 }}>
          <div className="row" style={{ gap: 6 }}>
            <span style={{ fontWeight: 550 }}>{j.label}{j.scene_number ? ` · scene ${j.scene_number}` : ""}</span>
            <Badge>{LANE_LABEL[j.lane]}</Badge>
          </div>
          {showProject && j.project_id && (
            <Link to={`/production/${j.project_id}`} className="small ellipsis" style={{ display: "block", color: "var(--muted)" }}>{j.project_title ?? `Project ${j.project_id}`}</Link>
          )}
        </td>
        <td><StatusBadge status={j.status} /></td>
        <td>
          {j.status === "running" ? (
            <div className="stack tight">
              <Progress value={j.progress} />
              <span className="tiny muted ellipsis">{j.progress_message}</span>
            </div>
          ) : j.status === "failed" ? (
            <button className="details-toggle" style={{ color: "var(--err)", textAlign: "left" }} onClick={() => setOpen(!open)}>{j.error_message}</button>
          ) : (
            <span className="tiny muted">{waiting ? `Retry ${timeAgo(j.next_attempt_at)} — ${j.error_message ?? ""}` : j.progress_message}</span>
          )}
        </td>
        <td className="small muted nowrap" title={dateTime(j.created_at)}>{timeAgo(j.created_at)}</td>
        <td className="small nowrap">{j.started_at ? elapsed(j.started_at, j.finished_at) : "—"}</td>
        <td className="small">{j.attempts}/{j.max_attempts}</td>
        <td className="right nowrap">
          {reorder && (j.status === "pending" || j.status === "paused") && (
            <>
              <button className="btn icon ghost" title="Move to top" onClick={() => move.mutate("top")}><ChevronsUp size={14} /></button>
              <button className="btn icon ghost" title="Move up" onClick={() => move.mutate("up")}><ArrowUp size={14} /></button>
              <button className="btn icon ghost" title="Move down" onClick={() => move.mutate("down")}><ArrowDown size={14} /></button>
            </>
          )}
          {j.status === "pending" && <button className="btn icon ghost" title="Hold this job" onClick={() => act.mutate("pause")}><Pause size={14} /></button>}
          {j.status === "paused" && <button className="btn icon ghost" title="Release this job" onClick={() => act.mutate("resume")}><Play size={14} /></button>}
          {(j.status === "pending" || j.status === "running" || j.status === "paused") && (
            <button className="btn icon ghost" title={j.status === "running" ? "Cancel safely (stops this generation)" : "Cancel"} onClick={() => act.mutate("cancel")}><Square size={13} /></button>
          )}
          {(j.status === "failed" || j.status === "cancelled") && <button className="btn icon ghost" title="Retry" onClick={() => act.mutate("retry")}><RotateCcw size={14} /></button>}
          {j.status !== "running" && <button className="btn icon ghost" title="Remove from list" onClick={() => remove.mutate()}><Trash2 size={14} /></button>}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} style={{ background: "var(--bg)" }}>
            <div className="small">Error type: <b>{j.error_kind}</b>{j.provider && <> · provider: {j.provider}</>}</div>
            {j.error_detail ? <Details text={j.error_detail} /> : <span className="tiny faint">No technical details.</span>}
          </td>
        </tr>
      )}
    </>
  );
}
