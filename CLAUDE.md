# AI API Studio — CLAUDE.md
> Developer reference · v1.0 beta · Last updated March 2026

This file is the single source of truth for anyone opening this project for the first time — AI agent or human developer. It covers architecture, all Flask routes, CSS system, theme engine, JS conventions, and a full changelog of v1.0 beta work.

---

## Quick Start

```bash
# Any OS — Python 3.11 required
python nbs.py
# → auto-installs Flask, Pillow, Requests on first run
# → opens at http://localhost:5000
# → login: admin / banana2024
```

Windows shortcut: double-click `start.bat`
macOS shortcut: double-click `start.sh`

---

## Project Structure

```
nano-banana-app/
├── nbs.py                  ← Main entry point (Flask + bootstrap auto-install)
├── app.py                  ← Compatibility shim → calls nbs.py
├── start.bat               ← Windows launcher (double-click)
├── start.sh                ← macOS/Linux launcher (double-click)
├── requirements.txt        ← flask>=3.0, requests>=2.31, Pillow
├── config.json             ← Runtime: API key + usage stats. DO NOT COMMIT.
├── talent_vocabulary.json  ← Vocabulary data for the Prompt Wizard
├── CLAUDE.md               ← This file
├── README.md               ← End-user quick start
│
├── static/
│   ├── style.css           ← All styles (~3800 lines). Dark + Light theme.
│   └── favicon.svg         ← Banana emoji SVG favicon
│
├── templates/
│   ├── login.html          ← Login page (themed, standalone)
│   ├── index.html          ← Main generator (sidebar, gallery, lightbox, modals)
│   ├── loved.html          ← Saved favorites gallery + lightbox
│   ├── settings.html       ← API key, stats, appearance (theme picker)
│   ├── published.html      ← Published images view
│   └── credits.html        ← About, installation guide, author, open source
│
├── Elements/
│   └── Model Managment/    ← Talent reference library
│       ├── images/         ← Reference photos (jpg)
│       └── json/           ← Talent profiles (JSON, one per talent)
│
├── generations/            ← Auto-created. Generated images (date-bucketed)
├── loved/                  ← Auto-created. Saved/loved images (date-bucketed)
└── published/              ← Legacy folder (migrated to loved/ on startup)
```

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 · Flask 3.x |
| Frontend | Vanilla JS · CSS Custom Properties · No build step |
| AI API | Google Gemini (REST, `generativelanguage.googleapis.com/v1beta`) |
| Image processing | Pillow (resize, format conversion) |
| Storage | Local filesystem (flat JSON + JPEG/PNG files) |
| Auth | Flask session + hardcoded `USERS` dict in `nbs.py` |

---

## AI Models

| Codename | Model ID | Resolutions | Aspect Ratios | Thinking | Ref images |
|---|---|---|---|---|---|
| Nano Banana | `gemini-2.5-flash-image` | 1K | Standard 10 | No | 0 |
| Nano Banana Pro | `gemini-3-pro-image-preview` | 1K · 2K · 4K | Standard 10 | No | up to 8 |
| Nano Banana 2 | `gemini-3.1-flash-image-preview` | 0.5K · 1K · 4K | Standard 10 + 4 extra | Yes | up to 14 |

**Standard aspect ratios (all models):** `21:9` `16:9` `4:3` `3:2` `1:1` `9:16` `3:4` `2:3` `5:4` `4:5`
**Extra (Nano Banana 2 only):** `4:1` `1:4` `8:1` `1:8`

### Thinking levels (Nano Banana 2 only)

| Level | `thinkingBudget` |
|---|---|
| Minimal | `0` |
| High | `8192` |
| Dynamic | `-1` (model decides) |

---

## Gemini API — Request Format

```json
{
  "contents": [
    { "role": "user", "parts": [
      { "inline_data": { "mime_type": "image/jpeg", "data": "<base64>" } },
      { "text": "<prompt>" }
    ]}
  ],
  "generationConfig": {
    "responseModalities": ["TEXT", "IMAGE"],
    "imageConfig": {
      "aspectRatio": "16:9",
      "imageSize": "2K",
      "numberOfImages": 1
    },
    "temperature": 1.0,
    "topP": 0.95,
    "maxOutputTokens": 65536,
    "thinkingConfig": { "thinkingBudget": 0 }
  },
  "tools": [{ "googleSearch": {} }]
}
```

Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}`

Images in response are base64-encoded PNG inside `response.candidates[0].content.parts[].inline_data.data`.

---

## Pricing (estimated, March 2026)

| Model | 0.5K | 1K | 2K | 4K |
|---|---|---|---|---|
| Nano Banana | — | $0.039 | — | — |
| Nano Banana Pro | — | $0.134 | $0.134 | $0.240 |
| Nano Banana 2 | $0.020 | $0.045 | — | $0.090 |

Free tier: ~500 req/day for Nano Banana and Nano Banana 2 at 1K. Pro and 4K require billing.

---

## Flask Routes — Full Reference

### Pages

| Method | Path | Template | Auth | Description |
|---|---|---|---|---|
| GET | `/` | — | No | Redirect → `/login` or `/index` |
| GET | `/login` | `login.html` | No | Login form |
| POST | `/login` | — | No | Authenticate, set session |
| GET | `/logout` | — | Yes | Clear session, redirect login |
| GET | `/index` | `index.html` | Yes | Main generator |
| GET | `/settings` | `settings.html` | Yes | API config + stats |
| GET | `/loved` | `loved.html` | Yes | Saved favorites gallery |
| GET | `/loved/<date>/<filename>` | — | Yes | Serve a loved image file |
| GET | `/credits` | `credits.html` | Yes | About, install guide, author |

### API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/generate` | Proxy to Gemini. Accepts prompt, model, AR, resolution, ref images, tools, thinking level. Saves result to `generations/`. |
| GET | `/api/generations` | List all generated images (grouped by date). |
| DELETE | `/api/generations/<date>/<filename>` | Delete a generated image. |
| POST | `/api/publish` | Save a generated image to `loved/`. |
| GET | `/api/loved-list` | List all loved images (grouped by date). |
| DELETE | `/api/loved/<date>/<filename>` | Delete a loved image + its JSON sidecar. |
| POST | `/api/save-config` | Save API key to `config.json`. |
| POST | `/api/verify-key` | Test API key with a minimal Gemini call. |
| GET | `/api/stats` | Return usage stats from `config.json`. |
| POST | `/api/reset-stats` | Zero out all stats in `config.json`. |
| GET | `/api/models-info` | Return model capabilities map (resolutions, AR, thinking, ref images). |
| GET | `/api/elements` | List all Elements entries grouped by category. |
| POST | `/api/elements/save-talent` | Create or update a talent JSON profile. |
| POST | `/api/elements/toggle-favorite` | Toggle is_favorite on a talent entry. |
| POST | `/api/elements/analyze-image` | Run Gemini vision analysis on a talent reference photo. |
| POST | `/api/elements/migrate-catalog` | Batch re-analyze and normalize all talent JSONs. |
| GET | `/elements/<path>` | Serve any file from the Elements directory. |

---

## CSS Architecture (`static/style.css` ~3800 lines)

### Theme System

All colors are CSS custom properties on `:root`. A second block `[data-theme="light"]` overrides them.

```css
:root {
  --bg:       #0d0d0d;
  --surface:  #1a1a1a;
  --surface3: #2a2a2a;
  --accent:   #c8ff00;   /* lime-green */
  --acc-fg:   #0d0d0d;   /* text on accent buttons (dark on lime) */
  --text:     #f0f0f0;
  --text2:    #999;
  --border:   #2a2a2a;
  --border2:  #3a3a3a;
}

[data-theme="light"] {
  --bg:       #fafafa;
  --surface:  #ffffff;
  --accent:   #ff5500;   /* saturated orange */
  --acc-fg:   #ffffff;   /* text on accent buttons (white on orange) */
  --text:     #111111;
  /* … etc */
}
```

**FOUC prevention:** Every page `<head>` has this inline script *before* the stylesheet link:
```html
<script>(function(){if(localStorage.getItem('nb-theme')==='light')document.documentElement.setAttribute('data-theme','light');}());</script>
```

**Theme persistence:** `localStorage` key `nb-theme`. Value `'light'` or absent (dark).

**Toggle functions** in every page's `<script>`:
- `toggleTheme()` — flips theme, updates localStorage
- `updateThemeBtn()` — syncs ☀️/🌙 button icon

### Key CSS Sections (by line range)

| Section | What it covers |
|---|---|
| `:root` variables | All design tokens |
| `.navbar` | Top navigation bar, logo, links, version badge |
| `.sidebar` | Left control panel (desktop collapsible) |
| `.gallery-grid` | CSS columns masonry layout for generated images |
| `.img-card` | Image card + `.img-actions` overlay buttons |
| `.lightbox` | Full-screen image viewer + action bar |
| `.modal-*` | Picker, Elements, Wizard modals |
| `.settings-*` | Settings page cards and form elements |
| `.loved-masonry` | Loved page grid (reuses `.img-card` + CSS columns) |
| `.credits-*` | Credits page layout (hero, cards, install boxes) |
| `.sidebar-collapsed` | Collapsed sidebar state (42px wide, hides `.ctrl-group`) |
| `[data-theme="light"]` | All light theme overrides (appended at end of file) |

### Collapsed Sidebar Rule

```css
.app-layout.sidebar-collapsed .sidebar .ctrl-group,
.app-layout.sidebar-collapsed .sidebar .sidebar-close-btn {
  display: none !important;  /* !important overrides JS inline style */
}
```

The `!important` is required because JS sets `thinkingGroup.style.display = 'block'` as an inline style when a model with thinking is selected. Without `!important`, the group would remain visible when the sidebar collapses.

---

## JavaScript Conventions (index.html)

### SVG Icon Constants

All action icons are inline SVGs defined as JS string constants before `makeActionBtn()`:

```js
const SVG_HEART_EMPTY = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61…"/></svg>`;
const SVG_HEART_FULL  = `<svg … fill="currentColor" stroke="none">…</svg>`;
const SVG_DOWNLOAD    = `<svg …>…</svg>`;
const SVG_REUSE       = `<svg …>…</svg>`;
const SVG_INFO        = `<svg …>…</svg>`;
const SVG_TRASH       = `<svg …>…</svg>`;
const SVG_X           = `<svg …>…</svg>`;
```

All icons use `stroke="currentColor"` so they inherit button color automatically, adapting to both dark and light themes.

### Key Functions

| Function | File | Description |
|---|---|---|
| `buildImgCard(img)` | index.html | Creates a gallery card DOM element with action buttons |
| `publishImage(btn, date, file)` | index.html | Saves image to loved/ via `/api/publish`, shows spinner |
| `openLightbox(src, date, file, prompt, model)` | index.html | Opens full-screen lightbox |
| `toggleTheme()` | all pages | Flips dark/light, updates localStorage |
| `updateThemeBtn()` | all pages | Syncs nav button icon |
| `setTheme(t)` | settings.html | Sets theme explicitly from theme picker cards |
| `syncModelUI(info)` | index.html | Updates all sidebar controls when model changes |
| `toggleSidebar()` | index.html | Mobile sidebar open/close |
| `toggleDesktopSidebar()` | index.html | Desktop sidebar collapse/expand |

---

## Elements System

Each talent entry is a JSON file in `Elements/Model Managment/json/`:

```json
{
  "id": "model_01",
  "name": "Zuri Aden",
  "gender": "female",
  "ethnicity": "african",
  "age_group": "young_adult",
  "skin_tone": "deep",
  "hair_color": "black",
  "hair_style": "braids",
  "eye_color": "hazel",
  "body_type": "slim",
  "description": "…",
  "tags": ["editorial", "beauty"],
  "profile": {
    "recommended_usage": ["editorial photography", "beauty close-up"],
    "skills": ["expressive eye contact"],
    "…": "…"
  },
  "is_favorite": false,
  "images": [
    { "filename": "model_01.jpg", "path": "images/model_01.jpg", "is_primary": true, "analyzed": false }
  ],
  "created_at": "2026-03-18T14:40:38.357800",
  "updated_at": "2026-03-18T14:40:38.357800"
}
```

Reference images are served via `/elements/<path>` and sent to Gemini as base64 inline_data when a talent is added to the prompt.

---

## Authentication

Simple session-based login. Credentials are hardcoded in `nbs.py`:

```python
USERS = {
    "admin": "banana2024"
}
```

Change the password here. Multi-user support would require extending this dict.
`@login_required` decorator is applied to all non-public routes.

---

## Bootstrap Auto-Install (nbs.py)

On startup, before any third-party imports, `_bootstrap()` runs:

```python
def _bootstrap():
    deps = [
        ("flask",    "flask>=3.0.0"),
        ("PIL",      "Pillow"),
        ("requests", "requests>=2.31.0"),
    ]
    missing = [(mod, pkg) for mod, pkg in deps if importlib.util.find_spec(mod) is None]
    if not missing:
        return
    # pip install missing packages, then continue
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + pkgs)
```

This uses only stdlib (`sys`, `subprocess`, `importlib.util`, `os`) so it works on a clean Python install with no dependencies at all.

---

## v1.0 Beta Changelog

All work completed in the March 2026 session:

### UI & Design
- **Dual theme system** — Dark (lime-green `#c8ff00`) and Light (orange `#ff5500`) switchable from navbar and Settings > Appearance
- **FOUC prevention** — inline script in every `<head>` applies saved theme before CSS renders
- **Lucide-style SVG icons** — replaced all emoji icons across the app (heart, download, reuse, info, trash, X, chevrons) with clean 16×16 stroke SVGs using `stroke="currentColor"`
- **Banana favicon** — `static/favicon.svg` emoji SVG linked in all pages
- **Version badge** — "1.0 beta" chip next to logo in every navbar
- **Masonry grid on Loved page** — replaced fixed-ratio `pub-card` with `loved-masonry` (CSS columns) + reused `.img-card` classes for visual consistency with home gallery
- **Sidebar collapse fix** — added `!important` to `.ctrl-group { display: none }` rule so Thinking Level form doesn't bleed through when sidebar is minimized

### New Pages & Features
- **Credits page** (`/credits`) — About the project, installation guide (Windows/macOS), How to Use (5 steps), License & Open Source, Author (Patreon + LinkedIn links), Tech Stack
- **Credits link** added to navbar on all pages

### Launch & Distribution
- **`nbs.py`** — renamed from `app.py`, with bootstrap auto-installer prepended
- **`app.py`** — kept as compatibility shim (`runpy.run_path('nbs.py')`)
- **`start.bat`** — Windows launcher with Python check and error pause
- **`start.sh`** — macOS/Linux launcher, made executable
- **Clean distribution folder** — `AI API Studio 1.0 beta/` with 5 curated talent entries, empty data dirs, clean `config.json`, and `INSTALL.md`

### Template Updates
All 5 HTML templates (`index`, `loved`, `settings`, `published`, `login`) updated with:
- FOUC prevention script
- Favicon link
- `nav-version` badge
- Theme toggle button in navbar
- Light theme CSS variable overrides

---

## Default Login Credentials

- **Username:** `admin`
- **Password:** `banana2024`

Change in `nbs.py` → `USERS` dict.

---

## Config File (`config.json`)

Auto-generated at first run. Structure:

```json
{
  "api_key": "AIza…",
  "stats": {
    "total_requests": 0,
    "total_images": 0,
    "total_cost_usd": 0.0,
    "requests_log": [],
    "vision_calls": 0,
    "vision_cost_usd": 0.0,
    "vision_log": []
  }
}
```

**Never commit `config.json`** — it contains the API key.

---

## Development Notes

- All images are stored as JPEG in date-bucketed subdirectories (`generations/YYYY-MM-DD/`)
- Loved images have a JSON sidecar (`filename.json`) with prompt, model, date metadata
- `published/` is a legacy folder; on startup, contents are migrated to `loved/` if it exists
- SynthID invisible watermark is added by Google to all generated images
- The Elements `images/` subfolder and root-level image paths (`mei_lin_001.jpg`) are both supported — the JSON `path` field is relative to the talent's folder
- CSS brace count should remain balanced — verify with `grep -o '{' style.css | wc -l` vs `grep -o '}' style.css | wc -l`
- `talent_vocabulary.json` powers the Prompt Wizard dropdowns — extend it to add new vocabulary categories

---

## Getting a Gemini API Key

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with Google, click **Create API key**
3. Copy the key (starts with `AIza…`)
4. In the app: Settings → paste key → Verify → Save
