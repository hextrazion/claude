import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from clipper import signals


class SignalTests(unittest.TestCase):
    def test_loudness_and_peaks(self):
        sr = 16000
        x = np.random.default_rng(1).normal(0, 0.01, 60 * sr).astype(np.float32)
        x[30 * sr:32 * sr] += np.random.default_rng(2).normal(0, 0.5, 2 * sr).astype(np.float32)
        db = signals.loudness_db(x, sr)
        self.assertEqual(len(db), 120)
        ms = signals.audio_moments(db)
        self.assertEqual(len(ms), 1)
        self.assertAlmostEqual(ms[0].t, 30.5, delta=2.0)
        self.assertGreater(ms[0].audio, 50)
        self.assertIsNone(ms[0].chat)

    def test_flat_audio_has_no_moments(self):
        x = np.random.default_rng(1).normal(0, 0.01, 30 * 16000).astype(np.float32)
        self.assertEqual(signals.audio_moments(signals.loudness_db(x, 16000)), [])

    def test_chat_burst_scores(self):
        times = [i * 5.0 for i in range(40)] + [100 + i * 0.1 for i in range(80)]  # steady, then a flood
        z = signals.chat_z_series(times, 200)
        i = int(105 / signals.HOP)
        self.assertGreater(z[i], 3)
        self.assertLess(z[int(20 / signals.HOP)], 1)

    def test_chat_loaders(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "c.json")
            p.write_text(json.dumps({"comments": [{"content_offset_seconds": 3.5}, {"content_offset_seconds": 9}]}))
            self.assertEqual(signals.load_chat_times(str(p)), [3.5, 9.0])
            p.write_text(json.dumps([1, 2.5, {"t": 7}]))
            self.assertEqual(signals.load_chat_times(str(p)), [1.0, 2.5, 7.0])
            p.write_text("1.5\n2\n")
            self.assertEqual(signals.load_chat_times(str(p)), [1.5, 2.0])


if __name__ == "__main__":
    unittest.main()
