import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Archive, ArchiveRestore, ExternalLink, Film, FolderOpen, Pencil, Search, Trash2 } from "lucide-react";
import { api, fileUrl } from "../lib/api";
import { useAction } from "../lib/hooks";
import type { Project } from "../lib/types";
import { Card, ConfirmDialog, Empty, ErrorNote, Field, Modal, PageHeader, Progress, StatusBadge, Toggle } from "../components/ui";
import { dateTime, duration } from "../lib/format";

type Item = Pick<Project, "id" | "title" | "created_at" | "updated_at" | "stage" | "status" | "export_status" | "review_status" | "folder" | "export"> & {
  archived: boolean;
  qc: { technical_ok: boolean | null; failures: number | null; warnings: number | null };
};

export default function Library() {
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const [onlyExported, setOnlyExported] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["library", q, archived],
    queryFn: () => api.get<Item[]>(`/library?include_archived=${archived}&q=${encodeURIComponent(q)}`),
  });
  const items = (data ?? []).filter((i) => (!onlyExported || i.export) && (archived || !i.archived));
  return (
    <div className="page">
      <PageHeader title="Video Library" sub="All projects and their finished videos." />
      <div className="row wrap" style={{ marginBottom: 16 }}>
        <div className="row" style={{ position: "relative" }}>
          <Search size={14} style={{ position: "absolute", left: 10, color: "var(--faint)" }} />
          <input className="input" style={{ paddingLeft: 30, width: 260 }} placeholder="Search titles" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Toggle checked={onlyExported} onChange={setOnlyExported} label="Only finished videos" />
        <Toggle checked={archived} onChange={setArchived} label="Include archived" />
      </div>
      <ErrorNote error={error} />
      {isLoading ? <Progress /> : !items.length ? (
        <Card><Empty icon={<Film size={28} />} title="Nothing here yet">Finished videos appear here after assembly.</Empty></Card>
      ) : (
        <div className="grid cols-4">{items.map((i) => <LibraryCard key={i.id} item={i} />)}</div>
      )}
    </div>
  );
}

function LibraryCard({ item }: { item: Item }) {
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [deleting, setDeleting] = useState(false);
  const [deleteFiles, setDeleteFiles] = useState(false);
  const inv = { invalidate: [["library"], ["projects"], ["dashboard"]] };
  const rename = useAction(() => api.patch(`/projects/${item.id}`, { title }), { ...inv, success: "Renamed" });
  const archive = useAction(() => api.post(`/projects/${item.id}/archive?archived=${!item.archived}`), { ...inv, success: item.archived ? "Restored" : "Archived" });
  const open = useAction(() => api.post(`/projects/${item.id}/open-folder`));
  const exp = useAction(() => api.post<{ path: string }>(`/projects/${item.id}/export`), { ...inv, success: (r) => `Copied to ${r.path}` });
  const del = useAction(() => api.del(`/projects/${item.id}`, { confirm: item.title, delete_files: deleteFiles }), { ...inv, success: "Project deleted" });
  const video = fileUrl(item.id, item.export?.path);
  return (
    <Card>
      <div className="stack">
        {video ? <div className="video-frame vertical"><video src={video} controls preload="metadata" /></div> : <div className="thumb-placeholder"><Film size={24} /></div>}
        <div>
          <Link to={`/production/${item.id}`} style={{ color: "var(--text)", fontWeight: 600 }}>{item.title}</Link>
          <div className="row wrap" style={{ marginTop: 6 }}>
            {item.review_status === "approved" ? <StatusBadge status="approved" label="Finished" />
              : item.export ? <StatusBadge status="waiting_approval" label="Awaiting review" />
              : <StatusBadge status={item.status} />}
            {item.archived && <StatusBadge status="cancelled" label="Archived" />}
            {item.qc?.technical_ok === false && <StatusBadge status="failed" label="QC failed" />}
            {!!item.qc?.warnings && <StatusBadge status="warning" label={`${item.qc.warnings} QC warning(s)`} />}
          </div>
        </div>
        <dl className="kv tiny">
          <dt>Created</dt><dd>{dateTime(item.created_at)}</dd>
          <dt>Duration</dt><dd>{duration(item.export?.duration)}</dd>
          <dt>Resolution</dt><dd>{item.export ? `${item.export.width}×${item.export.height}` : "—"}</dd>
          <dt>Folder</dt><dd className="mono" title={item.folder}>{item.folder.split(/[\\/]/).slice(-1)[0]}</dd>
        </dl>
        <div className="row wrap">
          <button className="btn sm" onClick={() => open.mutate()}><FolderOpen size={13} /> Folder</button>
          {item.export && <button className="btn sm" onClick={() => exp.mutate()}><ExternalLink size={13} /> Export</button>}
          <div className="spacer" />
          <button className="btn icon ghost" title="Rename" onClick={() => setRenaming(true)}><Pencil size={14} /></button>
          <button className="btn icon ghost" title={item.archived ? "Restore" : "Archive"} onClick={() => archive.mutate()}>{item.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}</button>
          <button className="btn icon ghost" title="Delete" onClick={() => setDeleting(true)}><Trash2 size={14} /></button>
        </div>
      </div>
      {renaming && (
        <Modal title="Rename project" onClose={() => setRenaming(false)} footer={<>
          <button className="btn" onClick={() => setRenaming(false)}>Cancel</button>
          <button className="btn primary" disabled={!title.trim()} onClick={() => rename.mutate(undefined, { onSuccess: () => setRenaming(false) })}>Rename</button>
        </>}>
          <Field label="Title" hint="The project folder keeps its original name."><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus /></Field>
        </Modal>
      )}
      {deleting && (
        <ConfirmDialog title="Delete project?" danger confirmLabel={deleteFiles ? "Delete project and files" : "Delete project record"} requireText={item.title}
          busy={del.isPending} onClose={() => setDeleting(false)} onConfirm={() => del.mutate(undefined, { onSuccess: () => setDeleting(false) })}>
          <p className="muted small">Removes the project from the studio. Only this project's own folder can be deleted; nothing outside it is touched.</p>
          <Toggle checked={deleteFiles} onChange={setDeleteFiles} label={<>Also delete its folder <span className="mono tiny">{item.folder}</span></>} />
          {item.export?.library_path && <p className="tiny faint">The copy in your library folder is kept.</p>}
        </ConfirmDialog>
      )}
    </Card>
  );
}
