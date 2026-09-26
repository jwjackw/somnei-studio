---
name: storyboard
description: |
  Turn an ad concept and a product into a scripted, scene-by-scene storyboard in
  Somnei Studio, get the human's approval in the Storyboards tab, then render every
  clip and auto-cut the final 9:16 video with captions and a song.
  Use when: "make an ad about...", "storyboard this concept", "script and make a
  video ad", "musical ad", "multi-scene ad", "check the storyboard", "make the video".
  NOT for: a single clip or image (use generate).
argument-hint: "[concept] [product] [length] [musical|voiceover|silent]"
allowed-tools: Bash
---

# Somnei Studio: storyboard

The human approves before any video credits are spent. Frames are cheap, clips are not.

## 1. Brief

Collect or decide: concept, product (and its real photos), target length (15 to 40s),
audio (musical, voiceover, or none), platform (default Reels/TikTok 9:16), main character.

## 2. Script

- **Hook in the first second.** The first line must stop the scroll on its own
  (a claim, a question, a conflict). No logo, no slow build.
- **One idea per scene**, 1 to 4 seconds each. Musical ads cut on the lyric; spoken ads
  cut on the sentence.
- **Product appears by the middle** and is hero-lit in the last 3 to 5 seconds, then an end card.
- Write every scene as `{start, end, line, picture, motion}`:
  - `line`: the lyric or spoken words (also used as the burned-in caption).
  - `picture`: a full description of the **still frame**: who, where, wardrobe, expression,
    framing, light. Repeat the character description in every scene; frames are drawn
    independently.
  - `motion`: only what moves in the clip, plus the camera move.
- Add `refs` (character sheet, product photos) with a `role` each (`character`, `product`,
  `style`, `setting`). Every frame prompt then opens with a line naming each image and a lock
  line per role (same face; exact product; style only). Use `refIdx` to limit a scene to some
  refs (e.g. no product in the problem scenes).
- Every clip prompt gets the board's `clipLock` appended (one continuous shot, only the
  described action, no on-screen text). Override per scene with `lock`.
- For one continuous camera move across two scenes, set `fromPrev: true` on the second: it
  starts from the first clip's real last frame instead of a newly drawn one.
- `still: true` for the end card. `clipModel: "veo3"` for a scene that needs real speech.
- For musical ads write `song: {lyrics, style, title, vocalGender}`. Make the song first
  (12 credits, needs the human's OK), then use timestamped lyrics to set scene times.

See `references/storyboard-spec.md` for the full JSON and a worked example.

## 3. Create and draw

```bash
python cli.py board create spec.json          # returns the board id
python cli.py board frames <id>               # Nano Banana 2, 8 credits a frame at 1K
```

Drawing frames is pre-approved up to about 200 credits per storyboard (including redos)
only if the human has said so; otherwise state the cost first.

## 4. Review

Tell the human to open http://localhost:4950 > Storyboards. They can edit text, redo frames,
pick takes and leave notes. When they say "check the storyboard":

```bash
python cli.py board show <id>                 # scene statuses and every NOTE
```

Apply each note (edit the scene via the MCP `board_update` tool or the UI, redraw that frame),
then tell them what changed.

## 5. Render

Only after a clear approval (their "Make the video" click in the UI counts):

```bash
python cli.py board render <id> --mode std          # prints the cost, exit 2
python cli.py board render <id> --mode std --yes    # makes every clip, then auto-cuts
```

The cut trims each clip to its scene, crops to 1080x1920, burns captions above the Reels
UI zone, and mixes the chosen song take. The file lands in `boards/<id>/final.mp4` and
`~/Downloads/somnei-studio/`. Recutting after a single clip redo is free:
`python cli.py board assemble <id>`.
