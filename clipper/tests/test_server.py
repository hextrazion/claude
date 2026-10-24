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
        from clipper import jobs
        from clipper.discover import Candidate
        from clipper.server import ServerConfig
        cls.ctx = jobs.Context(workdir=str(Path(cls.tmp.name, "work")), env={}, transcriber_available=lambda: False,
                               find=lambda spec, env=None: ([Candidate(url=src, credit="Test: me")], []))
        cls.srv = make_server(cls.plan_path, 0, ServerConfig(workdir=str(Path(cls.tmp.name, "work")), use_llm=False), cls.ctx)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def get(self, path, headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}))

    def send(self, method, path, obj, headers=None):
        h = {"X-Clipper": "1"} if headers is None else headers
        req = urllib.request.Request(self.base + path, data=json.dumps(obj).encode(), method=method, headers=h)
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
        r = json.load(self.send("POST", "/api/render", {"output": "../../evil/r.mp4", "overlay": True, "intro": False}))
        out = r["output"]
        self.assertEqual(Path(out).parent, Path(self.tmp.name, "work").resolve())   # path traversal is flattened
        for _ in range(120):
            s = json.load(self.get("/api/state"))
            if s["status"] != "running":
                break
            time.sleep(0.5)
        self.assertEqual(s["status"], "done", s)
        self.assertGreater(len(self.get("/video").read()), 10000)
        self.assertEqual(self.get("/thumbnail").headers["Content-Type"], "image/jpeg")


    def wait_job(self):
        for _ in range(240):
            j = json.load(self.get("/api/job"))
            if j["status"] != "running":
                return j
            time.sleep(0.5)
        self.fail("job did not finish")

    def test_writes_require_custom_header_and_local_host(self):
        for method, path in (("POST", "/api/chat"), ("POST", "/api/job"), ("PUT", "/api/plan"), ("POST", "/api/render")):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.send(method, path, {"message": "x"}, headers={})
            self.assertEqual(cm.exception.code, 403, path)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/plan", {"Host": "evil.example.com"})
        self.assertEqual(cm.exception.code, 403)

    def test_chat_then_start_job_produces_video_and_plan(self):
        r = json.load(self.send("POST", "/api/chat", {"message": "clips from Tester, top 2, square, no intro"}))
        self.assertEqual((r["spec"]["query"], r["spec"]["count"], r["spec"]["aspect"]), ("Tester", 2, "1:1"))
        self.assertEqual(len(json.load(self.get("/api/chat"))["history"]), 2)
        self.send("POST", "/api/job", {})
        j = self.wait_job()
        self.assertEqual(j["status"], "done", j)
        self.assertTrue(any("Rendering" in m for m in j["log"]))
        from clipper.models import Plan
        self.assertEqual(Plan.load(self.plan_path).settings["aspect"], "1:1")
        self.assertGreater(len(self.get("/video").read()), 10000)

    def test_job_without_target_is_rejected(self):
        srv = make_server(str(Path(self.tmp.name, "fresh.json")), 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_port}"

            def post(path, obj):
                return urllib.request.urlopen(urllib.request.Request(
                    base + path, data=json.dumps(obj).encode(), method="POST", headers={"X-Clipper": "1"}))
            r = json.load(post("/api/chat", {"message": "find funny clips"}))
            self.assertIsNone(r["spec"])
            self.assertIn("Who", r["reply"])
            with self.assertRaises(urllib.error.HTTPError) as cm:
                post("/api/job", {})
            self.assertEqual(cm.exception.code, 400)
            self.assertEqual(json.load(urllib.request.urlopen(base + "/api/plan"))["clips"], [])   # no plan file yet
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
