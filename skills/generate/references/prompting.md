# Prompting for ad generation

Rules that hold across the kie.ai models in this studio. Read before writing any prompt.

## Every prompt

- **Concrete and sensory.** Subject, setting, action, camera, light, medium. "A woman in her
  late 20s in a sunlit bathroom, holding a pink trimmer, handheld phone shot" beats "a nice
  bathroom scene".
- **Short.** Around 60 to 200 words. Very long prompts make models blend or drop details.
- **Positive phrasing.** Most models have no negative field, so say what you want:
  "tack sharp" instead of "no blur", "empty sky" instead of "no birds".
- **No real public figures, trademarks you don't own, or sexual content.** These fail the
  content filter; reword instead of retrying.

## Image to video (a start frame is attached)

- **Describe only what changes.** The frame already shows how everything looks. Re-describing
  it causes drift. Write the action and the camera move, nothing else.
- **One action per clip.** A second verb ("she smiles and then picks up the phone") is where
  clips go wrong. Split it into two scenes.
- **Close the doors.** Models fill leftover seconds with improvisation. Add a lock line:
  camera locked (or the one move you want), held props stay still, no on-screen text.
  Storyboards append this automatically (`clipLock`).
- **Camera vocabulary models understand:** dolly in/out, push in, pull back, orbit, crash zoom,
  whip pan, tracking shot, crane up, tilt reveal, rack focus, handheld, locked-off tripod, FPV
  fly-through, macro. One move per clip. The UI chips insert these (`presets.json`).

## Continuity across clips

- **Exact-frame handoff:** for a continuous move across two clips, start clip 2 from the
  *actual* last frame of clip 1 (`fromPrev: true` in a storyboard). Keep direction and speed
  matched across the seam.
- **End-frame reveal:** to land exactly on an approved composition, give the approved image as
  the last frame and describe the build-up toward it (Kling and Veo take start and end frames).
- **Seamless loop:** same image as start and end frame.

## References and consistency

- **Real product photos beat words.** Product fidelity comes from the reference image. Never
  let a model invent the product, its logo or its packaging.
- **Label every reference in the prompt**, first line:
  `image references: image 1 = Jess character sheet; image 2 = product`.
- **Lock each one by role:**
  - person: same face shape, eyes, nose, lips, jaw, skin tone, hairline, hair; do not beautify or restyle.
  - product: same shape, proportions, colours, materials, markings; do not add logos or text.
  - style image: take only the rendering style and grading, never its people, text or logos.
- **Repeat the character description in every scene.** Frames are drawn independently.
- **One style line for the whole board** (`style`), identical in every frame prompt.

## Text in images

- Nano Banana 2 and GPT Image 2 render text well. Quote the exact copy:
  `headline reading "Smooth in one pass"`.
- **Keep every instruction lowercase.** Nano Banana prints capitalised instruction words
  ("EXACTLY", "MUST") as part of the headline.
- Give placement as percentages ("leave the top 12 percent empty", "headline starts about
  30 percent down"). Vague words like "near the product" are ignored.
- For pixel-exact text, render the scene with the surface blank, then add text in a second
  pass or in an editor.

## Speech and sound

- Veo 3 speaks lines in quotes with lip sync. About 20 words fit an 8 second clip.
- Spoken scripts run at about 150 words per minute. Do not pad.
- For voiceover ads, make the voice track first (ElevenLabs), then fit the visuals to it.
- Avatars (OmniHuman, Kling Avatar, InfiniTalk) are priced per second of audio: trim silence first.

## Ad structure

- **Hook in the first second.** The first frame and line must stop the scroll on their own:
  a claim, a question, a conflict, a surprising image. Test several hooks on one body before
  testing several bodies.
- **Show the product by the midpoint** and hero it at the end, then an end card.
- **Match the look to the placement.** Phone-shot UGC reads organic in feed; polished studio
  reads as an ad. Don't mix them in one video without a reason.
- **Platform shapes:** Reels, TikTok and Shorts 9:16 (keep faces and text in the middle, out
  of the top 14% and bottom 35%); feed 4:5; Pinterest 2:3; YouTube 16:9.

## When a run fails

- Two identical failures mean the prompt or settings must change. Don't retry a third time.
- Content filter: remove brand names, body terms, public figures; describe the action more neutrally.
- Wrong shape or duration: check `studio model <key>`; some models only take certain ratios
  (Grok text-to-video: 2:3, 1:1, 3:2) or lengths (Veo: 8s, Gemini Omni: 4/6/8/10s).
