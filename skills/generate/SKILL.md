---
name: generate
description: |
  Generate video, image, song or voiceover ads through Somnei Studio (kie.ai models:
  Veo 3, Kling 3.0, Seedance 2.5, Wan 2.7, HappyHorse, MiniMax H3, Grok Imagine,
  Gemini Omni, Runway Aleph, OmniHuman, Kling Avatar, InfiniTalk, Nano Banana 2,
  GPT Image 2, Seedream 5, Flux 2, Topaz, Suno, ElevenLabs).
  Use when: "make a video", "animate this photo", "image to video", "make an ad",
  "UGC video", "talking avatar", "lip sync", "product shot", "ad static",
  "edit this clip", "make a song/jingle", "voiceover".
  NOT for: multi-scene ads that need a script and approval first (use storyboard).
argument-hint: "[what to make] [--model <key>] [--image|--video|--audio <path>]"
allowed-tools: Bash
---

# Somnei Studio: generate

Runs one generation through a local Somnei Studio server (http://localhost:4950) with
the `studio` CLI (`python cli.py` in the repo) or the `somnei-studio` MCP tools.

## Rules that always apply

1. **Price first, spend second.** Every spending command stops and prints its cost
   (exit code 2) unless given `--yes` / `confirm=true`. Show the cost to the user and get
   a clear yes before confirming. 1 credit = $0.005.
2. **Check the server.** If a command says the server is not running, start it with
   `python server.py` from the repo (or ask the user to open the app).
3. **Describe the model before using it.** `studio model <key>` lists every setting,
   allowed value and media input. Never guess a setting name.
4. **Use the user's real product images.** Pass their files with `-m`, never substitute
   an AI-made product. Product fidelity comes from references, not from prompt words.

## Loop

```bash
python cli.py credits                          # balance
python cli.py models --kind video              # pick a model (see below)
python cli.py model kling3                     # its settings
python cli.py cost kling3 -p "..." -s duration=5 -m image_urls=product.png
python cli.py generate kling3 -p "..." -s duration=5 -m image_urls=product.png          # prints cost, exit 2
python cli.py generate kling3 -p "..." -s duration=5 -m image_urls=product.png --yes --wait
```

`-m key=path` uploads a local file automatically; an asset id or URL also works.
Results land in `~/Downloads/somnei-studio/` and in `studio jobs`.

## Picking a model

| Need | Model key | Why |
|---|---|---|
| Person talking to camera with real speech and sound | `veo3` | Speech, lip sync and ambience in one pass. 8s. 60 credits Fast. |
| Animate a start frame (product or scene), 3 to 15s | `kling3` | Best motion per credit. `mode=pro` for 1080p, `sound=true` for audio. |
| Copy motion or look from reference clips or several images | `seedance25` | Takes frames or up to 9 image, 3 video, 3 audio references. |
| Cheapest realistic motion | `minimax-h3` | 8 credits per second. |
| Quick throwaway test | `grok-i2v` | About 27 credits. |
| Keep a person or product consistent across shots | `wan27-r2v`, `happyhorse-ref` | Reference-to-video. |
| Change an existing clip with words | `wan27-edit`, `happyhorse-edit`, `aleph` | Video edit. |
| Photo plus voice track becomes a talking head | `omnihuman` (best), `kling-avatar`, `infinitalk` | Costed per second of audio. |
| Voice track for an avatar | `tts` | ElevenLabs, 6 credits per 1k characters. |
| Song or jingle | `suno` | 2 takes, 12 credits. |
| Ad static, first frame, text in image | `nano-banana-2` | Accurate text rendering, up to 14 references. |
| Photoreal product or skin texture | `seedream5`, `gpt-image-2` | |
| Sharpen before animating | `topaz-image` | |

## Prompting

Read `references/prompting.md` before writing any prompt. Short version:

- Video prompts describe **one continuous shot**: subject, action, camera move, light, sound.
- Put the camera move in words the model knows (dolly in, orbit, crash zoom, handheld selfie).
  The Studio UI has one-click chips for these; the phrases are in `presets.json`.
- Image-to-video: describe only what **changes**. The frame already shows what things look like.
- Spoken lines go in quotes. Keep them under about 20 words for an 8s clip.
- Nano Banana renders capitalised instruction words as text. Keep instructions lowercase and
  quote only the copy you want printed.

## Failures

`studio job <id>` shows the error from kie.ai. Common ones: content filter (reword, remove
brand names or body terms), wrong aspect ratio for the model (`studio model <key>`),
expired media link (the server re-uploads files older than 20 hours automatically).
