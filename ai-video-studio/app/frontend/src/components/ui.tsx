import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import { ApiError } from "../lib/api";
import { titleCase } from "../lib/format";

// ---------- status badges ----------
const STATUS_TONE: Record<string, string> = {
  ok: "ok", completed: "ok", pass: "ok", approved: "ok", verified: "ok", produced: "ok",
  running: "info", queued: "info", pending: "info", processing: "info",
  warning: "warn", warn: "warn", waiting_approval: "accent", paused: "warn", stale: "warn", needs_review: "warn",
  draft: "accent", favorite: "accent", review: "accent",
  error: "err", failed: "err", fail: "err", contradicted: "err", rejected: "err", unavailable: "err",
  not_configured: "", cancelled: "", none: "", idle: "", skipped: "", not_checked: "", unverified: "warn", speculative: "",
};

const STATUS_LABEL: Record<string, string> = {
  ok: "Connected", not_configured: "Not configured", unavailable: "Unavailable", waiting_approval: "Needs approval",
  needs_review: "Needs review", not_checked: "Not checked", none: "Not started",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const tone = STATUS_TONE[status] ?? "";
  const live = status === "running" || status === "queued" || status === "pending";
  return (
    <span className={`badge ${tone} ${status === "running" ? "pulse" : ""}`}>
      {(tone || live) && <span className="dot" />}
      {label ?? STATUS_LABEL[status] ?? titleCase(status)}
    </span>
  );
}

export function Badge({ tone = "", children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

// ---------- basic blocks ----------
export function Card({ title, sub, actions, children, className = "" }: {
  title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children?: ReactNode; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-header">
          <div>
            {title && <h2>{title}</h2>}
            {sub && <div className="sub">{sub}</div>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {actions && <div className="header-actions">{actions}</div>}
    </header>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      {children && <div className="small">{children}</div>}
    </div>
  );
}

export function Progress({ value, indeterminate }: { value?: number | null; indeterminate?: boolean }) {
  const ind = indeterminate || value == null;
  return (
    <div className={`progress ${ind ? "indeterminate" : ""}`}>
      <div style={{ width: `${Math.round((value ?? 0) * 100)}%` }} />
    </div>
  );
}

export function Meter({ label, value, max, unit = "", warnAt = 0.85 }: { label: string; value?: number | null; max?: number | null; unit?: string; warnAt?: number }) {
  if (value == null || !max) {
    return (
      <div className="meter">
        <div className="row"><span className="muted">{label}</span><span className="faint">Unavailable</span></div>
        <div className="progress"><div style={{ width: 0 }} /></div>
      </div>
    );
  }
  const frac = Math.min(1, value / max);
  return (
    <div className="meter">
      <div className="row">
        <span className="muted">{label}</span>
        <span>{value.toFixed(value < 10 ? 1 : 0)}{unit} / {max.toFixed(0)}{unit}</span>
      </div>
      <div className="progress"><div style={{ width: `${frac * 100}%`, background: frac > warnAt ? "var(--warn)" : undefined }} /></div>
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="spin" />;
}

export function Note({ tone = "info", title, children, detail }: { tone?: "info" | "warn" | "err" | "ok"; title?: ReactNode; children?: ReactNode; detail?: string | null }) {
  const Icon = { info: Info, warn: AlertTriangle, err: XCircle, ok: CheckCircle2 }[tone];
  return (
    <div className={`note ${tone}`}>
      <Icon size={16} />
      <div style={{ minWidth: 0, flex: 1 }}>
        {title && <div style={{ fontWeight: 600 }}>{title}</div>}
        {children && <div>{children}</div>}
        {detail && <Details text={detail} />}
      </div>
    </div>
  );
}

export function Details({ text, label = "Technical details" }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button className="details-toggle" onClick={() => setOpen(!open)}>{open ? "Hide" : label}</button>
      {open && <pre className="detail-box mono">{text}</pre>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof ApiError) return <Note tone="err" title={error.message} detail={error.detail} />;
  return <Note tone="err" title={String((error as Error)?.message ?? error)} />;
}

// ---------- form controls ----------
export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className="toggle" style={disabled ? { opacity: 0.5 } : undefined}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      {label && <span>{label}</span>}
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button key={o.value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)} type="button">{o.label}</button>
      ))}
    </div>
  );
}

export function NumberInput({ value, onChange, min, max, step = 1 }: { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number }) {
  const [text, setText] = useState(String(value ?? ""));
  useEffect(() => setText(String(value ?? "")), [value]);
  return (
    <input
      className="input" type="number" value={text} min={min} max={max} step={step}
      onChange={(e) => {
        setText(e.target.value);
        const n = Number(e.target.value);
        if (e.target.value !== "" && !Number.isNaN(n)) onChange(n);
      }}
    />
  );
}

/** Comma-separated list editor; parses on blur so typing commas works. */
export function ListInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [text, setText] = useState((value ?? []).join(", "));
  useEffect(() => setText((value ?? []).join(", ")), [value]);
  const commit = () => onChange(text.split(",").map((x) => x.trim()).filter(Boolean));
  return <input className="input" value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />;
}

// ---------- modal & confirm ----------
export function Modal({ title, children, footer, onClose, wide }: { title: ReactNode; children: ReactNode; footer?: ReactNode; onClose: () => void; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true">
        <h2>{title}</h2>
        {children}
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ title, children, confirmLabel = "Confirm", danger, onConfirm, onClose, busy, requireText }: {
  title: string; children?: ReactNode; confirmLabel?: string; danger?: boolean; onConfirm: () => void; onClose: () => void; busy?: boolean; requireText?: string;
}) {
  const [typed, setTyped] = useState("");
  const ok = !requireText || typed.trim() === requireText.trim();
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className={`btn ${danger ? "danger solid" : "primary"}`} disabled={!ok || busy} onClick={onConfirm}>
            {busy && <Spinner size={14} />} {confirmLabel}
          </button>
        </>
      }
    >
      {children}
      {requireText && (
        <Field label={<>Type <b>{requireText}</b> to confirm</>}>
          <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
        </Field>
      )}
    </Modal>
  );
}

// ---------- toasts ----------
type Toast = { id: number; tone: "ok" | "err" | "info"; text: string; detail?: string | null };
const ToastCtx = createContext<{ push: (t: Omit<Toast, "id">) => void }>({ push: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = nextId.current++;
    setToasts((ts) => [...ts.slice(-3), { ...t, id }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), t.tone === "err" ? 9000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            {t.tone === "err" ? <XCircle size={16} color="var(--err)" /> : t.tone === "ok" ? <CheckCircle2 size={16} color="var(--ok)" /> : <Info size={16} />}
            <div style={{ minWidth: 0 }}>
              <div>{t.text}</div>
              {t.detail && <Details text={t.detail} />}
            </div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const { push } = useContext(ToastCtx);
  return {
    ok: (text: string) => push({ tone: "ok", text }),
    info: (text: string) => push({ tone: "info", text }),
    error: (e: unknown) =>
      push({ tone: "err", text: e instanceof Error ? e.message : String(e), detail: e instanceof ApiError ? e.detail : undefined }),
  };
}
