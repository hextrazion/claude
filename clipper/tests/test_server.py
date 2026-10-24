import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from clipper import pipeline
from clipper.server import make_server

from . import fixtures


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        src = fixtures.make_video(cls.tmp.name)
        plan = pipeline.analyze([{"path": src, "credit": "Test: me"}], pipeline.Settings(count=2), log=lambda m: None)
        cls.plan_path = str(Path(cls.tmp.name, "plan.json"))
        plan.save(cls.plan_path)
        cls.srv = make_server(cls.plan_path, 0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def get(self, path, headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}))

    def send(self, method, path, obj):
        req = urllib.request.Request(self.base + path, data=json.dumps(obj).encode(), method=method)
        return urllib.request.urlopen(req)

    def test_index_and_plan(self):
        self.assertIn(b"Clip Compiler", self.get("/").read())
        plan = json.load(self.get("/api/plan"))
        self.assertEqual(len(plan["clips"]), 2)

    def test_save_edits_and_reject_garbage(self):
        plan = json.load(self.get("/api/plan"))
        plan["clips"][0]["title"] = "Edited <b>title</b>"
        self.send("PUT", "/api/plan", plan)
        self.assertEqual(json.loads(Path(self.plan_path).read_text())["clips"][0]["title"], "Edited <b>title</b>")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.send("PUT", "/api/plan", {"clips": [{"nope": 1}]})
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(len(json.load(self.get("/api/plan"))["clips"]), 2)   # file untouched

    def test_preview_supports_range(self):
        r = self.get("/preview/0.mp4", {"Range": "bytes=0-99"})
        self.assertEqual(r.status, 206)
        self.assertEqual(len(r.read()), 100)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/preview/9.mp4")
        self.assertEqual(cm.exception.code, 404)

    def test_render_runs_in_background(self):
        out = str(Path(self.tmp.name, "r.mp4"))
        self.send("POST", "/api/render", {"output": out, "overlay": True, "intro": False})
        for _ in range(120):
            s = json.load(self.get("/api/state"))
            if s["status"] != "running":
                break
            time.sleep(0.5)
        self.assertEqual(s["status"], "done", s)
        self.assertGreater(len(self.get("/video").read()), 10000)
        self.assertEqual(self.get("/thumbnail").headers["Content-Type"], "image/jpeg")


if __name__ == "__main__":
    unittest.main()
