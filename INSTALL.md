# AI API Studio 1.0 beta — Installation Guide

> AI image generator powered by Google Gemini
> Local web app · Private network only · No cloud account required

---

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.10 | **3.11 or 3.12** |
| RAM | 512 MB | 1 GB |
| Storage | 200 MB | 500 MB+ (for generated images) |
| Network | LAN/Wi-Fi | — |
| Google Gemini API Key | Required | [Get one free →](https://aistudio.google.com/apikey) |

> **Python 3.10+ is required.** Versions 3.8/3.9 are not supported.
> Python 3.13 is untested — prefer 3.11 or 3.12 for best compatibility.

---

## Windows Installation

### 1 — Install Python

1. Go to [python.org/downloads](https://www.python.org/downloads/) and download **Python 3.11.x** (Windows installer, 64-bit)
2. Run the installer. **⚠️ Check "Add python.exe to PATH"** before clicking Install Now
3. Verify in a new Command Prompt:
   ```
   python --version
   ```
   Expected output: `Python 3.11.x`

### 2 — Install Pillow dependency (system-level)

AI API Studio uses Pillow for image processing. On Windows this installs automatically via pip.

### 3 — Set up the app

Open **Command Prompt** (`Win+R` → type `cmd` → Enter), then run:

```bat
cd "C:\path\to\AI API Studio 1.0 beta"

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
```

You should see packages installing. This may take 1–2 minutes on first run.

### 4 — Run the app

With the virtual environment still active:

```bat
python app.py
```

You'll see:
```
 * Running on http://127.0.0.1:5000
```

Open your browser and go to: **http://localhost:5000**

**Default login credentials:**
- Username: `admin`
- Password: `banana2024`

### 5 — Configure your API key

1. Log in → go to **Settings**
2. Paste your Google Gemini API key → click **Verify** → click **Save**

### Windows tip — run with a double-click

Create a file `start.bat` in the app folder with this content:

```bat
@echo off
call venv\Scripts\activate
python app.py
pause
```

Double-click `start.bat` to launch the app next time.

---

## macOS Installation

### 1 — Install Python

**Option A — Official installer (easiest):**
1. Go to [python.org/downloads](https://www.python.org/downloads/) and download **Python 3.11.x** (macOS universal installer)
2. Run the `.pkg` installer
3. Verify in Terminal:
   ```bash
   python3 --version
   ```

**Option B — Homebrew (for developers):**
```bash
brew install python@3.11
```

### 2 — Set up the app

Open **Terminal** and run:

```bash
cd "/path/to/AI API Studio 1.0 beta"

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 3 — Run the app

```bash
python app.py
```

Open your browser and go to: **http://localhost:5000**

**Default login credentials:**
- Username: `admin`
- Password: `banana2024`

### 4 — Configure your API key

1. Log in → go to **Settings**
2. Paste your Google Gemini API key → click **Verify** → click **Save**

### macOS tip — run with a script

Create `start.sh` in the app folder:

```bash
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python app.py
```

Make it executable:
```bash
chmod +x start.sh
```

Then double-click it in Finder (right-click → Open) or run `./start.sh` from Terminal.

---

## Getting a Google Gemini API Key

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with a Google account
3. Click **"Create API key"** → select or create a project
4. Copy the key (starts with `AIza...`)
5. Paste it in AI API Studio → **Settings → API Key → Verify → Save**

**Free tier:** ~500 image generation requests/day with the Nano Banana (Flash) model.
**Billing:** Not required for free tier. Enable for Pro models (gemini-3-pro-image-preview).

---

## Project Structure

```
AI API Studio 1.0 beta/
├── app.py                  ← Flask application (main server)
├── requirements.txt        ← Python dependencies
├── config.json             ← API key + usage stats (auto-generated)
├── talent_vocabulary.json  ← Vocabulary data for prompt builder
├── static/
│   ├── style.css           ← All app styles (dark + light theme)
│   └── favicon.svg         ← Banana favicon
├── templates/
│   ├── index.html          ← Main generator page
│   ├── loved.html          ← Saved favorites gallery
│   ├── settings.html       ← Settings & API stats
│   ├── login.html          ← Login page
│   └── published.html      ← Published images view
├── Elements/
│   └── Model Managment/    ← Talent reference library
│       ├── images/         ← Talent reference photos
│       └── json/           ← Talent profile data
├── generations/            ← Generated images (auto-created)
├── loved/                  ← Saved/loved images (auto-created)
└── published/              ← Published images (auto-created)
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'flask'`**
→ The virtual environment is not active. Run `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Mac) before `python app.py`.

**`ModuleNotFoundError: No module named 'PIL'`**
→ Run: `pip install Pillow`

**Port 5000 already in use**
→ Another app is using port 5000. Edit `app.py` last line: change `port=5000` to `port=5001` (or any free port), then access `http://localhost:5001`.

**On macOS — "App can't be opened because it is from an unidentified developer"**
→ This applies to `.app` bundles, not Python scripts. If you see this, right-click the file → Open.

**API key shows "Invalid"**
→ Make sure billing is enabled on your Google Cloud project, or try regenerating the key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

---

## Changing the Login Password

Open `app.py` in a text editor and find:

```python
USERS = {
    "admin": "banana2024"
}
```

Change the password to anything you like, save the file, and restart the app.

---

*AI API Studio 1.0 beta — Built with Flask + Google Gemini*
