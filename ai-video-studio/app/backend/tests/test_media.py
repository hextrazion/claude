"""Alignment, captions and FFmpeg assembly with small real media fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import anyio

from studio.media import alignment, assembly, captions, qc
from studio.media.ffmpeg import FFmpeg, media_info
from studio.pipeline.stages import repair_scene_narration
from studio.settings import CaptionSettings, Settings

from .conftest import needs_ffmpeg


def test_heuristic_alignment_snaps_to_silences():
    tokens = "One two three. Four five six.".split()
    # Speech 0.2-1.4, pause 1.4-1.9, speech 1.9-3.0
    words = alignment.heuristic_timings(tokens, 3.2, [(0.0, 0.2), (1.4, 1.9), (3.0, 3.2)])
    assert words[0].start >= 0.19
    assert abs(words[2].end - 1.4) < 0.05 and abs(words[3].start - 1.9) < 0.05
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))
    assert words[-1].end <= 3.2


def test_parse_silences():
    stderr = "[silencedetect @ 0x1] silence_start: 1.25\n[silencedetect @ 0x1] silence_end: 1.8 | silence_duration: 0.55\n"
    assert alignment.parse_silences(stderr) == [(1.25, 1.8)]


def test_align_to_transcript_fills_gaps():
    tokens = ["Light", "bends", "in", "water."]
    asr = [("light", 0.0, 0.3), ("bends", 0.3, 0.6), ("water", 1.0, 1.4)]
    words = alignment.align_to_transcript(tokens, asr, 1.5)
    assert words[2].start >= 0.6 and words[2].end <= 1.0
    assert words[3].start == 1.0


def test_scene_spans_cut_in_pauses():
    words = [alignment.Word("a", 0, 0.5), alignment.Word("b.", 0.5, 1.0), alignment.Word("c", 1.4, 2.0)]
    spans = alignment.scene_spans(["a b.", "c"], words, 2.0, 0.5)
    assert spans == [(0.0, 1.2), (1.2, 2.5)]


def test_repair_scene_narration_restores_exact_script():
    full = "First sentence here. Second one is longer, with a clause. Third ends it."
    scenes = [{"narration": "First sentence"}, {"narration": "Second one is longer with clause"}, {"narration": "Third"}]
    fixed, repaired = repair_scene_narration(full, scenes)
    assert repaired
    assert " ".join(s["narration"] for s in fixed).split() == full.split()
    assert len(fixed) == 3 and all(s["narration"] for s in fixed)
    same, rep2 = repair_scene_narration(full, fixed)
    assert not rep2


def test_caption_cues_and_files(tmp_path):
    words = [alignment.Word(t, i * 0.4, i * 0.4 + 0.35) for i, t in enumerate("The sky is not actually blue. It only looks that way.".split())]
    cues = captions.build_cues(words, max_words=3, max_chars=18)
    assert all(len(c.words) <= 3 for c in cues)
    assert cues[1].text.endswith("blue.")  # punctuation ends a cue
    assert all(c.end <= n.start + 1e-9 for c, n in zip(cues, cues[1:]))
    captions.write_srt(cues, tmp_path / "c.srt", 18)
    srt = (tmp_path / "c.srt").read_text()
    assert srt.startswith("1\n00:00:00,000 --> ")
    style = CaptionSettings()
    captions.write_ass(cues, tmp_path / "c.ass", style, 1080, 1920)
    ass = (tmp_path / "c.ass").read_text()
    assert "PlayResY: 1920" in ass and "\\c&H0AD6FF&" in ass  # highlight colour #FFD60A as BGR
    assert captions.fit_chars(style, 1080, 1920) <= 18


def _make_clip(path: Path, seconds: float, size: str, rate: int = 24):
    subprocess.run(["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r={rate}:d={seconds}",
                    "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)


def test_plan_segments_flags_short_clips():
    plans = assembly.plan_segments([(Path("a"), 5.0), (Path("b"), 1.0)], [(0, 3), (3, 8)], max_stretch=1.3, transition_s=0.3)
    assert plans[0].speed == 1.0 and plans[0].render_length == 3.3
    assert plans[1].speed == 1.3 and plans[1].freeze > 3 and plans[1].flags


@needs_ffmpeg
def test_assembly_mixed_formats_to_vertical_mp4(tmp_path, speech_like_mp3):
    """Clips with different sizes, fps and lengths become one 9:16 video with burned captions."""
    clips = [tmp_path / "landscape.mp4", tmp_path / "square.mp4", tmp_path / "short.mp4"]
    _make_clip(clips[0], 3, "640x360", 30)
    _make_clip(clips[1], 4, "400x400", 24)
    _make_clip(clips[2], 0.8, "360x640", 16)
    s = Settings.model_validate({"video": {"width": 360, "height": 640, "fps": 24, "transition": "fade", "transition_s": 0.3,
                                           "min_duration_s": 3}, "captions": {"font": "DejaVu Sans"}})
    ff = FFmpeg()

    async def go():
        infos = [media_info(await ff.probe(c)) for c in clips]
        narr = media_info(await ff.probe(speech_like_mp3))
        text = "Clip one shows the start. Clip two explains more of it. The last clip ends it."
        tokens = alignment.tokenize(text)
        sil = alignment.parse_silences(await ff.run(["-i", str(speech_like_mp3), "-af", "silencedetect=noise=-38dB:d=0.15",
                                                     "-f", "null", "-"]))
        words = alignment.heuristic_timings(tokens, narr.duration, sil)
        spans = alignment.scene_spans(["Clip one shows the start.", "Clip two explains more of it.", "The last clip ends it."],
                                      words, narr.duration, 0.5)
        plans = assembly.plan_segments([(c, i.duration) for c, i in zip(clips, infos)], spans, max_stretch=1.35,
                                       transition_s=0.3)
        cues = captions.build_cues(words, 3, 14)
        ass = tmp_path / "captions.ass"
        captions.write_ass(cues, ass, s.captions, 360, 640)
        out = tmp_path / "out" / "final.mp4"
        total = narr.duration + 0.5

        async def prog(f, m):
            pass

        await assembly.assemble(ff, tmp_path / "work", plans, speech_like_mp3, out, s, ass_file=ass, music=None,
                                total=total, on_progress=prog, is_cancelled=lambda: False)
        report = await qc.run_qc(ff, out, s, expect_audio=True, captions_expected=True, captions_present=True,
                                 narration_duration=narr.duration, scene_flags=[f for p in plans for f in p.flags],
                                 draft_scenes=0, missing_scenes=0)
        return out, report, plans, total

    out, report, plans, total = anyio.run(go)
    info = media_info(subprocess_probe(out))
    assert (info.width, info.height) == (360, 640)
    assert abs(info.fps - 24) < 0.01
    assert info.has_audio and abs(info.duration - total) < 0.15
    assert report["technical_ok"], report
    assert any(c["id"] == "timing" for c in report["checks"])  # the 0.8 s clip had to be held


@needs_ffmpeg
def test_music_mix_with_ducking(tmp_path, speech_like_mp3):
    music = tmp_path / "music.mp3"
    subprocess.run(["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "sine=f=440:d=3", str(music)], check=True,
                   capture_output=True)
    clip = tmp_path / "c.mp4"
    _make_clip(clip, 9, "360x640")
    s = Settings.model_validate({"video": {"width": 360, "height": 640, "fps": 24, "min_duration_s": 3},
                                 "music": {"enabled": True, "file": "music.mp3"}})
    plans = assembly.plan_segments([(clip, 9.0)], [(0.0, 8.0)], max_stretch=1.35, transition_s=0)
    out = tmp_path / "final.mp4"

    async def go():
        async def prog(f, m):
            pass
        await assembly.assemble(FFmpeg(), tmp_path / "work", plans, speech_like_mp3, out, s, ass_file=None, music=music,
                                total=8.0, on_progress=prog, is_cancelled=lambda: False)

    anyio.run(go)
    info = media_info(subprocess_probe(out))
    assert info.has_audio and abs(info.duration - 8.0) < 0.15  # music looped to length, cut with the video


@needs_ffmpeg
def test_qc_detects_missing_audio_and_wrong_size(tmp_path):
    clip = tmp_path / "noaudio.mp4"
    _make_clip(clip, 2, "320x240")
    s = Settings.model_validate({"video": {"width": 360, "height": 640, "min_duration_s": 3}})

    async def go():
        return await qc.run_qc(FFmpeg(), clip, s, expect_audio=True, captions_expected=True, captions_present=False,
                               narration_duration=None, scene_flags=[], draft_scenes=0, missing_scenes=0)

    report = anyio.run(go)
    status = {c["id"]: c["status"] for c in report["checks"]}
    assert not report["technical_ok"]
    assert status["resolution"] == "fail" and status["audio"] == "fail" and status["captions"] == "fail"
    assert status["duration"] == "warn"
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    report2 = anyio.run(lambda: qc.run_qc(FFmpeg(), empty, s, expect_audio=True, captions_expected=False,
                                          captions_present=False, narration_duration=None, scene_flags=[],
                                          draft_scenes=0, missing_scenes=0))
    assert report2["checks"][0]["status"] == "fail"


def subprocess_probe(path: Path) -> dict:
    import json

    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, check=True)
    return json.loads(out.stdout)
