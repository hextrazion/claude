"""Burned-in captions: group words into short on-screen chunks and write an ASS subtitle file."""
from __future__ import annotations

from typing import Iterable, List, Tuple


def group_words(words: Iterable[Tuple[float, float, str]], max_words: int = 4, max_seconds: float = 2.4,
                gap: float = 0.7) -> List[dict]:
    """[(t0, t1, word)] -> [{start, end, text}], breaking on word count, duration or a pause."""
    out: List[dict] = []
    cur: List[Tuple[float, float, str]] = []

    def flush():
        if cur:
            out.append({"start": cur[0][0], "end": cur[-1][1], "text": " ".join(w for _, _, w in cur)})
            cur.clear()

    for t0, t1, w in words:
        if cur and (len(cur) >= max_words or t1 - cur[0][0] > max_seconds or t0 - cur[-1][1] > gap):
            flush()
        cur.append((t0, t1, w))
    flush()
    return out


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\\", "").replace("\n", " ").strip()


def to_ass(captions: List[dict], width: int, height: int, fontsize: int, margin_v: int) -> str:
    """`captions` times are relative to the start of the rendered clip."""
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
        "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,"
        "MarginV,Encoding",
        f"Style: Default,Arial,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(3, fontsize // 12)},0,2,{width // 12},{width // 12},{margin_v},1",
        "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    for c in captions:
        if c["end"] > c["start"] and _clean(c["text"]):
            lines.append(f"Dialogue: 0,{_ts(c['start'])},{_ts(c['end'])},Default,,0,0,0,,{_clean(c['text']).upper()}")
    return "\n".join(lines) + "\n"
