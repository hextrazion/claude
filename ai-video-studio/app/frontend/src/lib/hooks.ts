import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api } from "./api";
import type { Settings } from "./types";
import { useToast } from "../components/ui";

// Server-sent events from the backend are hints: refetch whatever changed.
export function useLiveEvents() {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(true);
  useEffect(() => {
    const es = new EventSource("/api/events");
    let timer: ReturnType<typeof setTimeout> | null = null;
    const pending = new Set<string>();
    const flush = () => {
      pending.forEach((key) => qc.invalidateQueries({ queryKey: [key] }));
      pending.clear();
      timer = null;
    };
    const touch = (...keys: string[]) => {
      keys.forEach((k) => pending.add(k));
      if (!timer) timer = setTimeout(flush, 250);
    };
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (msg) => {
      let ev: { type: string };
      try {
        ev = JSON.parse(msg.data);
      } catch {
        return;
      }
      switch (ev.type) {
        case "job":
          touch("jobs", "queue", "project", "projects", "dashboard");
          break;
        case "project":
        case "scene":
          touch("project", "projects", "dashboard", "library");
          break;
        case "ideas":
          touch("ideas", "dashboard");
          break;
        case "activity":
          touch("dashboard", "activity");
          break;
        case "queue":
          touch("queue", "dashboard");
          break;
        case "integration":
          touch("integrations", "dashboard");
          break;
        case "settings":
          touch("settings", "queue");
          break;
      }
    };
    return () => {
      es.close();
      if (timer) clearTimeout(timer);
    };
  }, [qc]);
  return connected;
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/settings") });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (patch: Settings) => api.patch<Settings>("/settings", patch),
    onSuccess: (data) => {
      qc.setQueryData(["settings"], data);
      toast.ok("Settings saved");
    },
    onError: toast.error,
  });
}

/** Mutation that shows errors as toasts and refreshes the given queries. */
export function useAction<TArgs = void, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  { invalidate = [], success }: { invalidate?: QueryKey[]; success?: string | ((r: TResult) => string) } = {},
) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
      if (success) toast.ok(typeof success === "function" ? success(r) : success);
    },
    onError: toast.error,
  });
}
