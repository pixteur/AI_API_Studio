# AI API Studio

AI API Studio is a local Flask app for image generation, video generation, and upscale workflows across multiple providers. It combines prompt writing, reference-image management, project metadata, character/talent management, and asset browsing in one desktop-friendly workspace.

## What's in v1.4

- New edit workspace with persistent edit sessions and segment-based generation
- Expanded image support with `GPT Image 2` and `GPT Image 2 Edit`
- Expanded video support with `Seedance 2.0`, `Wan 2.7`, `LTX`, `Kling 4K`, and `Luma`
- Live cost estimates across image, edit, video, and upscale workflows
- Model-aware video controls for safety, audio generation, Wan driving audio, reference videos, and multi-shot
- Improved gallery/history bootstrapping, reusable params, and persistent error handling
- New `edit_sessions` asset storage with ignore rules for generated session history

## Core Features

### Image generation

- Multi-provider image generation
- Reference-image workflows with archive reuse
- Non-destructive reference masking
- Gemini reference description tools
- Prompt reuse from previous generations

![Image generation workflow](docs/images/image-generation-workflow.png)

Image mode combines prompt writing, archived references, reference description, and project metadata in one workspace.

### Video generation

- Text-to-video
- Image-to-video
- Reference-to-video
- Video-to-video for supported Kling routes
- Model-aware video safety controls where supported

![Video generation workflow](docs/images/video-generation-workflow.png)

Video mode supports start images, reference images, model-aware controls, and generated video review in the main viewer.

### Upscale

- Image upscale
- Video upscale with SeedVR2
- Main-viewer driven upscale workflow
- Before/after compare for supported results

![Upscale compare view](docs/images/upscale-compare-view.png)

Upscale mode works from the asset currently loaded in the main viewer and supports before/after comparison for review.

### Project metadata

- Top-bar metadata entry:
  - `Client`
  - `Project`
  - `Shot`
  - `Filename`
- Reusable dropdown suggestions from existing saved folders and metadata
- Saved into searchable metadata
- Used to build asset folder structure and filenames

### Character / Elements management

- Elements asset library
- Favorites / categories
- New Talent workflow
- Gemini vision-assisted image analysis for talent metadata

### Reference masking

- Non-destructive mask editing for archived references
- Reopen and refine masks before rerunning a generation
- Masked references remain linked for repeatable workflows

![Reference mask editor](docs/images/reference-mask-editor.png)

## Supported Providers

### Image

- `Gemini`
- `Fal`
- `BytePlus` for Seedream 4.5

### Video

- `Kling` direct API
- `Fal` for Kling, Seedance, Wan, LTX, and SeedVR2
- `Luma`

## Image Models

Current image families exposed in the app include:

- `Nano Banana`
- `Nano Banana Pro`
- `Nano Banana 2`
- `GPT Image 2`
- `Seedream 4.5`
- `Seedream 5 Lite`

Depending on provider, the app also supports provider-specific routes and variants behind those families.

## Video Models

Current video families exposed in the app include:

- `Kling`
- `Seedance`
- `Wan Video`
- `LTX Video`
- `Luma`
- `SeedVR2`

These include multiple text, image, reference, video-to-video, and upscale-capable routes where supported by the provider.

## Prompt Description Tools

In image and video workflows, you can use Gemini to generate detailed descriptive prompt text from loaded reference images.

The app:

- analyzes each loaded reference
- organizes results by filename
- appends the descriptions to the current prompt box instead of replacing your prompt

## Asset Storage

Generated assets are stored under:

- [E:\Code\comfy_app\AI_API_Studio\Image_assets](E:/Code/comfy_app/AI_API_Studio/Image_assets)

Main folders include:

- [E:\Code\comfy_app\AI_API_Studio\Image_assets\generations](E:/Code/comfy_app/AI_API_Studio/Image_assets/generations)
- [E:\Code\comfy_app\AI_API_Studio\Image_assets\videos](E:/Code/comfy_app/AI_API_Studio/Image_assets/videos)
- [E:\Code\comfy_app\AI_API_Studio\Image_assets\loved](E:/Code/comfy_app/AI_API_Studio/Image_assets/loved)
- [E:\Code\comfy_app\AI_API_Studio\Image_assets\reference_archive](E:/Code/comfy_app/AI_API_Studio/Image_assets/reference_archive)
- [E:\Code\comfy_app\AI_API_Studio\Image_assets\reference_masks](E:/Code/comfy_app/AI_API_Studio/Image_assets/reference_masks)
- [E:\Code\comfy_app\AI_API_Studio\Image_assets\reference_renders](E:/Code/comfy_app/AI_API_Studio/Image_assets/reference_renders)
- [E:\Code\comfy_app\AI_API_Studio\Image_assets\edit_sessions](E:/Code/comfy_app/AI_API_Studio/Image_assets/edit_sessions)

### Folder logic

Assets save inside:

- `Client/Project/Shot`

Filename format:

- `client_project_shot_filename.ext`

If a field is uncategorized, the app uses `uncategorized` for the folder value.

## API Setup

Configure keys in the Settings page:

- `Google Gemini API Key`
- `Fal API Key`
- `Kling API Token`
- `Luma API Key`
- `BytePlus API Key`

The app verifies and stores these from the UI.

## Install and Run

### Windows

Run:

```bat
cd "E:\Code\comfy_app\AI_API_Studio"
python nbs.py
```

Or double-click:

- [E:\Code\comfy_app\AI_API_Studio\start.bat](E:/Code/comfy_app/AI_API_Studio/start.bat)

### macOS / Linux

Run:

```bash
cd "/path/to/AI_API_Studio"
python3 nbs.py
```

Or use:

- [E:\Code\comfy_app\AI_API_Studio\start.sh](E:/Code/comfy_app/AI_API_Studio/start.sh)

### First-run bootstrap

The app auto-installs missing Python packages on first launch:

- `flask`
- `Pillow`
- `requests`
- `fal-client`

## Default Login

- Username: `admin`
- Password: `banana2024`

## Main Pages

- `Generator` for Image, Video, and Upscale workflows
- `Assets` for browsing history, references, loved assets, and videos
- `Workbench`
- `Reports`
- `Settings`
- `Credits`

## Recommended Workflow

1. Enter API keys in `Settings`
2. Set `Client / Project / Shot / Filename` in the top bar
3. Choose `Image`, `Video`, or `Upscale`
4. Add references or source media
5. Generate or upscale
6. Reuse prompts, refs, and settings from saved assets when needed

## Notes

- Some providers may return lower delivered resolution than the requested preset
- The app now records actual delivered size in metadata where possible
- Safety controls are shown only for video models/providers that support them

## Additional Docs

- Install guide: [E:\Code\comfy_app\AI_API_Studio\INSTALL.md](E:/Code/comfy_app/AI_API_Studio/INSTALL.md)
- Release notes: [E:\Code\comfy_app\AI_API_Studio\RELEASE_v1.4.md](E:/Code/comfy_app/AI_API_Studio/RELEASE_v1.4.md)
