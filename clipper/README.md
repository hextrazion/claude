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

## Use: just chat

```bash
python -m clipper chat          # opens http://127.0.0.1:8765
```

Type what you want, the way you'd text a person:

> *I need you to find funny clips from xQc and compile them into a top 5 vertical video with captions*

The assistant (your local model) turns that into a **job card**: who to search, how many clips, countdown or
plain compilation, 16:9 / 9:16 / 1:1, captions, overlays, intro. Check it, press **Start**, and watch the log:
find sources -> download -> pick the funniest moments -> edit -> render. Then review the clips on the same page
(preview, retitle, trim, reorder, remove, switch format) and render again. Follow-ups work too:
*"make it square"*, *"no intro"*, *"7 clips instead"*. You can also paste links.

If the local model is off or confused, simple keyword parsing still understands the common phrasings.

**Where clips come from**

| Source | How | Needs |
|---|---|---|
| Twitch top clips (best) | the official API, ranked by views, within a time window | free key: set `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` (create an app at dev.twitch.tv/console) |
| YouTube search | yt-dlp search for "<name> funny moments" | nothing |
| Your own links/files | paste URLs in the chat, or use the CLI below | nothing |

**Formats:** Top-N countdown (#N badges, #1 last) or plain compilation; 16:9, 9:16 (blurred-background fill, text kept
clear of the TikTok/Shorts buttons) or 1:1; optional burned-in captions; title + credit overlays; intro card.

### Command line (no chat)

```bash
python -m clipper analyze "https://www.twitch.tv/videos/123456789" stream2.mp4 --count 5   # -> plan.json
python -m clipper ui plan.json                                                             # review + render
python -m clipper run "https://youtu.be/XXXXXXXXXXX" --out top5.mp4                        # all in one
```

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

## Security notes

The app server listens on `127.0.0.1` only, rejects requests whose `Host` isn't localhost, and requires a custom
header on every write, so other websites open in your browser can't start jobs. Output files are always written
inside `--workdir`.

## Tests

```bash
python -m unittest discover -s tests -t .
```

Tests build a synthetic video with loud bursts at known times, and cover detection, the chat parser and LLM client
(against a fake local server), source discovery (mocked Twitch/YouTube), all render formats, and the app server.
Live Twitch/YouTube access, Whisper and a real local model are not exercised by the test suite.
