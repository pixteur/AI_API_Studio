# AI API Studio

AI API Studio is a local Flask app for image generation, video generation, and upscale workflows across multiple providers. It combines prompt writing, reference-image management, project metadata, character/talent management, and asset browsing in one desktop-friendly workspace.

## What's in v1.3

- App renamed to `AI API Studio`
- Expanded image model support across Gemini, Fal, and BytePlus
- Expanded video model support across Kling, Seedance, Wan, and SeedVR2
- Gemini-powered `Describe refs` tools for image and video reference images
- Unified asset metadata with `Client / Project / Shot / Filename`
- Improved archived reference reuse for repeatable generations
- Shared `Assets` browser for images, references, loved assets, and videos

## Core Features

### Image generation

- Multi-provider image generation
- Reference-image workflows with archive reuse
- Non-destructive reference masking
- Gemini reference description tools
- Prompt reuse from previous generations

### Video generation

- Text-to-video
- Image-to-video
- Reference-to-video
- Video-to-video for supported Kling routes
- Model-aware video safety controls where supported

### Upscale

- Image upscale
- Video upscale with SeedVR2
- Main-viewer driven upscale workflow
- Before/after compare for supported results

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

## Supported Providers

### Image

- `Gemini`
- `Fal`
- `BytePlus` for Seedream 4.5

### Video

- `Kling` direct API
- `Fal` for Kling, Seedance, Wan, and SeedVR2

## Image Models

Current image families exposed in the app include:

- `Nano Banana`
- `Nano Banana Pro`
- `Nano Banana 2`
- `Seedream 4.5`
- `Seedream 5 Lite`

Depending on provider, the app also supports provider-specific routes and variants behind those families.

## Video Models

Current video families exposed in the app include:

- `Kling`
- `Seedance`
- `Wan Video`
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
- Release notes: [E:\Code\comfy_app\AI_API_Studio\RELEASE_v1.3.md](E:/Code/comfy_app/AI_API_Studio/RELEASE_v1.3.md)
