# AI API Studio v1.3

## Summary

`v1.3` is the first release under the new `AI API Studio` name. This release expands model coverage, improves video workflows, adds Gemini-powered prompt description tools, and strengthens metadata-driven asset organization for repeatable production work.

## Highlights

### Renamed app

- Project renamed to `AI API Studio`
- Branding updated across the app and repo

### New image model capabilities

Expanded support across Gemini, Fal, and BytePlus, including:

- `Nano Banana`
- `Nano Banana Pro`
- `Nano Banana 2`
- `Seedream 4.5`
- `Seedream 5 Lite`

### New video capabilities

Expanded video workflows across:

- `Kling`
- `Seedance`
- `Wan Video`
- `SeedVR2`

This includes broader support for:

- text-to-video
- image-to-video
- reference-to-video
- video-to-video for supported Kling routes
- video upscale through SeedVR2

### Prompt description tools

Added Gemini-powered prompt description tools for reference media:

- `Describe refs` in image generation
- `Describe image` / `Describe refs` in supported video workflows

Descriptions are:

- generated per reference image
- organized by filename
- appended to the existing prompt instead of replacing it

### Better repeatability

- archived reference images now restore more reliably when reusing prompts and parameters
- saved metadata is richer and more consistent
- image and video workflows preserve more of the actual settings used

### Project metadata workflow

Added production-oriented metadata fields:

- `Client`
- `Project`
- `Shot`
- `Filename`

These are used for:

- searchable metadata
- reusable top-bar entry fields
- structured asset storage under `Image_assets`

New save logic:

- folder path: `Client/Project/Shot`
- filename: `client_project_shot_filename.ext`

## User-facing Improvements

- shared `Assets` browser for saved media
- improved info / prompt popups
- richer asset metadata
- better compare behavior for upscaled media
- better video/main-viewer integration
- improved reference masking and archive handling

## Notes

- some providers may still return lower actual resolution than the requested preset
- the app now records and shows delivered size more accurately where possible
- safety controls are shown only for providers/models that expose them

## Repo

- App name: `AI API Studio`
- Repo: [github.com/pixteur/AI_API_Studio](https://github.com/pixteur/AI_API_Studio)
