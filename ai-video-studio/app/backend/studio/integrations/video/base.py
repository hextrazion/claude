"""Generation adapter interface.

The pipeline talks to video/image engines only through this interface, so a
new engine (another local server, a remote homelab worker, a cloud API) is a
new adapter class rather than changes across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from ..base import HealthResult

ProgressFn = Callable[[float | None, str], Awaitable[None]]
CancelledFn = Callable[[], bool]


@dataclass
class GenerationRequest:
    kind: str  # "video" | "image"
    workflow: str
    prompt: str
    negative_prompt: str
    width: int
    height: int
    seed: int
    out_dir: Path
    filename_prefix: str
    num_frames: int | None = None
    fps: int | None = None
    image_path: Path | None = None
    ref_images: list[Path] = field(default_factory=list)  # style references for reference-to-video models
    extra: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    files: list[Path]
    meta: dict


@dataclass
class Capabilities:
    kind: str
    mode: str  # t2v | i2v | t2i
    width: int
    height: int
    fps: int
    max_frames: int
    frame_multiple: int = 1  # frame counts must be frame_multiple*n + frame_offset when > 1
    is_ai: bool = True
    frame_offset: int = 1

    @property
    def max_clip_s(self) -> float:
        return self.max_frames / self.fps if self.fps else 0

    def frames_for(self, seconds: float) -> int:
        """Frames for a clip of ``seconds``, rounded *up* to the model's m*n+offset rule
        (a little extra footage is trimmed; too little would be held) and capped
        at the largest valid count within ``max_frames``."""
        frames = max(1, round(seconds * self.fps))
        m, r = self.frame_multiple, self.frame_offset
        if m > 1:
            frames = max(r, frames + (r - frames) % m)
            cap = self.max_frames - (self.max_frames - r) % m
            return max(r, min(frames, cap))
        return min(frames, self.max_frames)

    def to_dict(self) -> dict:
        return {**self.__dict__, "max_clip_s": round(self.max_clip_s, 2)}


class GenerationAdapter(Protocol):
    name: str
    label: str
    is_ai: bool

    async def health(self) -> HealthResult: ...

    def capabilities(self, workflow: str) -> Capabilities: ...

    async def submit(self, req: GenerationRequest) -> str: ...

    async def wait(
        self, external_id: str, req: GenerationRequest, on_progress: ProgressFn, is_cancelled: CancelledFn, timeout: float
    ) -> GenerationResult: ...

    async def status(self, external_id: str) -> str:
        """queued | running | completed | failed | unknown"""
        ...

    async def cancel(self, external_id: str) -> bool: ...
