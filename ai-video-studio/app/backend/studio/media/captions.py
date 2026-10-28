"""Caption chunking and SRT/ASS writers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import CaptionSettings
from .alignment import Word


@dataclass
class Cue:
    start: float
    end: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def fit_chars(style: CaptionSettings, width: int, height: int) -> int:
    """Characters per line that fit the frame at the configured font size.

    Uses a conservative average glyph width for bold display fonts, so
    lines never run off the edge of a vertical video."""
    font_px = height * style.size_pct / 100
    usable = width * (1 - 2 * 0.08)
    glyph = font_px * (0.68 if style.uppercase else 0.58)
    return max(6, min(style.max_chars_per_line, int(usable / glyph)))


def build_cues(words: list[Word], max_words: int, max_chars: int, min_dur: float = 0.35) -> list[Cue]:
    cues: list[Cue] = []
    cur: list[Word] = []
    for w in words:
        candidate = " ".join(x.text for x in cur + [w])
        if cur and (len(cur) >= max_words or len(candidate) > max_chars * 2):
            cues.append(Cue(cur[0].start, cur[-1].end, cur))
            cur = []
        cur.append(w)
        if w.text[-1:] in ".!?;:" or w.text.endswith(","):
            cues.append(Cue(cur[0].start, cur[-1].end, cur))
            cur = []
    if cur:
        cues.append(Cue(cur[0].start, cur[-1].end, cur))
    # Each cue stays up until the next one starts (no flicker in short gaps).
    for i, c in enumerate(cues):
        nxt = cues[i + 1].start if i + 1 < len(cues) else c.end + 0.4
        gap = nxt - c.end
        c.end = nxt if gap < 0.6 else c.end + 0.25
        if c.end - c.start < min_dur:
            c.end = c.start + min_dur
        if i + 1 < len(cues) and c.end > cues[i + 1].start:
            c.end = cues[i + 1].start
    return cues


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _wrap(text: str, max_chars: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def write_srt(cues: list[Cue], path: Path, max_chars: int) -> None:
    out = []
    for i, c in enumerate(cues, 1):
        out.append(f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n" + "\n".join(_wrap(c.text, max_chars)) + "\n")
    path.write_text("\n".join(out), encoding="utf-8")


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_tag_color(hex_rgb: str) -> str:
    """Colour for inline override tags: &HBBGGRR&."""
    return f"&H{hex_rgb[5:7]}{hex_rgb[3:5]}{hex_rgb[1:3]}&".upper()


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(cues: list[Cue], path: Path, style: CaptionSettings, width: int, height: int) -> None:
    font_size = round(height * style.size_pct / 100)
    margin_v = round(height * style.position_pct / 100)
    primary = _ass_color(style.primary_color)
    highlight = _ass_tag_color(style.highlight_color)
    primary_tag = _ass_tag_color(style.primary_color)
    outline = _ass_color(style.outline_color)
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Caption,{style.font},{font_size},{primary},{primary},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{style.outline_px},{max(0, style.outline_px // 3)},2,{round(width * 0.08)},{round(width * 0.08)},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for c in cues:
        tokens = [w.text.upper() if style.uppercase else w.text for w in c.words]
        wrapped = _wrap(" ".join(tokens), fit_chars(style, width, height))
        # Index of the token at which each wrapped line starts, to insert \N.
        breaks, count = set(), 0
        for ln in wrapped[:-1]:
            count += len(ln.split())
            breaks.add(count)
        # One event per spoken word so the active word is highlighted.
        for wi, w in enumerate(c.words):
            start = w.start if wi > 0 else c.start
            end = c.words[wi + 1].start if wi + 1 < len(c.words) else c.end
            if end <= start:
                continue
            parts = []
            for ti, tok in enumerate(tokens):
                if ti in breaks:
                    parts.append("\\N")
                elif ti:
                    parts.append(" ")
                tok = _ass_escape(tok)
                parts.append(f"{{\\c{highlight}}}{tok}{{\\c{primary_tag}}}" if ti == wi else tok)
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{''.join(parts)}")
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
