import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from clipper import discover, jobs, media, render
from clipper.chat import ChatAgent, heuristic_spec
from clipper.discover import Candidate
from clipper.llm import LocalLLM
from clipper.models import Plan
from clipper.spec import JobSpec, normalize, summary

from . import fixtures


class HeuristicTests(unittest.TestCase):
    def test_full_request(self):
        d, _ = heuristic_spec("find funny clips from xQc and compile them into a top 5 vertical video with captions")
        self.assertEqual((d["query"], d["count"], d["aspect"], d["captions"], d["style"]), ("xQc", 5, "9:16", True, "countdown"))

    def test_destination_is_not_source_platform(self):
        d, _ = heuristic_spec("top 10 of Ludwig this week for youtube shorts, no intro")
        self.assertEqual((d["query"], d["period"], d["intro"], d["aspect"]), ("Ludwig", "week", False, "9:16"))
        self.assertNotIn("platform", d)

    def test_urls_and_compilation(self):
        d, _ = heuristic_spec("make a compilation of https://youtu.be/abc and https://twitch.tv/videos/9.")
        self.assertEqual(d["urls"], ["https://youtu.be/abc", "https://twitch.tv/videos/9"])
        self.assertEqual(d["style"], "compilation")

    def test_follow_up_edits_keep_earlier_choices(self):
        agent = ChatAgent(None)
        _, s1 = agent.respond([], "clips from Kai Cenat, top 3")
        _, s2 = agent.respond([], "make it square with captions", s1)
        self.assertEqual((s2.query, s2.count, s2.aspect, s2.captions), ("Kai Cenat", 3, "1:1", True))

    def test_asks_when_nothing_to_search(self):
        reply, spec = ChatAgent(None).respond([], "find funny clips")
        self.assertIsNone(spec)
        self.assertIn("Who", reply)

    def test_normalize_clamps_and_rejects_junk(self):
        s = normalize({"count": 500, "aspect": "4:3", "style": "weird", "captions": "yes", "max_clip_seconds": 1, "evil": 1})
        self.assertEqual((s.count, s.aspect, s.style, s.captions, s.max_clip_seconds), (20, "16:9", "countdown", True, 8))


class FakeModel(BaseHTTPRequestHandler):
    reply = ""

    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send({"data": [{"id": "m"}]})

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self._send({"choices": [{"message": {"content": FakeModel.reply}}]})


class LLMChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeModel)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_model_json_becomes_spec(self):
        FakeModel.reply = ('Sure!\n```json\n{"reply": "On it - 7 vertical clips of Ludwig.", "spec": {"query": "Ludwig", '
                           '"count": 7, "aspect": "9:16", "captions": true}}\n```')
        reply, spec = ChatAgent(LocalLLM(self.url)).respond([], "ludwig please, 7, tiktok style with subs")
        self.assertEqual((spec.query, spec.count, spec.aspect, spec.captions), ("Ludwig", 7, "9:16", True))
        self.assertIn("On it", reply)

    def test_model_asking_a_question_gives_no_spec(self):
        FakeModel.reply = '{"reply": "Which streamer?", "spec": null}'
        reply, spec = ChatAgent(LocalLLM(self.url)).respond([], "make me a video")
        self.assertIsNone(spec)
        self.assertEqual(reply, "Which streamer?")

    def test_garbage_reply_falls_back_to_keywords(self):
        FakeModel.reply = "I am a small model and I ignore instructions."
        _, spec = ChatAgent(LocalLLM(self.url)).respond([], "clips from xQc top 4")
        self.assertEqual((spec.query, spec.count), ("xQc", 4))

    def test_dead_server_falls_back_and_says_so(self):
        reply, spec = ChatAgent(LocalLLM("http://127.0.0.1:9/v1", timeout=1)).respond([], "clips from xQc")
        self.assertEqual(spec.query, "xQc")
        self.assertIn("keyword", reply)


class DiscoverTests(unittest.TestCase):
    def test_youtube_filters_by_duration(self):
        lines = [json.dumps({"id": "a", "title": "t", "duration": 30, "channel": "C"}),
                 json.dumps({"id": "b", "title": "good", "duration": 900, "channel": "C", "view_count": 5}),
                 json.dumps({"id": "c", "title": "too long", "duration": 99999}), "not json"]
        got = discover.search_youtube("xqc", 4, runner=lambda cmd: "\n".join(lines))
        self.assertEqual([c.url for c in got], ["https://www.youtube.com/watch?v=b"])
        self.assertEqual(got[0].credit, "YouTube: C")

    def test_twitch_clips_sorted_by_views_with_end_date(self):
        calls = []

        def http(method, url, headers=None, data=None):
            calls.append(url)
            if "oauth2" in url:
                return {"access_token": "tok"}
            if "/users" in url:
                return {"data": [{"id": "123"}]}
            return {"data": [{"url": "u1", "title": "a", "view_count": 5, "duration": 20, "creator_name": "viewer1", "broadcaster_name": "X"},
                             {"url": "u2", "title": "b", "view_count": 50, "duration": 30, "creator_name": "", "broadcaster_name": "X"}]}

        got = discover.twitch_clips("x qc", "week", 5, "id", "sec", http=http)
        self.assertEqual([c.url for c in got], ["u2", "u1"])
        self.assertIn("ended_at=", calls[-1])
        self.assertIn("login=xqc", calls[1])
        self.assertEqual(got[1].credit, "Twitch: X (clip by viewer1)")

    def test_auto_platform_needs_keys_for_twitch(self):
        spec = JobSpec(query="x", platform="twitch")
        with self.assertRaises(media.MediaError):
            discover.find_sources(spec, env={})
        got, notes = discover.find_sources(JobSpec(query="x"), env={}, runner=lambda c: "")
        self.assertEqual(got, [])
        self.assertTrue(any("YouTube" in n for n in notes))


class JobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.src = fixtures.make_video(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ctx(self, **kw):
        work = str(Path(self.tmp.name, "work"))
        return jobs.Context(workdir=work, env={}, transcriber_available=lambda: False,
                            find=lambda spec, env=None: ([Candidate(url=self.src, credit="Test: me", platform="url")], ["note!"]),
                            **kw)

    def test_vertical_countdown_end_to_end(self):
        log = []
        spec = JobSpec(query="Tester", count=2, aspect="9:16", captions=True)
        res = jobs.run_job(spec, self.ctx(), str(Path(self.tmp.name, "p.json")), log.append)
        self.assertEqual(media.probe_size(res["output"]), (1080, 1920))
        plan = Plan.load(res["plan"])
        self.assertEqual(plan.title, "Top 2 Funniest Tester Moments")
        self.assertEqual(plan.settings["aspect"], "9:16")
        self.assertFalse(plan.settings["captions"])            # no whisper here, so honestly off
        self.assertTrue(any("captions" in m.lower() for m in log))
        self.assertIn("note!", log)
        self.assertTrue(Path(res["output"]).with_suffix(".jpg").exists())

    def test_compilation_square(self):
        res = jobs.run_job(JobSpec(query="T", count=2, style="compilation", aspect="1:1", intro=False),
                           self.ctx(), str(Path(self.tmp.name, "q.json")), lambda m: None)
        self.assertEqual(media.probe_size(res["output"]), (1080, 1080))
        self.assertIn("compilation", res["output"])

    def test_no_sources_is_a_readable_error(self):
        ctx = jobs.Context(workdir=self.tmp.name, env={}, find=lambda spec, env=None: ([], []))
        with self.assertRaisesRegex(media.MediaError, "couldn't find"):
            jobs.run_job(JobSpec(query="nobody"), ctx, "x.json", lambda m: None)

    def test_failed_downloads_are_skipped_not_fatal(self):
        def fetch(url, d):
            raise media.MediaError("403")
        ctx = jobs.Context(workdir=self.tmp.name, env={}, fetch=fetch, find=lambda spec, env=None: (
            [Candidate(url="https://example.com/v", title="v")], []))
        with self.assertRaisesRegex(media.MediaError, "None of the sources"):
            jobs.run_job(JobSpec(query="x"), ctx, "x.json", lambda m: None)


if __name__ == "__main__":
    unittest.main()
