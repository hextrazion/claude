# Clip Compiler

Finds the funniest moments in Twitch / YouTube videos (or your own recordings) and assembles a
"Top 5" countdown video. A **local model** (Ollama, LM Studio, llama.cpp, Jan - anything OpenAI-compatible)
judges the moments, so nothing is sent to a cloud service.

UI design: [Figma file](https://www.figma.com/design/IDi8tIOIqPUqmbMSrVD32y)

## Install

Needs Python 3.9+ and [ffmpeg](https://ffmpeg.org/download.html) on your PATH.

```bash
cd clipper
pip install -e ".[all]"      # numpy + yt-dlp (downloads) + faster-whisper (speech-to-text)
```

## Use

```bash
# 1. find the best moments -> plan.json (add --chat for a chat log, see below)
python -m clipper analyze "https://www.twitch.tv/videos/123456789" stream2.mp4 --count 5

# 2. review/edit in the browser: preview clips, retitle, trim, reorder, remove, render
python -m clipper ui plan.json

# or skip the review and render straight away
python -m clipper run "https://youtu.be/XXXXXXXXXXX" --out top5.mp4
```

Output: `top5.mp4`, `top5.jpg` (thumbnail from the #1 clip) and a few title ideas.

### Local model

By default it talks to Ollama at `http://localhost:11434/v1` and uses the first model it lists.

```bash
python -m clipper analyze vod.mp4 --llm-url http://localhost:1234/v1 --llm-model qwen2.5:7b-instruct   # LM Studio
python -m clipper analyze vod.mp4 --no-llm                                                              # signals only
```

If the model server is not running, it carries on with audio/chat signals only and says so.

## How clips are chosen

1. **Audio**: loudness spikes (screams, slams) found with a robust z-score over the whole video.
2. **Laughter proxy**: how long the loudness stays elevated after the spike.
3. **Chat** (optional): a burst of chat messages shortly after the moment. Pass `--chat log.json` per source;
   accepts a JSON list of timestamps, `{"comments":[{"content_offset_seconds":..}]}` (Twitch downloaders),
   or one number of seconds per line.
4. **AI**: only the top candidates are transcribed (faster-whisper) and the local model rates the transcript 0-100
   and suggests a title.

Scores from the signals that exist are combined (missing signals don't penalise a clip), overlapping
clips are dropped, and the best N are ordered worst-first so **#1 plays last**.

## Permissions

Compiling other people's clips can be a copyright or monetization problem even with credit. Each clip in the plan
keeps a `credit` (shown on screen) and a `permission` (`unknown` / `granted` / `own`) so you can track which
creators you have cleared. Get the creator's OK before posting.

## Tests

```bash
python -m unittest discover -s tests -t .
```

Tests build a synthetic video with loud bursts at known times, and cover detection, the LLM client (against a
fake local server), rendering, and the review server.
