from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class Clip:
    source: str                      # local file path
    start: float                     # seconds
    end: float
    score: float                     # 0-100, final combined score
    signals: Dict[str, float] = field(default_factory=dict)  # audio/chat/laughter/ai, each 0-100
    title: str = ""
    reason: str = ""
    transcript: str = ""
    credit: str = ""                 # e.g. "Twitch: StreamerName"
    permission: str = "unknown"      # unknown | granted | own
    captions: List[dict] = field(default_factory=list)   # [{start, end, text}] in SOURCE time

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Plan:
    clips: List[Clip] = field(default_factory=list)   # in video order: #N first, #1 last
    title: str = "Top 5 Funniest Moments"
    video_titles: List[str] = field(default_factory=list)
    sources: List[dict] = field(default_factory=list)  # {path, url, credit, duration}
    settings: dict = field(default_factory=dict)

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Plan":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            clips=[Clip(**c) for c in d.get("clips", [])],
            title=d.get("title", "Top 5 Funniest Moments"),
            video_titles=d.get("video_titles", []),
            sources=d.get("sources", []),
            settings=d.get("settings", {}),
        )
