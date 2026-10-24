import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from clipper.llm import LLMError, LocalLLM, parse_judgement


class Handler(BaseHTTPRequestHandler):
    reply = '{"score": 88, "reason": "huge scream", "title": "The Scream"}'

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        self._send({"data": [{"id": "test-model"}]})

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        Handler.last = json.loads(self.rfile.read(n))
        self._send({"choices": [{"message": {"content": Handler.reply}}]})


class LLMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_judge_picks_first_model_and_parses(self):
        llm = LocalLLM(self.url)
        j = llm.judge("aaaah what")
        self.assertEqual(llm.model, "test-model")
        self.assertEqual(Handler.last["model"], "test-model")
        self.assertEqual((j.score, j.title), (88.0, "The Scream"))

    def test_parse_handles_fences_think_and_clamp(self):
        j = parse_judgement('<think>hmm {x}</think>```json\n{"score": 140, "reason": "r", "title": "t"}\n```')
        self.assertEqual(j.score, 100.0)
        with self.assertRaises(LLMError):
            parse_judgement("no json here")

    def test_unreachable_server_raises(self):
        with self.assertRaises(LLMError):
            LocalLLM("http://127.0.0.1:9/v1", timeout=1).models()


if __name__ == "__main__":
    unittest.main()
