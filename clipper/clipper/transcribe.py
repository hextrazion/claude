"""Speech-to-text for candidate windows only (transcribing a whole VOD would take hours)."""
from __future__ import annotations

import numpy as np


class Transcriber:
    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str = "default"):
        self.model_size, self.device, self.compute_type = model_size, device, compute_type
        self._model = None

    @staticmethod
    def available() -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, samples: np.ndarray) -> str:
        """`samples`: mono float32 at 16 kHz."""
        if len(samples) < 16000:
            return ""
        segments, _ = self._load().transcribe(samples, vad_filter=True, beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()
