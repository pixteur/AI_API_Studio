# AI API Studio 1.3 Installation Guide

## Requirements

- Python `3.11` or `3.12` recommended
- Internet access for provider APIs
- At least one configured API key:
  - Gemini
  - Fal
  - Kling
  - BytePlus

## Windows

### Quick start

```bat
cd "E:\Code\comfy_app\AI_API_Studio"
python nbs.py
```

Or launch:

- [E:\Code\comfy_app\AI_API_Studio\start.bat](E:/Code/comfy_app/AI_API_Studio/start.bat)

### Optional virtual environment

```bat
cd "E:\Code\comfy_app\AI_API_Studio"
python -m venv venv
venv\Scripts\activate
python nbs.py
```

## macOS / Linux

```bash
cd "/path/to/AI_API_Studio"
python3 -m venv venv
source venv/bin/activate
python3 nbs.py
```

Or use:

- [E:\Code\comfy_app\AI_API_Studio\start.sh](E:/Code/comfy_app/AI_API_Studio/start.sh)

## First Launch

On first run, the app auto-installs missing dependencies through its bootstrap step:

- `flask`
- `Pillow`
- `requests`
- `fal-client`

If the auto-install fails, run:

```bash
pip install -r requirements.txt
```

## Login

- Username: `admin`
- Password: `banana2024`

## API Key Setup

Open `Settings` and configure:

- `Google Gemini API Key`
- `Fal API Key`
- `Kling API Token`
- `BytePlus API Key`

## What the App Supports

### Image generation

- Gemini image models
- Fal image routes
- BytePlus Seedream 4.5
- references, masking, archived ref reuse, and prompt description tools

### Video generation

- Kling
- Seedance
- Wan Video
- provider-aware safety controls where supported

### Upscale

- Image upscale
- SeedVR2 video upscale

### Metadata and asset organization

- `Client / Project / Shot / Filename`
- storage under `Image_assets`
- searchable metadata inside the app

## Storage Layout

Main asset root:

- [E:\Code\comfy_app\AI_API_Studio\Image_assets](E:/Code/comfy_app/AI_API_Studio/Image_assets)

New saves follow:

- folder path: `Client/Project/Shot`
- filename: `client_project_shot_filename.ext`

## Troubleshooting

### App does not start

- Confirm Python is installed
- Confirm `python nbs.py` works from the project folder

### API calls fail

- Verify the relevant key in `Settings`
- Confirm provider billing / access is active where required

### UI changes do not appear

Use a hard refresh:

- `Ctrl + F5`

## Related Docs

- Main overview: [E:\Code\comfy_app\AI_API_Studio\README.md](E:/Code/comfy_app/AI_API_Studio/README.md)
- Release notes: [E:\Code\comfy_app\AI_API_Studio\RELEASE_v1.3.md](E:/Code/comfy_app/AI_API_Studio/RELEASE_v1.3.md)
