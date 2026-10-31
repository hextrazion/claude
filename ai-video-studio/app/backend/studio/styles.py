"""Style library: turn reference images/videos into a reusable visual style.

Nothing here trains a model. A style is:

* the reference files themselves (images, plus frames pulled from videos),
* measured facts: dominant colours and, for videos, how often they cut,
* a written style profile (by a vision model when one is available, or
  from the user's own description), which is added to every scene prompt,
* "key" images that MiniMax H3's reference-to-video mode can look at directly
  when its Ref2VA model is installed.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import shutil
from pathlib import Path

from .db import Database, dumps, loads, utcnow
from .errors import ProviderError, ValidationFailed
from .safety import IMAGE_EXTENSIONS, ensure_within, safe_filename

log = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
MAX_REFS = 24
MAX_KEY_IMAGES = 4  # images handed to H3's reference mode per clip
FRAMES_PER_VIDEO = 6
VISION_PATTERNS = ("llama-4", "vision", "-vl", "scout", "maverick")


def _decode(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = dict(row)
    row["profile"] = loads(row.pop("profile_json"), None)
    row["refs"] = loads(row.pop("refs_json"), [])
    return row


class StyleStore:
    def __init__(self, db: Database, root: Path):
        self.db = db
        self.root = root

    def folder(self, style_id: int) -> Path:
        d = self.root / f"style_{style_id:04d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list(self) -> list[dict]:
        return [_decode(r) for r in self.db.query("SELECT * FROM styles ORDER BY updated_at DESC")]

    def get(self, style_id: int | None) -> dict | None:
        if not style_id:
            return None
        return _decode(self.db.query_one("SELECT * FROM styles WHERE id = ?", (style_id,)))

    def require(self, style_id: int) -> dict:
        st = self.get(style_id)
        if not st:
            raise ValidationFailed("Style not found.")
        return st

    def create(self, name: str, notes: str = "") -> dict:
        now = utcnow()
        sid = self.db.execute("INSERT INTO styles(name, notes, created_at, updated_at) VALUES (?,?,?,?)",
                              (name.strip()[:80] or "My style", notes[:2000], now, now))
        self.folder(sid)
        return self.get(sid)

    def update(self, style_id: int, **fields) -> None:
        out = {}
        for k, v in fields.items():
            if k in ("profile", "refs"):
                out[f"{k}_json"] = dumps(v)
            else:
                out[k] = v
        out["updated_at"] = utcnow()
        self.db.update("styles", style_id, out)

    def delete(self, style_id: int) -> None:
        folder = self.root / f"style_{style_id:04d}"
        if folder.is_dir():
            shutil.rmtree(ensure_within(self.root, folder))
        self.db.execute("DELETE FROM styles WHERE id = ?", (style_id,))

    # -- references ----------------------------------------------------------------
    @staticmethod
    def kind_for(filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in VIDEO_EXTENSIONS:
            return "video"
        raise ValidationFailed("Add images (PNG, JPG, WebP) or videos (MP4, MOV, WebM).")

    def add_reference(self, style_id: int, filename: str, source: Path) -> dict:
        """Register an uploaded file (already written to ``source``) as a reference."""
        st = self.require(style_id)
        if len(st["refs"]) >= MAX_REFS:
            source.unlink(missing_ok=True)
            raise ValidationFailed(f"A style can hold up to {MAX_REFS} references.")
        name = safe_filename(filename or "reference")
        kind = self.kind_for(name)
        ext = Path(name).suffix.lower()
        refs_dir = self.folder(style_id) / "refs"
        refs_dir.mkdir(exist_ok=True)
        dest = refs_dir / name
        i = 2
        while dest.exists():
            dest = refs_dir / f"{Path(name).stem}-{i}{ext}"
            i += 1
        shutil.move(str(source), dest)
        keys = sum(1 for r in st["refs"] if r.get("key"))
        refs = st["refs"] + [{"file": f"refs/{dest.name}", "kind": kind, "key": keys < MAX_KEY_IMAGES, "frames": []}]
        self.update(style_id, refs=refs, **self._mark_changed(st))
        return self.get(style_id)

    @staticmethod
    def _mark_changed(st: dict) -> dict:
        """References changed: a ready style keeps working but is flagged for re-analysis."""
        if st["status"] == "ready" and st.get("profile"):
            return {"profile": {**st["profile"], "stale": True}}
        return {}

    def remove_reference(self, style_id: int, file: str) -> dict:
        st = self.require(style_id)
        keep = [r for r in st["refs"] if r["file"] != file]
        if len(keep) == len(st["refs"]):
            raise ValidationFailed("Reference not found.")
        removed = next(r for r in st["refs"] if r["file"] == file)
        folder = self.folder(style_id)
        for rel in [removed["file"], *removed.get("frames", [])]:
            p = ensure_within(folder, folder / rel)
            p.unlink(missing_ok=True)
        self.update(style_id, refs=keep, **self._mark_changed(st))
        return self.get(style_id)

    def set_key(self, style_id: int, file: str, key: bool) -> dict:
        st = self.require(style_id)
        refs = st["refs"]
        if key and sum(1 for r in refs if r.get("key")) >= MAX_KEY_IMAGES:
            raise ValidationFailed(f"Up to {MAX_KEY_IMAGES} key images (they are shown to the video model directly).")
        for r in refs:
            if r["file"] == file:
                r["key"] = key
        self.update(style_id, refs=refs)
        return self.get(style_id)

    def images(self, style: dict, key_only: bool = False) -> list[Path]:
        """Still images for a style: uploaded images first, then frames pulled from videos."""
        folder = self.folder(style["id"])
        out = []
        for r in style["refs"]:
            if key_only and not r.get("key"):
                continue
            if r["kind"] == "image":
                out.append(folder / r["file"])
            elif r.get("frames"):
                frames = r["frames"] if not key_only else r["frames"][len(r["frames"]) // 2:][:1]
                out += [folder / f for f in frames]
        return [p for p in out if p.is_file()]

    def key_images(self, style: dict) -> list[Path]:
        keys = self.images(style, key_only=True)
        if not keys:
            keys = self.images(style)
        return keys[:MAX_KEY_IMAGES]


# -- analysis helpers ---------------------------------------------------------------
def palette(images: list[Path], colors: int = 6) -> list[str]:
    """Dominant colours across the references (hex), most common first."""
    from PIL import Image

    counts: dict[tuple, int] = {}
    for p in images[:12]:
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail((160, 160))
                q = im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
                pal = q.getpalette()[: colors * 3]
                for count, idx in q.getcolors() or []:
                    rgb = tuple(pal[idx * 3: idx * 3 + 3])
                    key = tuple(c // 24 * 24 for c in rgb)  # merge near-identical colours
                    counts[key] = counts.get(key, 0) + count
        except Exception as exc:  # unreadable file: skip, the analysis still runs
            log.warning("palette: could not read %s: %s", p.name, exc)
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:colors]
    return ["#%02X%02X%02X" % rgb for rgb, _ in top]


def jpeg_data_url(path: Path, max_side: int = 768) -> str:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


_SHOWINFO_T = re.compile(r"pts_time:([\d.]+)")


async def video_facts(ffmpeg, video: Path, frames_dir: Path, stem: str) -> dict:
    """Pull evenly spaced frames and measure how often the video cuts."""
    from .media.ffmpeg import media_info

    info = media_info(await ffmpeg.probe(video))
    duration = max(0.1, info.duration)
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(FRAMES_PER_VIDEO):
        t = duration * (i + 0.5) / FRAMES_PER_VIDEO
        out = frames_dir / f"{stem}_{i + 1:02d}.jpg"
        await ffmpeg.run(["-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                          "-vf", "scale='min(768,iw)':-2", "-q:v", "3", str(out)], timeout=120)
        if out.is_file():
            frames.append(out)
    stderr = await ffmpeg.run(["-i", str(video), "-vf", "select='gt(scene,0.32)',showinfo", "-an", "-f", "null", "-"],
                              duration_hint=duration, timeout=600)
    cuts = sorted({round(float(t), 2) for t in _SHOWINFO_T.findall(stderr)})
    shots = len(cuts) + 1
    return {"frames": frames, "duration": round(duration, 2), "cuts": len(cuts),
            "avg_shot_s": round(duration / shots, 2), "width": info.width, "height": info.height}


def style_prompt_messages(notes: str, colours: list[str], pacing: dict | None, image_count: int) -> list[dict]:
    pace = (f"Measured from the reference videos: about {pacing['avg_shot_s']} s per shot "
            f"({pacing['cuts_per_10s']} cuts per 10 s)." if pacing else "No video timing available.")
    return [
        {"role": "system", "content": (
            "You are an art director. You describe the VISUAL STYLE of reference material precisely enough that "
            "a text-to-video model can reproduce the look on completely different subjects. Never describe the "
            "specific people, characters, logos or story in the references, only how things look and move."
        )},
        {"role": "user", "content": [
            {"type": "text", "text": (
                f"Here are {image_count} reference frames for one video style.\n"
                f"Dominant colours measured: {', '.join(f'{c} ({colour_name(c)})' for c in colours) or 'unknown'}.\n{pace}\n"
                f"The creator's own words about the style: {notes or '(none)'}\n\n"
                "Return JSON: {\"name\": short style name, \"summary\": 2 plain sentences for the creator, "
                "\"style_prompt\": 45-80 words for the video model covering medium/rendering, palette, lighting, "
                "texture, composition, camera language and motion feel, \"avoid\": comma-separated things that would "
                "break this look, \"camera\": typical camera moves, \"motion\": how things move, "
                "\"mood\": 3-6 words, \"uses_onscreen_text\": true/false}"
            )},
        ]},
    ]


_NAMED = {
    "black": (15, 15, 15), "charcoal": (55, 55, 60), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "white": (245, 245, 245), "cream": (245, 235, 205), "sand": (230, 195, 130), "beige": (215, 190, 160),
    "brown": (120, 75, 40), "rust": (180, 80, 40), "orange": (245, 130, 40), "peach": (250, 175, 135),
    "gold": (220, 175, 50), "yellow": (245, 220, 60), "olive": (120, 120, 40), "lime": (170, 220, 60),
    "green": (60, 160, 70), "forest green": (30, 80, 45), "teal": (30, 140, 140), "cyan": (60, 210, 225),
    "sky blue": (120, 190, 240), "blue": (40, 90, 210), "navy": (20, 30, 80), "indigo": (75, 50, 150),
    "purple": (130, 60, 170), "lavender": (190, 160, 230), "magenta": (220, 40, 160), "pink": (240, 140, 180),
    "crimson": (200, 20, 60), "red": (210, 40, 40), "maroon": (110, 20, 30),
}


def colour_name(hex_colour: str) -> str:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return min(_NAMED, key=lambda n: sum((a - c) ** 2 for a, c in zip(_NAMED[n], (r, g, b))))


def colour_words(colours: list[str], n: int = 4) -> list[str]:
    out: list[str] = []
    for c in colours:
        name = colour_name(c)
        if name not in out:
            out.append(name)
    return out[:n]


def profile_from_notes(notes: str, colours: list[str], pacing: dict | None) -> dict:
    """Fallback profile when no vision model is available: the creator's words plus measurements."""
    base = notes.strip().rstrip(".") or "clean, consistent visual style"
    words = colour_words(colours)
    palette_text = f" Colour palette of {', '.join(words)}." if words else ""
    return {
        "name": "", "summary": "",
        "style_prompt": f"{base}.{palette_text}", "avoid": "", "camera": "", "motion": "", "mood": "",
        "uses_onscreen_text": False,
    }


async def analyze_style(s, style_id: int, progress) -> dict:
    """Job body: frames, colours, pacing, then the written profile."""
    store: StyleStore = s.styles
    style = store.require(style_id)
    if not style["refs"]:
        raise ValidationFailed("Add at least one reference image or video first.")
    folder = store.folder(style_id)
    refs = style["refs"]
    shot_lengths, total_cuts, total_dur = [], 0, 0.0
    videos = [r for r in refs if r["kind"] == "video"]
    for i, r in enumerate(videos):
        await progress(0.05 + 0.4 * i / max(1, len(videos)), f"Reading video {i + 1}/{len(videos)}")
        facts = await video_facts(s.ffmpeg, folder / r["file"], folder / "frames", Path(r["file"]).stem)
        r["frames"] = [f"frames/{p.name}" for p in facts["frames"]]
        r["facts"] = {k: v for k, v in facts.items() if k != "frames"}
        shot_lengths.append(facts["avg_shot_s"])
        total_cuts += facts["cuts"]
        total_dur += facts["duration"]
    store.update(style_id, refs=refs)
    style = store.require(style_id)
    images = store.images(style)
    await progress(0.5, "Measuring colours")
    colours = palette(images)
    pacing = None
    if total_dur > 0:
        avg = total_dur / (total_cuts + len(videos))
        pacing = {"avg_shot_s": round(avg, 2), "cuts_per_10s": round(10 / avg, 1) if avg else None,
                  "videos": len(videos)}
    profile = None
    model_used = None
    if s.secrets.get("groq"):
        await progress(0.6, "Looking at the references")
        model_used = await s.groq.pick_vision_model(s.settings.get().text.model_vision)
        if model_used:
            sample = images[:: max(1, len(images) // 5)][:5]  # Groq accepts up to 5 images per request
            msgs = style_prompt_messages(style["notes"], colours, pacing, len(sample))
            msgs[1]["content"] += [{"type": "image_url", "image_url": {"url": jpeg_data_url(p)}} for p in sample]
            data = await s.groq.chat_json(msgs, model=model_used, operation="style", temperature=0.4, max_tokens=1200)
            profile = {
                "name": str(data.get("name", ""))[:60],
                "summary": str(data.get("summary", ""))[:500],
                "style_prompt": str(data.get("style_prompt", ""))[:900],
                "avoid": str(data.get("avoid", ""))[:400],
                "camera": str(data.get("camera", ""))[:200],
                "motion": str(data.get("motion", ""))[:200],
                "mood": str(data.get("mood", ""))[:120],
                "uses_onscreen_text": bool(data.get("uses_onscreen_text")),
            }
    if profile is None:
        profile = profile_from_notes(style["notes"], colours, pacing)
    profile.update(palette=colours, pacing=pacing, vision_model=model_used, analyzed_at=utcnow(),
                   images_analyzed=len(images))
    if not profile.get("style_prompt"):
        raise ProviderError("The analysis returned no style description.", kind="transient", provider="groq")
    return profile


def planner_style(style: dict | None) -> tuple[str, str]:
    """(style text for prompts, extra planner guidance) for a ready style."""
    if not style or not style.get("profile"):
        return "", ""
    p = style["profile"]
    text = p.get("style_prompt", "")
    guide = [f"Reference style '{style['name']}': {p.get('summary', '')}"]
    if p.get("camera"):
        guide.append(f"Typical camera: {p['camera']}.")
    if p.get("motion"):
        guide.append(f"Motion feel: {p['motion']}.")
    pacing = p.get("pacing") or {}
    if pacing.get("avg_shot_s"):
        guide.append(f"The references cut about every {pacing['avg_shot_s']} s: aim for scenes of roughly that length "
                     "(never longer than one clip).")
    if p.get("avoid"):
        guide.append(f"Avoid: {p['avoid']}.")
    return text, " ".join(guide)
