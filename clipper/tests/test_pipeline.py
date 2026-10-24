import tempfile
import unittest
from pathlib import Path

from clipper import media, pipeline, render
from clipper.models import Plan

from . import fixtures


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.src = fixtures.make_video(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_analyze_finds_bursts_and_orders_countdown(self):
        plan = pipeline.analyze([{"path": self.src, "credit": "Test: me"}],
                                pipeline.Settings(count=3), log=lambda m: None)
        self.assertEqual(len(plan.clips), 3)
        scores = [c.score for c in plan.clips]
        self.assertEqual(scores, sorted(scores))            # worst first, best (#1) last
        best = plan.clips[-1]
        self.assertTrue(best.start <= fixtures.BURSTS[2] <= best.end)   # longest burst is #1
        for burst in fixtures.BURSTS:
            self.assertTrue(any(c.start <= burst <= c.end for c in plan.clips))
        self.assertEqual(best.credit, "Test: me")

    def test_plan_roundtrip(self):
        plan = pipeline.analyze([{"path": self.src}], pipeline.Settings(count=2), log=lambda m: None)
        p = Path(self.tmp.name, "plan.json")
        plan.save(p)
        again = Plan.load(p)
        self.assertEqual([c.start for c in again.clips], [c.start for c in plan.clips])

    def test_render_makes_playable_video(self):
        plan = pipeline.analyze([{"path": self.src, "credit": "Test: me"}],
                                pipeline.Settings(count=2), log=lambda m: None)
        out = str(Path(self.tmp.name, "out", "final.mp4"))
        steps = []
        render.render(plan, out, on_progress=lambda i, n, m: steps.append((i, n)))
        dur, has_audio = media.probe(out)
        expected = 2.5 + sum(c.duration for c in plan.clips)
        self.assertAlmostEqual(dur, expected, delta=1.5)
        self.assertTrue(has_audio)
        self.assertEqual(steps[-1][0], steps[-1][1])
        thumb = render.thumbnail(plan, str(Path(self.tmp.name, "thumb.jpg")))
        self.assertGreater(Path(thumb).stat().st_size, 1000)

    def test_silent_source_is_skipped(self):
        silent = fixtures.make_video(self.tmp.name, "silent.mp4", with_audio=False)
        plan = pipeline.analyze([{"path": silent}], log=lambda m: None)
        self.assertEqual(plan.clips, [])


if __name__ == "__main__":
    unittest.main()
