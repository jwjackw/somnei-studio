# Storyboard spec

`POST /api/boards/create`, `python cli.py board create spec.json`, or the MCP `board_create` tool.

```json
{
  "title": "The People vs. The Razor",
  "subtitle": "Courtroom musical. 6 scenes, 18s, 9:16.",
  "hook": "\"Your Honor, my razor tried to kill me.\"",
  "product": "The Peach 2-in-1 trimmer",
  "style": "stylized 3d animated film look, warm courtroom light, expressive faces, consistent character design",
  "refs": [
    {"label": "Jess character sheet", "path": "C:/ads/jess.png", "role": "character"},
    {"label": "Product", "path": "C:/ads/peach.png", "role": "product"}
  ],
  "song": {
    "lyrics": "Your Honor, my razor tried to kill me\nEvery morning it bites and it burns...",
    "style": "upbeat broadway show tune, female lead, piano and brass, comedic",
    "title": "The People vs. The Razor",
    "vocalGender": "f"
  },
  "video": {"model": "kling3", "mode": "std"},
  "frameResolution": "1K",
  "captions": true,
  "scenes": [
    {"start": 0.0, "end": 2.5, "line": "Your Honor, my razor tried to kill me",
     "picture": "Grand wood panelled courtroom. Jess, late 20s, red hair in a messy bun, lavender t shirt, stands in the witness box pointing dramatically, outraged expression.",
     "motion": "Jess jabs her finger toward the defense table and sings; quick push in.",
     "tags": ["hook"], "refIdx": [0]},
    {"start": 2.5, "end": 4.0, "line": "every single morning",
     "picture": "The jury box: twelve sleepy jurors in pajamas, gasping, hands over mouths.",
     "motion": "Jurors gasp in unison; slight handheld shake.", "refIdx": []},
    {"start": 15.0, "end": 18.0, "line": "Case closed.", "still": true,
     "picture": "Clean end card: the product centred on soft pink, the words Case closed above it.",
     "tags": ["product", "endcard"], "refIdx": [1]}
  ]
}
```

## Fields

| Field | Meaning |
|---|---|
| `style` | Prepended to every frame prompt. Keep the look consistent here, not per scene. |
| `refs` | Local files copied into the board and sent as reference images with every frame. |
| `refs[].role` | `character`, `product`, `style` or `setting`. Adds the matching lock line to every frame prompt (same face, exact product, style only, same location). `refs[].lock` overrides the text. |
| `clipLock` | Appended to every clip prompt. Default: one continuous shot, nothing but the described action, no on-screen text. `""` turns it off. |
| `scenes[].lock` | Per-scene override of `clipLock` (e.g. "camera locked, she stays centred"). |
| `scenes[].fromPrev` | Start this clip from the previous clip's actual last frame (exact-frame handoff for one continuous move). No frame is drawn; the clip starts when the previous one lands. |
| `scenes[].refIdx` | Which refs this scene uses (indexes into `refs`). Omit for all. |
| `scenes[].still` | No clip: the frame is held for the scene's length (end cards). |
| `scenes[].sound` | Ask Kling for native audio on this clip (costs more). |
| `scenes[].clipModel` | `kling3` (default) or `veo3` for real speech. |
| `scenes[].caption` | Caption text if different from `line`. `noCaption: true` hides it. |
| `scenes[].clipOffset` | Seconds to skip at the start of the generated clip when cutting. |
| `song.offset` | Seconds to skip at the start of the song (trim a slow intro). |

Clip length is the scene length rounded up, 3 to 15 seconds for Kling (8 for Veo). The cut trims
each clip back to the exact scene length, so short scenes still cost a 3 second clip.

## Human notes

The Storyboards tab saves `scenes[].note` and a board-level `note`. Read them with
`python cli.py board show <id>` or the MCP `board_get` tool, apply them, then clear or
answer each one.
