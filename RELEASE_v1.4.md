# AI API Studio v1.4

## Summary

`v1.4` expands AI API Studio into a more complete production workspace with a new edit-session flow, broader image and video provider coverage, live cost estimates, and stronger video-generation controls.

## Highlights

### New edit workflow

- Added a dedicated edit workspace with persistent edit sessions
- Added segment-aware edit generation flows and session history storage
- Added support for archived edit-session media under `Image_assets/edit_sessions`

### Expanded image generation

- Added `GPT Image 2` in the image generator
- Added `GPT Image 2 Edit` in both the image and edit workflows
- Added size-aware pricing for `GPT Image 2`
- Added live cost estimates for image and edit generation

### Expanded video generation

- Added `Seedance 2.0` support and cleaned up its family/model labeling
- Upgraded Fal `Wan` support to `Wan 2.7`
- Added Wan-specific extras:
  - driving audio
  - reference videos
  - multi-shot toggle
- Added `LTX Video`, `LTX Video LoRA`, and `LTX 2.3 22B`
- Added Kling 4K Fal routes plus direct Kling 4K-capable options
- Added native `Luma` video provider support
- Added model-aware `Generate audio` toggles where supported

### Better estimates and controls

- Added live cost estimate chips across image, edit, video, and upscale flows
- Improved model-aware visibility for safety and search controls
- Added persistent error banners for failed background jobs until a new job starts
- Improved reusable parameter restore for newer video controls

### UI and workflow improvements

- Improved gallery/history bootstrapping and viewer behavior
- Improved settings coverage with Luma key management
- Continued English cleanup on login/settings surfaces
- Added ignore rules for generated edit-session history

## Notes

- `Generate audio` remains opt-in and off by default
- `Wan` driving audio is separate from generated audio and is shown only for supported Wan 2.7 modes
- Generated edit-session history stays out of git; only the folder scaffold is tracked

## Repo

- App name: `AI API Studio`
- Repo: [github.com/pixteur/AI_API_Studio](https://github.com/pixteur/AI_API_Studio)
