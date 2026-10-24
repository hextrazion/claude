from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from . import ingest, pipeline, render
from .llm import LLMError, LocalLLM
from .media import MediaError
from .models import Plan
from .transcribe import Transcriber


def _add_analyze_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("sources", nargs="+", help="video files or URLs (Twitch, YouTube, ...)")
    p.add_argument("--chat", action="append", default=[], metavar="FILE",
                   help="chat log for the matching source (repeat once per source, in order)")
    p.add_argument("--count", type=int, default=5, help="clips in the final video (default 5)")
    p.add_argument("--permission", choices=["unknown", "granted", "own"], default="unknown",
                   help="do you have the creator's OK to use these? stored in the plan")
    p.add_argument("--download-dir", default="downloads")
    p.add_argument("--llm-url", default="http://localhost:11434/v1",
                   help="OpenAI-compatible local server (Ollama default; LM Studio is http://localhost:1234/v1)")
    p.add_argument("--llm-model", default="", help="model name (default: first model the server lists)")
    p.add_argument("--no-llm", action="store_true", help="skip AI judging, use audio/chat signals only")
    p.add_argument("--whisper", default="small", help="faster-whisper model size (tiny/base/small/medium)")


def _analyze(args) -> Plan:
    srcs: List[dict] = []
    for i, s in enumerate(args.sources):
        d = {"permission": args.permission}
        if ingest.is_url(s):
            print(f"downloading {s}")
            path, info = ingest.fetch(s, args.download_dir)
            d.update(path=path, url=info["url"], credit=info["credit"])
        else:
            if not Path(s).exists():
                sys.exit(f"file not found: {s}")
            d.update(path=s)
        if i < len(args.chat):
            d["chat"] = args.chat[i]
        srcs.append(d)

    llm = None
    if not args.no_llm:
        llm = LocalLLM(args.llm_url, args.llm_model)
        try:
            print(f"local model: {llm.resolve_model()}")
        except LLMError as e:
            print(f"note: {e}\n      continuing with audio/chat signals only (use --no-llm to silence this)")
            llm = None
    transcriber = Transcriber(args.whisper) if llm else None
    if llm and not Transcriber.available():
        transcriber = None
    return pipeline.analyze(srcs, pipeline.Settings(count=args.count), llm, transcriber)


def _print_plan(plan: Plan) -> None:
    n = len(plan.clips)
    print(f"\n{plan.title}")
    for i, c in enumerate(plan.clips):
        print(f"  #{n - i}  {c.score:5.1f}  {c.source} {c.start:.0f}s-{c.end:.0f}s  {c.title}")


def _render(plan: Plan, out: str, overlay: bool) -> None:
    def prog(i, n, msg):
        print(f"  [{i}/{n}] {msg}")
    render.render(plan, out, overlay=overlay, on_progress=prog)
    thumb = str(Path(out).with_suffix(".jpg"))
    render.thumbnail(plan, thumb)
    print(f"\nvideo:     {out}\nthumbnail: {thumb}")
    for t in plan.video_titles:
        print(f"title idea: {t}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="clipper", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="find the best moments and write an editable plan.json")
    _add_analyze_args(a)
    a.add_argument("--out", default="plan.json")

    r = sub.add_parser("render", help="render a plan.json to MP4")
    r.add_argument("plan")
    r.add_argument("--out", default="top5.mp4")
    r.add_argument("--no-overlay", action="store_true")

    run = sub.add_parser("run", help="analyze + render in one go")
    _add_analyze_args(run)
    run.add_argument("--out", default="top5.mp4")
    run.add_argument("--plan", default="plan.json", help="where to save the plan")
    run.add_argument("--no-overlay", action="store_true")

    u = sub.add_parser("ui", help="open the review screen for a plan.json")
    u.add_argument("plan")
    u.add_argument("--port", type=int, default=8765)
    u.add_argument("--no-browser", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "analyze":
            plan = _analyze(args)
            plan.save(args.out)
            _print_plan(plan)
            print(f"\nsaved {args.out} - edit it, or run: clipper ui {args.out}")
        elif args.cmd == "render":
            _render(Plan.load(args.plan), args.out, not args.no_overlay)
        elif args.cmd == "run":
            plan = _analyze(args)
            plan.save(args.plan)
            _print_plan(plan)
            _render(plan, args.out, not args.no_overlay)
        elif args.cmd == "ui":
            from .server import serve
            serve(args.plan, args.port, open_browser=not args.no_browser)
    except (MediaError, LLMError) as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
