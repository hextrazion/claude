import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ConfirmDialog, ListInput, Meter, StatusBadge } from "./components/ui";
import { api, ApiError, fileUrl } from "./lib/api";
import { bytes, duration } from "./lib/format";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("StatusBadge", () => {
  it("uses friendly labels and tones", () => {
    render(<StatusBadge status="waiting_approval" />);
    const el = screen.getByText("Needs approval");
    expect(el.className).toContain("accent");
  });
  it("marks failures as errors", () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText("Failed").className).toContain("err");
  });
});

describe("Meter", () => {
  it("shows Unavailable instead of inventing a value", () => {
    render(<Meter label="GPU" value={null} max={null} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
});

describe("ConfirmDialog", () => {
  it("keeps destructive actions disabled until the title is typed", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog title="Delete?" danger requireText="My video" confirmLabel="Delete" onConfirm={onConfirm} onClose={() => undefined} />);
    const button = screen.getByRole("button", { name: /Delete/ });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "My vid" } });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "My video" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});

describe("ListInput", () => {
  it("lets commas be typed and parses on blur", () => {
    const onChange = vi.fn();
    render(<ListInput value={[]} onChange={onChange} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "game.exe, " } });
    expect((input as HTMLInputElement).value).toBe("game.exe, ");
    fireEvent.change(input, { target: { value: "game.exe, other.exe" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith(["game.exe", "other.exe"]);
  });
});

describe("api client", () => {
  it("sends the client header and surfaces server error messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { message: "Groq rejected the API key.", kind: "auth", detail: "HTTP 401" } }), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const err = (await api.post("/ideas/generate", { count: 1 }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("Groq rejected the API key.");
    expect(err.kind).toBe("auth");
    expect(fetchMock.mock.calls[0][1].headers["X-Studio-Client"]).toBe("web");
  });
  it("reports an unreachable backend clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = (await api.get("/health").catch((e: unknown) => e)) as ApiError;
    expect(err.kind).toBe("offline");
  });
  it("encodes file paths segment by segment", () => {
    expect(fileUrl(3, "exports/my video.mp4")).toBe("/api/files/3/exports/my%20video.mp4");
  });
});

describe("format", () => {
  it("formats durations and sizes", () => {
    expect(duration(75)).toBe("1m 15s");
    expect(duration(null)).toBe("—");
    expect(bytes(1536)).toBe("1.5 KB");
  });
});
