#!/usr/bin/env python3
"""
Nano Banana Studio (nbs.py)
AI image generator powered by Google Gemini
Run: python nbs.py
"""

# ---------------------------------------------------------------------------
# Bootstrap â€” auto-install missing dependencies on first run
# ---------------------------------------------------------------------------
import sys
import subprocess
import importlib.util
import os as _os

def _bootstrap():
    deps = [
        ("flask",    "flask>=3.0.0"),
        ("PIL",      "Pillow"),
        ("requests", "requests>=2.31.0"),
    ]
    missing = [(mod, pkg) for mod, pkg in deps if importlib.util.find_spec(mod) is None]
    if not missing:
        return
    pkgs = [pkg for _, pkg in missing]
    print("\n" + "="*52)
    print(f"  Nano Banana Studio {APP_VERSION} - First-run Setup")
    print("="*52)
    print(f"  Missing packages: {', '.join(pkgs)}")
    print("  Installing automatically... (one-time only)\n")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + pkgs
        )
        print("\n  Done! Starting Nano Banana Studio...\n")
    except subprocess.CalledProcessError as e:
        print(f"\n  Install failed: {e}")
        print("  Try manually: pip install -r requirements.txt")
        sys.exit(1)

_bootstrap()

# ---------------------------------------------------------------------------
# End bootstrap â€” normal imports follow
# ---------------------------------------------------------------------------
import base64
import glob
import io
import json
import os
import random
import re
import shutil
import sqlite3
import unicodedata
import requests
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, send_from_directory)
from PIL import Image, ImageOps

app = Flask(__name__)
app.secret_key = "nb-studio-secret-2024-change-me"

APP_VERSION = "1.1 beta"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Credenziali login
# ---------------------------------------------------------------------------
USERS = {
    "admin": "banana2024"
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR         = os.path.dirname(__file__)
CONFIG_FILE      = os.path.join(BASE_DIR, "config.json")
LOVED_DIR        = os.path.join(BASE_DIR, "loved")
GENERATIONS_DIR  = os.path.join(BASE_DIR, "generations")
ELEMENTS_DIR     = os.path.join(BASE_DIR, "Elements")
STUDIO_DB_FILE   = os.path.join(BASE_DIR, "studio.db")
REFERENCE_ARCHIVE_DIR = os.path.join(BASE_DIR, "reference_archive")

# Mapping folder â†’ display name and icon for Elements
ELEMENTS_CATEGORIES = {
    "Model Managment": {"label": "Characters", "icon": "ðŸ§‘", "slug": "characters"},
    "Locations":       {"label": "Locations",  "icon": "ðŸŒ", "slug": "locations"},
    "Props":           {"label": "Props",       "icon": "ðŸŽ¨", "slug": "props"},
}

DEFAULT_CONFIG = {
    "api_key": "",
    "seedream_api_key": "",
    "fal_api_key": "",
    "byteplus_api_key": "",
    "stats": {
        "total_requests":   0,
        "total_images":     0,
        "total_cost_usd":   0.0,
        "requests_log":     [],
        # Vision / Analisi (Gemini text-only calls)
        "vision_calls":     0,
        "vision_cost_usd":  0.0,
        "vision_log":       [],
    }
}

# ---------------------------------------------------------------------------
# Price per image in USD (verified March 2026)
# Gemini source: ai.google.dev/gemini-api/docs/pricing
# fal sources: fal.ai model pages
# BytePlus source: docs.byteplus.com ModelArk pricing
# ---------------------------------------------------------------------------
PRICING = {
    "gemini-2.5-flash-image": {
        "0.5K": 0.0,   "1K": 0.039, "2K": 0.039, "4K": 0.039
    },
    "gemini-3-pro-image-preview": {
        "0.5K": 0.0,   "1K": 0.134, "2K": 0.134, "4K": 0.240
    },
    "gemini-3.1-flash-image-preview": {
        "0.5K": 0.045, "1K": 0.067, "2K": 0.101, "4K": 0.151
    },
    "fal-ai/gemini-25-flash-image": {
        "0.5K": 0.0,   "1K": 0.039, "2K": 0.039, "4K": 0.039
    },
    "fal-ai/nano-banana-pro": {
        "0.5K": 0.0,   "1K": 0.150, "2K": 0.150, "4K": 0.300
    },
    "fal-ai/nano-banana-2": {
        "0.5K": 0.060, "1K": 0.080, "2K": 0.120, "4K": 0.160
    },
    "fal-ai/bytedance/seedream/v4.5/text-to-image": {
        "0.5K": 0.0, "1K": 0.0, "2K": 0.040, "4K": 0.040
    },
    "seedream-4-5-251128": {
        "0.5K": 0.0, "1K": 0.0, "2K": 0.040, "4K": 0.040
    },
    "fal-ai/bytedance/seedream/v5/lite/text-to-image": {
        "0.5K": 0.0, "1K": 0.0, "2K": 0.035, "4K": 0.035
    },
}

# ---------------------------------------------------------------------------
# Models - includes max reference images supported
# ---------------------------------------------------------------------------
ASPECT_RATIOS_BASE      = ["1:1","16:9","9:16","4:3","3:4","3:2","2:3","21:9","5:4","4:5"]
ASPECT_RATIOS_NB2_EXTRA = ["4:1","1:4","8:1","1:8"]
ASPECT_RATIOS_FAL       = ["1:1","16:9","9:16","4:3","3:4","3:2","2:3","21:9","5:4","4:5"]
ASPECT_RATIOS_BYTEPLUS  = ["1:1","16:9","9:16","4:3","3:4"]

PROVIDER_LABELS = {
    "gemini": "Gemini",
    "fal": "Fal",
    "byteplus": "BytePlus",
}

GEMINI_BASE_URL                 = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FAL_BASE_URL                    = "https://fal.run"
BYTEPLUS_BASE_URL               = "https://ark.ap-southeast.bytepluses.com/api/v3/images/generations"
FAL_NANO_BANANA_TEXT_ID         = "fal-ai/gemini-25-flash-image"
FAL_NANO_BANANA_EDIT_ID         = "fal-ai/gemini-25-flash-image/edit"
FAL_NANO_BANANA_PRO_TEXT_ID     = "fal-ai/nano-banana-pro"
FAL_NANO_BANANA_PRO_EDIT_ID     = "fal-ai/nano-banana-pro/edit"
FAL_NANO_BANANA_2_TEXT_ID       = "fal-ai/nano-banana-2"
FAL_NANO_BANANA_2_EDIT_ID       = "fal-ai/nano-banana-2/edit"
FAL_SEEDREAM_45_TEXT_ID         = "fal-ai/bytedance/seedream/v4.5/text-to-image"
FAL_SEEDREAM_45_EDIT_ID         = "fal-ai/bytedance/seedream/v4.5/edit"
FAL_SEEDREAM_5_TEXT_ID          = "fal-ai/bytedance/seedream/v5/lite/text-to-image"
FAL_SEEDREAM_5_EDIT_ID          = "fal-ai/bytedance/seedream/v5/lite/edit"
BYTEPLUS_SEEDREAM_45_MODEL_ID   = "seedream-4-5-251128"

MODELS_INFO = {
    "gemini-2.5-flash-image": {
        "provider":       "gemini",
        "provider_label": "Gemini",
        "family":         "nano-banana",
        "label":          "Nano Banana",
        "resolutions":    ["1K"],
        "thinking":       False,
        "aspect_ratios":  ASPECT_RATIOS_BASE,
        "max_images":     4,
        "max_ref_images": 0,
        "ref_note":       "Gemini API mode - does not support reference images"
    },
    "fal-ai/gemini-25-flash-image": {
        "provider":       "fal",
        "provider_label": "Fal",
        "family":         "nano-banana",
        "label":          "Nano Banana",
        "resolutions":    ["1K"],
        "thinking":       False,
        "aspect_ratios":  ASPECT_RATIOS_FAL,
        "max_images":     4,
        "max_ref_images": 14,
        "ref_note":       "Fal API mode - up to 14 reference images"
    },
    "gemini-3-pro-image-preview": {
        "provider":       "gemini",
        "provider_label": "Gemini",
        "family":         "nano-banana-pro",
        "label":          "Nano Banana Pro",
        "resolutions":    ["1K","2K","4K"],
        "thinking":       False,
        "aspect_ratios":  ASPECT_RATIOS_BASE,
        "max_images":     4,
        "max_ref_images": 8,
        "ref_note":       "Gemini API mode - up to 8 reference images"
    },
    "fal-ai/nano-banana-pro": {
        "provider":       "fal",
        "provider_label": "Fal",
        "family":         "nano-banana-pro",
        "label":          "Nano Banana Pro",
        "resolutions":    ["1K","2K","4K"],
        "thinking":       False,
        "aspect_ratios":  ASPECT_RATIOS_FAL,
        "max_images":     4,
        "max_ref_images": 14,
        "ref_note":       "Fal API mode - up to 14 reference images"
    },
    "gemini-3.1-flash-image-preview": {
        "provider":       "gemini",
        "provider_label": "Gemini",
        "family":         "nano-banana-2",
        "label":          "Nano Banana 2",
        "resolutions":    ["0.5K","1K","2K","4K"],
        "thinking":       True,
        "aspect_ratios":  ASPECT_RATIOS_BASE + ASPECT_RATIOS_NB2_EXTRA,
        "max_images":     4,
        "max_ref_images": 14,
        "ref_note":       "Gemini API mode - up to 14 reference images"
    },
    "fal-ai/nano-banana-2": {
        "provider":       "fal",
        "provider_label": "Fal",
        "family":         "nano-banana-2",
        "label":          "Nano Banana 2",
        "resolutions":    ["0.5K","1K","2K","4K"],
        "thinking":       False,
        "aspect_ratios":  ASPECT_RATIOS_FAL,
        "max_images":     4,
        "max_ref_images": 14,
        "ref_note":       "Fal API mode - up to 14 reference images"
    },
    "fal-ai/bytedance/seedream/v4.5/text-to-image": {
        "provider":       "fal",
        "provider_label": "Fal",
        "family":         "seedream-45",
        "label":          "Seedream 4.5",
        "resolutions":    ["2K","4K"],
        "thinking":       False,
        "aspect_ratios":  ASPECT_RATIOS_FAL,
        "max_images":     4,
        "max_ref_images": 10,
        "ref_note":       "Fal API mode - up to 10 reference images"
    },
    "seedream-4-5-251128": {
        "provider":       "byteplus",
        "provider_label": "BytePlus",
        "family":         "seedream-45",
        "label":          "Seedream 4.5",
        "resolutions":    ["2K","4K"],
        "thinking":       False,
        "aspect_ratios":  ASPECT_RATIOS_BYTEPLUS,
        "max_images":     4,
        "max_ref_images": 10,
        "ref_note":       "BytePlus API mode - up to 10 reference images"
    },
    "fal-ai/bytedance/seedream/v5/lite/text-to-image": {
        "provider":       "fal",
        "provider_label": "Fal",
        "family":         "seedream-5-lite",
        "label":          "Seedream 5 Lite",
        "resolutions":    ["2K","4K"],
        "thinking":       False,
        "aspect_ratios":  ASPECT_RATIOS_FAL,
        "max_images":     4,
        "max_ref_images": 10,
        "ref_note":       "Fal API mode - up to 10 reference images"
    }
}

MODEL_FAMILIES = {
    "nano-banana-2": {
        "label": "Nano Banana 2",
        "badge": "NB2",
        "default_provider": "gemini",
        "provider_order": ["gemini", "fal"],
        "providers": {
            "gemini": "gemini-3.1-flash-image-preview",
            "fal": FAL_NANO_BANANA_2_TEXT_ID,
        },
    },
    "seedream-45": {
        "label": "Seedream 4.5",
        "badge": "SD45",
        "default_provider": "fal",
        "provider_order": ["fal", "byteplus"],
        "providers": {
            "fal": FAL_SEEDREAM_45_TEXT_ID,
            "byteplus": BYTEPLUS_SEEDREAM_45_MODEL_ID,
        },
    },
    "seedream-5-lite": {
        "label": "Seedream 5 Lite",
        "badge": "SD5",
        "default_provider": "fal",
        "provider_order": ["fal"],
        "providers": {
            "fal": FAL_SEEDREAM_5_TEXT_ID,
        },
    },
    "nano-banana-pro": {
        "label": "Nano Banana Pro",
        "badge": "PRO",
        "default_provider": "gemini",
        "provider_order": ["gemini", "fal"],
        "providers": {
            "gemini": "gemini-3-pro-image-preview",
            "fal": FAL_NANO_BANANA_PRO_TEXT_ID,
        },
    },
    "nano-banana": {
        "label": "Nano Banana",
        "badge": "NB",
        "default_provider": "gemini",
        "provider_order": ["gemini", "fal"],
        "providers": {
            "gemini": "gemini-2.5-flash-image",
            "fal": FAL_NANO_BANANA_TEXT_ID,
        },
    },
}


def resolve_model_selection(requested_model: str = "", requested_family: str = "", requested_provider: str = "") -> tuple[str, str, str, dict]:
    model_id = str(requested_model or "").strip()
    family_key = str(requested_family or "").strip()
    provider_key = str(requested_provider or "").strip().lower()

    if family_key in MODEL_FAMILIES:
        family_info = MODEL_FAMILIES[family_key]
        available = family_info.get("providers", {})
        if provider_key not in available:
            provider_key = family_info.get("default_provider", "") or next(iter(available.keys()), "")
        model_id = available.get(provider_key, model_id)
        model_info = MODELS_INFO.get(model_id)
        if model_info:
            return model_id, family_key, provider_key, model_info

    if model_id in MODELS_INFO:
        model_info = MODELS_INFO[model_id]
        return model_id, model_info.get("family", family_key or "nano-banana-2"), model_info.get("provider", provider_key or "gemini"), model_info

    fallback_family = "nano-banana-2"
    fallback_provider = MODEL_FAMILIES[fallback_family]["default_provider"]
    fallback_model = MODEL_FAMILIES[fallback_family]["providers"][fallback_provider]
    return fallback_model, fallback_family, fallback_provider, MODELS_INFO[fallback_model]


def normalize_generation_request(body: dict | None) -> dict:
    payload = dict(body or {})
    model_id, family_key, provider_key, model_info = resolve_model_selection(
        payload.get("model", ""),
        payload.get("modelFamily", ""),
        payload.get("provider", ""),
    )
    payload["model"] = model_id
    payload["modelFamily"] = family_key
    payload["provider"] = provider_key
    payload["modelLabel"] = model_info.get("label", model_id)
    payload["providerLabel"] = model_info.get("provider_label", PROVIDER_LABELS.get(provider_key, provider_key.title()))
    return payload

# ---------------------------------------------------------------------------
# Vocabolario canonico â€” caricato da talent_vocabulary.json se presente
# Used to constrain Gemini to return normalized values only
# ---------------------------------------------------------------------------
_VOCAB_PATH = os.path.join(BASE_DIR, "talent_vocabulary.json")
if os.path.exists(_VOCAB_PATH):
    with open(_VOCAB_PATH, encoding="utf-8") as _vf:
        TALENT_VOCABULARY = json.load(_vf)
else:
    # Minimal inline fallback (refresh by running normalize_talent_json.py)
    TALENT_VOCABULARY = {
        "gender":     ["female","male","non-binary","androgynous"],
        "ethnicity":  ["african","afro_caribbean","east_asian","south_asian","southeast_asian",
                       "middle_eastern","hispanic_latino","caucasian","mediterranean",
                       "eastern_european","northern_european","mixed","other"],
        "age_group":  ["teen","young_adult","adult","mature","senior"],
        "skin_tone":  ["very_fair","fair","fair_warm","light","light_olive","medium",
                       "medium_warm","medium_olive","tan","brown","deep_brown","deep"],
        "hair_color": ["black","dark_brown","medium_brown","light_brown","auburn","red",
                       "copper","blonde","dark_blonde","platinum_blonde","gray","white",
                       "silver","salt_and_pepper","bald","colored"],
        "hair_style": ["bald","buzz_cut","short_crop","short_pixie","short_bob","short_curly",
                       "short_afro","fade","medium_straight","medium_wavy","medium_curly",
                       "bob","lob","long_straight","long_wavy","long_curly","braids",
                       "cornrows","afro","bun","ponytail","updo","tied_back","fantasy_styled"],
        "eye_color":  ["dark_brown","brown","light_brown","hazel","green","gray","blue",
                       "light_blue","amber","black","other"],
        "body_type":  ["slim","slender","athletic","lean_athletic","fit","curvy",
                       "average","muscular","full","plus_size"],
    }


def _build_vocab_prompt_block() -> str:
    """Costruisce il blocco testo del vocabolario da inserire nel prompt Gemini."""
    lines = ["MANDATORY ALLOWED VALUES â€” use ONLY these exact strings, no variations:"]
    for field, values in TALENT_VOCABULARY.items():
        lines.append(f'  "{field}": {" | ".join(values)}')
    return "\n".join(lines)


# Model for talent visual analysis (text output only, not image generation)
# gemini-3-flash-preview = Gemini 3 Flash (preview) - more capable than lite, great for structured JSON
# gemini-3.1-flash-lite-preview = lite version (faster/cheaper but less precise)
TALENT_ANALYSIS_MODEL = "gemini-3-flash-preview"

# ---------------------------------------------------------------------------
# Vision / analysis pricing (per token, not per image)
# Fonte: Google AI pricing Marzo 2026
# ---------------------------------------------------------------------------
VISION_MODELS_INFO = {
    "gemini-3-flash-preview": {
        "label":         "Gemini 3 Flash",
        "badge":         "Vis",
        "input_per_1m":  0.15,    # USD per 1M input tokens
        "output_per_1m": 0.60,    # USD per 1M output tokens
        "free_tier":     "Preview â€” free *",
        "note":          "Recommended for talent analysis â€” best JSON quality"
    },
    "gemini-3.1-flash-lite-preview": {
        "label":         "Gemini 3.1 Flash-Lite",
        "badge":         "Vis",
        "input_per_1m":  0.075,
        "output_per_1m": 0.30,
        "free_tier":     "Preview â€” free *",
        "note":          "Lite version â€” faster but less accurate on JSON"
    },
    "gemini-2.0-flash-lite": {
        "label":         "Gemini 2.0 Flash-Lite",
        "badge":         "Vis",
        "input_per_1m":  0.075,
        "output_per_1m": 0.30,
        "free_tier":     "~1500 req/day",
        "note":          "Stable, cost-effective"
    },
}


# ---------------------------------------------------------------------------
# Helpers â€” Talent individual JSON
# Talent JSON files for "Model Managment" live in the json/ subfolder
# ---------------------------------------------------------------------------
TALENT_JSON_SUBDIR = "json"   # subfolder inside Model Managment/


# ---------------------------------------------------------------------------
# Task Workbench - task templates, prompt automation, routing, reporting
# ---------------------------------------------------------------------------
DEFAULT_TASK_TEMPLATES = [
    {
        "slug": "campaign_launch",
        "name": "Launch Campaign",
        "description": "Multi-channel campaign visuals with clear brand direction and commercial polish.",
        "default_provider": "gemini",
        "default_workflow": "campaign-launch-v1",
        "default_model": "gemini-3.1-flash-image-preview",
        "default_aspect_ratio": "4:5",
        "default_image_size": "1K",
        "default_temperature": 0.95,
        "prompt_scaffold": "Build a flagship campaign image that feels art-directed, premium, and ready for client review.",
    },
    {
        "slug": "ad_variation_batch",
        "name": "Ad Variation Batch",
        "description": "High-volume paid social concepts optimized for fast iteration and multiple hooks.",
        "default_provider": "comfyui",
        "default_workflow": "ad-variation-batch-v1",
        "default_model": "gemini-3.1-flash-image-preview",
        "default_aspect_ratio": "4:5",
        "default_image_size": "1K",
        "default_temperature": 0.9,
        "prompt_scaffold": "Create a conversion-minded ad visual with a strong focal point, clean hierarchy, and room for copy overlays.",
    },
    {
        "slug": "editorial_lookbook",
        "name": "Editorial Lookbook",
        "description": "Fashion-forward imagery with strong styling, mood, and visual consistency.",
        "default_provider": "gemini",
        "default_workflow": "editorial-lookbook-v1",
        "default_model": "gemini-3-pro-image-preview",
        "default_aspect_ratio": "4:5",
        "default_image_size": "2K",
        "default_temperature": 1.05,
        "prompt_scaffold": "Compose an editorial image with intentional styling, cinematic lighting, and magazine-grade composition.",
    },
    {
        "slug": "product_hero",
        "name": "Product Hero",
        "description": "Clean hero visuals for product launches, e-commerce, and ad landing pages.",
        "default_provider": "comfyui",
        "default_workflow": "product-hero-v1",
        "default_model": "gemini-3-pro-image-preview",
        "default_aspect_ratio": "1:1",
        "default_image_size": "2K",
        "default_temperature": 0.8,
        "prompt_scaffold": "Highlight the product with premium materials, controlled reflections, and strong commercial clarity.",
    },
    {
        "slug": "location_concept",
        "name": "Location Concepting",
        "description": "Fast visual exploration for sets, environments, and brand worlds.",
        "default_provider": "gemini",
        "default_workflow": "location-concept-v1",
        "default_model": "gemini-3.1-flash-image-preview",
        "default_aspect_ratio": "16:9",
        "default_image_size": "1K",
        "default_temperature": 1.1,
        "prompt_scaffold": "Explore a location concept with a clear point of view, strong atmosphere, and believable production detail.",
    },
]

WORKBENCH_CHANNEL_LABELS = {
    "instagram_feed": "Instagram Feed",
    "meta_ads": "Meta Ads",
    "stories_reels": "Stories / Reels",
    "website": "Website / Landing Page",
    "email": "Email / CRM",
    "print": "Print / OOH",
}


def get_db_connection():
    conn = sqlite3.connect(STUDIO_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_task_runs_columns(conn):
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(task_runs)").fetchall()}
    desired = {
        "status":          "TEXT NOT NULL DEFAULT 'planned'",
        "run_count":       "INTEGER NOT NULL DEFAULT 0",
        "actual_images":   "INTEGER NOT NULL DEFAULT 0",
        "actual_cost_usd": "REAL NOT NULL DEFAULT 0",
        "actual_model":    "TEXT",
        "actual_provider": "TEXT",
        "last_run_at":     "TEXT",
        "last_error":      "TEXT",
        "plan_json":       "TEXT",
    }
    for name, ddl in desired.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE task_runs ADD COLUMN {name} {ddl}")


def init_studio_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            default_provider TEXT NOT NULL,
            default_workflow TEXT NOT NULL,
            default_model TEXT NOT NULL,
            default_aspect_ratio TEXT NOT NULL,
            default_image_size TEXT NOT NULL,
            default_temperature REAL NOT NULL,
            prompt_scaffold TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_uuid TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            client_name TEXT,
            project_name TEXT,
            task_slug TEXT NOT NULL,
            task_name TEXT NOT NULL,
            objective TEXT NOT NULL,
            channels_json TEXT NOT NULL,
            vibe TEXT,
            subject_summary TEXT,
            constraints_summary TEXT,
            automation_level TEXT NOT NULL,
            recommended_provider TEXT NOT NULL,
            execution_provider TEXT NOT NULL,
            recommended_model TEXT,
            recommended_workflow TEXT NOT NULL,
            aspect_ratio TEXT,
            image_size TEXT,
            prompt_text TEXT NOT NULL,
            estimated_outputs INTEGER NOT NULL DEFAULT 0,
            estimated_cost_low REAL NOT NULL DEFAULT 0,
            estimated_cost_high REAL NOT NULL DEFAULT 0
        )
        """
    )
    ensure_task_runs_columns(conn)
    now_ts = utc_now_iso()
    for template in DEFAULT_TASK_TEMPLATES:
        conn.execute(
            """
            INSERT OR IGNORE INTO task_templates (
                slug, name, description, default_provider, default_workflow,
                default_model, default_aspect_ratio, default_image_size,
                default_temperature, prompt_scaffold, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template["slug"],
                template["name"],
                template["description"],
                template["default_provider"],
                template["default_workflow"],
                template["default_model"],
                template["default_aspect_ratio"],
                template["default_image_size"],
                template["default_temperature"],
                template["prompt_scaffold"],
                now_ts,
                now_ts,
            ),
        )
    conn.commit()
    conn.close()


def fetch_task_templates():
    init_studio_db()
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT slug, name, description, default_provider, default_workflow, "
        "default_model, default_aspect_ratio, default_image_size, "
        "default_temperature, prompt_scaffold "
        "FROM task_templates ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_task_template(slug: str) -> dict | None:
    for template in fetch_task_templates():
        if template["slug"] == slug:
            return template
    return None


def _normalize_channels(raw_channels) -> list[str]:
    if isinstance(raw_channels, list):
        values = raw_channels
    else:
        values = str(raw_channels or "").split(",")
    cleaned = []
    for value in values:
        key = str(value).strip().lower()
        if key and key in WORKBENCH_CHANNEL_LABELS and key not in cleaned:
            cleaned.append(key)
    return cleaned


def _pick_aspect_ratio(channels: list[str], template: dict) -> str:
    if "stories_reels" in channels and len(channels) == 1:
        return "9:16"
    if any(ch in channels for ch in ("instagram_feed", "meta_ads")):
        return "4:5"
    if any(ch in channels for ch in ("website", "print")):
        return "16:9"
    return template.get("default_aspect_ratio", "1:1")


def _estimate_output_count(channels: list[str], automation_level: str) -> int:
    base = 4 + max(0, len(channels) - 1) * 2
    if automation_level == "aggressive":
        base += 4
    elif automation_level == "assisted":
        base -= 1
    return max(2, min(base, 16))


def _route_workbench_task(template: dict, channels: list[str], automation_level: str) -> dict:
    recommended_provider = template.get("default_provider", "gemini")
    execution_provider = "gemini"
    model = template.get("default_model", "gemini-3.1-flash-image-preview")
    workflow = template.get("default_workflow", "task-workbench-v1")
    notes = []

    if template["slug"] in ("ad_variation_batch", "product_hero"):
        notes.append("This task maps well to a hidden ComfyUI batch workflow once that adapter is added.")
    if template["slug"] == "editorial_lookbook":
        notes.append("Editorial work gets a higher-fidelity default model and larger output size.")
    if template["slug"] == "campaign_launch":
        notes.append("The route balances quality, speed, and reference-ready outputs for client review.")
    if automation_level == "aggressive" and template["slug"] in ("campaign_launch", "ad_variation_batch"):
        model = "gemini-3.1-flash-image-preview"
        notes.append("Automation is set high, so the route favors faster iteration over maximum fidelity.")
    if automation_level == "assisted" and template["slug"] in ("editorial_lookbook", "product_hero"):
        model = "gemini-3-pro-image-preview"
        notes.append("Assisted mode keeps the route closer to art-directed premium quality.")

    aspect_ratio = _pick_aspect_ratio(channels, template)
    image_size = template.get("default_image_size", "1K")
    temperature = float(template.get("default_temperature", 1.0))
    if automation_level == "aggressive":
        temperature = min(1.2, temperature + 0.05)
    elif automation_level == "assisted":
        temperature = max(0.75, temperature - 0.05)

    if aspect_ratio == "16:9" and image_size == "2K" and model == "gemini-3-pro-image-preview":
        notes.append("The current generator can execute this immediately, while a future workflow could expand into batch crops.")

    return {
        "recommended_provider": recommended_provider,
        "execution_provider": execution_provider,
        "model": model,
        "workflow": workflow,
        "aspect_ratio": aspect_ratio,
        "image_size": image_size,
        "temperature": round(temperature, 2),
        "top_p": 0.95,
        "notes": notes,
    }


def _build_prompt_from_brief(template: dict, route: dict, brief: dict) -> str:
    channels = brief.get("channels") or []
    channel_labels = [WORKBENCH_CHANNEL_LABELS.get(ch, ch) for ch in channels]
    sections = [
        template.get("prompt_scaffold", "Create a strong commercial visual."),
        f"Client: {brief.get('client_name') or 'Internal creative team'}.",
        f"Project: {brief.get('project_name') or 'Untitled project'}.",
        f"Objective: {brief.get('objective')}.",
    ]
    if brief.get("subject_summary"):
        sections.append(f"Subject and key assets: {brief['subject_summary']}.")
    if brief.get("vibe"):
        sections.append(f"Creative direction and vibe: {brief['vibe']}.")
    if channel_labels:
        sections.append(
            f"Design for these channels: {', '.join(channel_labels)}. Prefer an aspect ratio of {route['aspect_ratio']}."
        )
    sections.append(
        "The image should feel commercially usable, visually clean, and immediately understandable without extra explanation."
    )
    if brief.get("constraints_summary"):
        sections.append(f"Hard constraints: {brief['constraints_summary']}.")

    automation_level = brief.get("automation_level", "balanced")
    if automation_level == "aggressive":
        sections.append("Push for bold variation, strong hooks, and obvious first-read impact.")
    elif automation_level == "assisted":
        sections.append("Stay close to polished brand-safe art direction and avoid unnecessary stylistic risk.")
    else:
        sections.append("Balance originality with production practicality and brand readability.")

    sections.append("Use realistic lighting, coherent materials, and a production-ready sense of composition.")
    return "\n\n".join(sections)


def build_workbench_plan(body: dict) -> dict:
    task_slug = str(body.get("task_slug", "campaign_launch")).strip()
    template = get_task_template(task_slug)
    if not template:
        raise ValueError("Invalid task template")

    objective = str(body.get("objective", "")).strip()
    if not objective:
        raise ValueError("Objective is required")

    brief = {
        "client_name": str(body.get("client_name", "")).strip(),
        "project_name": str(body.get("project_name", "")).strip(),
        "objective": objective,
        "subject_summary": str(body.get("subject_summary", "")).strip(),
        "vibe": str(body.get("vibe", "")).strip(),
        "constraints_summary": str(body.get("constraints_summary", "")).strip(),
        "automation_level": str(body.get("automation_level", "balanced")).strip() or "balanced",
        "channels": _normalize_channels(body.get("channels", [])),
    }
    if not brief["channels"]:
        brief["channels"] = ["instagram_feed"]

    route = _route_workbench_task(template, brief["channels"], brief["automation_level"])
    prompt_text = _build_prompt_from_brief(template, route, brief)
    estimated_outputs = _estimate_output_count(brief["channels"], brief["automation_level"])
    price_per_image = PRICING.get(route["model"], {}).get(route["image_size"], 0.0)
    est_low = round(price_per_image * max(2, estimated_outputs // 2), 4)
    est_high = round(price_per_image * estimated_outputs, 4)

    reasoning = [
        f"{template['name']} gives the user a task-first starting point instead of a blank prompt box.",
        f"Recommended workflow: {route['workflow']}.",
        f"Primary route: {route['recommended_provider']} with immediate execution through {route['execution_provider']}.",
    ] + route["notes"]

    return {
        "task_slug": template["slug"],
        "task_name": template["name"],
        "description": template["description"],
        "brief": brief,
        "recommended_provider": route["recommended_provider"],
        "recommended_workflow": route["workflow"],
        "execution_target": {
            "provider": route["execution_provider"],
            "model": route["model"],
            "model_label": MODELS_INFO.get(route["model"], {}).get("label", route["model"]),
            "aspectRatio": route["aspect_ratio"],
            "imageSize": route["image_size"],
            "temperature": route["temperature"],
            "topP": route["top_p"],
        },
        "estimated_outputs": estimated_outputs,
        "estimated_cost_range_usd": {
            "low": est_low,
            "high": est_high,
        },
        "reasoning": reasoning,
        "prompt": prompt_text,
    }


def save_task_run(plan: dict) -> dict:
    init_studio_db()
    brief = plan.get("brief", {})
    execution = plan.get("execution_target", {})
    run_uuid = plan.get("run_uuid") or str(uuid4())
    plan["run_uuid"] = run_uuid
    conn = get_db_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO task_runs (
            run_uuid, created_at, client_name, project_name, task_slug, task_name,
            objective, channels_json, vibe, subject_summary, constraints_summary,
            automation_level, recommended_provider, execution_provider,
            recommended_model, recommended_workflow, aspect_ratio, image_size,
            prompt_text, estimated_outputs, estimated_cost_low, estimated_cost_high,
            status, run_count, actual_images, actual_cost_usd, actual_model,
            actual_provider, last_run_at, last_error, plan_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_uuid,
            plan.get("created_at") or utc_now_iso(),
            brief.get("client_name", ""),
            brief.get("project_name", ""),
            plan.get("task_slug", ""),
            plan.get("task_name", ""),
            brief.get("objective", ""),
            json.dumps(brief.get("channels", [])),
            brief.get("vibe", ""),
            brief.get("subject_summary", ""),
            brief.get("constraints_summary", ""),
            brief.get("automation_level", "balanced"),
            plan.get("recommended_provider", ""),
            execution.get("provider", ""),
            execution.get("model", ""),
            plan.get("recommended_workflow", ""),
            execution.get("aspectRatio", ""),
            execution.get("imageSize", ""),
            plan.get("prompt", ""),
            int(plan.get("estimated_outputs", 0)),
            float(plan.get("estimated_cost_range_usd", {}).get("low", 0.0)),
            float(plan.get("estimated_cost_range_usd", {}).get("high", 0.0)),
            plan.get("status", "planned"),
            int(plan.get("run_count", 0)),
            int(plan.get("actual_images", 0)),
            float(plan.get("actual_cost_usd", 0.0)),
            plan.get("actual_model", execution.get("model", "")),
            plan.get("actual_provider", execution.get("provider", "")),
            plan.get("last_run_at", ""),
            plan.get("last_error", ""),
            json.dumps(plan, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return plan


def get_task_run(run_uuid: str) -> dict | None:
    init_studio_db()
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM task_runs WHERE run_uuid = ? LIMIT 1",
        (run_uuid,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    plan_json = item.get("plan_json") or ""
    if plan_json:
        try:
            item["plan"] = json.loads(plan_json)
        except json.JSONDecodeError:
            item["plan"] = None
    else:
        item["plan"] = None
    return item


def update_task_run_after_generation(run_uuid: str, generation_result: dict | None = None, error: str = ""):
    init_studio_db()
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM task_runs WHERE run_uuid = ? LIMIT 1", (run_uuid,)).fetchone()
    if not row:
        conn.close()
        return
    item = dict(row)
    run_count = int(item.get("run_count") or 0)
    actual_images = int(item.get("actual_images") or 0)
    actual_cost = float(item.get("actual_cost_usd") or 0.0)
    now_ts = utc_now_iso()
    if generation_result is not None:
        actual_images += len(generation_result.get("images", []))
        actual_cost += float(generation_result.get("cost", 0.0) or 0.0)
        status = "completed"
        last_error = ""
        actual_model = generation_result.get("params", {}).get("model", item.get("recommended_model", ""))
        actual_provider = item.get("execution_provider", "gemini")
    else:
        status = "failed"
        last_error = error[:500]
        actual_model = item.get("actual_model", item.get("recommended_model", ""))
        actual_provider = item.get("actual_provider", item.get("execution_provider", "gemini"))
    conn.execute(
        """
        UPDATE task_runs
        SET status = ?, run_count = ?, actual_images = ?, actual_cost_usd = ?,
            actual_model = ?, actual_provider = ?, last_run_at = ?, last_error = ?
        WHERE run_uuid = ?
        """,
        (
            status,
            run_count + 1,
            actual_images,
            round(actual_cost, 6),
            actual_model,
            actual_provider,
            now_ts,
            last_error,
            run_uuid,
        ),
    )
    conn.commit()
    conn.close()


def get_workbench_report() -> dict:
    init_studio_db()
    conn = get_db_connection()
    summary_row = conn.execute(
        """
        SELECT COUNT(*) AS total_runs,
               COUNT(DISTINCT NULLIF(client_name, '')) AS total_clients,
               COALESCE(SUM(estimated_cost_low), 0) AS total_cost_low,
               COALESCE(SUM(estimated_cost_high), 0) AS total_cost_high,
               COALESCE(SUM(estimated_outputs), 0) AS total_outputs,
               COALESCE(SUM(actual_images), 0) AS actual_images,
               COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd,
               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_runs,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
               SUM(CASE WHEN run_count > 0 THEN 1 ELSE 0 END) AS executed_runs
        FROM task_runs
        """
    ).fetchone()
    task_breakdown = [
        dict(row) for row in conn.execute(
            "SELECT task_name, COUNT(*) AS runs FROM task_runs GROUP BY task_name ORDER BY runs DESC, task_name ASC LIMIT 6"
        ).fetchall()
    ]
    provider_breakdown = [
        dict(row) for row in conn.execute(
            "SELECT COALESCE(actual_provider, recommended_provider) AS provider, COUNT(*) AS runs "
            "FROM task_runs GROUP BY provider ORDER BY runs DESC, provider ASC LIMIT 6"
        ).fetchall()
    ]
    client_breakdown = [
        dict(row) for row in conn.execute(
            "SELECT CASE WHEN NULLIF(client_name, '') IS NULL THEN 'Unassigned' ELSE client_name END AS client_name, COUNT(*) AS runs "
            "FROM task_runs GROUP BY client_name ORDER BY runs DESC, client_name ASC LIMIT 6"
        ).fetchall()
    ]
    workflow_breakdown = [
        dict(row) for row in conn.execute(
            "SELECT recommended_workflow, COUNT(*) AS runs FROM task_runs GROUP BY recommended_workflow ORDER BY runs DESC, recommended_workflow ASC LIMIT 6"
        ).fetchall()
    ]
    recent_runs = []
    for row in conn.execute(
        """
        SELECT created_at, client_name, project_name, task_name, recommended_provider,
               recommended_workflow, recommended_model, estimated_outputs,
               estimated_cost_low, estimated_cost_high, status, run_count,
               actual_images, actual_cost_usd, last_run_at, last_error, run_uuid
        FROM task_runs
        ORDER BY id DESC
        LIMIT 12
        """
    ).fetchall():
        item = dict(row)
        created = item.get("created_at", "")
        item["created_at_label"] = created[:16].replace("T", " ") if created else ""
        last_run_at = item.get("last_run_at", "")
        item["last_run_at_label"] = last_run_at[:16].replace("T", " ") if last_run_at else ""
        recent_runs.append(item)
    conn.close()
    return {
        "summary": {
            "total_runs": int(summary_row["total_runs"] or 0),
            "total_clients": int(summary_row["total_clients"] or 0),
            "total_outputs": int(summary_row["total_outputs"] or 0),
            "total_cost_low": round(float(summary_row["total_cost_low"] or 0.0), 4),
            "total_cost_high": round(float(summary_row["total_cost_high"] or 0.0), 4),
            "executed_runs": int(summary_row["executed_runs"] or 0),
            "completed_runs": int(summary_row["completed_runs"] or 0),
            "failed_runs": int(summary_row["failed_runs"] or 0),
            "actual_images": int(summary_row["actual_images"] or 0),
            "actual_cost_usd": round(float(summary_row["actual_cost_usd"] or 0.0), 4),
        },
        "task_breakdown": task_breakdown,
        "provider_breakdown": provider_breakdown,
        "client_breakdown": client_breakdown,
        "workflow_breakdown": workflow_breakdown,
        "recent_runs": recent_runs,
    }
def talent_json_dir(folder_path: str) -> str:
    """Return the effective JSON directory for a talent folder.
    For 'Model Managment' use the json/ subfolder; for other folders use the root.
    """
    if os.path.basename(folder_path) == "Model Managment":
        return os.path.join(folder_path, TALENT_JSON_SUBDIR)
    return folder_path


def talent_json_path(folder_path: str, talent_id: str) -> str:
    """Path to the individual JSON file for a talent."""
    return os.path.join(talent_json_dir(folder_path), f"{talent_id}.json")


def load_talent_json(json_path: str) -> dict | None:
    """Load an individual talent JSON; returns None if missing/invalid."""
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_talent_json(json_path: str, data: dict):
    """Save talent data to the JSON file (creating parent dirs when needed)."""
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helper - image normalization
#   â€¢ Se larghezza > MAX_IMG_WIDTH: ridimensiona mantenendo aspect ratio
#   - Always converts to JPG with JPEG_QUALITY quality
#   â€¢ Ritorna (b64_string, "image/jpeg", orig_w, orig_h, new_w, new_h)
# ---------------------------------------------------------------------------
MAX_IMG_WIDTH  = 4000   # px sulla dimensione orizzontale
JPEG_QUALITY   = 90     # JPG output quality %
SEEDREAM_MAX_INPUT_BYTES = 10 * 1024 * 1024
SEEDREAM_TARGET_INPUT_BYTES = int(SEEDREAM_MAX_INPUT_BYTES * 0.92)


def open_base64_image(image_b64: str) -> tuple[Image.Image, dict]:
    raw = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(raw))
    img.load()
    info = dict(getattr(img, "info", {}) or {})
    img = ImageOps.exif_transpose(img)
    return img, info


def flatten_image_for_jpeg(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    if img.mode not in ("RGB", "L"):
        return img.convert("RGB")
    return img


def normalize_image_b64(image_b64: str, mime_type: str) -> tuple:
    """
    Process a base64 image:
      - se larghezza > MAX_IMG_WIDTH -> ridimensiona a MAX_IMG_WIDTH (mantiene ratio)
      - converte in JPG a JPEG_QUALITY
    Returns (processed_b64, "image/jpeg", orig_w, orig_h, final_w, final_h, resized: bool)
    """
    img, info = open_base64_image(image_b64)
    img = flatten_image_for_jpeg(img)

    orig_w, orig_h = img.size
    resized = False

    if orig_w > MAX_IMG_WIDTH:
        ratio = MAX_IMG_WIDTH / orig_w
        new_w = MAX_IMG_WIDTH
        new_h = int(orig_h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        resized = True
    else:
        new_w, new_h = orig_w, orig_h

    buf = io.BytesIO()
    save_kwargs = {"format": "JPEG", "quality": JPEG_QUALITY, "optimize": True}
    icc_profile = info.get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    img.save(buf, **save_kwargs)
    buf.seek(0)
    b64_out = base64.b64encode(buf.read()).decode("utf-8")

    return b64_out, "image/jpeg", orig_w, orig_h, new_w, new_h, resized


def convert_image_b64_to_png(image_b64: str, mime_type: str) -> tuple[str, str]:
    """Convert a base64 image payload to PNG while preserving alpha when present."""
    img, info = open_base64_image(image_b64)

    has_alpha = ("A" in img.getbands()) or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
    elif img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    save_kwargs = {"format": "PNG", "optimize": True}
    icc_profile = info.get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    img.save(buf, **save_kwargs)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8"), "image/png"


def name_to_slug(name: str) -> str:
    """Converte nome in slug (lowercase, underscore, senza accenti)."""
    slug = unicodedata.normalize("NFKD", name.lower())
    slug = slug.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", slug).strip()
    slug = re.sub(r"[\s\-]+", "_", slug)
    return slug or "talent"


def get_next_image_number(folder_path: str, slug: str) -> int:
    """Return the next incremental number for slug_NNN.ext."""
    pattern = re.compile(
        r"^" + re.escape(slug) + r"_(\d+)\.(jpg|jpeg|png|webp)$",
        re.IGNORECASE
    )
    max_n = 0
    for fname in os.listdir(folder_path):
        m = pattern.match(fname)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def list_talent_jsons(folder_path: str) -> list[str]:
    """List all individual talent JSON files.
    For 'Model Managment' search in json/; otherwise search in the folder root.
    """
    excluded = {"catalog.json", "catalog.json.bak"}
    search_dir = talent_json_dir(folder_path)
    return [
        p for p in glob.glob(os.path.join(search_dir, "*.json"))
        if os.path.basename(p) not in excluded
    ]


MAX_SEED_VALUE = 2147483647


def normalize_seed_mode(value) -> str:
    mode = str(value or "random").strip().lower()
    return mode if mode in {"fixed", "random", "incremental"} else "random"


def coerce_seed_value(value) -> int:
    try:
        seed = int(str(value).strip())
    except Exception:
        seed = random.randint(1, MAX_SEED_VALUE)
    return max(1, min(seed, MAX_SEED_VALUE))


def build_reference_archive_entries(ref_images: list[dict], date_str: str, time_prefix: str) -> list[dict]:
    if not ref_images:
        return []
    archive_day_dir = os.path.join(REFERENCE_ARCHIVE_DIR, date_str)
    os.makedirs(archive_day_dir, exist_ok=True)
    archived = []
    for idx, img in enumerate(ref_images):
        if not isinstance(img, dict):
            continue
        img_b64 = str(img.get("data", "") or "").strip()
        if not img_b64:
            continue
        mime_type = str(img.get("mime_type", "image/png") or "image/png")
        try:
            png_b64, png_mime = convert_image_b64_to_png(img_b64, mime_type)
        except Exception:
            continue
        original_name = os.path.basename(str(img.get("name", "") or f"reference-{idx + 1}.png"))
        stem = os.path.splitext(original_name)[0] or f"reference-{idx + 1}"
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or f"reference-{idx + 1}"
        filename = f"{time_prefix}_ref_{idx + 1}_{uuid4().hex[:6]}_{safe_stem}.png"
        archive_path = os.path.join(archive_day_dir, filename)
        with open(archive_path, "wb") as fh:
            fh.write(base64.b64decode(png_b64))
        archived.append({
            "date": date_str,
            "filename": filename,
            "name": original_name,
            "mime_type": png_mime,
            "url": f"/reference-archive/{date_str}/{filename}",
        })
    return archived


def delete_reference_archive_entries(entries: list[dict]):
    safe_root = os.path.realpath(REFERENCE_ARCHIVE_DIR)
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        date_str = str(item.get("date", "") or "").strip()
        filename = os.path.basename(str(item.get("filename", "") or "").strip())
        if not date_str or not filename:
            continue
        archive_path = os.path.realpath(os.path.join(REFERENCE_ARCHIVE_DIR, date_str, filename))
        if not archive_path.startswith(safe_root + os.sep):
            continue
        if os.path.exists(archive_path):
            try:
                os.remove(archive_path)
            except Exception:
                pass
        archive_day_dir = os.path.dirname(archive_path)
        if os.path.isdir(archive_day_dir) and not os.listdir(archive_day_dir):
            try:
                os.rmdir(archive_day_dir)
            except Exception:
                pass


class GenerationDebugError(RuntimeError):
    def __init__(self, message: str, debug: dict | None = None):
        super().__init__(message)
        self.debug = debug or {}


def build_gemini_failure_debug(result: dict, safety_preset: str = "default", safety_settings_sent: bool = False) -> dict:
    prompt_feedback = result.get("promptFeedback") or {}
    candidates = []
    for idx, candidate in enumerate(result.get("candidates", []) or []):
        finish_reason = candidate.get("finishReason")
        finish_message = candidate.get("finishMessage")
        parts = (candidate.get("content") or {}).get("parts") or []
        has_image = any("inlineData" in part for part in parts)
        safety_ratings = candidate.get("safetyRatings") or []
        candidates.append({
            "index": idx + 1,
            "finishReason": finish_reason or "",
            "finishMessage": finish_message or "",
            "hasImage": has_image,
            "safetyRatings": [
                {
                    "category": rating.get("category", ""),
                    "probability": rating.get("probability", ""),
                    "blocked": bool(rating.get("blocked", False)),
                }
                for rating in safety_ratings
                if isinstance(rating, dict)
            ],
        })

    summary_parts = []
    block_reason = prompt_feedback.get("blockReason")
    block_reason_message = prompt_feedback.get("blockReasonMessage")
    if block_reason:
        summary_parts.append(f"Prompt blocked: {block_reason}")
    if block_reason_message:
        summary_parts.append(str(block_reason_message))
    for item in candidates:
        finish_reason = item.get("finishReason")
        if finish_reason and finish_reason != "STOP":
            note = finish_reason
            if item.get("finishMessage"):
                note += f": {item['finishMessage']}"
            summary_parts.append(f"Candidate {item['index']}: {note}")
        elif finish_reason == "STOP" and not item.get("hasImage"):
            note = "STOP but no image was returned"
            if item.get("finishMessage"):
                note += f": {item['finishMessage']}"
            summary_parts.append(f"Candidate {item['index']}: {note}")

    if not summary_parts:
        summary_parts.append("Gemini returned no image for this request.")

    return {
        "provider": "gemini",
        "safetyPreset": safety_preset,
        "safetySettingsSent": bool(safety_settings_sent),
        "promptBlockReason": block_reason or "",
        "promptBlockReasonMessage": block_reason_message or "",
        "candidates": candidates,
        "summary": " | ".join(summary_parts),
    }


def summarize_generate_response_issue(result: dict, safety_preset: str = "default", safety_settings_sent: bool = False) -> tuple[str, dict]:
    debug = build_gemini_failure_debug(result, safety_preset=safety_preset, safety_settings_sent=safety_settings_sent)
    return debug["summary"], debug


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def mask_api_key(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value[:8] + "..." + value[-4:] if len(value) > 12 else "***"


def normalize_seedream_size(image_size: str) -> str:
    image_size = (image_size or "2K").strip().upper()
    if image_size not in {"2K", "4K"}:
        return "2K"
    return image_size


GEMINI_SAFETY_CATEGORIES = [
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
    "HARM_CATEGORY_CIVIC_INTEGRITY",
]


def build_gemini_safety_settings(profile: str) -> tuple[list[dict] | None, str]:
    normalized = (profile or "default").strip().lower()
    threshold = {
        "default": None,
        "relaxed": "BLOCK_ONLY_HIGH",
        "off": "OFF",
        "strict": "BLOCK_LOW_AND_ABOVE",
    }.get(normalized)
    if normalized not in {"default", "relaxed", "off", "strict"}:
        normalized = "default"
        threshold = None
    if threshold is None:
        return None, normalized
    return ([{"category": category, "threshold": threshold} for category in GEMINI_SAFETY_CATEGORIES], normalized)


def normalize_fal_safety_tolerance(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 4
    return max(1, min(parsed, 6))


def compress_seedream_ref_image(image_b64: str, mime_type: str) -> tuple[str, str]:
    """Shrink/compress a reference image until it fits BytePlus Seedream's 10 MiB limit."""
    raw = base64.b64decode(image_b64)
    if len(raw) <= SEEDREAM_TARGET_INPUT_BYTES:
        return image_b64, mime_type

    img, info = open_base64_image(image_b64)
    img = flatten_image_for_jpeg(img)

    width, height = img.size
    quality = 88
    max_side = max(width, height)

    while True:
        working = img.copy()
        current_max = max(working.size)
        if current_max > max_side:
            scale = max_side / float(current_max)
            new_w = max(256, int(working.size[0] * scale))
            new_h = max(256, int(working.size[1] * scale))
            working = working.resize((new_w, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        save_kwargs = {"format": "JPEG", "quality": quality, "optimize": True}
        icc_profile = info.get("icc_profile")
        if icc_profile:
            save_kwargs["icc_profile"] = icc_profile
        working.save(buf, **save_kwargs)
        payload = buf.getvalue()
        if len(payload) <= SEEDREAM_TARGET_INPUT_BYTES:
            return base64.b64encode(payload).decode("utf-8"), "image/jpeg"

        if quality > 50:
            quality -= 8
            continue
        if max_side > 1536:
            max_side = int(max_side * 0.82)
            quality = 82
            continue
        return base64.b64encode(payload).decode("utf-8"), "image/jpeg"


def build_data_uri_ref_inputs(ref_images: list[dict]) -> list[str]:
    items = []
    for img in ref_images:
        mime = img.get("mime_type", "image/png")
        data = img.get("data", "")
        if data:
            items.append(f"data:{mime};base64,{data}")
    return items


def build_byteplus_seedream_ref_inputs(ref_images: list[dict]) -> list[str]:
    items = []
    for img in ref_images:
        mime = img.get("mime_type", "image/png")
        data = img.get("data", "")
        if data:
            safe_b64, safe_mime = compress_seedream_ref_image(data, mime)
            items.append(f"data:{safe_mime};base64,{safe_b64}")
    return items


def extract_fal_error(resp: requests.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        return f"HTTP {resp.status_code}"
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                msg = first.get("msg") or first.get("message") or first.get("detail")
                loc = first.get("loc")
                if msg and loc:
                    return f"{'.'.join(str(x) for x in loc)}: {msg}"
                if msg:
                    return str(msg)
            elif isinstance(first, str):
                return first
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return f"HTTP {resp.status_code}"


def extract_byteplus_error(resp: requests.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        raw = (resp.text or "").strip()
        return raw or f"HTTP {resp.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "").strip()
            message = str(error.get("message") or error.get("msg") or "").strip()
            if code and message:
                return f"{code} - {message}"
            if message:
                return message
        for key in ("message", "msg", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                code = str(payload.get("code") or "").strip()
                return f"{code} - {value.strip()}" if code else value.strip()
    return f"HTTP {resp.status_code}"


def build_fal_seedream_image_size(model_id: str, image_size: str) -> str:
    normalized = (image_size or "2K").strip().upper()
    if model_id == FAL_SEEDREAM_5_TEXT_ID:
        return "auto_3K" if normalized == "4K" else "auto_2K"
    return "auto_4K" if normalized == "4K" else "auto_2K"


def build_fal_seedream_endpoint(model_id: str, has_refs: bool) -> str:
    if model_id == FAL_SEEDREAM_45_TEXT_ID:
        return FAL_SEEDREAM_45_EDIT_ID if has_refs else FAL_SEEDREAM_45_TEXT_ID
    if model_id == FAL_SEEDREAM_5_TEXT_ID:
        return FAL_SEEDREAM_5_EDIT_ID if has_refs else FAL_SEEDREAM_5_TEXT_ID
    raise ValueError("Unsupported Fal Seedream model")


def build_fal_nano_banana_endpoint(model_id: str, has_refs: bool) -> str:
    if model_id == FAL_NANO_BANANA_TEXT_ID:
        return FAL_NANO_BANANA_EDIT_ID if has_refs else FAL_NANO_BANANA_TEXT_ID
    if model_id == FAL_NANO_BANANA_PRO_TEXT_ID:
        return FAL_NANO_BANANA_PRO_EDIT_ID if has_refs else FAL_NANO_BANANA_PRO_TEXT_ID
    if model_id == FAL_NANO_BANANA_2_TEXT_ID:
        return FAL_NANO_BANANA_2_EDIT_ID if has_refs else FAL_NANO_BANANA_2_TEXT_ID
    raise ValueError("Unsupported Fal Nano Banana model")


def build_fal_nano_banana_resolution(model_id: str, image_size: str) -> str:
    normalized = (image_size or "1K").strip().upper()
    if model_id == FAL_NANO_BANANA_TEXT_ID:
        return "1K"
    if model_id == FAL_NANO_BANANA_PRO_TEXT_ID and normalized not in {"1K", "2K", "4K"}:
        return "1K"
    if model_id == FAL_NANO_BANANA_2_TEXT_ID and normalized not in {"0.5K", "1K", "2K", "4K"}:
        return "1K"
    return normalized


def decode_fal_image_result(item: dict) -> dict | None:
    image_url = str(item.get("url") or item.get("image_url") or item.get("data_uri") or "").strip()
    if image_url.startswith("data:"):
        header, _, b64_data = image_url.partition(",")
        mime_type = header.split(";", 1)[0][5:] or "image/png"
        return {"mime_type": mime_type, "data": b64_data}
    if image_url:
        try:
            image_resp = requests.get(image_url, timeout=120)
            image_resp.raise_for_status()
            raw = image_resp.content
            png_b64, png_mime = convert_image_b64_to_png(
                base64.b64encode(raw).decode("utf-8"),
                image_resp.headers.get("Content-Type", item.get("content_type", "image/png"))
            )
            return {"mime_type": png_mime, "data": png_b64}
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes â€” Auth
# ---------------------------------------------------------------------------
@app.route("/")
def root():
    if "user" in session:
        return redirect(url_for("index"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username in USERS and USERS[username] == password:
            session["user"] = username
            return redirect(url_for("index"))
        error = "Invalid credentials. Please try again."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes â€” App
# ---------------------------------------------------------------------------
@app.route("/index")
@login_required
def index():
    config = load_config()
    has_key = bool(
        config.get("api_key", "").strip()
        or config.get("fal_api_key", "").strip()
        or config.get("byteplus_api_key", "").strip()
    )
    return render_template("index.html",
                           models=MODELS_INFO,
                           model_families=MODEL_FAMILIES,
                           provider_labels=PROVIDER_LABELS,
                           has_key=has_key,
                           user=session["user"])


@app.route("/settings")
@login_required
def settings():
    config = load_config()
    stats = config.get("stats", DEFAULT_CONFIG["stats"])
    api_key = config.get("api_key", "")
    fal_api_key = config.get("fal_api_key", "")
    byteplus_api_key = config.get("byteplus_api_key", "") or config.get("seedream_api_key", "")
    return render_template("settings.html",
                           masked_key=mask_api_key(api_key),
                           has_key=bool(api_key),
                           masked_fal_key=mask_api_key(fal_api_key),
                           has_fal_key=bool(fal_api_key),
                           masked_byteplus_key=mask_api_key(byteplus_api_key),
                           has_byteplus_key=bool(byteplus_api_key),
                           stats=stats,
                           vision_models=VISION_MODELS_INFO,
                           analysis_model=TALENT_ANALYSIS_MODEL,
                           user=session["user"])


# ---------------------------------------------------------------------------
# Route â€” Credits
# ---------------------------------------------------------------------------
@app.route("/credits")
@login_required
def credits():
    return render_template("credits.html", user=session["user"])


# ---------------------------------------------------------------------------
# Route - Task Workbench
# ---------------------------------------------------------------------------
@app.route("/workbench")
@login_required
def workbench():
    return render_template(
        "workbench.html",
        task_templates=fetch_task_templates(),
        report=get_workbench_report(),
        channel_labels=WORKBENCH_CHANNEL_LABELS,
        user=session["user"],
    )


# ---------------------------------------------------------------------------
# Route - Reports
# ---------------------------------------------------------------------------
@app.route("/reports")
@login_required
def reports_page():
    return render_template(
        "reports.html",
        report=get_workbench_report(),
        user=session["user"],
    )


# ---------------------------------------------------------------------------
# Route â€” Loved gallery (saved favorites)
# ---------------------------------------------------------------------------
@app.route("/loved")
@login_required
def loved_gallery():
    days = []
    if os.path.isdir(LOVED_DIR):
        date_dirs = sorted(
            [d for d in os.listdir(LOVED_DIR)
             if os.path.isdir(os.path.join(LOVED_DIR, d))],
            reverse=True
        )
        for date_str in date_dirs:
            day_path   = os.path.join(LOVED_DIR, date_str)
            meta_files = sorted(glob.glob(os.path.join(day_path, "*.json")), reverse=True)
            items = []
            for mf in meta_files:
                try:
                    with open(mf) as f:
                        meta = json.load(f)
                    # Look for the image file with any supported extension
                    base     = mf[:-5]  # rimuove ".json"
                    img_path = None
                    for ext in (".jpeg", ".jpg", ".png", ".webp"):
                        candidate = base + ext
                        if os.path.exists(candidate):
                            img_path = candidate
                            break
                    if img_path:
                        items.append({
                            "filename": os.path.basename(img_path),
                            "date":     date_str,
                            "meta":     meta
                        })
                except Exception:
                    pass
            if items:
                try:
                    dt    = datetime.strptime(date_str, "%Y-%m-%d")
                    label = dt.strftime("%-d %B %Y")
                except Exception:
                    label = date_str
                days.append({"date": date_str, "label": label, "entries": items})
    return render_template("loved.html", days=days, user=session["user"])


@app.route("/loved/<date_str>/<filename>")
@login_required
def serve_loved(date_str, filename):
    day_path = os.path.join(LOVED_DIR, date_str)
    return send_from_directory(day_path, filename)


@app.route("/reference-archive/<date_str>/<filename>")
@login_required
def serve_reference_archive(date_str, filename):
    day_path = os.path.join(REFERENCE_ARCHIVE_DIR, date_str)
    return send_from_directory(day_path, filename)


@app.route("/generations/<date_str>/<filename>")
@login_required
def serve_generation(date_str, filename):
    day_path = os.path.join(GENERATIONS_DIR, date_str)
    return send_from_directory(day_path, filename)


# ---------------------------------------------------------------------------
# API â€” Delete a loved image (image + JSON sidecar, never touches generations/)
# ---------------------------------------------------------------------------
@app.route("/api/loved/<date_str>/<filename>", methods=["DELETE"])
@login_required
def api_delete_loved(date_str, filename):
    safe_root = os.path.realpath(LOVED_DIR)
    img_path  = os.path.realpath(os.path.join(LOVED_DIR, date_str, filename))

    # Security: must stay inside loved/
    if not img_path.startswith(safe_root + os.sep):
        return jsonify({"ok": False, "error": "Invalid path"}), 400

    # Only image extensions allowed
    if os.path.splitext(filename)[1].lower() not in (".jpeg", ".jpg", ".png", ".webp"):
        return jsonify({"ok": False, "error": "Invalid file type"}), 400

    if not os.path.exists(img_path):
        return jsonify({"ok": False, "error": "File not found"}), 404

    try:
        os.remove(img_path)
        json_path = os.path.splitext(img_path)[0] + ".json"
        if os.path.exists(json_path):
            os.remove(json_path)
        # Remove day dir if now empty
        day_dir = os.path.dirname(img_path)
        if os.path.isdir(day_dir) and not os.listdir(day_dir):
            os.rmdir(day_dir)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API â€” Loved list (for reference image picker)
# ---------------------------------------------------------------------------
@app.route("/api/loved-list")
@login_required
def api_loved_list():
    """
    Returns list of loved images for the picker (no base64, only URL and meta).
    """
    result = []
    if os.path.isdir(LOVED_DIR):
        date_dirs = sorted(
            [d for d in os.listdir(LOVED_DIR)
             if os.path.isdir(os.path.join(LOVED_DIR, d))],
            reverse=True
        )
        for date_str in date_dirs:
            day_path   = os.path.join(LOVED_DIR, date_str)
            meta_files = sorted(glob.glob(os.path.join(day_path, "*.json")), reverse=True)
            for mf in meta_files:
                try:
                    with open(mf) as f:
                        meta = json.load(f)
                    # Look for the image file with any supported extension
                    base     = mf[:-5]  # rimuove ".json"
                    img_path = None
                    filename = None
                    for ext in (".jpeg", ".jpg", ".png", ".webp"):
                        candidate = base + ext
                        if os.path.exists(candidate):
                            img_path = candidate
                            filename = os.path.basename(candidate)
                            break
                    if img_path:
                        result.append({
                            "url":      f"/loved/{date_str}/{filename}",
                            "date":     date_str,
                            "filename": filename,
                            "prompt":   (meta.get("prompt") or "")[:60],
                            "model_label": meta.get("model_label", ""),
                            "imageSize":   meta.get("imageSize", ""),
                            "aspectRatio": meta.get("aspectRatio", ""),
                        })
                except Exception:
                    pass
    return jsonify(result)


# ---------------------------------------------------------------------------
# Routes â€” Elements (asset library)
# ---------------------------------------------------------------------------

@app.route("/elements/<path:filepath>")
@login_required
def serve_element_file(filepath):
    """Serve element images (model, location, prop)."""
    full_path = os.path.join(ELEMENTS_DIR, filepath)
    directory = os.path.dirname(full_path)
    filename  = os.path.basename(full_path)
    return send_from_directory(directory, filename)


@app.route("/api/elements")
@login_required
def api_elements_catalog():
    """
    Return all categories and their assets from catalog.json.
    Supporta ?category=slug e ?q=search per filtrare.
    """
    category_filter = request.args.get("category", "all")
    search_query    = request.args.get("q", "").strip().lower()
    page            = int(request.args.get("page", 1))
    per_page        = int(request.args.get("per_page", 60))
    # Filtri metadati (solo characters) â€” tutti exact-match con vocabolario canonico
    def _fset(param): return {v.strip().lower() for v in request.args.get(param,"").split(",") if v.strip()}
    f_gender     = _fset("gender")
    f_age        = _fset("age_group")
    f_ethnicity  = _fset("ethnicity")
    f_skin       = _fset("skin_tone")
    f_hair       = _fset("hair_color")
    f_hair_style = _fset("hair_style")
    f_body       = _fset("body_type")

    result_categories = []
    all_items         = []

    if not os.path.isdir(ELEMENTS_DIR):
        return jsonify({"categories": [], "items": [], "total": 0})

    for folder_name, cat_meta in ELEMENTS_CATEGORIES.items():
        folder_path  = os.path.join(ELEMENTS_DIR, folder_name)
        catalog_path = os.path.join(folder_path, "catalog.json")

        if not os.path.isdir(folder_path):
            continue

        result_categories.append({
            "slug":  cat_meta["slug"],
            "label": cat_meta["label"],
            "icon":  cat_meta["icon"],
        })

        if category_filter not in ("all", cat_meta["slug"]):
            continue

        # Priority 1: individual talent JSON files
        individual_jsons = list_talent_jsons(folder_path)
        if individual_jsons:
            raw_items = []
            for jpath in sorted(individual_jsons):
                talent = load_talent_json(jpath)
                if not talent:
                    continue
                # Derive image_path from the primary image (or the first available one)
                images = talent.get("images", [])
                primary = next((i for i in images if i.get("is_primary")), None)
                if not primary and images:
                    primary = images[0]
                if primary:
                    talent["image_path"] = primary.get("path", "")
                raw_items.append(talent)
        # Priority 2: legacy catalog.json
        elif os.path.exists(catalog_path):
            try:
                with open(catalog_path, encoding="utf-8") as f:
                    data = json.load(f)
                raw_items = data.get("talents", data.get("items", []))
            except Exception:
                raw_items = []
        else:
            # Fallback: scan images in the images/ folder
            img_dir   = os.path.join(folder_path, "images")
            raw_items = []
            if os.path.isdir(img_dir):
                for fname in sorted(os.listdir(img_dir)):
                    if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                        name = os.path.splitext(fname)[0].replace("_", " ").title()
                        raw_items.append({"id": fname, "name": name, "image_path": f"images/{fname}"})

        for item in raw_items:
            img_path = item.get("image_path", "")
            # Verify that the image exists on disk
            full_img = os.path.join(folder_path, img_path)
            if not os.path.exists(full_img):
                continue

            # Costruisci URL di servizio
            img_url = f"/elements/{folder_name}/{img_path}"

            asset = {
                "id":          item.get("id", img_path),
                "name":        item.get("name", ""),
                "category":    cat_meta["slug"],
                "cat_label":   cat_meta["label"],
                "img_url":     img_url,
                "folder":      folder_name,
                "img_path":    img_path,
                # All physical metadata for the @mention prompt
                "gender":      item.get("gender", ""),
                "ethnicity":   item.get("ethnicity", ""),
                "age_group":   item.get("age_group", ""),
                "skin_tone":   item.get("skin_tone", ""),
                "hair_color":  item.get("hair_color", ""),
                "hair_style":  item.get("hair_style", ""),
                "eye_color":   item.get("eye_color", ""),
                "body_type":   item.get("body_type", ""),
                "tags":        item.get("tags", []),
                "description": item.get("description", ""),
                "is_favorite": item.get("is_favorite", False),
                "profile":     item.get("profile", {}),
            }
            all_items.append(asset)

    # Deduplicate by id (same person with multiple images in the catalog)
    seen_ids = set()
    unique_items = []
    for it in all_items:
        if it["id"] not in seen_ids:
            seen_ids.add(it["id"])
            unique_items.append(it)

    # Filter by text search
    if search_query:
        def matches(item):
            return (search_query in item["name"].lower() or
                    search_query in item.get("description", "").lower() or
                    any(search_query in t.lower() for t in item.get("tags", [])) or
                    search_query in item.get("gender", "").lower() or
                    search_query in item.get("ethnicity", "").lower())
        unique_items = [i for i in unique_items if matches(i)]

    # Filtri metadati â€” exact match (vocabolario canonico, tutti underscored)
    def _exact(items, field, fset):
        return [i for i in items if i.get(field, "").lower() in fset] if fset else items
    unique_items = _exact(unique_items, "gender",     f_gender)
    unique_items = _exact(unique_items, "age_group",  f_age)
    unique_items = _exact(unique_items, "ethnicity",  f_ethnicity)
    unique_items = _exact(unique_items, "skin_tone",  f_skin)
    unique_items = _exact(unique_items, "hair_color", f_hair)
    unique_items = _exact(unique_items, "hair_style", f_hair_style)
    unique_items = _exact(unique_items, "body_type",  f_body)

    # Newest first, then favorites at the top
    unique_items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    unique_items.sort(key=lambda x: not x.get("is_favorite", False))

    total = len(unique_items)
    start = (page - 1) * per_page
    paged = unique_items[start:start + per_page]

    return jsonify({
        "categories": result_categories,
        "items":      paged,
        "total":      total,
        "page":       page,
        "per_page":   per_page,
        "pages":      (total + per_page - 1) // per_page
    })


@app.route("/api/elements/toggle-favorite", methods=["POST"])
@login_required
def api_elements_toggle_favorite():
    """Update is_favorite for an asset (individual JSON or catalog.json)."""
    body        = request.get_json()
    asset_id    = body.get("id")
    folder_name = body.get("folder")
    favorite    = bool(body.get("favorite", False))

    folder_path = os.path.join(ELEMENTS_DIR, folder_name)

    # Prova prima il JSON individuale
    jpath = talent_json_path(folder_path, asset_id)
    if os.path.exists(jpath):
        try:
            talent = load_talent_json(jpath)
            if talent:
                talent["is_favorite"] = favorite
                talent["updated_at"]  = datetime.now().isoformat()
                save_talent_json(jpath, talent)
                return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # Fallback: catalog.json
    catalog_path = os.path.join(folder_path, "catalog.json")
    if not os.path.exists(catalog_path):
        return jsonify({"ok": False, "error": "Talent not found"})
    try:
        with open(catalog_path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("talents", []):
            if item.get("id") == asset_id:
                item["is_favorite"] = favorite
                break
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# API - Elements: catalog migration -> individual JSON files
# ---------------------------------------------------------------------------
@app.route("/api/elements/migrate-catalog", methods=["POST"])
@login_required
def api_migrate_catalog():
    """
    Migrate catalog.json into individual JSON files (one file per talent).
    Safe: does not overwrite existing JSON files. Creates an automatic backup of catalog.json.
    """
    body        = request.get_json(silent=True) or {}
    folder_name = body.get("folder", "Model Managment")
    folder_path = os.path.join(ELEMENTS_DIR, folder_name)
    catalog_path = os.path.join(folder_path, "catalog.json")

    if not os.path.exists(catalog_path):
        return jsonify({"ok": False, "error": "catalog.json not found"})

    try:
        with open(catalog_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error reading catalog: {e}"})

    raw_items = data.get("talents", data.get("items", []))
    now_ts    = datetime.now().isoformat()

    # Deduplica per id â€” per ogni id teniamo il record con image_path valido
    seen: dict[str, dict] = {}
    for item in raw_items:
        tid = item.get("id")
        if not tid:
            continue
        img_path = item.get("image_path", "")
        full_img = os.path.join(folder_path, img_path) if img_path else ""
        if tid not in seen:
            seen[tid] = item
        elif img_path and os.path.exists(full_img) and not seen[tid].get("image_path"):
            seen[tid] = item

    created = skipped = 0
    for talent_id, item in seen.items():
        jpath = talent_json_path(folder_path, talent_id)
        if os.path.exists(jpath):
            skipped += 1
            continue

        img_path = item.get("image_path", "")
        images   = []
        if img_path and os.path.exists(os.path.join(folder_path, img_path)):
            images.append({
                "filename":   os.path.basename(img_path),
                "path":       img_path,
                "added_at":   now_ts,
                "is_primary": True,
                "analyzed":   False,
            })

        talent_data = {
            "id":          talent_id,
            "name":        item.get("name", ""),
            "gender":      item.get("gender", ""),
            "ethnicity":   item.get("ethnicity", ""),
            "age_group":   item.get("age_group", ""),
            "skin_tone":   item.get("skin_tone", ""),
            "hair_color":  item.get("hair_color", ""),
            "hair_style":  item.get("hair_style", ""),
            "eye_color":   item.get("eye_color", ""),
            "body_type":   item.get("body_type", ""),
            "description": item.get("description", ""),
            "tags":        item.get("tags", []),
            "profile":     item.get("profile", {}),
            "is_favorite": item.get("is_favorite", False),
            "images":      images,
            "created_at":  now_ts,
            "updated_at":  now_ts,
        }
        save_talent_json(jpath, talent_data)
        created += 1

    # Backup catalog.json (one time only)
    bak_path = catalog_path + ".bak"
    if not os.path.exists(bak_path):
        shutil.copy2(catalog_path, bak_path)

    return jsonify({
        "ok":      True,
        "created": created,
        "skipped": skipped,
        "total":   len(seen),
        "message": f"Migration completed: {created} created, {skipped} already existed across {len(seen)} talents."
    })


# ---------------------------------------------------------------------------
# API - Elements: image analysis with Gemini Vision
# ---------------------------------------------------------------------------
@app.route("/api/elements/analyze-image", methods=["POST"])
@login_required
def api_analyze_talent_image():
    """
    Analyze a talent image with Gemini Vision and return JSON metadata.
    Uses TALENT_ANALYSIS_MODEL (gemini-3-flash-preview) - more capable for structured JSON extraction.
    """
    config  = load_config()
    api_key = config.get("api_key", "").strip()
    if not api_key:
        return jsonify({"ok": False, "error": "API key not configured"})

    body      = request.get_json(silent=True) or {}
    image_b64 = body.get("data", "")
    mime_type = body.get("mime_type", "image/jpeg")

    if not image_b64:
        return jsonify({"ok": False, "error": "Image data missing"})

    # Normalize the image before sending it to Gemini
    try:
        image_b64, mime_type, orig_w, orig_h, proc_w, proc_h, was_resized = \
            normalize_image_b64(image_b64, mime_type)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Image pre-processing error: {e}"})

    vocab_block = _build_vocab_prompt_block()
    analysis_prompt = (
        "You are a professional talent catalog specialist. Analyze this portrait photo carefully and extract structured metadata.\n"
        "Your task: fill in EVERY field â€” never leave anything empty or use values outside the allowed lists.\n\n"
        f"{vocab_block}\n\n"
        "Additional field rules:\n"
        "- name: INVENT a realistic first+last name that fits the person's apparent ethnicity and vibe "
        "(e.g. Sofia Esposito, Kai Nakamura, Amara Diallo, Luca Ferretti, Yuki Tanaka, Zara Osei)\n"
        "- description: 2 precise sentences for AI image generation â€” describe face shape, skin quality, "
        "distinctive features (nose, lips, jawline, cheekbones), eye shape, expression, overall aesthetic vibe\n"
        "- tags: JSON array of 4â€“6 lowercase, single-word or hyphenated tags useful for searching "
        "(e.g. [\"editorial\", \"beauty\", \"runway\", \"high-fashion\", \"dark-skin\", \"versatile\"])\n\n"
        "CRITICAL: You MUST use ONLY the exact string values listed above. "
        "Do NOT invent new values, do NOT use variations, plurals, or spaces instead of underscores.\n\n"
        "Return ONLY a valid JSON object â€” no markdown fences, no extra text, no comments:\n"
        "{\n"
        '  "name": "...",\n'
        '  "gender": "...",\n'
        '  "ethnicity": "...",\n'
        '  "age_group": "...",\n'
        '  "skin_tone": "...",\n'
        '  "hair_color": "...",\n'
        '  "hair_style": "...",\n'
        '  "eye_color": "...",\n'
        '  "body_type": "...",\n'
        '  "description": "...",\n'
        '  "tags": ["...", "..."]\n'
        "}"
    )

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": image_b64}},
                {"text": analysis_prompt}
            ]
        }],
        "generationConfig": {
            "temperature":     0.2,
            "maxOutputTokens": 2048,
        }
    }

    try:
        resp = requests.post(
            GEMINI_BASE_URL.format(model=TALENT_ANALYSIS_MODEL),
            params={"key": api_key},
            json=payload,
            timeout=60
        )
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Image analysis timeout (60s)"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    if resp.status_code != 200:
        try:
            err_body = resp.json()
            err_msg  = err_body.get("error", {}).get("message", f"HTTP {resp.status_code}")
        except Exception:
            err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
        return jsonify({"ok": False, "error": err_msg})

    result   = resp.json()
    raw_text = ""
    # Estrae testo dal primo candidato con parti testo
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "text" in part:
                raw_text = part["text"].strip()
                break
        if raw_text:
            break

    # Calcola costo Vision da usageMetadata (token-based)
    usage         = result.get("usageMetadata", {})
    input_tokens  = usage.get("promptTokenCount", 0)
    output_tokens = usage.get("candidatesTokenCount", 0)
    vp            = VISION_MODELS_INFO.get(TALENT_ANALYSIS_MODEL, {})
    vision_cost   = round(
        input_tokens  * vp.get("input_per_1m",  0.075) / 1_000_000 +
        output_tokens * vp.get("output_per_1m", 0.30)  / 1_000_000,
        8
    )
    # Registra la chiamata nelle statistiche
    cfg_v  = load_config()
    sv     = cfg_v.setdefault("stats", DEFAULT_CONFIG["stats"].copy())
    sv["vision_calls"]    = sv.get("vision_calls",    0) + 1
    sv["vision_cost_usd"] = round(sv.get("vision_cost_usd", 0.0) + vision_cost, 8)
    vlog   = sv.setdefault("vision_log", [])
    vlog.insert(0, {
        "ts":           utc_now_iso(),
        "model":        TALENT_ANALYSIS_MODEL,
        "input_tok":    input_tokens,
        "output_tok":   output_tokens,
        "cost":         vision_cost,
    })
    if len(vlog) > 200:
        sv["vision_log"] = vlog[:200]
    save_config(cfg_v)

    if not raw_text:
        return jsonify({"ok": False, "error": "Empty response from Gemini", "raw": str(result)[:300]})

    # Parsing JSON robusto: prova diretta, poi estrai il primo { ... } block
    metadata = None
    # 1) Remove any markdown code fences ```json ... ```
    cleaned = re.sub(r"```(?:json)?\s*", "", raw_text).replace("```", "").strip()
    for candidate_text in [cleaned, raw_text]:
        try:
            metadata = json.loads(candidate_text)
            break
        except json.JSONDecodeError:
            pass
        # Look for the largest JSON block
        match = re.search(r"\{[\s\S]*\}", candidate_text)
        if match:
            try:
                metadata = json.loads(match.group())
                break
            except json.JSONDecodeError:
                pass

    if metadata is None:
        return jsonify({"ok": False, "error": "Could not extract JSON from response", "raw": raw_text[:500]})

    # Normalize missing keys with empty values
    defaults = {"name":"","gender":"","ethnicity":"","age_group":"","skin_tone":"",
                "hair_color":"","hair_style":"","eye_color":"","body_type":"","description":"","tags":[]}
    for k, v in defaults.items():
        if k not in metadata:
            metadata[k] = v

    return jsonify({
        "ok":         True,
        "metadata":   metadata,
        "raw_text":   raw_text,
        "usage":      {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": vision_cost},
        "image_info": {"orig_w": orig_w, "orig_h": orig_h,
                       "proc_w": proc_w, "proc_h": proc_h, "resized": was_resized},
    })


# ---------------------------------------------------------------------------
# API - Elements: save new talent
# ---------------------------------------------------------------------------
@app.route("/api/elements/save-talent", methods=["POST"])
@login_required
def api_save_talent():
    """
    Save a new talent: image with an incremental filename + JSON metadata.
    If the talent (slug) already exists, append the new image to images[].
    """
    body        = request.get_json(silent=True) or {}
    image_b64   = body.get("image_data", "")
    mime_type   = body.get("mime_type", "image/jpeg")
    folder_name = body.get("folder", "Model Managment")
    metadata    = body.get("metadata", {})

    if not image_b64:
        return jsonify({"ok": False, "error": "Image data missing"})

    folder_path = os.path.join(ELEMENTS_DIR, folder_name)
    if not os.path.isdir(folder_path):
        return jsonify({"ok": False, "error": f"Folder '{folder_name}' not found"})

    name = metadata.get("name", "talent").strip() or "talent"
    slug = name_to_slug(name)

    # Normalize image (resize if >4000px, convert to JPG 90%)
    try:
        image_b64, mime_type, _, _, _, _, _ = normalize_image_b64(image_b64, mime_type)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Image pre-processing error: {e}"})

    # Numero progressivo immagine â€” sempre .jpg dopo normalizzazione
    num      = get_next_image_number(folder_path, slug)
    img_file = f"{slug}_{num:03d}.jpg"
    img_full = os.path.join(folder_path, img_file)

    # Save image to disk
    try:
        img_bytes = base64.b64decode(image_b64)
        with open(img_full, "wb") as f:
            f.write(img_bytes)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Image save error: {e}"})

    now_ts     = datetime.now().isoformat()
    jpath      = talent_json_path(folder_path, slug)
    new_img    = {
        "filename":   img_file,
        "path":       img_file,
        "added_at":   now_ts,
        "is_primary": not os.path.exists(jpath),   # first image = primary
        "analyzed":   True,
    }

    if os.path.exists(jpath):
        # Talent esistente â†’ aggiungi immagine
        talent = load_talent_json(jpath)
        if talent:
            talent["images"].append(new_img)
            talent["updated_at"] = now_ts
            save_talent_json(jpath, talent)
    else:
        # New talent
        talent = {
            "id":          slug,
            "name":        metadata.get("name", name),
            "gender":      metadata.get("gender", ""),
            "ethnicity":   metadata.get("ethnicity", ""),
            "age_group":   metadata.get("age_group", ""),
            "skin_tone":   metadata.get("skin_tone", ""),
            "hair_color":  metadata.get("hair_color", ""),
            "hair_style":  metadata.get("hair_style", ""),
            "eye_color":   metadata.get("eye_color", ""),
            "body_type":   metadata.get("body_type", ""),
            "description": metadata.get("description", ""),
            "tags":        metadata.get("tags", []),
            "profile":     {},
            "is_favorite": False,
            "images":      [new_img],
            "created_at":  now_ts,
            "updated_at":  now_ts,
        }
        save_talent_json(jpath, talent)

    return jsonify({
        "ok":        True,
        "talent_id": slug,
        "image_url": f"/elements/{folder_name}/{img_file}",
        "is_new":    len(talent.get("images", [])) == 1,
    })


# ---------------------------------------------------------------------------
# API â€” Config / Key
# ---------------------------------------------------------------------------
@app.route("/api/save-config", methods=["POST"])
@login_required
def api_save_config():
    data = request.get_json() or {}
    config = load_config()
    if "api_key" in data:
        config["api_key"] = data["api_key"].strip()
    if "fal_api_key" in data:
        config["fal_api_key"] = data["fal_api_key"].strip()
    if "byteplus_api_key" in data:
        config["byteplus_api_key"] = data["byteplus_api_key"].strip()
        config["seedream_api_key"] = data["byteplus_api_key"].strip()
    if "seedream_api_key" in data:
        config["byteplus_api_key"] = data["seedream_api_key"].strip()
        config["seedream_api_key"] = data["seedream_api_key"].strip()
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/verify-fal-key", methods=["POST"])
@app.route("/api/verify-seedream-key", methods=["POST"])
@login_required
def api_verify_fal_key():
    data = request.get_json() or {}
    key = (data.get("fal_api_key") or data.get("seedream_api_key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "Fal API key is empty"})
    payload = {
        "prompt": "Fal provider verification image",
        "image_size": "auto_2K",
        "num_images": 1,
        "max_images": 1,
        "sync_mode": True,
        "enable_safety_checker": True,
    }
    headers = {
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(f"{FAL_BASE_URL}/{FAL_SEEDREAM_45_TEXT_ID}", headers=headers, json=payload, timeout=45)
        if resp.status_code == 200:
            return jsonify({"ok": True, "message": "Valid Fal key and model access confirmed."})
        return jsonify({"ok": False, "error": extract_fal_error(resp)})
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Connection timeout"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/verify-byteplus-key", methods=["POST"])
@login_required
def api_verify_byteplus_key():
    data = request.get_json() or {}
    key = (data.get("byteplus_api_key") or data.get("seedream_api_key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "BytePlus API key is empty"})
    payload = {
        "model": BYTEPLUS_SEEDREAM_45_MODEL_ID,
        "prompt": "BytePlus provider verification image",
        "sequential_image_generation": "disabled",
        "response_format": "url",
        "size": "2K",
        "stream": False,
        "watermark": False,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(BYTEPLUS_BASE_URL, headers=headers, json=payload, timeout=45)
        if resp.status_code == 200:
            return jsonify({"ok": True, "message": "Valid BytePlus key and Seedream access confirmed."})
        return jsonify({"ok": False, "error": extract_byteplus_error(resp)})
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Connection timeout"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/verify-key", methods=["POST"])
@login_required
def api_verify_key():
    data = request.get_json()
    key  = data.get("api_key", "").strip()
    if not key:
        return jsonify({"ok": False, "error": "API key is empty"})
    try:
        resp = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key}, timeout=10
        )
        if resp.status_code == 200:
            models_list = resp.json().get("models", [])
            return jsonify({"ok": True, "message": f"Valid key. {len(models_list)} models available."})
        elif resp.status_code == 400:
            return jsonify({"ok": False, "error": "Invalid API key (400)"})
        elif resp.status_code == 403:
            return jsonify({"ok": False, "error": "Access denied â€” check billing is active (403)"})
        else:
            return jsonify({"ok": False, "error": f"HTTP error {resp.status_code}"})
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Connection timeout"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# API â€” Generate (con supporto immagini di riferimento)
# ---------------------------------------------------------------------------
def run_gemini_generation_job(body: dict, api_key: str) -> dict:
    body = normalize_generation_request(body)
    model_id     = body.get("model", "gemini-3.1-flash-image-preview")
    image_size   = body.get("imageSize", "1K")
    num_images   = max(1, min(int(body.get("numberOfImages", 1)), 4))
    temperature  = float(body.get("temperature", 1.0))
    top_p        = float(body.get("topP", 0.95))
    thinking_lvl = body.get("thinkingLevel", "Minimal")
    use_search   = bool(body.get("useSearch", False))
    gemini_safety_settings, gemini_safety_preset = build_gemini_safety_settings(body.get("geminiSafetyPreset", "default"))
    output_mode  = body.get("outputMode", "images_text")
    ref_images   = body.get("refImages", [])
    aspect_ratio = body.get("aspectRatio", "1:1")
    seed_mode    = normalize_seed_mode(body.get("seedMode", "random"))
    seed_value   = coerce_seed_value(body.get("seedValue", 1))
    actual_seed  = seed_value if seed_mode != "random" else random.randint(1, MAX_SEED_VALUE)

    raw_prompt = body.get("prompt", "")
    if isinstance(raw_prompt, dict):
        prompt = json.dumps(raw_prompt, ensure_ascii=False, indent=2)
    else:
        prompt = str(raw_prompt).strip()

    if prompt.startswith("{"):
        try:
            prompt_obj = json.loads(prompt)
            ar_from_prompt = (prompt_obj.get("composition", {}) or {}).get("aspect_ratio", "")
            if ar_from_prompt and aspect_ratio == "1:1":
                aspect_ratio = ar_from_prompt
        except (json.JSONDecodeError, AttributeError):
            pass

    if not prompt:
        raise ValueError("Please enter a prompt")
    if model_id not in MODELS_INFO:
        raise ValueError("Invalid model")

    model_info = MODELS_INFO[model_id]
    max_ref = model_info["max_ref_images"]
    if ref_images and max_ref == 0:
        raise ValueError(f"{model_info['label']} does not support reference images.")
    ref_images = [
        {
            "mime_type": img.get("mime_type", "image/png"),
            "data": img.get("data", ""),
            "name": img.get("name", ""),
        }
        for img in (ref_images[:max_ref] if isinstance(ref_images, list) else [])
        if isinstance(img, dict) and img.get("data")
    ]

    parts = []
    for img in ref_images:
        parts.append({
            "inlineData": {
                "mimeType": img.get("mime_type", "image/png"),
                "data": img.get("data", "")
            }
        })
    parts.append({"text": prompt})

    modalities = ["IMAGE"] if output_mode == "images_only" else ["TEXT", "IMAGE"]
    image_config = {"aspectRatio": aspect_ratio}
    if model_id == "gemini-3.1-flash-image-preview":
        image_config["imageSize"] = image_size

    gen_config = {
        "responseModalities": modalities,
        "imageConfig": image_config,
        "temperature": temperature,
        "topP": top_p,
        "maxOutputTokens": 65536,
    }
    if model_id == "gemini-3.1-flash-image-preview":
        thinking_budget_map = {"Minimal": 0, "High": 8192, "Dynamic": -1}
        gen_config["thinkingConfig"] = {
            "thinkingBudget": thinking_budget_map.get(thinking_lvl, 0)
        }

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen_config,
    }
    if gemini_safety_settings:
        payload["safetySettings"] = gemini_safety_settings
    if use_search:
        payload["tools"] = [{"googleSearch": {}}]

    all_responses = []
    for _ in range(num_images):
        try:
            response = requests.post(
                GEMINI_BASE_URL.format(model=model_id),
                params={"key": api_key},
                json=payload,
                timeout=120,
            )
            all_responses.append(response)
        except requests.exceptions.Timeout as exc:
            raise TimeoutError("Timeout: generation took too long.") from exc
        except Exception as exc:
            raise RuntimeError(f"Network error: {exc}") from exc

    for response in all_responses:
        if response.status_code != 200:
            try:
                err_msg = response.json().get("error", {}).get("message", f"HTTP {response.status_code}")
            except Exception:
                err_msg = f"HTTP {response.status_code}"
            raise RuntimeError(err_msg)

    images = []
    text_parts = []
    response_issues = []
    for response in all_responses:
        result = response.json()
        response_images_before = len(images)
        for candidate in result.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "inlineData" in part:
                    img_data = part["inlineData"]
                    images.append({
                        "mime_type": img_data.get("mimeType", "image/png"),
                        "data": img_data.get("data", "")
                    })
                elif "text" in part:
                    text_parts.append(part["text"])
        if len(images) == response_images_before:
            response_issues.append(
                summarize_generate_response_issue(
                    result,
                    safety_preset=gemini_safety_preset,
                    safety_settings_sent=bool(gemini_safety_settings),
                )
            )

    if not images:
        issue_entry = next((item for item in response_issues if item and item[0]), None)
        if issue_entry:
            issue_message, issue_debug = issue_entry
        else:
            issue_message, issue_debug = (
                "Gemini returned no image for this request.",
                {
                    "provider": "gemini",
                    "safetyPreset": gemini_safety_preset,
                    "safetySettingsSent": bool(gemini_safety_settings),
                    "summary": "Gemini returned no image for this request.",
                    "candidates": [],
                },
            )
        raise GenerationDebugError(issue_message, issue_debug)

    png_images = []
    for img in images:
        try:
            png_b64, png_mime = convert_image_b64_to_png(
                img.get("data", ""),
                img.get("mime_type", "image/png")
            )
            png_images.append({
                "mime_type": png_mime,
                "data": png_b64,
            })
        except Exception:
            png_images.append(img)
    images = png_images

    price_per_image = PRICING.get(model_id, {}).get(image_size, 0.0)
    cost = price_per_image * len(images)
    params_meta = {
        "model": model_id,
        "modelFamily": body.get("modelFamily", model_info.get("family", "")),
        "model_label": model_info["label"],
        "provider": body.get("provider", model_info.get("provider", "gemini")),
        "provider_label": model_info.get("provider_label", PROVIDER_LABELS.get(body.get("provider", "gemini"), "Gemini")),
        "imageSize": image_size,
        "aspectRatio": aspect_ratio,
        "temperature": temperature,
        "topP": top_p,
        "thinkingLevel": thinking_lvl,
        "useSearch": use_search,
        "geminiSafetyPreset": gemini_safety_preset,
        "outputMode": output_mode,
        "prompt": prompt,
        "ref_count": len(ref_images),
        "seedMode": seed_mode,
        "seedValue": actual_seed,
    }
    return {
        "ok": True,
        "images": images,
        "text": "\n".join(text_parts),
        "cost": round(cost, 4),
        "model_label": model_info["label"],
        "params": params_meta,
        "_input_ref_images": ref_images,
    }


def persist_generation_result(result: dict):
    config = load_config()
    stats  = config.setdefault("stats", DEFAULT_CONFIG["stats"].copy())
    stats["total_requests"] = stats.get("total_requests", 0) + 1
    stats["total_images"]   = stats.get("total_images", 0) + len(result.get("images", []))
    stats["total_cost_usd"] = round(stats.get("total_cost_usd", 0.0) + result.get("cost", 0.0), 6)
    params = result.get("params", {})
    raw_ref_images = result.pop("_input_ref_images", [])
    log_entry = {
        "ts": utc_now_iso(),
        "model": params.get("model", ""),
        "provider": params.get("provider", ""),
        "size": params.get("imageSize", ""),
        "aspect": params.get("aspectRatio", ""),
        "n": len(result.get("images", [])),
        "ref_n": params.get("ref_count", 0),
        "cost": round(result.get("cost", 0.0), 4),
        "prompt_preview": params.get("prompt", "")[:60],
    }
    log = stats.setdefault("requests_log", [])
    log.insert(0, log_entry)
    stats["requests_log"] = log[:50]
    save_config(config)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S%f")[:12]
    archived_refs = build_reference_archive_entries(raw_ref_images, date_str, time_str)
    params["refArchive"] = archived_refs
    params["ref_count"] = len(archived_refs)
    result["params"] = params

    gen_day_dir = os.path.join(GENERATIONS_DIR, date_str)
    os.makedirs(gen_day_dir, exist_ok=True)
    for g_idx, img in enumerate(result.get("images", [])):
        basename = f"{time_str}_{g_idx}"
        try:
            png_b64, png_mime = convert_image_b64_to_png(
                img.get("data", ""),
                img.get("mime_type", "image/png")
            )
            img["data"] = png_b64
            img["mime_type"] = png_mime
            img["gen_date"] = date_str
            img["gen_filename"] = f"{basename}.png"
            img_path = os.path.join(gen_day_dir, f"{basename}.png")
            meta_path = os.path.join(gen_day_dir, f"{basename}.json")
            with open(img_path, "wb") as fh:
                fh.write(base64.b64decode(png_b64))
            gen_meta = dict(params)
            gen_meta.update({
                "generated_at": now.isoformat(),
                "mime_type": png_mime,
                "filename": os.path.basename(img_path),
                "text": result.get("text", "") if g_idx == 0 else "",
            })
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(gen_meta, fh, indent=2, ensure_ascii=False)
        except Exception:
            pass
    return result


def run_fal_seedream_generation_job(body: dict, api_key: str) -> dict:
    body = normalize_generation_request(body)
    model_id = body.get("model", FAL_SEEDREAM_45_TEXT_ID)
    image_size = body.get("imageSize", "2K")
    num_images = max(1, min(int(body.get("numberOfImages", 1)), 4))
    aspect_ratio = body.get("aspectRatio", "1:1")
    ref_images = body.get("refImages", [])
    enable_safety_checker = bool(body.get("falSafetyChecker", True))
    seed_mode = normalize_seed_mode(body.get("seedMode", "random"))
    seed_value = coerce_seed_value(body.get("seedValue", 1))

    raw_prompt = body.get("prompt", "")
    if isinstance(raw_prompt, dict):
        prompt = json.dumps(raw_prompt, ensure_ascii=False, indent=2)
    else:
        prompt = str(raw_prompt).strip()

    if not prompt:
        raise ValueError("Please enter a prompt")
    if model_id not in MODELS_INFO:
        raise ValueError("Invalid model")

    model_info = MODELS_INFO[model_id]
    max_ref = model_info["max_ref_images"]
    if ref_images and max_ref == 0:
        raise ValueError(f"{model_info['label']} does not support reference images.")
    ref_images = [
        {
            "mime_type": img.get("mime_type", "image/png"),
            "data": img.get("data", ""),
            "name": img.get("name", ""),
        }
        for img in (ref_images[:max_ref] if isinstance(ref_images, list) else [])
        if isinstance(img, dict) and img.get("data")
    ]

    endpoint = build_fal_seedream_endpoint(model_id, bool(ref_images))
    payload = {
        "prompt": prompt,
        "image_size": build_fal_seedream_image_size(model_id, image_size),
        "num_images": num_images,
        "max_images": 1,
        "sync_mode": True,
        "enable_safety_checker": enable_safety_checker,
    }
    if ref_images:
        payload["image_urls"] = build_data_uri_ref_inputs(ref_images)

    actual_seed = None
    if seed_mode != "random":
        actual_seed = seed_value
        payload["seed"] = actual_seed

    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(f"{FAL_BASE_URL}/{endpoint}", headers=headers, json=payload, timeout=240)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timeout: Fal Seedream generation took too long.") from exc
    except Exception as exc:
        raise RuntimeError(f"Network error: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(extract_fal_error(response))

    result = response.json()
    returned_seed = result.get("seed") if isinstance(result, dict) else None
    items = result.get("images") or result.get("data") or []
    images = []
    for item in items:
        if not isinstance(item, dict):
            continue
        decoded = decode_fal_image_result(item)
        if decoded:
            images.append(decoded)

    if not images:
        raise RuntimeError("Fal Seedream returned no image for this request.")

    png_images = []
    for img in images:
        try:
            png_b64, png_mime = convert_image_b64_to_png(img.get("data", ""), img.get("mime_type", "image/png"))
            png_images.append({"mime_type": png_mime, "data": png_b64})
        except Exception:
            png_images.append(img)

    price_per_image = PRICING.get(model_id, {}).get(image_size, 0.0)
    cost = price_per_image * len(png_images)
    params_meta = {
        "model": model_id,
        "modelFamily": body.get("modelFamily", model_info.get("family", "")),
        "model_label": model_info["label"],
        "provider": body.get("provider", model_info.get("provider", "fal")),
        "provider_label": model_info.get("provider_label", PROVIDER_LABELS.get(body.get("provider", "fal"), "Fal")),
        "imageSize": image_size,
        "aspectRatio": aspect_ratio,
        "temperature": float(body.get("temperature", 1.0)),
        "topP": float(body.get("topP", 0.95)),
        "thinkingLevel": body.get("thinkingLevel", "Minimal"),
        "useSearch": bool(body.get("useSearch", False)),
        "outputMode": body.get("outputMode", "images_only"),
        "prompt": prompt,
        "ref_count": len(ref_images),
        "seedMode": seed_mode,
        "seedValue": int(returned_seed if returned_seed is not None else actual_seed if actual_seed is not None else seed_value),
        "falSafetyChecker": enable_safety_checker,
    }
    return {
        "ok": True,
        "images": png_images,
        "text": "",
        "cost": round(cost, 4),
        "model_label": model_info["label"],
        "params": params_meta,
        "_input_ref_images": ref_images,
    }


def run_fal_nano_banana_generation_job(body: dict, api_key: str) -> dict:
    body = normalize_generation_request(body)
    model_id = body.get("model", FAL_NANO_BANANA_2_TEXT_ID)
    image_size = body.get("imageSize", "1K")
    num_images = max(1, min(int(body.get("numberOfImages", 1)), 4))
    aspect_ratio = body.get("aspectRatio", "1:1")
    ref_images = body.get("refImages", [])
    use_search = bool(body.get("useSearch", False))
    fal_safety_tolerance = normalize_fal_safety_tolerance(body.get("falSafetyTolerance", 4))
    seed_mode = normalize_seed_mode(body.get("seedMode", "random"))
    seed_value = coerce_seed_value(body.get("seedValue", 1))

    raw_prompt = body.get("prompt", "")
    if isinstance(raw_prompt, dict):
        prompt = json.dumps(raw_prompt, ensure_ascii=False, indent=2)
    else:
        prompt = str(raw_prompt).strip()

    if not prompt:
        raise ValueError("Please enter a prompt")
    if model_id not in MODELS_INFO:
        raise ValueError("Invalid model")

    model_info = MODELS_INFO[model_id]
    max_ref = model_info["max_ref_images"]
    if ref_images and max_ref == 0:
        raise ValueError(f"{model_info['label']} does not support reference images.")
    ref_images = [
        {
            "mime_type": img.get("mime_type", "image/png"),
            "data": img.get("data", ""),
            "name": img.get("name", ""),
        }
        for img in (ref_images[:max_ref] if isinstance(ref_images, list) else [])
        if isinstance(img, dict) and img.get("data")
    ]

    endpoint = build_fal_nano_banana_endpoint(model_id, bool(ref_images))
    payload = {
        "prompt": prompt,
        "num_images": num_images,
        "resolution": build_fal_nano_banana_resolution(model_id, image_size),
        "aspect_ratio": aspect_ratio,
        "output_format": "png",
        "sync_mode": True,
        "safety_tolerance": fal_safety_tolerance,
    }
    if ref_images:
        payload["image_urls"] = build_data_uri_ref_inputs(ref_images)
    if use_search:
        payload["enable_web_search"] = True
    actual_seed = None
    if seed_mode != "random":
        actual_seed = seed_value
        payload["seed"] = actual_seed

    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(f"{FAL_BASE_URL}/{endpoint}", headers=headers, json=payload, timeout=240)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timeout: Fal Nano Banana generation took too long.") from exc
    except Exception as exc:
        raise RuntimeError(f"Network error: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(extract_fal_error(response))

    result = response.json()
    returned_seed = result.get("seed") if isinstance(result, dict) else None
    items = result.get("images") or result.get("data") or []
    images = []
    for item in items:
        if not isinstance(item, dict):
            continue
        decoded = decode_fal_image_result(item)
        if decoded:
            images.append(decoded)

    if not images:
        raise RuntimeError("Fal Nano Banana returned no image for this request.")

    png_images = []
    for img in images:
        try:
            png_b64, png_mime = convert_image_b64_to_png(img.get("data", ""), img.get("mime_type", "image/png"))
            png_images.append({"mime_type": png_mime, "data": png_b64})
        except Exception:
            png_images.append(img)

    price_per_image = PRICING.get(model_id, {}).get(image_size, 0.0)
    cost = price_per_image * len(png_images)
    params_meta = {
        "model": model_id,
        "modelFamily": body.get("modelFamily", model_info.get("family", "")),
        "model_label": model_info["label"],
        "provider": body.get("provider", model_info.get("provider", "fal")),
        "provider_label": model_info.get("provider_label", PROVIDER_LABELS.get(body.get("provider", "fal"), "Fal")),
        "imageSize": image_size,
        "aspectRatio": aspect_ratio,
        "temperature": float(body.get("temperature", 1.0)),
        "topP": float(body.get("topP", 0.95)),
        "thinkingLevel": body.get("thinkingLevel", "Minimal"),
        "useSearch": use_search,
        "outputMode": body.get("outputMode", "images_only"),
        "prompt": prompt,
        "ref_count": len(ref_images),
        "seedMode": seed_mode,
        "seedValue": int(returned_seed if returned_seed is not None else actual_seed if actual_seed is not None else seed_value),
        "falSafetyTolerance": fal_safety_tolerance,
    }
    text_value = ""
    if isinstance(result, dict):
        text_value = str(result.get("description") or result.get("text") or "")
    return {
        "ok": True,
        "images": png_images,
        "text": text_value,
        "cost": round(cost, 4),
        "model_label": model_info["label"],
        "params": params_meta,
        "_input_ref_images": ref_images,
    }


def run_byteplus_seedream_generation_job(body: dict, api_key: str) -> dict:
    body = normalize_generation_request(body)
    model_id = body.get("model", BYTEPLUS_SEEDREAM_45_MODEL_ID)
    image_size = normalize_seedream_size(body.get("imageSize", "2K"))
    num_images = max(1, min(int(body.get("numberOfImages", 1)), 4))
    aspect_ratio = body.get("aspectRatio", "1:1")
    ref_images = body.get("refImages", [])
    seed_mode = normalize_seed_mode(body.get("seedMode", "random"))
    seed_value = coerce_seed_value(body.get("seedValue", 1))

    raw_prompt = body.get("prompt", "")
    if isinstance(raw_prompt, dict):
        prompt = json.dumps(raw_prompt, ensure_ascii=False, indent=2)
    else:
        prompt = str(raw_prompt).strip()

    if not prompt:
        raise ValueError("Please enter a prompt")
    if model_id not in MODELS_INFO:
        raise ValueError("Invalid model")

    model_info = MODELS_INFO[model_id]
    max_ref = model_info["max_ref_images"]
    ref_images = [
        {
            "mime_type": img.get("mime_type", "image/png"),
            "data": img.get("data", ""),
            "name": img.get("name", ""),
        }
        for img in (ref_images[:max_ref] if isinstance(ref_images, list) else [])
        if isinstance(img, dict) and img.get("data")
    ]

    payload = {
        "model": BYTEPLUS_SEEDREAM_45_MODEL_ID,
        "prompt": prompt,
        "sequential_image_generation": "auto" if num_images > 1 else "disabled",
        "response_format": "url",
        "size": image_size,
        "stream": False,
        "watermark": False,
    }
    if num_images > 1:
        payload["sequential_image_generation_options"] = {"max_images": num_images}
    if ref_images:
        ref_inputs = build_byteplus_seedream_ref_inputs(ref_images)
        payload["image"] = ref_inputs[0] if len(ref_inputs) == 1 else ref_inputs
    if seed_mode != "random":
        payload["seed"] = seed_value

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(BYTEPLUS_BASE_URL, headers=headers, json=payload, timeout=240)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timeout: BytePlus Seedream generation took too long.") from exc
    except Exception as exc:
        raise RuntimeError(f"Network error: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(extract_byteplus_error(response))

    result = response.json()
    items = result.get("data") or result.get("images") or []
    images = []
    for item in items:
        if isinstance(item, dict):
            decoded = decode_fal_image_result(item)
            if decoded:
                images.append(decoded)
        elif isinstance(item, str):
            decoded = decode_fal_image_result({"url": item})
            if decoded:
                images.append(decoded)

    if not images:
        raise RuntimeError("BytePlus Seedream returned no image for this request.")

    price_per_image = PRICING.get(model_id, {}).get(image_size, 0.0)
    cost = price_per_image * len(images)
    params_meta = {
        "model": model_id,
        "modelFamily": body.get("modelFamily", model_info.get("family", "")),
        "model_label": model_info["label"],
        "provider": body.get("provider", model_info.get("provider", "byteplus")),
        "provider_label": model_info.get("provider_label", PROVIDER_LABELS.get(body.get("provider", "byteplus"), "BytePlus")),
        "byteplusSafetyMode": str(body.get("byteplusSafetyMode", "platform_default") or "platform_default"),
        "imageSize": image_size,
        "aspectRatio": aspect_ratio,
        "temperature": float(body.get("temperature", 1.0)),
        "topP": float(body.get("topP", 0.95)),
        "thinkingLevel": body.get("thinkingLevel", "Minimal"),
        "useSearch": bool(body.get("useSearch", False)),
        "outputMode": body.get("outputMode", "images_only"),
        "prompt": prompt,
        "ref_count": len(ref_images),
        "seedMode": seed_mode,
        "seedValue": seed_value,
    }
    return {
        "ok": True,
        "images": images,
        "text": "",
        "cost": round(cost, 4),
        "model_label": model_info["label"],
        "params": params_meta,
        "_input_ref_images": ref_images,
    }


def run_generation_job(body: dict, config: dict) -> dict:
    payload = normalize_generation_request(body)
    model_id = payload.get("model", "gemini-3.1-flash-image-preview")
    if model_id not in MODELS_INFO:
        raise ValueError("Invalid model")
    provider = payload.get("provider") or MODELS_INFO[model_id].get("provider", "gemini")
    family = payload.get("modelFamily") or MODELS_INFO[model_id].get("family", "")

    if provider == "gemini":
        gemini_key = (config.get("api_key", "") or "").strip()
        if not gemini_key:
            raise ValueError("Gemini API key not configured. Go to Settings.")
        return run_gemini_generation_job(payload, gemini_key)

    if provider == "fal":
        fal_key = (config.get("fal_api_key", "") or "").strip()
        if not fal_key:
            raise ValueError("Fal API key not configured. Go to Settings.")
        if family.startswith("seedream"):
            return run_fal_seedream_generation_job(payload, fal_key)
        return run_fal_nano_banana_generation_job(payload, fal_key)

    if provider == "byteplus":
        byteplus_key = (config.get("byteplus_api_key", "") or config.get("seedream_api_key", "") or "").strip()
        if not byteplus_key:
            raise ValueError("BytePlus API key not configured. Go to Settings.")
        return run_byteplus_seedream_generation_job(payload, byteplus_key)

    raise ValueError("Unsupported provider")


@app.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    config = load_config()
    body = request.get_json(silent=True) or {}
    try:
        result = run_generation_job(body, config)
        persist_generation_result(result)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except TimeoutError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except GenerationDebugError as exc:
        return jsonify({"ok": False, "error": str(exc), "debug": exc.debug})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/workbench/run", methods=["POST"])
@login_required
def api_workbench_run():
    config = load_config()

    body = request.get_json(silent=True) or {}
    run_uuid = str(body.get("run_uuid", "")).strip()
    task_run = get_task_run(run_uuid)
    if not task_run:
        return jsonify({"ok": False, "error": "Task run not found."}), 404

    plan = task_run.get("plan") or {}
    execution = dict(plan.get("execution_target") or {})
    payload = {
        "model": execution.get("model", task_run.get("recommended_model", "gemini-3.1-flash-image-preview")),
        "prompt": plan.get("prompt", task_run.get("prompt_text", "")),
        "aspectRatio": execution.get("aspectRatio", task_run.get("aspect_ratio", "1:1")),
        "imageSize": execution.get("imageSize", task_run.get("image_size", "1K")),
        "numberOfImages": int(body.get("numberOfImages", 1) or 1),
        "temperature": float(execution.get("temperature", 1.0)),
        "topP": float(execution.get("topP", 0.95)),
        "thinkingLevel": body.get("thinkingLevel", "Minimal"),
        "useSearch": bool(body.get("useSearch", False)),
        "outputMode": body.get("outputMode", "images_text"),
        "refImages": body.get("refImages", []),
    }
    try:
        result = run_generation_job(payload, config)
        persist_generation_result(result)
        update_task_run_after_generation(run_uuid, generation_result=result)
        fresh_report = get_workbench_report()
        task_state = get_task_run(run_uuid)
        return jsonify({
            "ok": True,
            "result": result,
            "report": fresh_report,
            "task_run": task_state,
        })
    except Exception as exc:
        update_task_run_after_generation(run_uuid, generation_result=None, error=str(exc))
        return jsonify({"ok": False, "error": str(exc), "report": get_workbench_report()}), 500


@app.route("/api/generations")
@login_required
def api_generations():
    """
    Returns the last N saved generations for gallery reload on restart.
    Each item includes a local image URL plus prompt metadata.
    """
    MAX_LOAD = 100   # load up to last 100 images on startup
    result   = []
    if os.path.isdir(GENERATIONS_DIR):
        date_dirs = sorted(
            [d for d in os.listdir(GENERATIONS_DIR)
             if os.path.isdir(os.path.join(GENERATIONS_DIR, d))],
            reverse=True
        )
        for date_str in date_dirs:
            if len(result) >= MAX_LOAD:
                break
            day_path   = os.path.join(GENERATIONS_DIR, date_str)
            meta_files = sorted(glob.glob(os.path.join(day_path, "*.json")), reverse=True)
            for mf in meta_files:
                if len(result) >= MAX_LOAD:
                    break
                try:
                    with open(mf, encoding="utf-8") as f:
                        meta = json.load(f)
                    base     = mf[:-5]
                    img_path = None
                    for ext in (".jpeg", ".jpg", ".png", ".webp"):
                        candidate = base + ext
                        if os.path.exists(candidate):
                            img_path = candidate
                            break
                    if not img_path:
                        continue
                    filename = os.path.basename(img_path)
                    model_id = str(meta.get("model", "") or "")
                    model_info = MODELS_INFO.get(model_id, {})
                    result.append({
                        "mime_type":    meta.get("mime_type", "image/jpeg"),
                        "url":          f"/generations/{date_str}/{filename}",
                        "generated_at": meta.get("generated_at", ""),
                        "text":         meta.get("text", ""),
                        "gen_date":     date_str,
                        "gen_filename": meta.get("filename", filename),
                        "params": {
                            "model":         model_id,
                            "modelFamily":   meta.get("modelFamily", model_info.get("family", "")),
                            "model_label":   meta.get("model_label", model_info.get("label", "")),
                            "provider":      meta.get("provider", model_info.get("provider", "")),
                            "provider_label": meta.get("provider_label", model_info.get("provider_label", "")),
                            "imageSize":     meta.get("imageSize", ""),
                            "aspectRatio":   meta.get("aspectRatio", ""),
                            "temperature":   meta.get("temperature", 1.0),
                            "topP":          meta.get("topP", 0.95),
                            "thinkingLevel": meta.get("thinkingLevel", "Minimal"),
                            "useSearch":     meta.get("useSearch", False),
                            "outputMode":    meta.get("outputMode", "images_text"),
                            "prompt":        meta.get("prompt", ""),
                            "ref_count":     meta.get("ref_count", 0),
                            "refArchive":    meta.get("refArchive", []),
                            "seedMode":      meta.get("seedMode", "random"),
                            "seedValue":     meta.get("seedValue", 1),
                            "falSafetyChecker": meta.get("falSafetyChecker", True),
                            "falSafetyTolerance": meta.get("falSafetyTolerance", 4),
                            "geminiSafetyPreset": meta.get("geminiSafetyPreset", "default"),
                            "byteplusSafetyMode": meta.get("byteplusSafetyMode", "platform_default"),
                        }
                    })
                except Exception:
                    pass
    return jsonify(result)


# ---------------------------------------------------------------------------
# API â€” Delete a generation (image + sidecar JSON only, never loved/)
# ---------------------------------------------------------------------------
@app.route("/api/generations/<date_str>/<filename>", methods=["DELETE"])
@login_required
def api_delete_generation(date_str, filename):
    safe_root = os.path.realpath(GENERATIONS_DIR)
    img_path  = os.path.realpath(os.path.join(GENERATIONS_DIR, date_str, filename))

    if not img_path.startswith(safe_root + os.sep):
        return jsonify({"ok": False, "error": "Invalid path"}), 400

    if os.path.splitext(filename)[1].lower() not in (".jpeg", ".jpg", ".png", ".webp"):
        return jsonify({"ok": False, "error": "Invalid file type"}), 400

    if not os.path.exists(img_path):
        return jsonify({"ok": False, "error": "File not found"}), 404

    try:
        json_path = os.path.splitext(img_path)[0] + ".json"
        archived_refs = []
        if os.path.exists(json_path):
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                archived_refs = meta.get("refArchive", [])
            except Exception:
                archived_refs = []

        os.remove(img_path)
        if os.path.exists(json_path):
            os.remove(json_path)

        delete_reference_archive_entries(archived_refs)

        day_dir = os.path.dirname(img_path)
        if os.path.isdir(day_dir) and not os.listdir(day_dir):
            os.rmdir(day_dir)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API â€” Publish (save to loved/)
# ---------------------------------------------------------------------------
@app.route("/api/publish", methods=["POST"])
@login_required
def api_publish():
    body      = request.get_json()
    img_b64   = body.get("data", "")
    mime_type = body.get("mime_type", "image/png")
    meta      = body.get("meta", {})

    if not img_b64:
        return jsonify({"ok": False, "error": "No image data provided"})

    now      = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")

    day_dir = os.path.join(LOVED_DIR, date_str)
    os.makedirs(day_dir, exist_ok=True)

    try:
        img_b64, mime_type = convert_image_b64_to_png(img_b64, mime_type)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Image conversion error: {e}"})

    ext         = "png"
    model_short = (meta.get("model_label", "nb")
                   .replace(" ", "").lower()
                   .replace("nanobanana", "nb"))
    size_str  = meta.get("imageSize", "1K").lower()
    basename  = f"{time_str}_{model_short}_{size_str}"

    idx       = 1
    img_path  = os.path.join(day_dir, f"{basename}.{ext}")
    meta_path = os.path.join(day_dir, f"{basename}.json")
    while os.path.exists(img_path):
        img_path  = os.path.join(day_dir, f"{basename}_{idx}.{ext}")
        meta_path = os.path.join(day_dir, f"{basename}_{idx}.json")
        idx += 1

    img_bytes = base64.b64decode(img_b64)
    with open(img_path, "wb") as f:
        f.write(img_bytes)

    meta["mime_type"]    = mime_type
    meta["published_at"] = now.isoformat()
    meta["filename"]     = os.path.basename(img_path)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return jsonify({
        "ok":      True,
        "date":    date_str,
        "file":    os.path.basename(img_path),
        "url":     f"/loved/{date_str}/{os.path.basename(img_path)}",
        "gallery": url_for("loved_gallery")
    })


# ---------------------------------------------------------------------------
# API - Task Workbench
# ---------------------------------------------------------------------------
@app.route("/api/workbench/templates")
@login_required
def api_workbench_templates():
    return jsonify(fetch_task_templates())


@app.route("/api/workbench/report")
@login_required
def api_workbench_report():
    return jsonify(get_workbench_report())




@app.route("/api/reports/overview")
@login_required
def api_reports_overview():
    return jsonify(get_workbench_report())
@app.route("/api/workbench/plan", methods=["POST"])
@login_required
def api_workbench_plan():
    body = request.get_json(silent=True) or {}
    try:
        plan = build_workbench_plan(body)
        save_task_run(plan)
        return jsonify({"ok": True, "plan": plan, "report": get_workbench_report()})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API â€” Stats
# ---------------------------------------------------------------------------
@app.route("/api/stats")
@login_required
def api_stats():
    config = load_config()
    return jsonify(config.get("stats", DEFAULT_CONFIG["stats"]))


@app.route("/api/reset-stats", methods=["POST"])
@login_required
def api_reset_stats():
    config = load_config()
    config["stats"] = {
        "total_requests":  0,
        "total_images":    0,
        "total_cost_usd":  0.0,
        "requests_log":    [],
        "vision_calls":    0,
        "vision_cost_usd": 0.0,
        "vision_log":      [],
    }
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/models-info")
@login_required
def api_models_info():
    return jsonify(MODELS_INFO)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    os.makedirs(LOVED_DIR, exist_ok=True)
    os.makedirs(GENERATIONS_DIR, exist_ok=True)
    os.makedirs(REFERENCE_ARCHIVE_DIR, exist_ok=True)
    init_studio_db()
    # Migrate old published/ folder to loved/ if it exists and loved/ is empty
    _old_pub = os.path.join(BASE_DIR, "published")
    if os.path.isdir(_old_pub) and not os.listdir(LOVED_DIR):
        for item in os.listdir(_old_pub):
            src = os.path.join(_old_pub, item)
            dst = os.path.join(LOVED_DIR, item)
            if not os.path.exists(dst):
                shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)
        print("  Migrated published/ -> loved/")
    print("\n" + "="*52)
    print(f"  Nano Banana Studio {APP_VERSION}")
    print("  http://localhost:5000")
    print("  Login: admin / banana2024")
    print("  Max ref images: NB=0, Pro=8, NB2=14")
    print("="*52 + "\n")
    app.run(debug=True, port=5000)



