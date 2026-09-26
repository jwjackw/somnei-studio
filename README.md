# somnei studio

A local, Higgsfield-style ad generator built on the [kie.ai](https://kie.ai) API.
Make videos, images, songs and voiceovers from one dashboard, and review
Claude-written storyboards before any video credits are spent.

## Run it

```
python server.py
```

Then open http://localhost:4950. Python 3.10+ standard library only, no installs.

- **kie.ai key:** read from `~/somnei-shopify/.kie-token` (or the `KIE_AI_API_KEY` env var). It never reaches the browser.
- **ffmpeg** (for cutting storyboard videos): `winget install Gyan.FFmpeg --scope user`
- **Outputs:** saved to `~/Downloads/somnei-studio/`

## Tabs

**Generate.** Pick a model, fill in its settings, add images, clips or audio, and press Generate. The button shows the credit cost before you click. Models:

- Video: Veo 3, Kling 3.0, Seedance 2.5, Wan 2.7, HappyHorse, MiniMax H3, Grok Imagine, Gemini Omni
- Video edits: Wan and HappyHorse video edit, Runway Aleph, Wan 2.2 motion copy and person swap
- Talking avatars: OmniHuman 1.5, Kling Avatar, InfiniTalk
- Images: Nano Banana 2, GPT Image 2, Seedream 5 Pro, Flux 2 Pro, Topaz upscale
- Audio: Suno songs, ElevenLabs voiceover

**Storyboards.** Claude writes the concept into scenes (line, picture, motion, timing) and draws a start frame for each one. You then:

1. edit the text or redo frames;
2. pick a song take;
3. leave notes for Claude;
4. press **Make the video**, which approves the spend.

The server then animates every scene with Kling. It cuts them to length, burns in captions and mixes the song with ffmpeg.

## Files

| Path | What it is |
|---|---|
| `server.py` | HTTP server, kie.ai calls, job polling, storyboard pipeline, ffmpeg cut |
| `models.json` | Every model's endpoint, settings and pricing. The settings UI is generated from it. |
| `static/` | Front end (no build step) |
| `data/`, `uploads/`, `boards/` | Your history, media and storyboards (git-ignored) |

Prices come from kie.ai's public price list as of 2026-09-25 (1 credit = $0.005).
