"""Synthetic test media: quiet noise with loud bursts at known times."""
import subprocess
import wave
from pathlib import Path

import numpy as np

BURSTS = [20.0, 55.0, 90.0]   # seconds; the third is longest/loudest
DURATION = 120


def make_video(dirpath: str, name: str = "src.mp4", with_audio: bool = True) -> str:
    d = Path(dirpath)
    out = str(d / name)
    sr = 16000
    rng = np.random.default_rng(7)
    audio = rng.normal(0, 0.01, DURATION * sr).astype(np.float32)
    for t, amp, length in [(BURSTS[0], 0.35, 2.0), (BURSTS[1], 0.5, 3.0), (BURSTS[2], 0.8, 6.0)]:
        a, b = int(t * sr), int((t + length) * sr)
        audio[a:b] += rng.normal(0, amp, b - a).astype(np.float32)
    audio = np.clip(audio, -1, 1)
    wav = d / "a.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={DURATION}"]
    if with_audio:
        cmd += ["-i", str(wav), "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, check=True)
    return out
