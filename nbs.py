#!/usr/bin/env python3
"""
AI API Studio (nbs.py)
AI image generator powered by Google Gemini
Run: python nbs.py
"""

# ---------------------------------------------------------------------------
# Bootstrap Ã¢â‚¬â€ auto-install missing dependencies on first run
# ---------------------------------------------------------------------------
import sys
import subprocess
import importlib.util
import os as _os

APP_VERSION = "1.3"

def _bootstrap():
    deps = [
        ("flask",    "flask>=3.0.0"),
        ("PIL",      "Pillow"),
        ("requests", "requests>=2.31.0"),
        ("fal_client", "fal-client>=0.7.0"),
    ]
    missing = [(mod, pkg) for mod, pkg in deps if importlib.util.find_spec(mod) is None]
    if not missing:
        return
    pkgs = [pkg for _, pkg in missing]
    print("\n" + "="*52)
    print(f"  AI API Studio {APP_VERSION} - First-run Setup")
    print("="*52)
    print(f"  Missing packages: {', '.join(pkgs)}")
    print("  Installing automatically... (one-time only)\n")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + pkgs
        )
        print("\n  Done! Starting AI API Studio...\n")
    except subprocess.CalledProcessError as e:
        print(f"\n  Install failed: {e}")
        print("  Try manually: pip install -r requirements.txt")
        sys.exit(1)

_bootstrap()

# ---------------------------------------------------------------------------
# End bootstrap Ã¢â‚¬â€ normal imports follow
# ---------------------------------------------------------------------------
import base64
import glob
import hashlib
import io
import json
import os
import random
import re
import secrets
import shutil
import sqlite3
import threading
import tempfile
import unicodedata
import requests
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse, unquote
from uuid import uuid4
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, send_from_directory)
from PIL import Image, ImageOps
import fal_client

app = Flask(__name__)
app.secret_key = None


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
IMAGE_ASSETS_DIR = os.path.join(BASE_DIR, "Image_assets")
LOVED_DIR        = os.path.join(IMAGE_ASSETS_DIR, "loved")
GENERATIONS_DIR  = os.path.join(IMAGE_ASSETS_DIR, "generations")
VIDEOS_DIR       = os.path.join(IMAGE_ASSETS_DIR, "videos")
ELEMENTS_DIR     = os.path.join(BASE_DIR, "Elements")
STUDIO_DB_FILE   = os.path.join(BASE_DIR, "studio.db")
REFERENCE_ARCHIVE_DIR = os.path.join(IMAGE_ASSETS_DIR, "reference_archive")
REFERENCE_ARCHIVE_INDEX_FILE = os.path.join(REFERENCE_ARCHIVE_DIR, "_index.json")
REFERENCE_MASKS_DIR = os.path.join(IMAGE_ASSETS_DIR, "reference_masks")
REFERENCE_RENDERS_DIR = os.path.join(IMAGE_ASSETS_DIR, "reference_renders")
ASSET_UNCATEGORIZED_VALUE = "uncategorized"
ASSET_UNCATEGORIZED_FOLDER = "uncategorized"
ASSET_META_FIELDS = ("assetClient", "assetProject", "assetShot", "assetFilename")


def move_tree_contents(src_dir: str, dst_dir: str) -> None:
    if not os.path.isdir(src_dir):
        return
    os.makedirs(dst_dir, exist_ok=True)
    for item in os.listdir(src_dir):
        src = os.path.join(src_dir, item)
        dst = os.path.join(dst_dir, item)
        if os.path.exists(dst):
            if os.path.isfile(src) and os.path.basename(src) == ".gitkeep":
                os.remove(src)
                continue
            if os.path.isdir(src) and os.path.isdir(dst):
                move_tree_contents(src, dst)
                if os.path.isdir(src) and not os.listdir(src):
                    os.rmdir(src)
            continue
        shutil.move(src, dst)


def sanitize_asset_meta_text(value) -> str:
    text = str(value or "").strip()
    text = text.replace("\\", " ").replace("/", " ")
    text = re.sub(r"[\x00-\x1f]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_asset_scope_text(value) -> str:
    text = sanitize_asset_meta_text(value)
    if not text or text == "-" or text.lower() == "uncategorized":
        return ASSET_UNCATEGORIZED_VALUE
    return text


def sanitize_asset_path_segment(value: str, fallback: str = ASSET_UNCATEGORIZED_FOLDER) -> str:
    text = normalize_asset_scope_text(value)
    if not text or text == ASSET_UNCATEGORIZED_VALUE:
        return fallback
    text = re.sub(r'[<>:"/\\\\|?*]+', "_", text)
    text = text.rstrip(". ").strip()
    return text[:120] or fallback


def sanitize_asset_filename_stem(value: str, fallback: str = "untitled") -> str:
    text = os.path.splitext(sanitize_asset_meta_text(value))[0]
    text = re.sub(r'[<>:"/\\\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._- ")
    return text[:120] or fallback


def normalize_asset_metadata(raw: dict | None, *, require_filename: bool = False, fallback_filename: str = "") -> dict:
    raw = raw or {}
    relpath = str(raw.get("assetRelpath", "") or "").replace("\\", "/").strip("/")
    rel_parts = [part for part in relpath.split("/") if part]
    inferred_client = rel_parts[0] if len(rel_parts) >= 4 else ""
    inferred_project = rel_parts[1] if len(rel_parts) >= 4 else ""
    inferred_shot = rel_parts[2] if len(rel_parts) >= 4 else ""
    inferred_filename = os.path.splitext(rel_parts[3])[0] if len(rel_parts) >= 4 else ""
    client = normalize_asset_scope_text(raw.get("assetClient", raw.get("client", inferred_client))) or ASSET_UNCATEGORIZED_VALUE
    project = normalize_asset_scope_text(raw.get("assetProject", raw.get("project", inferred_project))) or ASSET_UNCATEGORIZED_VALUE
    shot = normalize_asset_scope_text(raw.get("assetShot", raw.get("shot", inferred_shot))) or ASSET_UNCATEGORIZED_VALUE
    filename_seed = raw.get("assetFilename", raw.get("filename_stem", raw.get("filenameStem", inferred_filename or fallback_filename)))
    filename = sanitize_asset_filename_stem(filename_seed, fallback=fallback_filename or "untitled") if (require_filename or str(filename_seed or "").strip()) else ""
    return {
        "assetClient": client,
        "assetProject": project,
        "assetShot": shot,
        "assetFilename": filename,
    }


def merge_asset_metadata(params_meta: dict | None, payload: dict | None = None, *, fallback_source: dict | None = None) -> dict:
    merged = dict(params_meta or {})
    source = {}
    if isinstance(fallback_source, dict):
        source.update(fallback_source)
    if isinstance(payload, dict):
        source.update(payload)
    merged.update(normalize_asset_metadata(source, require_filename=False))
    return merged


SAFE_REQUEST_SETTING_KEYS = {
    "imageSize",
    "aspectRatio",
    "numberOfImages",
    "temperature",
    "topP",
    "thinkingLevel",
    "useSearch",
    "outputMode",
    "falSafetyChecker",
    "falSafetyTolerance",
    "geminiSafetyPreset",
    "byteplusSafetyMode",
    "seedMode",
    "seedValue",
    "videoInputMode",
    "duration",
    "resolution",
    "negativePrompt",
    "videoSafetyChecker",
    "videoOutputSafetyChecker",
    "videoUpscaleMode",
    "videoUpscaleFactor",
    "videoUpscaleTargetResolution",
    "videoUpscaleNoiseScale",
    "videoUpscaleOutputFormat",
    "videoUpscaleOutputQuality",
    "videoUpscaleOutputWriteMode",
    "videoUpscaleSeed",
    "videoUpscaleSyncMode",
    "upscaleModel",
    "upscalePreset",
    "upscaleMode",
    "upscaleFactor",
    "upscaleTargetResolution",
    "upscaleTargetWidth",
    "upscaleTargetHeight",
    "upscaleTargetAnchor",
    "upscaleDisplaySize",
    "upscaleOutputWidth",
    "upscaleOutputHeight",
    "upscaleSourceDate",
    "upscaleSourceFilename",
}


def merge_request_settings(params_meta: dict | None, payload: dict | None = None) -> dict:
    merged = dict(params_meta or {})
    if not isinstance(payload, dict):
        return merged
    for key in SAFE_REQUEST_SETTING_KEYS:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            merged[key] = value
    return merged


def build_asset_storage_relative_dir(asset_meta: dict) -> str:
    return os.path.join(
        sanitize_asset_path_segment(asset_meta.get("assetClient")),
        sanitize_asset_path_segment(asset_meta.get("assetProject")),
        sanitize_asset_path_segment(asset_meta.get("assetShot")),
    )


def build_asset_storage_file_prefix(asset_meta: dict) -> str:
    prefix_parts = []
    for key in ("assetClient", "assetProject", "assetShot"):
        value = sanitize_asset_meta_text(asset_meta.get(key, ""))
        value = normalize_asset_scope_text(value)
        if value and value != ASSET_UNCATEGORIZED_VALUE:
            prefix_parts.append(sanitize_asset_filename_stem(value))
    prefix_parts.append(sanitize_asset_filename_stem(asset_meta.get("assetFilename", ""), fallback="untitled"))
    return "_".join([part for part in prefix_parts if part]) or "untitled"


def build_asset_storage_paths(root_dir: str, asset_meta: dict, extension: str, *, variant_suffix: str = "") -> tuple[str, str, str]:
    rel_dir = build_asset_storage_relative_dir(asset_meta)
    abs_dir = os.path.join(root_dir, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    ext = str(extension or "").lower().lstrip(".") or "bin"
    base_stem = build_asset_storage_file_prefix(asset_meta)
    if variant_suffix:
        base_stem = f"{base_stem}_{variant_suffix}"
    candidate = base_stem
    counter = 2
    while (
        os.path.exists(os.path.join(abs_dir, f"{candidate}.{ext}"))
        or os.path.exists(os.path.join(abs_dir, f"{candidate}.json"))
    ):
        candidate = f"{base_stem}_{counter}"
        counter += 1
    filename = f"{candidate}.{ext}"
    rel_path = os.path.join(rel_dir, filename)
    return abs_dir, rel_path.replace("\\", "/"), candidate


def asset_meta_value_matches(selected: str, actual: str) -> bool:
    selected_text = normalize_asset_scope_text(selected)
    actual_text = normalize_asset_scope_text(actual)
    if not selected_text:
        return True
    if selected_text == ASSET_UNCATEGORIZED_VALUE:
        return not actual_text or actual_text == ASSET_UNCATEGORIZED_VALUE
    return actual_text == selected_text


def ensure_asset_metadata_memory_shape(memory: dict | None) -> dict:
    memory = dict(memory or {})
    return {
        "clients": list(memory.get("clients")) if isinstance(memory.get("clients"), list) and memory.get("clients") else [ASSET_UNCATEGORIZED_VALUE],
        "projects": list(memory.get("projects")) if isinstance(memory.get("projects"), list) and memory.get("projects") else [ASSET_UNCATEGORIZED_VALUE],
        "shots": list(memory.get("shots")) if isinstance(memory.get("shots"), list) and memory.get("shots") else [ASSET_UNCATEGORIZED_VALUE],
        "filenames": list(memory.get("filenames")) if isinstance(memory.get("filenames"), list) else [],
    }


def update_asset_metadata_memory(config: dict, asset_meta: dict | None) -> dict:
    asset_meta = normalize_asset_metadata(asset_meta, require_filename=False)
    memory = ensure_asset_metadata_memory_shape(config.get("asset_metadata_memory"))

    def _upsert(bucket: list[str], value: str, *, allow_uncategorized: bool) -> list[str]:
        clean_value = sanitize_asset_meta_text(value)
        if not clean_value:
            clean_value = ASSET_UNCATEGORIZED_VALUE if allow_uncategorized else ""
        clean_value = normalize_asset_scope_text(clean_value) if allow_uncategorized else clean_value
        if not clean_value:
            return bucket
        deduped = [item for item in bucket if sanitize_asset_meta_text(item) != clean_value]
        deduped.insert(0, clean_value)
        return deduped[:200]

    memory["clients"] = _upsert(memory.get("clients", []), asset_meta.get("assetClient", ""), allow_uncategorized=True)
    memory["projects"] = _upsert(memory.get("projects", []), asset_meta.get("assetProject", ""), allow_uncategorized=True)
    memory["shots"] = _upsert(memory.get("shots", []), asset_meta.get("assetShot", ""), allow_uncategorized=True)
    if asset_meta.get("assetFilename"):
        memory["filenames"] = _upsert(memory.get("filenames", []), asset_meta.get("assetFilename", ""), allow_uncategorized=False)

    for key in ("clients", "projects", "shots"):
        unique_values = []
        for value in memory.get(key, []):
            clean_value = normalize_asset_scope_text(value) or ASSET_UNCATEGORIZED_VALUE
            if clean_value not in unique_values:
                unique_values.append(clean_value)
        if ASSET_UNCATEGORIZED_VALUE not in unique_values:
            unique_values.insert(0, ASSET_UNCATEGORIZED_VALUE)
        memory[key] = unique_values[:200]

    filename_values = []
    for value in memory.get("filenames", []):
        clean_value = sanitize_asset_filename_stem(value, fallback="")
        if clean_value and clean_value not in filename_values:
            filename_values.append(clean_value)
    memory["filenames"] = filename_values[:400]

    config["asset_metadata_memory"] = memory
    return memory


def resolve_asset_relpath(relpath: str = "", date_str: str = "", filename: str = "") -> str:
    raw = str(relpath or "").strip().replace("\\", "/")
    if raw:
        parts = [part for part in raw.split("/") if part not in ("", ".", "..")]
        return "/".join(parts)
    safe_date = str(date_str or "").strip().replace("\\", "/").strip("/")
    safe_filename = os.path.basename(str(filename or "").strip())
    if safe_date and safe_filename:
        return f"{safe_date}/{safe_filename}"
    raise ValueError("Missing asset file.")


def safe_asset_path(root_dir: str, relpath: str) -> str:
    safe_root = os.path.realpath(root_dir)
    local_path = os.path.realpath(os.path.join(root_dir, relpath.replace("/", os.sep)))
    if not local_path.startswith(safe_root + os.sep):
        raise ValueError("Invalid path.")
    if not os.path.exists(local_path):
        raise FileNotFoundError("File not found.")
    return local_path


def list_meta_files_recursive(root_dir: str) -> list[str]:
    meta_files: list[str] = []
    if not os.path.isdir(root_dir):
        return meta_files
    for current_root, _, filenames in os.walk(root_dir):
        for name in filenames:
            if name.lower().endswith(".json"):
                meta_files.append(os.path.join(current_root, name))
    meta_files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return meta_files


def find_existing_binary_for_meta(meta_file: str, extensions: tuple[str, ...]) -> tuple[str | None, str | None]:
    base = meta_file[:-5]
    for ext in extensions:
        candidate = base + ext
        if os.path.exists(candidate):
            return candidate, os.path.basename(candidate)
    return None, None


def build_asset_public_url(prefix: str, relpath: str) -> str:
    clean_relpath = resolve_asset_relpath(relpath=relpath)
    return f"/{prefix}/{clean_relpath}"


def derive_asset_date_key(relpath: str, generated_at: str = "") -> str:
    rel_parts = [part for part in str(relpath or "").replace("\\", "/").split("/") if part]
    if rel_parts and re.fullmatch(r"\d{4}-\d{2}-\d{2}", rel_parts[0]):
        return rel_parts[0]
    generated = str(generated_at or "").strip()
    if generated:
        return generated[:10]
    return ""


def find_generation_relpath_by_filename(filename: str, *, preferred_dir: str = "", preferred_date: str = "") -> str:
    safe_name = os.path.basename(str(filename or "").strip())
    if not safe_name or not os.path.isdir(GENERATIONS_DIR):
        return ""
    preferred_dir = str(preferred_dir or "").replace("\\", "/").strip("/")
    preferred_date = str(preferred_date or "").strip()

    candidates: list[str] = []
    if preferred_dir:
        candidates.append(f"{preferred_dir}/{safe_name}")
    if preferred_date:
        candidates.append(f"{preferred_date}/{safe_name}")

    for relpath in candidates:
        try:
            local_path = safe_asset_path(GENERATIONS_DIR, relpath)
        except Exception:
            continue
        if os.path.exists(local_path):
            return relpath

    for root, _, files in os.walk(GENERATIONS_DIR):
        if safe_name not in files:
            continue
        full_path = os.path.join(root, safe_name)
        try:
            relpath = os.path.relpath(full_path, GENERATIONS_DIR).replace("\\", "/")
        except Exception:
            continue
        if preferred_dir and relpath.startswith(preferred_dir + "/"):
            return relpath
        if preferred_date and relpath.startswith(preferred_date + "/"):
            return relpath
        return relpath
    return ""
    if os.path.isdir(src_dir) and not os.listdir(src_dir):
        os.rmdir(src_dir)


def migrate_image_assets_layout() -> None:
    os.makedirs(IMAGE_ASSETS_DIR, exist_ok=True)
    legacy_dirs = {
        os.path.join(BASE_DIR, "loved"): LOVED_DIR,
        os.path.join(BASE_DIR, "generations"): GENERATIONS_DIR,
        os.path.join(BASE_DIR, "videos"): VIDEOS_DIR,
        os.path.join(BASE_DIR, "reference_archive"): REFERENCE_ARCHIVE_DIR,
        os.path.join(BASE_DIR, "reference_masks"): REFERENCE_MASKS_DIR,
        os.path.join(BASE_DIR, "reference_renders"): REFERENCE_RENDERS_DIR,
    }
    for legacy_dir, target_dir in legacy_dirs.items():
        if os.path.realpath(legacy_dir) == os.path.realpath(target_dir):
            continue
        if os.path.isdir(legacy_dir):
            move_tree_contents(legacy_dir, target_dir)
        else:
            os.makedirs(target_dir, exist_ok=True)

# Mapping folder to display name and icon for Elements
ELEMENTS_CATEGORIES = {
    "Model Managment": {"label": "Characters", "icon": "&#128100;", "slug": "characters"},
    "Locations":       {"label": "Locations",  "icon": "&#127757;", "slug": "locations"},
    "Props":           {"label": "Props",      "icon": "&#128230;", "slug": "props"},
}

DEFAULT_CONFIG = {
    "api_key": "",
    "seedream_api_key": "",
    "fal_api_key": "",
    "byteplus_api_key": "",
    "kling_api_token": "",
    "flask_secret_key": "",
    "asset_metadata_memory": {
        "clients": [ASSET_UNCATEGORIZED_VALUE],
        "projects": [ASSET_UNCATEGORIZED_VALUE],
        "shots": [ASSET_UNCATEGORIZED_VALUE],
        "filenames": [],
    },
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


ASYNC_JOBS_LOCK = threading.Lock()
ASYNC_JOBS: dict[str, dict] = {}


def clone_jsonable(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def build_async_job_public_record(job: dict) -> dict:
    return {
        "ok": True,
        "jobId": job.get("job_id", ""),
        "kind": job.get("kind", ""),
        "status": job.get("status", "queued"),
        "createdAt": job.get("created_at", ""),
        "updatedAt": job.get("updated_at", ""),
        "completedAt": job.get("completed_at", ""),
        "result": clone_jsonable(job.get("result")),
        "error": job.get("error", ""),
        "debug": clone_jsonable(job.get("debug")),
    }


def create_async_job(kind: str) -> dict:
    now_ts = utc_now_iso()
    job = {
        "job_id": str(uuid4()),
        "kind": kind,
        "status": "queued",
        "created_at": now_ts,
        "updated_at": now_ts,
        "completed_at": "",
        "result": None,
        "error": "",
        "debug": None,
    }
    with ASYNC_JOBS_LOCK:
        ASYNC_JOBS[job["job_id"]] = job
    return build_async_job_public_record(job)


def get_async_job(job_id: str) -> dict | None:
    with ASYNC_JOBS_LOCK:
        job = ASYNC_JOBS.get(job_id)
        if not job:
            return None
        return build_async_job_public_record(job)


def update_async_job(job_id: str, **updates) -> None:
    with ASYNC_JOBS_LOCK:
        job = ASYNC_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = utc_now_iso()


def compact_generation_result(result: dict) -> dict:
    params = clone_jsonable(result.get("params") or {}) or {}
    compact_images = []
    for img in result.get("images", []) or []:
        gen_date = str(img.get("gen_date") or params.get("gen_date") or "").strip()
        gen_filename = str(img.get("gen_filename") or "").strip()
        gen_relpath = str(img.get("gen_relpath") or params.get("gen_relpath") or "").strip()
        img_url = build_asset_public_url("generations", gen_relpath) if gen_relpath else (f"/generations/{gen_date}/{gen_filename}" if gen_date and gen_filename else "")
        compact_images.append({
            "gen_date": gen_date,
            "gen_filename": gen_filename,
            "gen_relpath": gen_relpath,
            "mime_type": str(img.get("mime_type") or "image/png"),
            "url": img_url,
        })
    first_image = compact_images[0] if compact_images else {}
    if first_image:
        params.setdefault("assetUrl", first_image.get("url", ""))
        params.setdefault("gen_filename", first_image.get("gen_filename", ""))
        params.setdefault("gen_relpath", first_image.get("gen_relpath", ""))
    return {
        "params": params,
        "images": compact_images,
        "url": first_image.get("url", ""),
        "filename": first_image.get("gen_filename", ""),
        "gen_filename": first_image.get("gen_filename", ""),
        "gen_relpath": first_image.get("gen_relpath", ""),
        "mime_type": first_image.get("mime_type", "image/png"),
        "text": str(result.get("text") or ""),
        "cost": round(float(result.get("cost") or 0.0), 6),
        "model_label": str(result.get("model_label") or ""),
    }


def compact_video_result(result: dict) -> dict:
    params = clone_jsonable(result.get("params") or {}) or {}
    compact_videos = []
    for item in result.get("videos", []) or []:
        gen_date = str(item.get("gen_date") or params.get("gen_date") or "").strip()
        gen_filename = str(item.get("gen_filename") or "").strip()
        gen_relpath = str(item.get("gen_relpath") or params.get("gen_relpath") or "").strip()
        video_url = build_asset_public_url("videos", gen_relpath) if gen_relpath else (f"/videos/{gen_date}/{gen_filename}" if gen_date and gen_filename else "")
        compact_videos.append({
            "gen_date": gen_date,
            "gen_filename": gen_filename,
            "gen_relpath": gen_relpath,
            "mime_type": str(item.get("mime_type") or "video/mp4"),
            "url": video_url,
            "poster_url": str(item.get("poster_url") or ""),
        })
    return {
        "params": params,
        "videos": compact_videos,
        "text": str(result.get("text") or ""),
        "cost": round(float(result.get("cost") or 0.0), 6),
        "model_label": str(result.get("model_label") or ""),
    }


def _run_generate_async_job(job_id: str, payload: dict) -> None:
    update_async_job(job_id, status="running", error="", debug=None)
    try:
        result = run_generation_job(clone_jsonable(payload) or {}, load_config())
        persist_generation_result(result)
        update_async_job(
            job_id,
            status="completed",
            completed_at=utc_now_iso(),
            result=compact_generation_result(result),
            error="",
            debug=None,
        )
    except GenerationDebugError as exc:
        update_async_job(
            job_id,
            status="failed",
            completed_at=utc_now_iso(),
            result=None,
            error=str(exc),
            debug=clone_jsonable(exc.debug),
        )
    except Exception as exc:
        update_async_job(
            job_id,
            status="failed",
            completed_at=utc_now_iso(),
            result=None,
            error=str(exc),
            debug=None,
        )


def _run_upscale_async_job(job_id: str, payload: dict) -> None:
    update_async_job(job_id, status="running", error="", debug=None)
    try:
        config = load_config()
        fal_key = (config.get("fal_api_key", "") or "").strip()
        if not fal_key:
            raise ValueError("Fal API key not configured. Go to Settings.")
        request_payload = clone_jsonable(payload) or {}
        is_video_upscale = bool(
            str(request_payload.get("assetType") or "").strip().lower() == "video"
            or str((request_payload.get("modelFamily") or "")).strip().lower() == "seedvr-video"
            or isinstance(request_payload.get("sourceVideo"), dict)
        )
        if is_video_upscale:
            result = run_fal_seedvr_video_job(request_payload, fal_key)
            persist_video_result(result)
            compact_result = compact_video_result(result)
        else:
            result = run_fal_seedvr_upscale_job(request_payload, fal_key)
            persist_generation_result(result)
            compact_result = compact_generation_result(result)
        update_async_job(
            job_id,
            status="completed",
            completed_at=utc_now_iso(),
            result=compact_result,
            error="",
            debug=None,
        )
    except Exception as exc:
        update_async_job(
            job_id,
            status="failed",
            completed_at=utc_now_iso(),
            result=None,
            error=str(exc),
            debug=None,
        )


def _run_video_async_job(job_id: str, payload: dict) -> None:
    update_async_job(job_id, status="running", error="", debug=None)
    try:
        result = run_video_job(clone_jsonable(payload) or {}, load_config())
        persist_video_result(result)
        update_async_job(
            job_id,
            status="completed",
            completed_at=utc_now_iso(),
            result=compact_video_result(result),
            error="",
            debug=None,
        )
    except Exception as exc:
        update_async_job(
            job_id,
            status="failed",
            completed_at=utc_now_iso(),
            result=None,
            error=str(exc),
            debug=None,
        )


def start_async_generate_job(payload: dict) -> dict:
    job = create_async_job("generate")
    threading.Thread(
        target=_run_generate_async_job,
        args=(job["jobId"], clone_jsonable(payload) or {}),
        daemon=True,
    ).start()
    return job


def start_async_upscale_job(payload: dict) -> dict:
    job = create_async_job("upscale")
    threading.Thread(
        target=_run_upscale_async_job,
        args=(job["jobId"], clone_jsonable(payload) or {}),
        daemon=True,
    ).start()
    return job


def start_async_video_job(payload: dict) -> dict:
    job = create_async_job("video")
    threading.Thread(
        target=_run_video_async_job,
        args=(job["jobId"], clone_jsonable(payload) or {}),
        daemon=True,
    ).start()
    return job

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
    "kling": "Kling",
}

GEMINI_BASE_URL                 = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FAL_BASE_URL                    = "https://fal.run"
BYTEPLUS_BASE_URL               = "https://ark.ap-southeast.bytepluses.com/api/v3/images/generations"
KLING_BASE_URL                  = "https://api-singapore.klingai.com"
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
FAL_SEEDVR_UPSCALE_ID           = "fal-ai/seedvr/upscale/image"
FAL_SEEDVR_VIDEO_ID             = "fal-ai/seedvr/upscale/video"
FAL_KLING_V1_STD_T2V_ID         = "fal-ai/kling-video/v1/standard/text-to-video"
FAL_KLING_V1_STD_I2V_ID         = "fal-ai/kling-video/v1/standard/image-to-video"
FAL_KLING_V15_PRO_T2V_ID        = "fal-ai/kling-video/v1.5/pro/text-to-video"
FAL_KLING_V15_PRO_I2V_ID        = "fal-ai/kling-video/v1.5/pro/image-to-video"
FAL_KLING_V16_STD_T2V_ID        = "fal-ai/kling-video/v1.6/standard/text-to-video"
FAL_KLING_V16_STD_I2V_ID        = "fal-ai/kling-video/v1.6/standard/image-to-video"
FAL_KLING_V16_STD_ELEMENTS_ID   = "fal-ai/kling-video/v1.6/standard/elements"
FAL_KLING_V16_PRO_T2V_ID        = "fal-ai/kling-video/v1.6/pro/text-to-video"
FAL_KLING_V16_PRO_I2V_ID        = "fal-ai/kling-video/v1.6/pro/image-to-video"
FAL_KLING_V16_PRO_ELEMENTS_ID   = "fal-ai/kling-video/v1.6/pro/elements"
FAL_KLING_V2_MASTER_T2V_ID      = "fal-ai/kling-video/v2/master/text-to-video"
FAL_KLING_V2_MASTER_I2V_ID      = "fal-ai/kling-video/v2/master/image-to-video"
FAL_KLING_V21_STD_I2V_ID        = "fal-ai/kling-video/v2.1/standard/image-to-video"
FAL_KLING_V21_PRO_I2V_ID        = "fal-ai/kling-video/v2.1/pro/image-to-video"
FAL_KLING_V21_MASTER_T2V_ID     = "fal-ai/kling-video/v2.1/master/text-to-video"
FAL_KLING_V21_MASTER_I2V_ID     = "fal-ai/kling-video/v2.1/master/image-to-video"
FAL_KLING_V25_TURBO_PRO_T2V_ID  = "fal-ai/kling-video/v2.5-turbo/pro/text-to-video"
FAL_KLING_V25_TURBO_STD_I2V_ID  = "fal-ai/kling-video/v2.5-turbo/standard/image-to-video"
FAL_KLING_V25_TURBO_PRO_I2V_ID  = "fal-ai/kling-video/v2.5-turbo/pro/image-to-video"
FAL_KLING_V26_PRO_T2V_ID        = "fal-ai/kling-video/v2.6/pro/text-to-video"
FAL_KLING_V26_PRO_I2V_ID        = "fal-ai/kling-video/v2.6/pro/image-to-video"
FAL_KLING_V30_STD_T2V_ID        = "fal-ai/kling-video/v3/standard/text-to-video"
FAL_KLING_V30_STD_I2V_ID        = "fal-ai/kling-video/v3/standard/image-to-video"
FAL_KLING_V30_PRO_T2V_ID        = "fal-ai/kling-video/v3/pro/text-to-video"
FAL_KLING_V30_PRO_I2V_ID        = "fal-ai/kling-video/v3/pro/image-to-video"
FAL_KLING_O1_STD_I2V_ID         = "fal-ai/kling-video/o1/standard/image-to-video"
FAL_KLING_O1_REF_I2V_ID         = "fal-ai/kling-video/o1/standard/reference-to-video"
FAL_KLING_O1_PRO_I2V_ID         = "fal-ai/kling-video/o1/image-to-video"
FAL_KLING_O1_PRO_REF_I2V_ID     = "fal-ai/kling-video/o1/reference-to-video"
FAL_KLING_O3_STD_T2V_ID         = "fal-ai/kling-video/o3/standard/text-to-video"
FAL_KLING_O3_STD_I2V_ID         = "fal-ai/kling-video/o3/standard/image-to-video"
FAL_KLING_O3_REF_I2V_ID         = "fal-ai/kling-video/o3/standard/reference-to-video"
FAL_KLING_O3_STD_V2V_ID         = "fal-ai/kling-video/o3/standard/video-to-video/edit"
FAL_KLING_O3_PRO_T2V_ID         = "fal-ai/kling-video/o3/pro/text-to-video"
FAL_KLING_O3_PRO_I2V_ID         = "fal-ai/kling-video/o3/pro/image-to-video"
FAL_KLING_O3_PRO_REF_I2V_ID     = "fal-ai/kling-video/o3/pro/reference-to-video"
FAL_KLING_O3_PRO_V2V_ID         = "fal-ai/kling-video/o3/pro/video-to-video/edit"
FAL_SEEDANCE_V1_LITE_T2V_ID     = "fal-ai/bytedance/seedance/v1/lite/text-to-video"
FAL_SEEDANCE_V1_LITE_I2V_ID     = "fal-ai/bytedance/seedance/v1/lite/image-to-video"
FAL_SEEDANCE_V1_LITE_REF_ID     = "fal-ai/bytedance/seedance/v1/lite/reference-to-video"
FAL_SEEDANCE_V1_PRO_T2V_ID      = "fal-ai/bytedance/seedance/v1/pro/text-to-video"
FAL_SEEDANCE_V1_PRO_I2V_ID      = "fal-ai/bytedance/seedance/v1/pro/image-to-video"
FAL_SEEDANCE_V1_PRO_FAST_T2V_ID = "fal-ai/bytedance/seedance/v1/pro/fast/text-to-video"
FAL_SEEDANCE_V1_PRO_FAST_I2V_ID = "fal-ai/bytedance/seedance/v1/pro/fast/image-to-video"
FAL_SEEDANCE_V15_PRO_T2V_ID     = "fal-ai/bytedance/seedance/v1.5/pro/text-to-video"
FAL_SEEDANCE_V15_PRO_I2V_ID     = "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"
FAL_WAN_T2V_ID                  = "fal-ai/wan/v2.2-a14b/text-to-video"
FAL_WAN_I2V_ID                  = "fal-ai/wan/v2.2-a14b/image-to-video"
KLING_DIRECT_TEXT_DEFAULT_ID    = "kling-v3-pro"
KLING_DIRECT_IMAGE_DEFAULT_ID   = "kling-v3-pro"
UPSCALER_MODELS = {
    "seedvr2": {"id": FAL_SEEDVR_UPSCALE_ID, "label": "SeedVR2"},
}

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
    payload.update(normalize_asset_metadata(payload, require_filename=False))
    return payload


def resolve_video_model_selection(
    requested_model: str = "",
    requested_family: str = "",
    requested_provider: str = "",
    requested_input_mode: str = "text",
) -> tuple[str, str, str, dict]:
    model_id = str(requested_model or "").strip()
    family_key = str(requested_family or "").strip()
    provider_key = str(requested_provider or "").strip().lower()
    input_mode = str(requested_input_mode or "").strip().lower()

    if model_id in VIDEO_MODELS_INFO:
        model_info = VIDEO_MODELS_INFO[model_id]
        return (
            model_id,
            model_info.get("family", family_key or "kling"),
            model_info.get("provider", provider_key or "kling"),
            model_info,
        )

    if family_key in VIDEO_MODEL_FAMILIES:
        family_info = VIDEO_MODEL_FAMILIES[family_key]
        providers = list(family_info.get("provider_order", [])) or list((family_info.get("providers") or {}).keys())
        if provider_key and provider_key in providers:
            ordered_providers = [provider_key] + [prov for prov in providers if prov != provider_key]
        elif provider_key:
            ordered_providers = [provider_key] + providers
        else:
            default_provider = family_info.get("default_provider", "") or (providers[0] if providers else "")
            ordered_providers = [default_provider] + [prov for prov in providers if prov != default_provider]
        for provider_name in ordered_providers:
            candidates = get_video_model_candidates(family_key, provider_name, input_mode)
            if not candidates:
                candidates = get_video_model_candidates(family_key, provider_name, "")
            if candidates:
                resolved_model_id, resolved_model_info = candidates[0]
                return resolved_model_id, family_key, provider_name, resolved_model_info

    fallback_family = "kling"
    fallback_family_info = VIDEO_MODEL_FAMILIES[fallback_family]
    fallback_provider = fallback_family_info["default_provider"]
    fallback_candidates = get_video_model_candidates(fallback_family, fallback_provider, input_mode)
    if not fallback_candidates:
        fallback_candidates = get_video_model_candidates(fallback_family, fallback_provider, "")
    fallback_model, fallback_info = fallback_candidates[0]
    return fallback_model, fallback_family, fallback_provider, fallback_info


def normalize_video_duration(value, default: int = 5) -> int:
    try:
        duration = int(str(value or default).strip())
    except Exception:
        duration = default
    return duration if duration in VIDEO_DURATION_ALL_OPTIONS else default


def normalize_video_resolution(value: str) -> str:
    resolution = str(value or "720p").strip().lower()
    return resolution if resolution in {"480p", "720p", "1080p", "1440p", "2160p"} else "720p"


def normalize_video_input_mode(value: str) -> str:
    mode = str(value or "text").strip().lower()
    return mode if mode in {"text", "image", "reference", "video"} else "text"


def normalize_video_image_payload(image: dict | None, default_name: str) -> dict:
    if not isinstance(image, dict):
        image = {}
    payload = {
        "mime_type": str(image.get("mime_type") or "image/png"),
        "data": str(image.get("data") or ""),
        "name": str(image.get("name") or default_name),
        "original_data": str(image.get("original_data") or ""),
        "original_mime_type": str(image.get("original_mime_type") or ""),
        "mask_png_data": str(image.get("mask_png_data") or ""),
        "archive_date": str(image.get("archive_date") or ""),
        "archive_filename": os.path.basename(str(image.get("archive_filename") or "")),
        "original_url": str(image.get("original_url") or ""),
        "masked_url": str(image.get("masked_url") or ""),
        "mask_url": str(image.get("mask_url") or ""),
        "has_mask": bool(image.get("has_mask")),
    }
    if payload["data"]:
        try:
            clamped_b64, clamped_mime = clamp_image_b64_max_side(payload["data"], payload["mime_type"])
            payload["data"] = clamped_b64
            payload["mime_type"] = clamped_mime
            safe_b64, safe_mime = compress_video_input_image(payload["data"], payload["mime_type"])
            payload["data"] = safe_b64
            payload["mime_type"] = safe_mime
        except Exception:
            pass
    return payload


def normalize_video_image_payloads(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    normalized = []
    for idx, item in enumerate(items, start=1):
        payload = normalize_video_image_payload(item, f"video-reference-{idx}.png")
        if payload.get("data"):
            normalized.append(payload)
    return normalized


def normalize_video_file_payload(video: dict | None, default_name: str) -> dict:
    if not isinstance(video, dict):
        video = {}
    mime_type = str(video.get("mime_type") or "video/mp4").split(";", 1)[0].strip().lower() or "video/mp4"
    payload = {
        "mime_type": mime_type,
        "data": str(video.get("data") or ""),
        "name": os.path.basename(str(video.get("name") or default_name)) or default_name,
        "url": str(video.get("url") or ""),
    }
    return payload


def normalize_video_upscale_mode(value: str | None) -> str:
    mode = str(value or "factor").strip().lower()
    return mode if mode in {"factor", "target"} else "factor"


def normalize_video_upscale_factor(value, default: float = 2.0) -> float:
    try:
        factor = float(value)
    except Exception:
        factor = default
    return max(1.0, min(10.0, round(factor, 3)))


def normalize_video_upscale_target_resolution(value: str | None) -> str:
    resolution = str(value or "1080p").strip().lower()
    return resolution if resolution in {"720p", "1080p", "1440p", "2160p"} else "1080p"


def normalize_video_upscale_noise_scale(value, default: float = 0.1) -> float:
    try:
        noise = float(value)
    except Exception:
        noise = default
    return max(0.0, min(1.0, round(noise, 3)))


def normalize_video_upscale_write_mode(value: str | None) -> str:
    write_mode = str(value or "balanced").strip().lower()
    return write_mode if write_mode in {"fast", "balanced", "small"} else "balanced"


def normalize_video_upscale_output_quality(value: str | None) -> str:
    quality = str(value or "high").strip().lower()
    return quality if quality in {"low", "medium", "high", "maximum"} else "high"


def normalize_video_upscale_output_format(value: str | None) -> str:
    fmt = str(value or "X264 (.mp4)").strip()
    allowed = {"X264 (.mp4)", "VP9 (.webm)", "PRORES4444 (.mov)", "GIF (.gif)"}
    return fmt if fmt in allowed else "X264 (.mp4)"


def normalize_optional_int(value):
    if value in (None, "", False):
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def normalize_video_request(body: dict | None) -> dict:
    payload = dict(body or {})
    requested_input_mode = normalize_video_input_mode(payload.get("videoInputMode", "text"))
    model_id, family_key, provider_key, model_info = resolve_video_model_selection(
        payload.get("model", ""),
        payload.get("modelFamily", ""),
        payload.get("provider", ""),
        requested_input_mode,
    )
    payload["model"] = model_id
    payload["modelFamily"] = family_key
    payload["provider"] = provider_key
    payload["modelLabel"] = model_info.get("label", model_id)
    payload["providerLabel"] = model_info.get("provider_label", PROVIDER_LABELS.get(provider_key, provider_key.title()))
    supported_modes = [str(mode).strip().lower() for mode in model_info.get("input_modes", [])]
    payload["videoInputMode"] = requested_input_mode if requested_input_mode in supported_modes or not supported_modes else supported_modes[0]
    input_mode = payload["videoInputMode"]
    supports_start_image = bool(model_info.get("supports_start_image")) and input_mode != "text"
    supports_reference_images = bool(model_info.get("supports_reference_images")) and input_mode == "reference"
    supports_source_video = bool(model_info.get("supports_source_video")) and input_mode == "video"
    payload["duration"] = normalize_video_duration(payload.get("duration", 5))
    payload["aspectRatio"] = str(payload.get("aspectRatio", "16:9") or "16:9").strip()
    if payload["aspectRatio"] not in VIDEO_ASPECT_RATIOS:
        payload["aspectRatio"] = "16:9"
    payload["resolution"] = normalize_video_resolution(payload.get("resolution", "720p"))
    payload["negativePrompt"] = str(payload.get("negativePrompt", "") or "").strip()
    payload["videoSafetyChecker"] = bool(payload.get("videoSafetyChecker", True))
    payload["videoOutputSafetyChecker"] = bool(payload.get("videoOutputSafetyChecker", True))
    payload["sourceImage"] = normalize_video_image_payload(payload.get("sourceImage"), "video-source.png") if supports_start_image else {}
    payload["sourceVideo"] = normalize_video_file_payload(payload.get("sourceVideo"), "video-source.mp4") if supports_source_video else {}
    payload["referenceImages"] = normalize_video_image_payloads(payload.get("referenceImages")) if supports_reference_images else []
    if not supports_reference_images:
        payload["referenceImages"] = []
    else:
        max_refs = max(0, int(model_info.get("max_reference_images", 0) or 0))
        if max_refs:
            payload["referenceImages"] = payload["referenceImages"][:max_refs]
    payload["videoUpscaleMode"] = normalize_video_upscale_mode(payload.get("videoUpscaleMode", "factor"))
    payload["videoUpscaleFactor"] = normalize_video_upscale_factor(payload.get("videoUpscaleFactor", 2))
    payload["videoUpscaleTargetResolution"] = normalize_video_upscale_target_resolution(payload.get("videoUpscaleTargetResolution", payload.get("resolution", "1080p")))
    payload["videoUpscaleNoiseScale"] = normalize_video_upscale_noise_scale(payload.get("videoUpscaleNoiseScale", 0.1))
    payload["videoUpscaleOutputWriteMode"] = normalize_video_upscale_write_mode(payload.get("videoUpscaleOutputWriteMode", "balanced"))
    payload["videoUpscaleOutputFormat"] = normalize_video_upscale_output_format(payload.get("videoUpscaleOutputFormat", "X264 (.mp4)"))
    payload["videoUpscaleOutputQuality"] = normalize_video_upscale_output_quality(payload.get("videoUpscaleOutputQuality", "high"))
    payload["videoUpscaleSeed"] = normalize_optional_int(payload.get("videoUpscaleSeed"))
    payload.update(normalize_asset_metadata(payload, require_filename=False))
    return payload

# ---------------------------------------------------------------------------
# Vocabolario canonico Ã¢â‚¬â€ caricato da talent_vocabulary.json se presente
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
    lines = ["MANDATORY ALLOWED VALUES Ã¢â‚¬â€ use ONLY these exact strings, no variations:"]
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
        "free_tier":     "Preview Ã¢â‚¬â€ free *",
        "note":          "Recommended for talent analysis Ã¢â‚¬â€ best JSON quality"
    },
    "gemini-3.1-flash-lite-preview": {
        "label":         "Gemini 3.1 Flash-Lite",
        "badge":         "Vis",
        "input_per_1m":  0.075,
        "output_per_1m": 0.30,
        "free_tier":     "Preview Ã¢â‚¬â€ free *",
        "note":          "Lite version Ã¢â‚¬â€ faster but less accurate on JSON"
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
# Helpers Ã¢â‚¬â€ Talent individual JSON
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
#   Ã¢â‚¬Â¢ Se larghezza > MAX_IMG_WIDTH: ridimensiona mantenendo aspect ratio
#   - Always converts to JPG with JPEG_QUALITY quality
#   Ã¢â‚¬Â¢ Ritorna (b64_string, "image/jpeg", orig_w, orig_h, new_w, new_h)
# ---------------------------------------------------------------------------
MAX_IMG_WIDTH  = 4000   # px sulla dimensione orizzontale
JPEG_QUALITY   = 90     # JPG output quality %
SEEDREAM_MAX_INPUT_PIXELS = 36_000_000
SEEDREAM_MAX_INPUT_BYTES = 10 * 1024 * 1024
SEEDREAM_TARGET_INPUT_BYTES = int(SEEDREAM_MAX_INPUT_BYTES * 0.92)
VIDEO_MAX_INPUT_PIXELS = 36_000_000
VIDEO_MAX_INPUT_BYTES = 10 * 1024 * 1024
VIDEO_TARGET_INPUT_BYTES = int(VIDEO_MAX_INPUT_BYTES * 0.92)
REMOTE_REF_FETCH_MAX_BYTES = 30 * 1024 * 1024
MAX_REFERENCE_IMAGE_PIXELS = 5504 * 3072


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


def load_reference_archive_index() -> dict[str, dict]:
    if not os.path.exists(REFERENCE_ARCHIVE_INDEX_FILE):
        return {}
    try:
        with open(REFERENCE_ARCHIVE_INDEX_FILE, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_reference_archive_index(index: dict[str, dict]) -> None:
    os.makedirs(REFERENCE_ARCHIVE_DIR, exist_ok=True)
    with open(REFERENCE_ARCHIVE_INDEX_FILE, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)


def compute_reference_archive_hash(source_png_b64: str, mask_png_b64: str = "") -> str:
    digest = hashlib.sha256()
    try:
        digest.update(base64.b64decode(source_png_b64))
    except Exception:
        digest.update(str(source_png_b64 or "").encode("utf-8"))
    digest.update(b"\n--mask--\n")
    if mask_png_b64:
        try:
            digest.update(base64.b64decode(mask_png_b64))
        except Exception:
            digest.update(str(mask_png_b64 or "").encode("utf-8"))
    return digest.hexdigest()


def get_reference_archive_index_entry(ref_hash: str, index: dict[str, dict] | None = None) -> dict | None:
    current_index = index if isinstance(index, dict) else load_reference_archive_index()
    raw_entry = current_index.get(str(ref_hash or "").strip())
    if not isinstance(raw_entry, dict):
        return None
    ref_date = str(raw_entry.get("date", "") or "").strip()
    filename = os.path.basename(str(raw_entry.get("filename", "") or "").strip())
    if not ref_date or not filename:
        return None
    archive_path = os.path.join(REFERENCE_ARCHIVE_DIR, ref_date, filename)
    if not os.path.exists(archive_path):
        current_index.pop(str(ref_hash or "").strip(), None)
        save_reference_archive_index(current_index)
        return None
    return {
        "hash": str(ref_hash or "").strip(),
        "date": ref_date,
        "filename": filename,
        "name": str(raw_entry.get("name", "") or filename),
        "mime_type": str(raw_entry.get("mime_type", "image/png") or "image/png"),
    }


def upsert_reference_archive_index_entry(ref_hash: str, entry: dict, index: dict[str, dict] | None = None) -> None:
    normalized_hash = str(ref_hash or "").strip()
    if not normalized_hash:
        return
    current_index = index if isinstance(index, dict) else load_reference_archive_index()
    current_index[normalized_hash] = {
        "date": str(entry.get("date", "") or "").strip(),
        "filename": os.path.basename(str(entry.get("filename", "") or "").strip()),
        "name": str(entry.get("name", "") or "").strip(),
        "mime_type": str(entry.get("mime_type", "image/png") or "image/png"),
        "updated_at": utc_now_iso(),
    }
    if current_index is not index:
        save_reference_archive_index(current_index)


def remove_reference_archive_index_entries(date_str: str, filename: str, index: dict[str, dict] | None = None) -> None:
    safe_date = str(date_str or "").strip()
    safe_filename = os.path.basename(str(filename or "").strip())
    if not safe_date or not safe_filename:
        return
    current_index = index if isinstance(index, dict) else load_reference_archive_index()
    stale_keys = []
    for key, value in current_index.items():
        if not isinstance(value, dict):
            stale_keys.append(key)
            continue
        value_date = str(value.get("date", "") or "").strip()
        value_filename = os.path.basename(str(value.get("filename", "") or "").strip())
        if value_date == safe_date and value_filename == safe_filename:
            stale_keys.append(key)
    for key in stale_keys:
        current_index.pop(key, None)
    if stale_keys and current_index is not index:
        save_reference_archive_index(current_index)


def meta_uses_reference_archive_entry(meta: dict, date_str: str, filename: str) -> bool:
    if not isinstance(meta, dict):
        return False
    safe_date = str(date_str or "").strip()
    safe_filename = os.path.basename(str(filename or "").strip())
    if not safe_date or not safe_filename:
        return False

    archive_groups = []
    ref_archive = meta.get("refArchive")
    if isinstance(ref_archive, list):
        archive_groups.append(ref_archive)
    video_ref_archive = meta.get("videoRefArchive")
    if isinstance(video_ref_archive, list):
        archive_groups.append(video_ref_archive)
    video_source_archive = meta.get("videoSourceArchive")
    if isinstance(video_source_archive, dict):
        archive_groups.append([video_source_archive])

    for group in archive_groups:
        for ref in group:
            if not isinstance(ref, dict):
                continue
            ref_date = str(ref.get("date", "") or "").strip()
            ref_name = os.path.basename(str(ref.get("filename", "") or "").strip())
            if ref_date == safe_date and ref_name == safe_filename:
                return True
    return False


def is_reference_archive_entry_still_used(date_str: str, filename: str) -> bool:
    safe_date = str(date_str or "").strip()
    safe_filename = os.path.basename(str(filename or "").strip())
    if not safe_date or not safe_filename:
        return False
    for root_dir in (GENERATIONS_DIR, VIDEOS_DIR):
        if not os.path.isdir(root_dir):
            continue
        for meta_file in list_meta_files_recursive(root_dir):
            try:
                with open(meta_file, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except Exception:
                continue
            if meta_uses_reference_archive_entry(meta, safe_date, safe_filename):
                return True
    return False


def normalize_reference_recovery_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def iter_candidate_reference_source_files() -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    search_roots = (
        GENERATIONS_DIR,
        VIDEOS_DIR,
        os.path.join(ELEMENTS_DIR, "Model Managment"),
        REFERENCE_ARCHIVE_DIR,
    )
    allowed_exts = {".png", ".jpg", ".jpeg", ".webp"}
    for root_dir in search_roots:
        if not os.path.isdir(root_dir):
            continue
        for current_root, _, filenames in os.walk(root_dir):
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext not in allowed_exts:
                    continue
                path = os.path.join(current_root, name)
                if path in seen:
                    continue
                seen.add(path)
                candidates.append(path)
    return candidates


def find_reference_recovery_source(filename: str) -> tuple[str, str] | tuple[None, None]:
    safe_filename = os.path.basename(str(filename or "").strip())
    stem = os.path.splitext(safe_filename)[0]
    stem = re.sub(r"^\d+_ref_\d+_[0-9a-f]{10}_", "", stem)
    search_key = normalize_reference_recovery_key(stem)
    if not search_key:
        return None, None

    best_path = None
    best_name = None
    best_score = -1
    best_delta = 10**9
    for path in iter_candidate_reference_source_files():
        base_name = os.path.basename(path)
        base_stem = os.path.splitext(base_name)[0]
        candidate_key = normalize_reference_recovery_key(base_stem)
        if not candidate_key:
            continue
        score = -1
        if candidate_key == search_key:
            score = 100
        elif candidate_key.startswith(search_key) or search_key.startswith(candidate_key):
            score = 80
        elif search_key in candidate_key or candidate_key in search_key:
            score = 60
        if score < 0:
            continue
        delta = abs(len(candidate_key) - len(search_key))
        if score < best_score:
            continue
        if score == best_score and delta >= best_delta:
            continue
        best_score = score
        best_delta = delta
        best_path = path
        best_name = base_name
    if best_path and best_score >= 60:
        return best_path, best_name
    return None, None


def build_reference_payload_from_file(file_path: str, display_name: str = "") -> dict:
    with open(file_path, "rb") as fh:
        payload_b64 = base64.b64encode(fh.read()).decode("utf-8")
    mime_type = "image/png"
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    elif ext == ".webp":
        mime_type = "image/webp"
    return {
        "ok": True,
        "name": display_name or os.path.basename(file_path),
        "mime_type": mime_type,
        "data": payload_b64,
        "original_data": payload_b64,
        "original_mime_type": mime_type,
        "mask_png_data": "",
        "original_url": "",
        "masked_url": "",
        "mask_url": "",
        "has_mask": False,
        "recovered": True,
    }


def compute_reference_archive_file_hash(date_str: str, filename: str) -> str:
    paths = get_reference_mask_file_paths(date_str, filename)
    if not os.path.exists(paths["original_path"]):
        return ""
    try:
        digest = hashlib.sha256()
        with open(paths["original_path"], "rb") as fh:
            digest.update(fh.read())
        digest.update(b"\n--mask--\n")
        if os.path.exists(paths["mask_path"]):
            with open(paths["mask_path"], "rb") as fh:
                digest.update(fh.read())
        return digest.hexdigest()
    except Exception:
        return ""


def build_reference_archive_entries(ref_images: list[dict], date_str: str, time_prefix: str) -> list[dict]:
    if not ref_images:
        return []
    archive_day_dir = os.path.join(REFERENCE_ARCHIVE_DIR, date_str)
    os.makedirs(archive_day_dir, exist_ok=True)
    archived = []
    archive_index = load_reference_archive_index()
    index_changed = False
    for idx, img in enumerate(ref_images):
        if not isinstance(img, dict):
            continue
        img_b64 = str(img.get("data", "") or "").strip()
        if not img_b64:
            continue
        source_b64 = str(img.get("original_data", "") or "").strip()
        mime_type = str(img.get("original_mime_type", img.get("mime_type", "image/png")) or "image/png")
        existing_date = str(img.get("archive_date", "") or "").strip()
        existing_filename = os.path.basename(str(img.get("archive_filename", "") or "").strip())
        existing_path = os.path.join(REFERENCE_ARCHIVE_DIR, existing_date, existing_filename) if existing_date and existing_filename else ""
        mask_png_data = str(img.get("mask_png_data", "") or "").strip()

        # Reusing an already-archived reference should keep pointing at the same
        # archive entry unless the user explicitly edited the mask/source data.
        if existing_path and os.path.exists(existing_path) and not mask_png_data:
            existing_hash = compute_reference_archive_file_hash(existing_date, existing_filename)
            if existing_hash and not get_reference_archive_index_entry(existing_hash, archive_index):
                upsert_reference_archive_index_entry(existing_hash, {
                    "date": existing_date,
                    "filename": existing_filename,
                    "name": str(img.get("name", "") or existing_filename),
                    "mime_type": "image/png",
                }, archive_index)
                index_changed = True
            existing_entry = enrich_reference_archive_entry({
                "date": existing_date,
                "filename": existing_filename,
                "name": str(img.get("name", "") or existing_filename),
                "mime_type": "image/png",
            })
            archived.append(existing_entry)
            continue

        if not source_b64:
            source_date = existing_date
            source_filename = existing_filename
            source_path = os.path.join(REFERENCE_ARCHIVE_DIR, source_date, source_filename) if source_date and source_filename else ""
            if source_path and os.path.exists(source_path):
                try:
                    with open(source_path, "rb") as fh:
                        source_b64 = base64.b64encode(fh.read()).decode("utf-8")
                    mime_type = "image/png"
                except Exception:
                    source_b64 = ""
        if not source_b64:
            source_b64 = img_b64
        try:
            png_b64, png_mime = convert_image_b64_to_png(source_b64, mime_type)
        except Exception:
            continue
        ref_hash = compute_reference_archive_hash(png_b64, mask_png_data)
        indexed_entry = get_reference_archive_index_entry(ref_hash, archive_index)
        if indexed_entry:
            # Keep mask assets in sync if this run supplied a fresh mask payload.
            if mask_png_data:
                try:
                    save_reference_mask_assets(indexed_entry["date"], indexed_entry["filename"], mask_png_data)
                except Exception:
                    pass
            archived.append(enrich_reference_archive_entry(indexed_entry))
            continue

        original_name = os.path.basename(str(img.get("name", "") or f"reference-{idx + 1}.png"))
        stem = os.path.splitext(original_name)[0] or f"reference-{idx + 1}"
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or f"reference-{idx + 1}"
        filename = f"{time_prefix}_ref_{idx + 1}_{ref_hash[:10]}_{safe_stem}.png"
        archive_path = os.path.join(archive_day_dir, filename)
        with open(archive_path, "wb") as fh:
            fh.write(base64.b64decode(png_b64))
        if mask_png_data:
            try:
                save_reference_mask_assets(date_str, filename, mask_png_data)
            except Exception:
                pass
        archive_entry = {
            "date": date_str,
            "filename": filename,
            "name": original_name,
            "mime_type": png_mime,
        }
        upsert_reference_archive_index_entry(ref_hash, archive_entry, archive_index)
        index_changed = True
        archived.append(enrich_reference_archive_entry(archive_entry))
    if index_changed:
        save_reference_archive_index(archive_index)
    return archived


def delete_reference_archive_entries(entries: list[dict]):
    safe_root = os.path.realpath(REFERENCE_ARCHIVE_DIR)
    seen = set()
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        date_str = str(item.get("date", "") or "").strip()
        filename = os.path.basename(str(item.get("filename", "") or "").strip())
        if not date_str or not filename:
            continue
        ref_key = f"{date_str}/{filename}"
        if ref_key in seen:
            continue
        seen.add(ref_key)
        archive_path = os.path.realpath(os.path.join(REFERENCE_ARCHIVE_DIR, date_str, filename))
        if not archive_path.startswith(safe_root + os.sep):
            continue
        if is_reference_archive_entry_still_used(date_str, filename):
            continue
        if os.path.exists(archive_path):
            try:
                os.remove(archive_path)
            except Exception:
                pass
        delete_reference_mask_assets(date_str, filename)
        remove_reference_archive_index_entries(date_str, filename)
        archive_day_dir = os.path.dirname(archive_path)
        if os.path.isdir(archive_day_dir) and not os.listdir(archive_day_dir):
            try:
                os.rmdir(archive_day_dir)
            except Exception:
                pass


def normalize_ref_image_payloads(ref_images: list[dict] | None, max_ref: int) -> list[dict]:
    normalized = []
    for img in (ref_images[:max_ref] if isinstance(ref_images, list) else []):
        if not isinstance(img, dict):
            continue
        data = str(img.get("data", "") or "").strip()
        if not data:
            continue
        item = {
            "mime_type": str(img.get("mime_type", "image/png") or "image/png"),
            "data": data,
            "name": str(img.get("name", "") or ""),
        }
        try:
            clamped_b64, clamped_mime = clamp_image_b64_max_side(item["data"], item["mime_type"])
            item["data"] = clamped_b64
            item["mime_type"] = clamped_mime
        except Exception:
            pass
        extra_fields = (
            "original_data",
            "original_mime_type",
            "mask_png_data",
            "archive_date",
            "archive_filename",
            "original_url",
            "masked_url",
            "mask_url",
        )
        for key in extra_fields:
            value = img.get(key)
            if value is None:
                continue
            item[key] = str(value or "")
        if img.get("has_mask") is not None:
            item["has_mask"] = bool(img.get("has_mask"))
        normalized.append(item)
    return normalized


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


def ensure_flask_secret_key() -> str:
    env_secret = (_os.environ.get("FLASK_SECRET_KEY", "") or "").strip()
    if env_secret:
        return env_secret

    config = load_config()
    secret = str(config.get("flask_secret_key", "") or "").strip()
    if not secret:
        secret = secrets.token_hex(32)
        config["flask_secret_key"] = secret
        save_config(config)
    return secret


app.secret_key = ensure_flask_secret_key()


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


def constrain_image_to_max_pixels(width: int, height: int, max_pixels: int) -> tuple[int, int]:
    width = max(1, int(width or 1))
    height = max(1, int(height or 1))
    max_pixels = max(1, int(max_pixels or 1))
    total_pixels = width * height
    if total_pixels <= max_pixels:
        return width, height

    scale = (max_pixels / float(total_pixels)) ** 0.5
    new_width = max(1, min(width, int(width * scale)))
    new_height = max(1, min(height, int(height * scale)))

    while new_width * new_height > max_pixels:
        if new_width >= new_height and new_width > 1:
            new_width -= 1
        elif new_height > 1:
            new_height -= 1
        else:
            break

    return new_width, new_height


def compress_seedream_ref_image(image_b64: str, mime_type: str) -> tuple[str, str]:
    """Clamp/compress a Seedream reference image to provider-safe pixel and byte limits."""
    raw = base64.b64decode(image_b64)
    img, info = open_base64_image(image_b64)
    orig_width, orig_height = img.size
    needs_pixel_clamp = (orig_width * orig_height) > SEEDREAM_MAX_INPUT_PIXELS
    if not needs_pixel_clamp and len(raw) <= SEEDREAM_TARGET_INPUT_BYTES:
        return image_b64, mime_type

    img = flatten_image_for_jpeg(img)
    clamped_width, clamped_height = constrain_image_to_max_pixels(orig_width, orig_height, SEEDREAM_MAX_INPUT_PIXELS)
    if (clamped_width, clamped_height) != img.size:
        img = img.resize((clamped_width, clamped_height), Image.LANCZOS)

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


def compress_video_input_image(image_b64: str, mime_type: str) -> tuple[str, str]:
    """Clamp/compress video start/reference images to provider-safe pixel and byte limits."""
    raw = base64.b64decode(image_b64)
    img, info = open_base64_image(image_b64)
    orig_width, orig_height = img.size
    needs_pixel_clamp = (orig_width * orig_height) > VIDEO_MAX_INPUT_PIXELS
    if not needs_pixel_clamp and len(raw) <= VIDEO_TARGET_INPUT_BYTES:
        return image_b64, mime_type

    img = flatten_image_for_jpeg(img)
    clamped_width, clamped_height = constrain_image_to_max_pixels(orig_width, orig_height, VIDEO_MAX_INPUT_PIXELS)
    if (clamped_width, clamped_height) != img.size:
        img = img.resize((clamped_width, clamped_height), Image.LANCZOS)

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
        if len(payload) <= VIDEO_TARGET_INPUT_BYTES:
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


def build_seedream_data_uri_ref_inputs(ref_images: list[dict]) -> list[str]:
    items = []
    for img in ref_images:
        mime = img.get("mime_type", "image/png")
        data = img.get("data", "")
        if data:
            safe_b64, safe_mime = compress_seedream_ref_image(data, mime)
            items.append(f"data:{safe_mime};base64,{safe_b64}")
    return items


def fetch_remote_reference_image(url: str) -> tuple[str, str, str]:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https image URLs are supported.")

    try:
        response = requests.get(
            url,
            headers={"User-Agent": f"AI API Studio/{APP_VERSION}"},
            stream=True,
            timeout=20,
        )
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timed out while downloading the dropped image.") from exc
    except Exception as exc:
        raise RuntimeError(f"Could not download the dropped image: {exc}") from exc

    with response:
        if response.status_code != 200:
            raise ValueError(f"Could not download the dropped image ({response.status_code}).")

        content_type = (response.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            raise ValueError("The dropped URL did not return an image.")

        chunks = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > REMOTE_REF_FETCH_MAX_BYTES:
                raise ValueError("The dropped image is too large to import.")
            chunks.append(chunk)

    raw = b"".join(chunks)
    if not raw:
        raise ValueError("The dropped image was empty.")

    filename = os.path.basename(unquote(parsed.path or "")) or "reference-image"
    return base64.b64encode(raw).decode("utf-8"), content_type, filename


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


def extract_kling_error(resp: requests.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        raw = (resp.text or "").strip()
        return raw or f"HTTP {resp.status_code}"
    if isinstance(payload, dict):
        for key in ("message", "msg", "error_msg", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if isinstance(payload.get("data"), dict):
            data = payload["data"]
            for key in ("task_status_msg", "message", "msg"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
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


def normalize_seedvr_preset(value: str | None) -> tuple[str, float | None, str | None, str]:
    presets = {
        "factor:2": ("factor", 2.0, None, "2X"),
        "factor:4": ("factor", 4.0, None, "4X"),
        "target:720p": ("target", None, "720p", "720P"),
        "target:1080p": ("target", None, "1080p", "1080P"),
        "target:1440p": ("target", None, "1440p", "1440P"),
        "target:2160p": ("target", None, "2160p", "4K"),
    }
    return presets.get(str(value or "factor:2").strip().lower(), presets["factor:2"])


def normalize_seedvr_custom_resolution(
    source_width: int,
    source_height: int,
    target_width: int | str | None,
    target_height: int | str | None,
    anchor: str | None,
) -> tuple[int, int, float, str]:
    safe_source_width = max(1, int(source_width or 0))
    safe_source_height = max(1, int(source_height or 0))
    if not safe_source_width or not safe_source_height:
        raise ValueError("Could not read the selected image size for custom upscaling.")

    safe_anchor = str(anchor or "width").strip().lower()
    if safe_anchor not in {"width", "height"}:
        safe_anchor = "width"

    raw_width = int(target_width or 0)
    raw_height = int(target_height or 0)
    if raw_width <= 0 and raw_height <= 0:
        raise ValueError("Enter a custom output width or height.")

    if safe_anchor == "height":
        locked_height = max(64, raw_height or int(round((raw_width * safe_source_height) / safe_source_width)))
        locked_width = max(64, int(round((locked_height * safe_source_width) / safe_source_height)))
    else:
        locked_width = max(64, raw_width or int(round((raw_height * safe_source_width) / safe_source_height)))
        locked_height = max(64, int(round((locked_width * safe_source_height) / safe_source_width)))

    upscale_factor = max(1.0, locked_width / safe_source_width, locked_height / safe_source_height)
    return locked_width, locked_height, round(upscale_factor, 6), safe_anchor


def approximate_image_size_label(width: int, height: int) -> str:
    max_dim = max(int(width or 0), int(height or 0))
    if max_dim >= 3840:
        return "4K"
    if max_dim >= 2048:
        return "2K"
    if max_dim >= 1024:
        return "1K"
    if max_dim >= 512:
        return "0.5K"
    return f"{max_dim}px" if max_dim else ""


def measure_image_dimensions(image_b64: str, mime_type: str = "image/png") -> tuple[int, int]:
    try:
        raw = base64.b64decode(image_b64)
        with Image.open(io.BytesIO(raw)) as img:
            return img.size
    except Exception:
        return 0, 0


def measure_image_file_dimensions(file_path: str) -> tuple[int, int]:
    try:
        with Image.open(file_path) as img:
            return img.size
    except Exception:
        return 0, 0


def resize_image_b64_to_exact_png(image_b64: str, mime_type: str, target_width: int, target_height: int) -> tuple[str, str]:
    """Resize an image payload to an exact PNG output while preserving ICC data."""
    safe_width = max(1, int(target_width or 0))
    safe_height = max(1, int(target_height or 0))
    if not safe_width or not safe_height:
        return image_b64, mime_type or "image/png"

    img, info = open_base64_image(image_b64)
    has_alpha = ("A" in img.getbands()) or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
    elif img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    if img.size != (safe_width, safe_height):
        img = img.resize((safe_width, safe_height), Image.LANCZOS)

    buf = io.BytesIO()
    save_kwargs = {"format": "PNG", "optimize": True}
    icc_profile = info.get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    img.save(buf, **save_kwargs)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8"), "image/png"


def clamp_image_b64_max_side(image_b64: str, mime_type: str, max_pixels: int = MAX_REFERENCE_IMAGE_PIXELS) -> tuple[str, str]:
    """Resize an image proportionally when it exceeds the app's 4K-equivalent pixel budget."""
    img, info = open_base64_image(image_b64)
    width, height = img.size
    if (width * height) <= max_pixels:
        return image_b64, mime_type

    new_width, new_height = constrain_image_to_max_pixels(width, height, max_pixels)
    img = img.resize((new_width, new_height), Image.LANCZOS)

    has_alpha = ("A" in img.getbands()) or (img.mode == "P" and "transparency" in img.info)
    buf = io.BytesIO()
    icc_profile = info.get("icc_profile")
    if has_alpha:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        save_kwargs = {"format": "PNG", "optimize": True}
        if icc_profile:
            save_kwargs["icc_profile"] = icc_profile
        img.save(buf, **save_kwargs)
        out_mime = "image/png"
    else:
        img = flatten_image_for_jpeg(img)
        save_kwargs = {"format": "JPEG", "quality": JPEG_QUALITY, "optimize": True}
        if icc_profile:
            save_kwargs["icc_profile"] = icc_profile
        img.save(buf, **save_kwargs)
        out_mime = "image/jpeg"

    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8"), out_mime


def get_reference_mask_file_paths(date_str: str, filename: str) -> dict[str, str]:
    safe_date = str(date_str or "").strip()
    safe_filename = os.path.basename(str(filename or "").strip())
    base_stem = os.path.splitext(safe_filename)[0]
    return {
        "original_dir": os.path.join(REFERENCE_ARCHIVE_DIR, safe_date),
        "original_path": os.path.join(REFERENCE_ARCHIVE_DIR, safe_date, safe_filename),
        "mask_dir": os.path.join(REFERENCE_MASKS_DIR, safe_date),
        "mask_path": os.path.join(REFERENCE_MASKS_DIR, safe_date, safe_filename),
        "meta_path": os.path.join(REFERENCE_MASKS_DIR, safe_date, f"{base_stem}.json"),
        "render_dir": os.path.join(REFERENCE_RENDERS_DIR, safe_date),
        "render_path": os.path.join(REFERENCE_RENDERS_DIR, safe_date, safe_filename),
    }


def build_reference_mask_bundle(date_str: str, filename: str) -> dict:
    safe_date = str(date_str or "").strip()
    safe_filename = os.path.basename(str(filename or "").strip())
    paths = get_reference_mask_file_paths(safe_date, safe_filename)
    has_mask = os.path.exists(paths["mask_path"]) and os.path.exists(paths["render_path"])
    return {
        "date": safe_date,
        "filename": safe_filename,
        "has_mask": has_mask,
        "original_url": f"/reference-archive/{safe_date}/{safe_filename}",
        "masked_url": f"/reference-render/{safe_date}/{safe_filename}" if has_mask else "",
        "mask_url": f"/reference-mask/{safe_date}/{safe_filename}" if has_mask else "",
        "display_url": f"/reference-render/{safe_date}/{safe_filename}" if has_mask else f"/reference-archive/{safe_date}/{safe_filename}",
        "mask_edit_payload": {
            "kind": "references",
            "date": safe_date,
            "filename": safe_filename,
        },
    }


def load_reference_mask_metadata(date_str: str, filename: str) -> dict:
    paths = get_reference_mask_file_paths(date_str, filename)
    if not os.path.exists(paths["meta_path"]):
        return {}
    try:
        with open(paths["meta_path"], "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def delete_reference_mask_assets(date_str: str, filename: str) -> None:
    paths = get_reference_mask_file_paths(date_str, filename)
    for key in ("mask_path", "meta_path", "render_path"):
        path = paths[key]
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    for dir_key in ("mask_dir", "render_dir"):
        folder = paths[dir_key]
        if os.path.isdir(folder) and not os.listdir(folder):
            try:
                os.rmdir(folder)
            except Exception:
                pass


def save_reference_mask_assets(date_str: str, filename: str, mask_png_b64: str) -> dict:
    paths = get_reference_mask_file_paths(date_str, filename)
    original_path = paths["original_path"]
    if not os.path.exists(original_path):
        raise FileNotFoundError("Reference image not found.")

    mask_img, _ = open_base64_image(mask_png_b64)
    original_img = Image.open(original_path)
    original_img.load()
    original_info = dict(getattr(original_img, "info", {}) or {})
    original_img = ImageOps.exif_transpose(original_img).convert("RGBA")

    mask_img = ImageOps.exif_transpose(mask_img).convert("L")
    if mask_img.size != original_img.size:
        mask_img = mask_img.resize(original_img.size, Image.Resampling.LANCZOS)

    render_img = original_img.copy()
    render_img.putalpha(mask_img)

    os.makedirs(paths["mask_dir"], exist_ok=True)
    os.makedirs(paths["render_dir"], exist_ok=True)

    mask_buf = io.BytesIO()
    mask_img.save(mask_buf, format="PNG", optimize=True)
    with open(paths["mask_path"], "wb") as fh:
        fh.write(mask_buf.getvalue())

    render_buf = io.BytesIO()
    save_kwargs = {"format": "PNG", "optimize": True}
    icc_profile = original_info.get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    render_img.save(render_buf, **save_kwargs)
    with open(paths["render_path"], "wb") as fh:
        fh.write(render_buf.getvalue())

    metadata = {
        "date": str(date_str or "").strip(),
        "filename": os.path.basename(str(filename or "").strip()),
        "updated_at": utc_now_iso(),
        "width": int(original_img.width),
        "height": int(original_img.height),
        "mode": "alpha_mask",
    }
    with open(paths["meta_path"], "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, ensure_ascii=False)
    return metadata


def enrich_reference_archive_entry(entry: dict | None) -> dict:
    entry = dict(entry or {})
    ref_date = str(entry.get("date", "") or "").strip()
    filename = os.path.basename(str(entry.get("filename", "") or "").strip())
    if not ref_date or not filename:
        return entry
    bundle = build_reference_mask_bundle(ref_date, filename)
    enriched = {
        "date": ref_date,
        "filename": filename,
        "name": entry.get("name", "") or filename,
        "mime_type": entry.get("mime_type", "image/png"),
        "url": entry.get("url") or bundle["display_url"],
        "original_url": entry.get("original_url") or bundle["original_url"],
        "masked_url": entry.get("masked_url") or bundle["masked_url"],
        "mask_url": entry.get("mask_url") or bundle["mask_url"],
        "has_mask": bool(entry.get("has_mask")) or bundle["has_mask"],
        "mask_edit_payload": entry.get("mask_edit_payload") or bundle["mask_edit_payload"],
    }
    enriched["url"] = enriched["masked_url"] if enriched["has_mask"] and enriched["masked_url"] else (enriched["original_url"] or bundle["display_url"])
    return enriched


def enrich_reference_archive_entries(entries: list[dict] | None) -> list[dict]:
    result = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        result.append(enrich_reference_archive_entry(entry))
    return result


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


def download_remote_binary(url: str, *, headers: dict | None = None, timeout: int = 240) -> tuple[bytes, str]:
    response = requests.get(url, headers=headers or {}, timeout=timeout)
    response.raise_for_status()
    return response.content, str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()


def extract_fal_video_result(payload: dict) -> dict | None:
    candidates = []
    if isinstance(payload, dict):
        if isinstance(payload.get("video"), dict):
            candidates.append(payload.get("video"))
        if isinstance(payload.get("videos"), list):
            candidates.extend([item for item in payload.get("videos") if isinstance(item, dict)])
        if isinstance(payload.get("data"), dict):
            data_payload = payload.get("data")
            if isinstance(data_payload.get("video"), dict):
                candidates.append(data_payload.get("video"))
            if isinstance(data_payload.get("videos"), list):
                candidates.extend([item for item in data_payload.get("videos") if isinstance(item, dict)])
    for item in candidates:
        video_url = str(item.get("url") or item.get("video_url") or "").strip()
        if video_url:
            return {
                "url": video_url,
                "mime_type": str(item.get("content_type") or item.get("mime_type") or "video/mp4").strip() or "video/mp4",
                "poster_url": str(item.get("thumbnail_url") or item.get("poster_url") or item.get("preview_image_url") or "").strip(),
                "width": int(item.get("width") or 0),
                "height": int(item.get("height") or 0),
            }
    return None


def normalize_video_extension(mime_type: str, fallback_url: str = "") -> tuple[str, str]:
    mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if mime in {"video/mp4", "application/mp4"}:
        return "mp4", "video/mp4"
    if mime in {"video/webm"}:
        return "webm", "video/webm"
    if mime in {"video/quicktime"}:
        return "mov", "video/quicktime"
    if mime in {"image/gif", "video/gif"}:
        return "gif", "image/gif"
    parsed_path = os.path.basename(urlparse(str(fallback_url or "")).path or "")
    ext = os.path.splitext(parsed_path)[1].lower()
    if ext in {".mp4", ".webm", ".mov", ".gif"}:
        return ext.lstrip("."), mime or {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".gif": "image/gif",
        }[ext]
    return "mp4", "video/mp4"


def get_video_extension_for_payload(mime_type: str = "", filename: str = "") -> str:
    _, normalized_mime = normalize_video_extension(mime_type, filename)
    ext, _ = normalize_video_extension(normalized_mime, filename)
    return ext or "mp4"


def resolve_local_video_url_to_path(video_url: str) -> str:
    parsed = urlparse(str(video_url or "").strip())
    path = unquote(parsed.path or "")
    if not path.startswith("/videos/"):
        return ""
    relpath = "/".join([part for part in path.split("/") if part][1:])
    if not relpath:
        return ""
    try:
        local_path = safe_asset_path(VIDEOS_DIR, relpath)
    except Exception:
        return ""
    return local_path if os.path.exists(local_path) else ""


def upload_video_payload_to_fal(client: fal_client.SyncClient, video_payload: dict) -> str:
    if not isinstance(video_payload, dict):
        raise ValueError("Choose or drop a source video for this model.")
    data_b64 = str(video_payload.get("data") or "").strip()
    direct_url = str(video_payload.get("url") or "").strip()
    mime_type = str(video_payload.get("mime_type") or "video/mp4").strip() or "video/mp4"
    name = os.path.basename(str(video_payload.get("name") or "video-source.mp4")) or "video-source.mp4"

    if direct_url.startswith("http://") or direct_url.startswith("https://"):
        return direct_url

    local_path = resolve_local_video_url_to_path(direct_url)
    if local_path:
        return str(client.upload_file(local_path))

    if not data_b64:
        raise ValueError("Choose or drop a source video for this model.")

    suffix = f".{get_video_extension_for_payload(mime_type, name)}"
    temp_path = ""
    try:
        raw_bytes = base64.b64decode(data_b64, validate=False)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(raw_bytes)
            temp_path = temp_file.name
        return str(client.upload_file(temp_path))
    except Exception as exc:
        raise RuntimeError(f"Could not upload the selected source video: {exc}") from exc
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass


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
# Routes Ã¢â‚¬â€ Auth
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
# Routes Ã¢â‚¬â€ App
# ---------------------------------------------------------------------------
@app.route("/index")
@login_required
def index():
    config = load_config()
    has_key = bool(
        config.get("api_key", "").strip()
        or config.get("fal_api_key", "").strip()
        or config.get("byteplus_api_key", "").strip()
        or config.get("kling_api_token", "").strip()
    )
    return render_template("index.html",
                           models=MODELS_INFO,
                           model_families=MODEL_FAMILIES,
                           video_models=VIDEO_MODELS_INFO,
                           video_model_families=VIDEO_MODEL_FAMILIES,
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
    kling_api_token = config.get("kling_api_token", "")
    return render_template("settings.html",
                           masked_key=mask_api_key(api_key),
                           has_key=bool(api_key),
                           masked_fal_key=mask_api_key(fal_api_key),
                           has_fal_key=bool(fal_api_key),
                           masked_byteplus_key=mask_api_key(byteplus_api_key),
                           has_byteplus_key=bool(byteplus_api_key),
                           masked_kling_token=mask_api_key(kling_api_token),
                           has_kling_token=bool(kling_api_token),
                           stats=stats,
                           vision_models=VISION_MODELS_INFO,
                           analysis_model=TALENT_ANALYSIS_MODEL,
                           user=session["user"])


# ---------------------------------------------------------------------------
# Route Ã¢â‚¬â€ Credits
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
# Routes - Asset galleries
# ---------------------------------------------------------------------------
ASSET_GALLERY_PAGE_CONFIG = {
    "loved": {
        "title": "Loved Images",
        "subtitle": "Favorites saved for reuse and reference.",
        "empty_title": "No loved images yet.",
        "empty_subtitle": "Generate images and press the heart button to save them here.",
    },
    "references": {
        "title": "References",
        "subtitle": "Previously used saved references from your archived generation inputs.",
        "empty_title": "No archived references yet.",
        "empty_subtitle": "Generate with reference images and they will appear here for reuse.",
    },
    "history": {
        "title": "History",
        "subtitle": "Saved generations with the same filters, selection, and scaling flow as the Generator sidebar.",
        "empty_title": "No history images yet.",
        "empty_subtitle": "Generate images and they will appear here automatically.",
    },
    "videos": {
        "title": "Videos",
        "subtitle": "Saved generated videos with the same filters, selection, and scaling flow as the Generator sidebar.",
        "empty_title": "No videos yet.",
        "empty_subtitle": "Generate videos and they will appear here automatically.",
    },
}

VIDEO_ASPECT_RATIOS = ["16:9", "9:16", "1:1"]
VIDEO_DURATION_OPTIONS = [5, 10]
VIDEO_DURATION_EXTENDED_OPTIONS = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
VIDEO_DURATION_OMNI_OPTIONS = [3, 4, 5, 6, 7, 8, 9, 10]
VIDEO_DURATION_ALL_OPTIONS = sorted({*VIDEO_DURATION_OPTIONS, *VIDEO_DURATION_EXTENDED_OPTIONS})
KLING_RESOLUTION_OPTIONS = ["1080p"]
WAN_RESOLUTION_OPTIONS = ["720p", "1080p"]
SEEDANCE_RESOLUTION_OPTIONS = ["480p", "720p", "1080p"]

KLING_DIRECT_MODEL_SPECS = [
    {
        "id": "kling-v1-std",
        "native_model_name": "kling-v1",
        "label": "Kling 1.0 Standard",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 10,
        "kling_mode": "std",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v1-pro",
        "native_model_name": "kling-v1",
        "label": "Kling 1.0 Pro",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 11,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v1-5-std",
        "native_model_name": "kling-v1-5",
        "label": "Kling 1.5 Standard",
        "input_modes": ["image"],
        "durations": [5, 10],
        "sort_order": 20,
        "kling_mode": "std",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v1-5-pro",
        "native_model_name": "kling-v1-5",
        "label": "Kling 1.5 Pro",
        "input_modes": ["image"],
        "durations": [5, 10],
        "sort_order": 21,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v1-6-std",
        "native_model_name": "kling-v1-6",
        "label": "Kling 1.6 Standard",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 30,
        "kling_mode": "std",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v1-6-pro",
        "native_model_name": "kling-v1-6",
        "label": "Kling 1.6 Pro",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 31,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v1-6-reference-std",
        "native_model_name": "kling-v1-6",
        "label": "Kling 1.6 Reference Standard",
        "input_modes": ["reference"],
        "durations": [5, 10],
        "sort_order": 32,
        "kling_mode": "std",
        "video_mode_kind": "reference_to_video",
        "native_video_endpoint": "/v1/videos/multi-image2video",
        "native_reference_item_key": "image",
        "supports_reference_images": True,
        "reference_images_required": True,
        "max_reference_images": 4,
    },
    {
        "id": "kling-v1-6-reference-pro",
        "native_model_name": "kling-v1-6",
        "label": "Kling 1.6 Reference Pro",
        "input_modes": ["reference"],
        "durations": [5, 10],
        "sort_order": 33,
        "kling_mode": "pro",
        "video_mode_kind": "reference_to_video",
        "native_video_endpoint": "/v1/videos/multi-image2video",
        "native_reference_item_key": "image",
        "supports_reference_images": True,
        "reference_images_required": True,
        "max_reference_images": 4,
    },
    {
        "id": "kling-v2-master",
        "native_model_name": "kling-v2-master",
        "label": "Kling 2.0 Master",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 40,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v2-1-std",
        "native_model_name": "kling-v2-1",
        "label": "Kling 2.1 Standard",
        "input_modes": ["image"],
        "durations": [5, 10],
        "sort_order": 50,
        "kling_mode": "std",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v2-1-pro",
        "native_model_name": "kling-v2-1",
        "label": "Kling 2.1 Pro",
        "input_modes": ["image"],
        "durations": [5, 10],
        "sort_order": 51,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v2-1-master",
        "native_model_name": "kling-v2-1-master",
        "label": "Kling 2.1 Master",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 52,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v2-5-turbo-std",
        "native_model_name": "kling-v2-5-turbo",
        "label": "Kling 2.5 Turbo Standard",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 60,
        "kling_mode": "std",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v2-5-turbo-pro",
        "native_model_name": "kling-v2-5-turbo",
        "label": "Kling 2.5 Turbo Pro",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 61,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v2-6-std",
        "native_model_name": "kling-v2-6",
        "label": "Kling 2.6 Standard",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 70,
        "kling_mode": "std",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v2-6-pro",
        "native_model_name": "kling-v2-6",
        "label": "Kling 2.6 Pro",
        "input_modes": ["text", "image"],
        "durations": [5, 10],
        "sort_order": 71,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v3-std",
        "native_model_name": "kling-v3",
        "label": "Kling 3.0 Standard",
        "input_modes": ["text", "image"],
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "sort_order": 80,
        "kling_mode": "std",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-v3-pro",
        "native_model_name": "kling-v3",
        "label": "Kling 3.0 Pro",
        "input_modes": ["text", "image"],
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "sort_order": 81,
        "kling_mode": "pro",
        "supports_start_image": True,
        "start_image_required": True,
    },
    {
        "id": "kling-video-o1-std",
        "native_model_name": "kling-video-o1",
        "label": "Kling O1 Standard",
        "input_modes": ["text", "reference"],
        "durations": VIDEO_DURATION_OMNI_OPTIONS,
        "sort_order": 90,
        "kling_mode": "std",
        "video_mode_kind": "omni_video",
        "native_video_endpoint": "/v1/videos/omni-video",
        "native_reference_item_key": "image_url",
        "supports_start_image": True,
        "start_image_required": False,
        "supports_reference_images": True,
        "reference_images_required": False,
        "max_reference_images": 7,
    },
    {
        "id": "kling-video-o1-pro",
        "native_model_name": "kling-video-o1",
        "label": "Kling O1 Pro",
        "input_modes": ["text", "reference"],
        "durations": VIDEO_DURATION_OMNI_OPTIONS,
        "sort_order": 91,
        "kling_mode": "pro",
        "video_mode_kind": "omni_video",
        "native_video_endpoint": "/v1/videos/omni-video",
        "native_reference_item_key": "image_url",
        "supports_start_image": True,
        "start_image_required": False,
        "supports_reference_images": True,
        "reference_images_required": False,
        "max_reference_images": 7,
    },
    {
        "id": "kling-v3-omni-std",
        "native_model_name": "kling-v3-omni",
        "label": "Kling 3.0 Omni Standard",
        "input_modes": ["text", "reference"],
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "sort_order": 100,
        "kling_mode": "std",
        "video_mode_kind": "omni_video",
        "native_video_endpoint": "/v1/videos/omni-video",
        "native_reference_item_key": "image_url",
        "supports_start_image": True,
        "start_image_required": False,
        "supports_reference_images": True,
        "reference_images_required": False,
        "max_reference_images": 7,
    },
    {
        "id": "kling-v3-omni-pro",
        "native_model_name": "kling-v3-omni",
        "label": "Kling 3.0 Omni Pro",
        "input_modes": ["text", "reference"],
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "sort_order": 101,
        "kling_mode": "pro",
        "video_mode_kind": "omni_video",
        "native_video_endpoint": "/v1/videos/omni-video",
        "native_reference_item_key": "image_url",
        "supports_start_image": True,
        "start_image_required": False,
        "supports_reference_images": True,
        "reference_images_required": False,
        "max_reference_images": 7,
    },
]

FAL_KLING_MODEL_SPECS = [
    {
        "id": FAL_KLING_V1_STD_T2V_ID,
        "label": "Kling 1.0 Standard",
        "input_modes": ["text"],
        "durations": [5, 10],
        "sort_order": 80,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V1_STD_I2V_ID,
        "label": "Kling 1.0 Standard",
        "input_modes": ["image"],
        "durations": [5, 10],
        "sort_order": 81,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V15_PRO_T2V_ID,
        "label": "Kling 1.5 Pro",
        "durations": [5, 10],
        "input_modes": ["text"],
        "sort_order": 90,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V15_PRO_I2V_ID,
        "label": "Kling 1.5 Pro",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 91,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V16_STD_T2V_ID,
        "label": "Kling 1.6 Standard",
        "durations": [5, 10],
        "input_modes": ["text"],
        "sort_order": 100,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V16_STD_I2V_ID,
        "label": "Kling 1.6 Standard",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 101,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V16_STD_ELEMENTS_ID,
        "label": "Kling 1.6 Elements Standard",
        "durations": [5, 10],
        "input_modes": ["reference"],
        "sort_order": 102,
        "video_mode_kind": "reference_to_video",
        "supports_reference_images": True,
        "reference_images_required": True,
        "reference_images_field": "input_image_urls",
        "max_reference_images": 4,
    },
    {
        "id": FAL_KLING_V16_PRO_T2V_ID,
        "label": "Kling 1.6 Pro",
        "durations": [5, 10],
        "input_modes": ["text"],
        "sort_order": 110,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V16_PRO_I2V_ID,
        "label": "Kling 1.6 Pro",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 111,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V16_PRO_ELEMENTS_ID,
        "label": "Kling 1.6 Elements Pro",
        "durations": [5, 10],
        "input_modes": ["reference"],
        "sort_order": 112,
        "video_mode_kind": "reference_to_video",
        "supports_reference_images": True,
        "reference_images_required": True,
        "reference_images_field": "input_image_urls",
        "max_reference_images": 4,
    },
    {
        "id": FAL_KLING_V2_MASTER_T2V_ID,
        "label": "Kling 2.0 Master",
        "durations": [5, 10],
        "input_modes": ["text"],
        "sort_order": 115,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V2_MASTER_I2V_ID,
        "label": "Kling 2.0 Master",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 116,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V21_STD_I2V_ID,
        "label": "Kling 2.1 Standard",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 118,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V21_PRO_I2V_ID,
        "label": "Kling 2.1 Pro",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 119,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V21_MASTER_T2V_ID,
        "label": "Kling 2.1 Master",
        "durations": [5, 10],
        "input_modes": ["text"],
        "sort_order": 120,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V21_MASTER_I2V_ID,
        "label": "Kling 2.1 Master",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 121,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V25_TURBO_PRO_T2V_ID,
        "label": "Kling 2.5 Turbo Pro",
        "durations": [5, 10],
        "input_modes": ["text"],
        "sort_order": 125,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V25_TURBO_STD_I2V_ID,
        "label": "Kling 2.5 Turbo Standard",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 126,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V25_TURBO_PRO_I2V_ID,
        "label": "Kling 2.5 Turbo Pro",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 127,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_V26_PRO_T2V_ID,
        "label": "Kling 2.6 Pro",
        "durations": [5, 10],
        "input_modes": ["text"],
        "sort_order": 130,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V26_PRO_I2V_ID,
        "label": "Kling 2.6 Pro",
        "durations": [5, 10],
        "input_modes": ["image"],
        "sort_order": 131,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "start_image_url",
    },
    {
        "id": FAL_KLING_V30_STD_T2V_ID,
        "label": "Kling 3.0 Standard",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["text"],
        "sort_order": 140,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V30_STD_I2V_ID,
        "label": "Kling 3.0 Standard",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["image"],
        "sort_order": 141,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "start_image_url",
    },
    {
        "id": FAL_KLING_V30_PRO_T2V_ID,
        "label": "Kling 3.0 Pro",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["text"],
        "sort_order": 150,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_V30_PRO_I2V_ID,
        "label": "Kling 3.0 Pro",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["image"],
        "sort_order": 151,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "start_image_url",
    },
    {
        "id": FAL_KLING_O1_STD_I2V_ID,
        "label": "Kling O1 Standard",
        "durations": [3, 4, 5, 6, 7, 8, 9, 10],
        "input_modes": ["image"],
        "sort_order": 158,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "start_image_url",
    },
    {
        "id": FAL_KLING_O1_REF_I2V_ID,
        "label": "Kling O1 Standard Reference",
        "durations": [3, 4, 5, 6, 7, 8, 9, 10],
        "input_modes": ["reference"],
        "sort_order": 160,
        "video_mode_kind": "reference_to_video",
        "supports_reference_images": True,
        "reference_images_required": True,
        "reference_images_field": "image_urls",
        "max_reference_images": 7,
    },
    {
        "id": FAL_KLING_O1_PRO_I2V_ID,
        "label": "Kling O1 Pro",
        "durations": [3, 4, 5, 6, 7, 8, 9, 10],
        "input_modes": ["image"],
        "sort_order": 165,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "start_image_url",
    },
    {
        "id": FAL_KLING_O1_PRO_REF_I2V_ID,
        "label": "Kling O1 Pro Reference",
        "durations": [3, 4, 5, 6, 7, 8, 9, 10],
        "input_modes": ["reference"],
        "sort_order": 166,
        "video_mode_kind": "reference_to_video",
        "supports_reference_images": True,
        "reference_images_required": True,
        "reference_images_field": "image_urls",
        "max_reference_images": 7,
    },
    {
        "id": FAL_KLING_O3_STD_T2V_ID,
        "label": "Kling O3 Standard",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["text"],
        "sort_order": 170,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_O3_STD_I2V_ID,
        "label": "Kling O3 Standard",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["image"],
        "sort_order": 171,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_O3_STD_V2V_ID,
        "label": "Kling O3 Standard V2V",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["video"],
        "sort_order": 171,
        "video_mode_kind": "video_to_video",
        "supports_source_video": True,
        "source_video_required": True,
        "source_video_field": "video_url",
    },
    {
        "id": FAL_KLING_O3_REF_I2V_ID,
        "label": "Kling O3 Reference",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["reference"],
        "sort_order": 172,
        "video_mode_kind": "reference_to_video",
        "supports_start_image": True,
        "start_image_required": False,
        "start_image_field": "start_image_url",
        "supports_reference_images": True,
        "reference_images_required": True,
        "reference_images_field": "image_urls",
        "max_reference_images": 4,
    },
    {
        "id": FAL_KLING_O3_PRO_T2V_ID,
        "label": "Kling O3 Pro",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["text"],
        "sort_order": 175,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_KLING_O3_PRO_I2V_ID,
        "label": "Kling O3 Pro",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["image"],
        "sort_order": 176,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_KLING_O3_PRO_V2V_ID,
        "label": "Kling O3 Pro V2V",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["video"],
        "sort_order": 176,
        "video_mode_kind": "video_to_video",
        "supports_source_video": True,
        "source_video_required": True,
        "source_video_field": "video_url",
    },
    {
        "id": FAL_KLING_O3_PRO_REF_I2V_ID,
        "label": "Kling O3 Pro Reference",
        "durations": VIDEO_DURATION_EXTENDED_OPTIONS,
        "input_modes": ["reference"],
        "sort_order": 177,
        "video_mode_kind": "reference_to_video",
        "supports_start_image": True,
        "start_image_required": False,
        "start_image_field": "start_image_url",
        "supports_reference_images": True,
        "reference_images_required": True,
        "reference_images_field": "image_urls",
        "max_reference_images": 4,
    },
]

for _spec in KLING_DIRECT_MODEL_SPECS:
    _spec.setdefault("resolutions", list(KLING_RESOLUTION_OPTIONS))

for _spec in FAL_KLING_MODEL_SPECS:
    _spec.setdefault("resolutions", list(KLING_RESOLUTION_OPTIONS))

FAL_SEEDANCE_MODEL_SPECS = [
    {
        "id": FAL_SEEDANCE_V1_LITE_T2V_ID,
        "label": "Seedance 1.0 Lite",
        "input_modes": ["text"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 220,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_SEEDANCE_V1_LITE_I2V_ID,
        "label": "Seedance 1.0 Lite",
        "input_modes": ["image"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 221,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_SEEDANCE_V1_LITE_REF_ID,
        "label": "Seedance 1.0 Lite Reference",
        "input_modes": ["reference"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 222,
        "video_mode_kind": "reference_to_video",
        "supports_reference_images": True,
        "reference_images_required": True,
        "reference_images_field": "reference_image_urls",
        "max_reference_images": 4,
    },
    {
        "id": FAL_SEEDANCE_V1_PRO_T2V_ID,
        "label": "Seedance 1.0 Pro",
        "input_modes": ["text"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 225,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_SEEDANCE_V1_PRO_I2V_ID,
        "label": "Seedance 1.0 Pro",
        "input_modes": ["image"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 226,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_SEEDANCE_V1_PRO_FAST_T2V_ID,
        "label": "Seedance 1.0 Pro Fast",
        "input_modes": ["text"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 230,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_SEEDANCE_V1_PRO_FAST_I2V_ID,
        "label": "Seedance 1.0 Pro Fast",
        "input_modes": ["image"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 231,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
    {
        "id": FAL_SEEDANCE_V15_PRO_T2V_ID,
        "label": "Seedance 1.5 Pro",
        "input_modes": ["text"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 240,
        "video_mode_kind": "text_to_video",
    },
    {
        "id": FAL_SEEDANCE_V15_PRO_I2V_ID,
        "label": "Seedance 1.5 Pro",
        "input_modes": ["image"],
        "durations": [5, 10],
        "resolutions": SEEDANCE_RESOLUTION_OPTIONS,
        "sort_order": 241,
        "video_mode_kind": "image_to_video",
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
    },
]


def _build_video_models_info() -> dict:
    info: dict[str, dict] = {}
    for spec in KLING_DIRECT_MODEL_SPECS:
        info[spec["id"]] = {
            "provider": "kling",
            "provider_label": "Kling",
            "family": "kling",
            "label": spec["label"],
            "input_modes": list(spec.get("input_modes", ["text"])),
            "durations": list(spec.get("durations", VIDEO_DURATION_OPTIONS)),
            "aspect_ratios": list(spec.get("aspect_ratios", VIDEO_ASPECT_RATIOS)),
            "supports_negative_prompt": True,
            "supports_safety_checker": False,
            "supports_resolution": True,
            "resolutions": list(spec.get("resolutions", KLING_RESOLUTION_OPTIONS)),
            "supports_start_image": bool(spec.get("supports_start_image", False)),
            "start_image_required": bool(spec.get("start_image_required", False)),
            "supports_reference_images": bool(spec.get("supports_reference_images", False)),
            "reference_images_required": bool(spec.get("reference_images_required", False)),
            "max_reference_images": int(spec.get("max_reference_images", 0) or 0),
            "direct_image_limit_mb": 10,
            "sort_order": int(spec.get("sort_order", 999)),
            "video_mode_kind": spec.get("video_mode_kind", "hybrid"),
            "native_model_name": str(spec.get("native_model_name") or spec["id"]),
            "native_video_endpoint": str(spec.get("native_video_endpoint") or ""),
            "kling_mode": str(spec.get("kling_mode") or "pro"),
            "native_reference_item_key": str(spec.get("native_reference_item_key") or "image"),
        }

    for spec in FAL_KLING_MODEL_SPECS:
        info[spec["id"]] = {
            "provider": "fal",
            "provider_label": "Fal",
            "family": "kling",
            "label": spec["label"],
            "input_modes": list(spec.get("input_modes", ["text"])),
            "durations": list(spec.get("durations", VIDEO_DURATION_OPTIONS)),
            "aspect_ratios": list(spec.get("aspect_ratios", VIDEO_ASPECT_RATIOS)),
            "supports_negative_prompt": True,
            "supports_safety_checker": False,
            "supports_resolution": True,
            "resolutions": list(spec.get("resolutions", KLING_RESOLUTION_OPTIONS)),
            "supports_start_image": bool(spec.get("supports_start_image", False)),
            "start_image_required": bool(spec.get("start_image_required", False)),
            "start_image_field": spec.get("start_image_field", "image_url"),
            "supports_reference_images": bool(spec.get("supports_reference_images", False)),
            "reference_images_required": bool(spec.get("reference_images_required", False)),
            "reference_images_field": spec.get("reference_images_field", "image_urls"),
            "max_reference_images": int(spec.get("max_reference_images", 0) or 0),
            "supports_source_video": bool(spec.get("supports_source_video", False)),
            "source_video_required": bool(spec.get("source_video_required", False)),
            "source_video_field": spec.get("source_video_field", "video_url"),
            "sort_order": int(spec.get("sort_order", 999)),
            "video_mode_kind": spec.get("video_mode_kind", "text_to_video"),
        }

    for spec in FAL_SEEDANCE_MODEL_SPECS:
        info[spec["id"]] = {
            "provider": "fal",
            "provider_label": "Fal",
            "family": "seedance",
            "label": spec["label"],
            "input_modes": list(spec.get("input_modes", ["text"])),
            "durations": list(spec.get("durations", VIDEO_DURATION_OPTIONS)),
            "aspect_ratios": list(spec.get("aspect_ratios", VIDEO_ASPECT_RATIOS)),
            "supports_negative_prompt": True,
            "supports_safety_checker": True,
            "supports_resolution": True,
            "resolutions": list(spec.get("resolutions", SEEDANCE_RESOLUTION_OPTIONS)),
            "supports_start_image": bool(spec.get("supports_start_image", False)),
            "start_image_required": bool(spec.get("start_image_required", False)),
            "start_image_field": spec.get("start_image_field", "image_url"),
            "supports_reference_images": bool(spec.get("supports_reference_images", False)),
            "reference_images_required": bool(spec.get("reference_images_required", False)),
            "reference_images_field": spec.get("reference_images_field", "reference_image_urls"),
            "max_reference_images": int(spec.get("max_reference_images", 0) or 0),
            "sort_order": int(spec.get("sort_order", 999)),
            "video_mode_kind": spec.get("video_mode_kind", "text_to_video"),
        }

    info[FAL_WAN_T2V_ID] = {
        "provider": "fal",
        "provider_label": "Fal",
        "family": "wan-video",
        "label": "Wan Video 2.2",
        "input_modes": ["text"],
        "durations": VIDEO_DURATION_OPTIONS,
        "aspect_ratios": VIDEO_ASPECT_RATIOS,
        "supports_negative_prompt": True,
        "supports_safety_checker": True,
        "supports_output_safety_checker": True,
        "supports_resolution": True,
        "resolutions": WAN_RESOLUTION_OPTIONS,
        "supports_start_image": False,
        "start_image_required": False,
        "supports_reference_images": False,
        "reference_images_required": False,
        "max_reference_images": 0,
        "sort_order": 210,
        "video_mode_kind": "text_to_video",
    }
    info[FAL_WAN_I2V_ID] = {
        "provider": "fal",
        "provider_label": "Fal",
        "family": "wan-video",
        "label": "Wan Video 2.2",
        "input_modes": ["image"],
        "durations": VIDEO_DURATION_OPTIONS,
        "aspect_ratios": VIDEO_ASPECT_RATIOS,
        "supports_negative_prompt": True,
        "supports_safety_checker": True,
        "supports_output_safety_checker": True,
        "supports_resolution": True,
        "resolutions": WAN_RESOLUTION_OPTIONS,
        "supports_start_image": True,
        "start_image_required": True,
        "start_image_field": "image_url",
        "supports_reference_images": False,
        "reference_images_required": False,
        "max_reference_images": 0,
        "sort_order": 211,
        "video_mode_kind": "image_to_video",
    }
    info[FAL_SEEDVR_VIDEO_ID] = {
        "provider": "fal",
        "provider_label": "Fal",
        "family": "seedvr-video",
        "label": "SeedVR2 Video",
        "input_modes": ["video"],
        "durations": [],
        "aspect_ratios": [],
        "supports_prompt": False,
        "supports_negative_prompt": False,
        "supports_safety_checker": False,
        "supports_resolution": False,
        "supports_duration": False,
        "supports_aspect_ratio": False,
        "supports_start_image": False,
        "start_image_required": False,
        "supports_source_video": True,
        "source_video_required": True,
        "supports_reference_images": False,
        "reference_images_required": False,
        "max_reference_images": 0,
        "supports_seedvr_video_settings": True,
        "video_target_resolutions": ["720p", "1080p", "1440p", "2160p"],
        "video_output_formats": ["X264 (.mp4)", "VP9 (.webm)", "PRORES4444 (.mov)", "GIF (.gif)"],
        "video_output_qualities": ["low", "medium", "high", "maximum"],
        "video_output_write_modes": ["fast", "balanced", "small"],
        "sort_order": 310,
        "video_mode_kind": "video_upscale",
    }
    return info


VIDEO_MODELS_INFO = _build_video_models_info()

VIDEO_MODEL_FAMILIES = {
    "kling": {
        "label": "Kling",
        "default_provider": "kling",
        "provider_order": ["kling", "fal"],
        "providers": {
            "kling": KLING_DIRECT_TEXT_DEFAULT_ID,
            "fal": FAL_KLING_V30_PRO_T2V_ID,
        },
    },
    "seedance": {
        "label": "Seedance",
        "default_provider": "fal",
        "provider_order": ["fal"],
        "providers": {
            "fal": FAL_SEEDANCE_V15_PRO_T2V_ID,
        },
    },
    "wan-video": {
        "label": "Wan Video",
        "default_provider": "fal",
        "provider_order": ["fal"],
        "providers": {
            "fal": FAL_WAN_T2V_ID,
        },
    },
    "seedvr-video": {
        "label": "SeedVR2",
        "default_provider": "fal",
        "provider_order": ["fal"],
        "providers": {
            "fal": FAL_SEEDVR_VIDEO_ID,
        },
    },
}


def get_video_model_candidates(family_key: str = "", provider_key: str = "", input_mode: str = "") -> list[tuple[str, dict]]:
    mode_key = str(input_mode or "").strip().lower()
    matches = []
    for model_id, model_info in VIDEO_MODELS_INFO.items():
        if family_key and model_info.get("family") != family_key:
            continue
        if provider_key and model_info.get("provider") != provider_key:
            continue
        supported_modes = [str(mode).strip().lower() for mode in model_info.get("input_modes", [])]
        if mode_key and supported_modes and mode_key not in supported_modes:
            continue
        matches.append((model_id, model_info))
    matches.sort(key=lambda item: (int(item[1].get("sort_order", 999)), str(item[1].get("label") or item[0]).lower()))
    return matches


VIDEO_PRICING = {
    model_id: {str(duration): 0.0 for duration in VIDEO_DURATION_ALL_OPTIONS}
    for model_id in VIDEO_MODELS_INFO
}


def build_asset_page_context(kind: str) -> dict:
    cfg = ASSET_GALLERY_PAGE_CONFIG.get(kind, ASSET_GALLERY_PAGE_CONFIG["history"])
    return {
        "asset_kind": kind,
        "page_title": "Assets",
        "page_subtitle": cfg.get("subtitle", "Browse history, references, loved images, and videos in one place."),
        "asset_gallery_config": ASSET_GALLERY_PAGE_CONFIG,
        "initial_asset_items": collect_asset_records(kind),
        "user": session["user"],
    }


@app.route("/images")
@login_required
def images_gallery():
    kind = str(request.args.get("kind") or "history").strip().lower()
    if kind not in ASSET_GALLERY_PAGE_CONFIG:
        kind = "history"
    return render_template("asset_gallery.html", **build_asset_page_context(kind))


@app.route("/loved")
@login_required
def loved_gallery():
    return redirect(url_for("images_gallery", kind="loved"))


@app.route("/references")
@login_required
def references_gallery():
    return redirect(url_for("images_gallery", kind="references"))


@app.route("/history")
@login_required
def history_gallery():
    return redirect(url_for("images_gallery", kind="history"))


def collect_video_asset_records(max_load: int | None = None) -> list[dict]:
    limit = max_load if max_load is not None else None
    result = []
    if not os.path.isdir(VIDEOS_DIR):
        return result

    for meta_file in list_meta_files_recursive(VIDEOS_DIR):
        if limit is not None and len(result) >= limit:
            break
        try:
            with open(meta_file, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            filename = str(meta.get("filename") or "").strip()
            if not filename:
                continue
            relpath = str(meta.get("assetRelpath") or os.path.relpath(os.path.join(os.path.dirname(meta_file), filename), VIDEOS_DIR)).replace("\\", "/")
            video_path = os.path.join(VIDEOS_DIR, relpath.replace("/", os.sep))
            if not os.path.exists(video_path):
                continue
            generated_at = str(meta.get("generated_at") or "")
            date_key = derive_asset_date_key(relpath, generated_at)
            meta = dict(meta)
            meta["assetRelpath"] = relpath
            result.append({
                "id": f"videos:{relpath}".replace("/", ":"),
                "kind": "videos",
                "url": build_asset_public_url("videos", relpath),
                "download_url": build_asset_public_url("videos", relpath),
                "date": date_key,
                "filename": filename,
                "relpath": relpath,
                "generated_at": generated_at,
                "sortTimestamp": generated_at or f"{date_key}T00:00:00",
                "prompt_preview": str(meta.get("prompt") or meta.get("text") or filename)[:120],
                "text": str(meta.get("text") or meta.get("prompt") or ""),
                "mime_type": str(meta.get("mime_type") or "video/mp4"),
                "poster_url": str(meta.get("poster_url") or ""),
                "delete_url": f"/api/videos/{relpath}",
                "folder_open_payload": {
                    "kind": "videos",
                    "date": date_key,
                    "filename": filename,
                    "relpath": relpath,
                },
                "params": meta,
            })
        except Exception:
            continue
    return result


@app.route("/loved/<path:asset_relpath>")
@login_required
def serve_loved(asset_relpath):
    safe_relpath = resolve_asset_relpath(relpath=asset_relpath)
    local_path = safe_asset_path(LOVED_DIR, safe_relpath)
    return send_from_directory(os.path.dirname(local_path), os.path.basename(local_path))


@app.route("/reference-archive/<date_str>/<filename>")
@login_required
def serve_reference_archive(date_str, filename):
    day_path = os.path.join(REFERENCE_ARCHIVE_DIR, date_str)
    return send_from_directory(day_path, filename)


@app.route("/reference-mask/<date_str>/<filename>")
@login_required
def serve_reference_mask(date_str, filename):
    day_path = os.path.join(REFERENCE_MASKS_DIR, date_str)
    return send_from_directory(day_path, filename)


@app.route("/reference-render/<date_str>/<filename>")
@login_required
def serve_reference_render(date_str, filename):
    day_path = os.path.join(REFERENCE_RENDERS_DIR, date_str)
    return send_from_directory(day_path, filename)


@app.route("/generations/<path:asset_relpath>")
@login_required
def serve_generation(asset_relpath):
    safe_relpath = resolve_asset_relpath(relpath=asset_relpath)
    local_path = safe_asset_path(GENERATIONS_DIR, safe_relpath)
    return send_from_directory(os.path.dirname(local_path), os.path.basename(local_path))


@app.route("/videos/<path:asset_relpath>")
@login_required
def serve_video(asset_relpath):
    safe_relpath = resolve_asset_relpath(relpath=asset_relpath)
    local_path = safe_asset_path(VIDEOS_DIR, safe_relpath)
    return send_from_directory(os.path.dirname(local_path), os.path.basename(local_path))


def open_file_in_folder(img_path: str):
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", img_path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", img_path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(img_path)])


def resolve_asset_image_path(kind: str, date_str: str = "", filename: str = "", relpath: str = "") -> tuple[str, str, str]:
    kind = str(kind or "").strip()
    mapping = {
        "history": GENERATIONS_DIR,
        "generations": GENERATIONS_DIR,
        "videos": VIDEOS_DIR,
        "video": VIDEOS_DIR,
        "loved": LOVED_DIR,
        "references": REFERENCE_ARCHIVE_DIR,
        "reference_archive": REFERENCE_ARCHIVE_DIR,
    }
    root_dir = mapping.get(kind)
    if not root_dir:
        raise ValueError("Invalid asset kind.")
    safe_relpath = resolve_asset_relpath(relpath=relpath, date_str=date_str, filename=filename)
    img_path = safe_asset_path(root_dir, safe_relpath)
    return os.path.realpath(root_dir), img_path, safe_relpath


@app.route("/api/generations/open-folder", methods=["POST"])
@login_required
def api_open_generation_folder():
    body = request.get_json(silent=True) or {}
    date_str = str(body.get("date") or "").strip()
    filename = os.path.basename(str(body.get("filename") or "").strip())
    relpath = str(body.get("relpath") or "").strip()

    try:
        resolve_asset_image_path("history", date_str, filename, relpath)
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        _, img_path, _ = resolve_asset_image_path("history", date_str, filename, relpath)
        open_file_in_folder(img_path)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/assets/open-folder", methods=["POST"])
@login_required
def api_open_asset_folder():
    body = request.get_json(silent=True) or {}
    kind = str(body.get("kind") or "").strip()
    date_str = str(body.get("date") or "").strip()
    filename = os.path.basename(str(body.get("filename") or "").strip())
    relpath = str(body.get("relpath") or "").strip()

    try:
        _, img_path, _ = resolve_asset_image_path(kind, date_str, filename, relpath)
        open_file_in_folder(img_path)
        return jsonify({"ok": True})
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# API Ã¢â‚¬â€ Delete a loved image (image + JSON sidecar, never touches generations/)
# ---------------------------------------------------------------------------
@app.route("/api/loved/<path:asset_relpath>", methods=["DELETE"])
@login_required
def api_delete_loved(asset_relpath):
    try:
        _, img_path, safe_relpath = resolve_asset_image_path("loved", relpath=asset_relpath)
        filename = os.path.basename(img_path)
        if os.path.splitext(filename)[1].lower() not in (".jpeg", ".jpg", ".png", ".webp"):
            return jsonify({"ok": False, "error": "Invalid file type"}), 400
        if not os.path.exists(img_path):
            return jsonify({"ok": False, "error": "File not found"}), 404
        os.remove(img_path)
        json_path = os.path.splitext(img_path)[0] + ".json"
        if os.path.exists(json_path):
            os.remove(json_path)
        current_dir = os.path.dirname(img_path)
        safe_root = os.path.realpath(LOVED_DIR)
        while current_dir.startswith(safe_root + os.sep) and current_dir != safe_root:
            if os.path.isdir(current_dir) and not os.listdir(current_dir):
                os.rmdir(current_dir)
                current_dir = os.path.dirname(current_dir)
                continue
            break
        return jsonify({"ok": True, "relpath": safe_relpath})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "File not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reference-archive/<date_str>/<filename>", methods=["DELETE"])
@login_required
def api_delete_reference_archive(date_str, filename):
    safe_root = os.path.realpath(REFERENCE_ARCHIVE_DIR)
    filename = os.path.basename(filename)
    img_path = os.path.realpath(os.path.join(REFERENCE_ARCHIVE_DIR, date_str, filename))

    if not img_path.startswith(safe_root + os.sep):
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    if os.path.splitext(filename)[1].lower() not in (".jpeg", ".jpg", ".png", ".webp"):
        return jsonify({"ok": False, "error": "Invalid file type"}), 400
    if not os.path.exists(img_path):
        return jsonify({"ok": False, "error": "File not found"}), 404

    try:
        os.remove(img_path)
        delete_reference_mask_assets(date_str, filename)
        remove_reference_archive_index_entries(date_str, filename)
        archive_day_dir = os.path.dirname(img_path)
        if os.path.isdir(archive_day_dir) and not os.listdir(archive_day_dir):
            os.rmdir(archive_day_dir)

        if os.path.isdir(GENERATIONS_DIR):
            for gen_date in os.listdir(GENERATIONS_DIR):
                day_path = os.path.join(GENERATIONS_DIR, gen_date)
                if not os.path.isdir(day_path):
                    continue
                meta_files = glob.glob(os.path.join(day_path, "*.json"))
                for meta_file in meta_files:
                    try:
                        with open(meta_file, encoding="utf-8") as fh:
                            meta = json.load(fh)
                    except Exception:
                        continue
                    refs = meta.get("refArchive") or []
                    if not isinstance(refs, list) or not refs:
                        continue
                    new_refs = []
                    changed = False
                    for ref in refs:
                        if not isinstance(ref, dict):
                            continue
                        ref_date = str(ref.get("date", "") or "").strip()
                        ref_name = os.path.basename(str(ref.get("filename", "") or "").strip())
                        if ref_date == date_str and ref_name == filename:
                            changed = True
                            continue
                        new_refs.append(ref)
                    if changed:
                        meta["refArchive"] = new_refs
                        meta["ref_count"] = len(new_refs)
                        with open(meta_file, "w", encoding="utf-8") as fh:
                            json.dump(meta, fh, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reference-mask/<date_str>/<filename>", methods=["GET", "POST"])
@login_required
def api_reference_mask(date_str, filename):
    safe_date = str(date_str or "").strip()
    safe_filename = os.path.basename(str(filename or "").strip())
    paths = get_reference_mask_file_paths(safe_date, safe_filename)
    safe_root = os.path.realpath(REFERENCE_ARCHIVE_DIR)
    original_path = os.path.realpath(paths["original_path"])

    if not original_path.startswith(safe_root + os.sep):
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    if not os.path.exists(original_path):
        return jsonify({"ok": False, "error": "Reference image not found"}), 404

    if request.method == "GET":
        return jsonify({
            "ok": True,
            "bundle": build_reference_mask_bundle(safe_date, safe_filename),
            "meta": load_reference_mask_metadata(safe_date, safe_filename),
        })

    body = request.get_json(silent=True) or {}
    mask_png_data = str(body.get("mask_data", "") or "").strip()
    clear_mask = bool(body.get("clear")) or not mask_png_data
    try:
        if clear_mask:
            delete_reference_mask_assets(safe_date, safe_filename)
            metadata = {}
        else:
            metadata = save_reference_mask_assets(safe_date, safe_filename, mask_png_data)
        return jsonify({
            "ok": True,
            "bundle": build_reference_mask_bundle(safe_date, safe_filename),
            "meta": metadata,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API Ã¢â‚¬â€ Loved list (for reference image picker)
# ---------------------------------------------------------------------------
@app.route("/api/loved-list")
@login_required
def api_loved_list():
    """
    Returns list of loved images for the picker (no base64, only URL and meta).
    """
    result = []
    for item in collect_asset_records("loved"):
        params = item.get("params", {})
        result.append({
            "url": item.get("url", ""),
            "date": item.get("date", ""),
            "filename": item.get("filename", ""),
            "prompt": (params.get("prompt", "") or "")[:60],
            "model_label": params.get("model_label", ""),
            "imageSize": params.get("imageSize", ""),
            "aspectRatio": params.get("aspectRatio", ""),
        })
    return jsonify(result)


def build_common_asset_params(meta: dict | None, *, default_model: str = "", default_provider: str = "") -> dict:
    meta = meta or {}
    model_id = str(meta.get("model", default_model) or default_model or "")
    model_info = MODELS_INFO.get(model_id, {})
    provider = str(meta.get("provider", default_provider or model_info.get("provider", "")) or default_provider or model_info.get("provider", ""))
    provider_label = str(meta.get("provider_label", model_info.get("provider_label", PROVIDER_LABELS.get(provider, provider.title() if provider else ""))) or "")
    asset_meta = normalize_asset_metadata(meta, require_filename=False)
    asset_relpath = str(meta.get("assetRelpath", "") or "").strip()
    upscale_source_filename = str(meta.get("upscaleSourceFilename", "") or "").strip()
    upscale_source_date = str(meta.get("upscaleSourceDate", "") or "").strip()
    upscale_source_relpath = str(meta.get("upscaleSourceRelpath", "") or "").strip()
    if not upscale_source_relpath and upscale_source_filename:
        preferred_dir = os.path.dirname(asset_relpath).replace("\\", "/").strip("/")
        upscale_source_relpath = find_generation_relpath_by_filename(
            upscale_source_filename,
            preferred_dir=preferred_dir,
            preferred_date=upscale_source_date,
        )
    return {
        "model": model_id,
        "modelFamily": meta.get("modelFamily", model_info.get("family", model_id)),
        "model_label": meta.get("model_label", model_info.get("label", "")),
        "provider": provider,
        "provider_label": provider_label,
        "imageSize": meta.get("imageSize", ""),
        "deliveredImageSize": meta.get("deliveredImageSize", ""),
        "deliveredWidth": meta.get("deliveredWidth", 0),
        "deliveredHeight": meta.get("deliveredHeight", 0),
        "aspectRatio": meta.get("aspectRatio", ""),
        "prompt": meta.get("prompt", ""),
        "temperature": meta.get("temperature", 1.0),
        "topP": meta.get("topP", 0.95),
        "thinkingLevel": meta.get("thinkingLevel", "Minimal"),
        "useSearch": meta.get("useSearch", False),
        "ref_count": meta.get("ref_count", 0),
        "refArchive": enrich_reference_archive_entries(meta.get("refArchive", [])),
        "seedMode": meta.get("seedMode", "random"),
        "seedValue": meta.get("seedValue", 1),
        "falSafetyChecker": meta.get("falSafetyChecker", True),
        "falSafetyTolerance": meta.get("falSafetyTolerance", 4),
        "geminiSafetyPreset": meta.get("geminiSafetyPreset", "default"),
        "byteplusSafetyMode": meta.get("byteplusSafetyMode", "platform_default"),
        "upscaled": meta.get("upscaled", False),
        "upscalerType": meta.get("upscalerType", ""),
        "upscalerLabel": meta.get("upscalerLabel", ""),
        "upscaleModel": meta.get("upscaleModel", meta.get("upscalerType", "")),
        "upscalePreset": meta.get("upscalePreset", ""),
        "upscaleMode": meta.get("upscaleMode", ""),
        "upscaleFactor": meta.get("upscaleFactor"),
        "upscaleTargetResolution": meta.get("upscaleTargetResolution", ""),
        "upscaleTargetWidth": meta.get("upscaleTargetWidth", 0),
        "upscaleTargetHeight": meta.get("upscaleTargetHeight", 0),
        "upscaleTargetAnchor": meta.get("upscaleTargetAnchor", ""),
        "upscaleDisplaySize": meta.get("upscaleDisplaySize", ""),
        "upscaleSourceDate": meta.get("upscaleSourceDate", ""),
        "upscaleSourceFilename": upscale_source_filename,
        "upscaleSourceRelpath": upscale_source_relpath,
        "upscaleSourceUrl": build_asset_public_url("generations", upscale_source_relpath) if upscale_source_relpath else "",
        "upscaleOutputWidth": meta.get("upscaleOutputWidth", 0),
        "upscaleOutputHeight": meta.get("upscaleOutputHeight", 0),
        "mime_type": meta.get("mime_type", "image/png"),
        "assetClient": asset_meta["assetClient"],
        "assetProject": asset_meta["assetProject"],
        "assetShot": asset_meta["assetShot"],
        "assetFilename": asset_meta["assetFilename"],
        "assetRelpath": asset_relpath,
    }


def find_existing_image_for_meta_base(base_path: str) -> tuple[str | None, str | None]:
    for ext in (".jpeg", ".jpg", ".png", ".webp"):
        candidate = base_path + ext
        if os.path.exists(candidate):
            return candidate, os.path.basename(candidate)
    return None, None


def iso_sort_key(value: str, fallback: str) -> str:
    raw = str(value or "").strip()
    return raw or fallback


def collect_generation_records(max_load: int | None = None) -> list[dict]:
    result = []
    if not os.path.isdir(GENERATIONS_DIR):
        return result

    for mf in list_meta_files_recursive(GENERATIONS_DIR):
        if max_load is not None and len(result) >= max_load:
            break
        try:
            with open(mf, encoding="utf-8") as f:
                meta = json.load(f)
            img_path, filename = find_existing_binary_for_meta(mf, (".jpeg", ".jpg", ".png", ".webp"))
            if not img_path or not filename:
                continue
            relpath = os.path.relpath(img_path, GENERATIONS_DIR).replace("\\", "/")
            generated_at = str(meta.get("generated_at", "") or "")
            date_key = derive_asset_date_key(relpath, generated_at)
            params = build_common_asset_params(meta)
            if not params.get("deliveredImageSize"):
                delivered_width, delivered_height = measure_image_file_dimensions(img_path)
                if delivered_width and delivered_height:
                    params["deliveredWidth"] = delivered_width
                    params["deliveredHeight"] = delivered_height
                    params["deliveredImageSize"] = approximate_image_size_label(delivered_width, delivered_height)
            params["assetRelpath"] = relpath
            params["assetUrl"] = build_asset_public_url("generations", relpath)
            params["gen_date"] = date_key
            params["gen_filename"] = filename
            params["gen_relpath"] = relpath
            result.append({
                "id": f"history:{relpath}".replace("/", ":"),
                "kind": "history",
                "url": build_asset_public_url("generations", relpath),
                "download_url": build_asset_public_url("generations", relpath),
                "date": date_key,
                "filename": filename,
                "relpath": relpath,
                "generated_at": generated_at,
                "sortTimestamp": iso_sort_key(generated_at, f"{date_key}T00:00:00"),
                "prompt_preview": (params.get("prompt", "") or "")[:120],
                "text": meta.get("text", ""),
                "params": params,
                "delete_url": f"/api/generations/{relpath}",
                "folder_open_payload": {"kind": "history", "date": date_key, "filename": filename, "relpath": relpath},
            })
        except Exception:
            pass
    return result


def collect_loved_records() -> list[dict]:
    result = []
    if not os.path.isdir(LOVED_DIR):
        return result

    for mf in list_meta_files_recursive(LOVED_DIR):
        try:
            with open(mf, encoding="utf-8") as f:
                meta = json.load(f)
            img_path, filename = find_existing_binary_for_meta(mf, (".jpeg", ".jpg", ".png", ".webp"))
            if not img_path or not filename:
                continue
            relpath = os.path.relpath(img_path, LOVED_DIR).replace("\\", "/")
            published_at = str(meta.get("published_at", meta.get("generated_at", "")) or "")
            date_key = derive_asset_date_key(relpath, published_at)
            params = build_common_asset_params(meta)
            if not params.get("deliveredImageSize"):
                delivered_width, delivered_height = measure_image_file_dimensions(img_path)
                if delivered_width and delivered_height:
                    params["deliveredWidth"] = delivered_width
                    params["deliveredHeight"] = delivered_height
                    params["deliveredImageSize"] = approximate_image_size_label(delivered_width, delivered_height)
            params["assetRelpath"] = relpath
            params["assetUrl"] = build_asset_public_url("loved", relpath)
            result.append({
                "id": f"loved:{relpath}".replace("/", ":"),
                "kind": "loved",
                "url": build_asset_public_url("loved", relpath),
                "download_url": build_asset_public_url("loved", relpath),
                "date": date_key,
                "filename": filename,
                "relpath": relpath,
                "generated_at": published_at,
                "sortTimestamp": iso_sort_key(published_at, f"{date_key}T00:00:00"),
                "prompt_preview": (params.get("prompt", "") or "")[:120],
                "text": meta.get("text", ""),
                "params": params,
                "delete_url": f"/api/loved/{relpath}",
                "folder_open_payload": {"kind": "loved", "date": date_key, "filename": filename, "relpath": relpath},
            })
        except Exception:
            pass
    return result


def collect_reference_archive_records() -> list[dict]:
    result = []
    seen_refs = set()
    if not os.path.isdir(GENERATIONS_DIR):
        return result

    for mf in list_meta_files_recursive(GENERATIONS_DIR):
        try:
            with open(mf, encoding="utf-8") as f:
                meta = json.load(f)
            params = build_common_asset_params(meta)
            generated_at = str(meta.get("generated_at", "") or "")
            source_relpath = str(meta.get("assetRelpath") or "").strip()
            for ref_entry in meta.get("refArchive", []) or []:
                if not isinstance(ref_entry, dict):
                    continue
                ref_date = str(ref_entry.get("date", "") or "").strip()
                filename = os.path.basename(str(ref_entry.get("filename", "") or "").strip())
                if not ref_date or not filename:
                    continue
                ref_key = compute_reference_archive_file_hash(ref_date, filename) or f"{ref_date}/{filename}"
                if ref_key in seen_refs:
                    continue
                ref_path = os.path.join(REFERENCE_ARCHIVE_DIR, ref_date, filename)
                if not os.path.exists(ref_path):
                    continue
                seen_refs.add(ref_key)
                enriched_ref = enrich_reference_archive_entry(ref_entry)
                result.append({
                    "id": f"reference:{ref_date}:{filename}",
                    "kind": "references",
                    "url": str(enriched_ref.get("url") or f"/reference-archive/{ref_date}/{filename}"),
                    "download_url": str(enriched_ref.get("url") or f"/reference-archive/{ref_date}/{filename}"),
                    "date": ref_date,
                    "filename": filename,
                    "generated_at": generated_at,
                    "sortTimestamp": iso_sort_key(generated_at, f"{ref_date}T00:00:00"),
                    "prompt_preview": str(enriched_ref.get("name") or params.get("prompt", "") or filename)[:120],
                    "text": "",
                    "params": params,
                    "reference_name": str(enriched_ref.get("name", "") or ""),
                    "source_generation_date": derive_asset_date_key(source_relpath, generated_at),
                    "source_generation_filename": str(meta.get("filename", "") or ""),
                    "delete_url": f"/api/reference-archive/{ref_date}/{filename}",
                    "folder_open_payload": {"kind": "references", "date": ref_date, "filename": filename},
                    "original_url": str(enriched_ref.get("original_url") or ""),
                    "masked_url": str(enriched_ref.get("masked_url") or ""),
                    "mask_url": str(enriched_ref.get("mask_url") or ""),
                    "has_mask": bool(enriched_ref.get("has_mask")),
                    "mask_edit_payload": enriched_ref.get("mask_edit_payload") or {"kind": "references", "date": ref_date, "filename": filename},
                })
        except Exception:
            pass
    return result


def collect_asset_records(kind: str) -> list[dict]:
    if kind == "history":
        return collect_generation_records(max_load=None)
    if kind == "loved":
        return collect_loved_records()
    if kind == "references":
        return collect_reference_archive_records()
    if kind == "videos":
        return collect_video_asset_records(max_load=None)
    raise ValueError("Invalid asset kind")


def collect_asset_metadata_records() -> list[dict]:
    records: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    def append_record(client_value: str, project_value: str, shot_value: str, filename_value: str) -> None:
        client = normalize_asset_scope_text(client_value) or ASSET_UNCATEGORIZED_VALUE
        project = normalize_asset_scope_text(project_value) or ASSET_UNCATEGORIZED_VALUE
        shot = normalize_asset_scope_text(shot_value) or ASSET_UNCATEGORIZED_VALUE
        filename = sanitize_asset_filename_stem(filename_value, fallback="")
        if not filename:
            return
        key = (client, project, shot, filename)
        if key in seen:
            return
        seen.add(key)
        records.append({
            "assetClient": client,
            "assetProject": project,
            "assetShot": shot,
            "assetFilename": filename,
        })

    for root_dir in (GENERATIONS_DIR, VIDEOS_DIR):
        if not os.path.isdir(root_dir):
            continue
        for current_root, dirnames, _ in os.walk(root_dir):
            rel_dir = os.path.relpath(current_root, root_dir).replace("\\", "/")
            rel_parts = [part for part in rel_dir.split("/") if part and part != "."]
            if len(rel_parts) >= 4:
                append_record(rel_parts[0], rel_parts[1], rel_parts[2], os.path.splitext(rel_parts[3])[0])
            for file_name in os.listdir(current_root):
                file_path = os.path.join(current_root, file_name)
                if not os.path.isfile(file_path):
                    continue
                if file_name.lower().endswith(".json"):
                    continue
                if len(rel_parts) >= 3:
                    append_record(rel_parts[0], rel_parts[1], rel_parts[2], os.path.splitext(file_name)[0])

    for item in (
        collect_generation_records(max_load=None)
        + collect_video_asset_records(max_load=None)
        + collect_loved_records()
        + collect_reference_archive_records()
    ):
        params = item.get("params", {}) or {}
        append_record(
            params.get("assetClient", ""),
            params.get("assetProject", ""),
            params.get("assetShot", ""),
            params.get("assetFilename", ""),
        )
    return records


def collect_asset_metadata_options() -> dict:
    options = {
        "clients": [ASSET_UNCATEGORIZED_VALUE],
        "projects": [ASSET_UNCATEGORIZED_VALUE],
        "shots": [ASSET_UNCATEGORIZED_VALUE],
        "filenames": [],
    }
    seen = {
        "clients": {ASSET_UNCATEGORIZED_VALUE},
        "projects": {ASSET_UNCATEGORIZED_VALUE},
        "shots": {ASSET_UNCATEGORIZED_VALUE},
        "filenames": set(),
    }
    for record in collect_asset_metadata_records():
        client = normalize_asset_scope_text(record.get("assetClient", "")) or ASSET_UNCATEGORIZED_VALUE
        project = normalize_asset_scope_text(record.get("assetProject", "")) or ASSET_UNCATEGORIZED_VALUE
        shot = normalize_asset_scope_text(record.get("assetShot", "")) or ASSET_UNCATEGORIZED_VALUE
        filename = sanitize_asset_filename_stem(record.get("assetFilename", ""), fallback="")
        if client not in seen["clients"]:
            seen["clients"].add(client)
            options["clients"].append(client)
        if project not in seen["projects"]:
            seen["projects"].add(project)
            options["projects"].append(project)
        if shot not in seen["shots"]:
            seen["shots"].add(shot)
            options["shots"].append(shot)
        if filename and filename not in seen["filenames"]:
            seen["filenames"].add(filename)
            options["filenames"].append(filename)

    config = load_config()
    memory = ensure_asset_metadata_memory_shape(config.get("asset_metadata_memory"))
    for key in ("clients", "projects", "shots"):
        for value in memory.get(key, []):
            clean_value = normalize_asset_scope_text(value) or ASSET_UNCATEGORIZED_VALUE
            if clean_value not in seen[key]:
                seen[key].add(clean_value)
                options[key].append(clean_value)
    for value in memory.get("filenames", []):
        clean_value = sanitize_asset_filename_stem(value, fallback="")
        if clean_value and clean_value not in seen["filenames"]:
            seen["filenames"].add(clean_value)
            options["filenames"].append(clean_value)
    return options


@app.context_processor
def inject_asset_metadata_bootstrap():
    try:
        return {
            "asset_meta_bootstrap": {
                "options": collect_asset_metadata_options(),
                "records": collect_asset_metadata_records(),
            }
        }
    except Exception:
        return {
            "asset_meta_bootstrap": {
                "options": {
                    "clients": [ASSET_UNCATEGORIZED_VALUE],
                    "projects": [ASSET_UNCATEGORIZED_VALUE],
                    "shots": [ASSET_UNCATEGORIZED_VALUE],
                    "filenames": [],
                },
                "records": [],
            }
        }


@app.route("/api/asset-metadata-options")
@login_required
def api_asset_metadata_options():
    return jsonify({
        "ok": True,
        "options": collect_asset_metadata_options(),
        "records": collect_asset_metadata_records(),
    })


@app.route("/api/asset-metadata-memory", methods=["POST"])
@login_required
def api_asset_metadata_memory():
    body = request.get_json(silent=True) or {}
    asset_meta = normalize_asset_metadata(body, require_filename=False)
    config = load_config()
    memory = update_asset_metadata_memory(config, asset_meta)
    save_config(config)
    return jsonify({"ok": True, "options": collect_asset_metadata_options(), "memory": memory})


@app.route("/api/reference-archive-list")
@login_required
def api_reference_archive_list():
    result = []
    for item in collect_reference_archive_records():
        params = item.get("params", {})
        result.append({
            "url": item.get("url", ""),
            "original_url": item.get("original_url", ""),
            "masked_url": item.get("masked_url", ""),
            "mask_url": item.get("mask_url", ""),
            "has_mask": item.get("has_mask", False),
            "mask_edit_payload": item.get("mask_edit_payload", {}),
            "date": item.get("date", ""),
            "filename": item.get("filename", ""),
            "prompt": (item.get("reference_name") or params.get("prompt", "") or "")[:60],
            "model_label": params.get("model_label", ""),
            "imageSize": params.get("imageSize", ""),
            "aspectRatio": params.get("aspectRatio", ""),
        })
    return jsonify(result)


@app.route("/api/reference-archive-payload/<date_str>/<filename>")
@login_required
def api_reference_archive_payload(date_str, filename):
    safe_date = str(date_str or "").strip()
    safe_filename = os.path.basename(str(filename or "").strip())
    if not safe_date or not safe_filename:
        return jsonify({"ok": False, "error": "Invalid archive reference"}), 400

    paths = get_reference_mask_file_paths(safe_date, safe_filename)
    original_path = paths["original_path"]
    if not os.path.exists(original_path):
        recovered_path, recovered_name = find_reference_recovery_source(safe_filename)
        if recovered_path:
            try:
                payload = build_reference_payload_from_file(recovered_path, recovered_name or safe_filename)
                payload.update({
                    "date": safe_date,
                    "filename": safe_filename,
                })
                return jsonify(payload)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": False, "error": "Reference archive entry not found"}), 404

    bundle = build_reference_mask_bundle(safe_date, safe_filename)
    display_path = paths["render_path"] if bundle["has_mask"] and os.path.exists(paths["render_path"]) else original_path

    try:
        with open(original_path, "rb") as fh:
            original_b64 = base64.b64encode(fh.read()).decode("utf-8")
        with open(display_path, "rb") as fh:
            display_b64 = base64.b64encode(fh.read()).decode("utf-8")
        mask_b64 = ""
        if bundle["has_mask"] and os.path.exists(paths["mask_path"]):
            with open(paths["mask_path"], "rb") as fh:
                mask_b64 = base64.b64encode(fh.read()).decode("utf-8")
        return jsonify({
            "ok": True,
            "date": safe_date,
            "filename": safe_filename,
            "name": safe_filename,
            "mime_type": "image/png",
            "data": display_b64,
            "original_data": original_b64,
            "original_mime_type": "image/png",
            "mask_png_data": mask_b64,
            "original_url": bundle["original_url"],
            "masked_url": bundle["masked_url"],
            "mask_url": bundle["mask_url"],
            "has_mask": bundle["has_mask"],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/asset-gallery/<kind>")
@login_required
def api_asset_gallery(kind):
    if kind not in ASSET_GALLERY_PAGE_CONFIG:
        return jsonify({"ok": False, "error": "Invalid gallery kind"}), 404
    return jsonify({"ok": True, "items": collect_asset_records(kind)})


@app.route("/api/import-ref-image", methods=["POST"])
@login_required
def api_import_ref_image():
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Image URL is empty"})

    try:
        image_b64, mime_type, filename = fetch_remote_reference_image(url)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})

    return jsonify({
        "ok": True,
        "data": image_b64,
        "mime_type": mime_type,
        "name": filename,
    })

# ---------------------------------------------------------------------------
# Routes Ã¢â‚¬â€ Elements (asset library)
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
    # Filtri metadati (solo characters) Ã¢â‚¬â€ tutti exact-match con vocabolario canonico
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

    # Filtri metadati Ã¢â‚¬â€ exact match (vocabolario canonico, tutti underscored)
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

    # Deduplica per id Ã¢â‚¬â€ per ogni id teniamo il record con image_path valido
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
        "Your task: fill in EVERY field Ã¢â‚¬â€ never leave anything empty or use values outside the allowed lists.\n\n"
        f"{vocab_block}\n\n"
        "Additional field rules:\n"
        "- name: INVENT a realistic first+last name that fits the person's apparent ethnicity and vibe "
        "(e.g. Sofia Esposito, Kai Nakamura, Amara Diallo, Luca Ferretti, Yuki Tanaka, Zara Osei)\n"
        "- description: 2 precise sentences for AI image generation Ã¢â‚¬â€ describe face shape, skin quality, "
        "distinctive features (nose, lips, jawline, cheekbones), eye shape, expression, overall aesthetic vibe\n"
        "- tags: JSON array of 4Ã¢â‚¬â€œ6 lowercase, single-word or hyphenated tags useful for searching "
        "(e.g. [\"editorial\", \"beauty\", \"runway\", \"high-fashion\", \"dark-skin\", \"versatile\"])\n\n"
        "CRITICAL: You MUST use ONLY the exact string values listed above. "
        "Do NOT invent new values, do NOT use variations, plurals, or spaces instead of underscores.\n\n"
        "Return ONLY a valid JSON object Ã¢â‚¬â€ no markdown fences, no extra text, no comments:\n"
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


@app.route("/api/references/describe", methods=["POST"])
@login_required
def api_describe_reference_images():
    config = load_config()
    api_key = (config.get("api_key", "") or "").strip()
    if not api_key:
        return jsonify({"ok": False, "error": "Gemini API key not configured."}), 400

    body = request.get_json(silent=True) or {}
    ref_images = normalize_ref_image_payloads(body.get("refImages"), 32)
    if not ref_images:
        return jsonify({"ok": False, "error": "No reference images provided."}), 400

    describe_prompt = (
        "You are a high-end visual prompt writer for image generation.\n"
        "Analyze this reference image and write one detailed, production-ready descriptive prompt.\n"
        "Focus on visible subject matter, wardrobe, materials, textures, colors, styling, pose, composition, "
        "camera perspective, lighting, environment, mood, and any distinctive visual cues.\n"
        "Write a single dense paragraph in clean English.\n"
        "Do not use bullet points, markdown, labels, or filenames.\n"
        "Do not speculate about things that are not visible.\n"
        "Return only the prompt text."
    )

    descriptions: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0

    for idx, item in enumerate(ref_images, start=1):
        image_b64 = str(item.get("data", "") or "").strip()
        mime_type = str(item.get("mime_type", "image/jpeg") or "image/jpeg")
        filename = (
            str(item.get("name") or "").strip()
            or os.path.basename(str(item.get("archive_filename") or "").strip())
            or f"reference_{idx}.png"
        )
        if not image_b64:
            continue

        try:
            image_b64, mime_type, _, _, _, _, _ = normalize_image_b64(image_b64, mime_type)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Image pre-processing error for {filename}: {e}"}), 400

        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"inlineData": {"mimeType": mime_type, "data": image_b64}},
                    {"text": describe_prompt}
                ]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1024,
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
            return jsonify({"ok": False, "error": f"Description timeout for {filename} (60s)."}), 504
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        if resp.status_code != 200:
            try:
                err_body = resp.json()
                err_msg = err_body.get("error", {}).get("message", f"HTTP {resp.status_code}")
            except Exception:
                err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return jsonify({"ok": False, "error": f"{filename}: {err_msg}"}), 400

        result = resp.json()
        raw_text = ""
        for candidate in result.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part and str(part["text"]).strip():
                    raw_text = str(part["text"]).strip()
                    break
            if raw_text:
                break

        if not raw_text:
            return jsonify({"ok": False, "error": f"Gemini returned no description for {filename}."}), 400

        usage = result.get("usageMetadata", {})
        input_tokens = int(usage.get("promptTokenCount", 0) or 0)
        output_tokens = int(usage.get("candidatesTokenCount", 0) or 0)
        vp = VISION_MODELS_INFO.get(TALENT_ANALYSIS_MODEL, {})
        vision_cost = round(
            input_tokens * vp.get("input_per_1m", 0.075) / 1_000_000 +
            output_tokens * vp.get("output_per_1m", 0.30) / 1_000_000,
            8
        )
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_cost += vision_cost

        descriptions.append({
            "filename": filename,
            "description": raw_text,
        })

    cfg_v = load_config()
    sv = cfg_v.setdefault("stats", DEFAULT_CONFIG["stats"].copy())
    sv["vision_calls"] = sv.get("vision_calls", 0) + len(descriptions)
    sv["vision_cost_usd"] = round(sv.get("vision_cost_usd", 0.0) + total_cost, 8)
    vlog = sv.setdefault("vision_log", [])
    vlog.insert(0, {
        "ts": utc_now_iso(),
        "model": TALENT_ANALYSIS_MODEL,
        "input_tok": total_input_tokens,
        "output_tok": total_output_tokens,
        "cost": round(total_cost, 8),
        "refs_described": len(descriptions),
    })
    if len(vlog) > 200:
        sv["vision_log"] = vlog[:200]
    save_config(cfg_v)

    return jsonify({
        "ok": True,
        "descriptions": descriptions,
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cost_usd": round(total_cost, 8),
        }
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

    # Numero progressivo immagine Ã¢â‚¬â€ sempre .jpg dopo normalizzazione
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
        # Talent esistente Ã¢â€ â€™ aggiungi immagine
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
# API Ã¢â‚¬â€ Config / Key
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
    if "kling_api_token" in data:
        config["kling_api_token"] = data["kling_api_token"].strip()
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


@app.route("/api/verify-kling-token", methods=["POST"])
@login_required
def api_verify_kling_token():
    data = request.get_json() or {}
    token = str(data.get("kling_api_token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Kling API token is empty"})
    headers = build_kling_headers(token)
    try:
        response = requests.get(f"{KLING_BASE_URL}/v1/videos/text2video?pageNum=1&pageSize=1", headers=headers, timeout=45)
        if response.status_code == 200:
            return jsonify({"ok": True, "message": "Valid Kling token confirmed."})
        return jsonify({"ok": False, "error": extract_kling_error(response)})
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Connection timeout"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


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
            return jsonify({"ok": False, "error": "Access denied Ã¢â‚¬â€ check billing is active (403)"})
        else:
            return jsonify({"ok": False, "error": f"HTTP error {resp.status_code}"})
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Connection timeout"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# API Ã¢â‚¬â€ Generate (con supporto immagini di riferimento)
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
    ref_images = normalize_ref_image_payloads(ref_images, max_ref)

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
    if model_id in {"gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview"}:
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
    params_meta = merge_request_settings(merge_asset_metadata({
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
    }, body), body)
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
    raw_ref_images = result.pop("_input_ref_images", None)
    log_entry = {
        "ts": utc_now_iso(),
        "model": params.get("model", ""),
        "provider": params.get("provider", ""),
        "size": params.get("imageSize", ""),
        "aspect": params.get("aspectRatio", ""),
        "upscaler": params.get("upscalerType", ""),
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
    fallback_filename = sanitize_asset_filename_stem(params.get("prompt", ""), fallback=time_str)
    asset_meta = normalize_asset_metadata(params, require_filename=True, fallback_filename=fallback_filename)
    params.update(asset_meta)
    update_asset_metadata_memory(config, asset_meta)
    if raw_ref_images is not None:
        archived_refs = build_reference_archive_entries(raw_ref_images, date_str, time_str)
        params["refArchive"] = archived_refs
        params["ref_count"] = len(archived_refs)
    else:
        params["refArchive"] = params.get("refArchive", []) or []
        params["ref_count"] = int(params.get("ref_count", len(params["refArchive"])))
    result["params"] = params

    for g_idx, img in enumerate(result.get("images", [])):
        try:
            png_b64, png_mime = convert_image_b64_to_png(
                img.get("data", ""),
                img.get("mime_type", "image/png")
            )
            img["data"] = png_b64
            img["mime_type"] = png_mime
            delivered_width, delivered_height = measure_image_dimensions(png_b64, png_mime)
            delivered_size = approximate_image_size_label(delivered_width, delivered_height)
            img["deliveredWidth"] = delivered_width
            img["deliveredHeight"] = delivered_height
            img["deliveredImageSize"] = delivered_size
            abs_dir, relpath, basename = build_asset_storage_paths(
                GENERATIONS_DIR,
                asset_meta,
                "png",
                variant_suffix=str(g_idx + 1) if len(result.get("images", [])) > 1 else "",
            )
            img_path = os.path.join(GENERATIONS_DIR, relpath.replace("/", os.sep))
            meta_path = os.path.join(abs_dir, f"{basename}.json")
            img["gen_date"] = derive_asset_date_key(relpath, now.isoformat())
            img["gen_filename"] = os.path.basename(img_path)
            img["gen_relpath"] = relpath
            with open(img_path, "wb") as fh:
                fh.write(base64.b64decode(png_b64))
            gen_meta = dict(params)
            gen_meta.update({
                "generated_at": now.isoformat(),
                "mime_type": png_mime,
                "gen_date": img["gen_date"],
                "gen_filename": img["gen_filename"],
                "gen_relpath": img["gen_relpath"],
                "deliveredWidth": delivered_width,
                "deliveredHeight": delivered_height,
                "deliveredImageSize": delivered_size,
                "filename": os.path.basename(img_path),
                "assetRelpath": relpath,
                "text": result.get("text", "") if g_idx == 0 else "",
            })
            if g_idx == 0:
                params["deliveredWidth"] = delivered_width
                params["deliveredHeight"] = delivered_height
                params["deliveredImageSize"] = delivered_size
                result["params"] = params
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(gen_meta, fh, indent=2, ensure_ascii=False)
        except Exception:
            pass
    save_config(config)
    return result


def persist_video_result(result: dict):
    params = result.get("params", {}) or {}
    raw_source_image = result.pop("_input_source_image", None)
    raw_source_video = result.pop("_input_source_video", None)
    raw_reference_images = result.pop("_input_reference_images", None)
    config = load_config()
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S%f")[:12]
    fallback_filename = sanitize_asset_filename_stem(
        params.get("prompt", "") or params.get("modelLabel", "") or "video",
        fallback=time_str,
    )
    asset_meta = normalize_asset_metadata(params, require_filename=True, fallback_filename=fallback_filename)
    params.update(asset_meta)
    update_asset_metadata_memory(config, asset_meta)

    if isinstance(raw_source_image, dict) and str(raw_source_image.get("data") or "").strip():
        archived_source = build_reference_archive_entries([raw_source_image], date_str, f"{time_str}_video_src")
        params["videoSourceArchive"] = archived_source[0] if archived_source else {}
    else:
        params["videoSourceArchive"] = params.get("videoSourceArchive", {}) or {}

    if isinstance(raw_reference_images, list):
        archived_refs = build_reference_archive_entries(raw_reference_images, date_str, f"{time_str}_video_ref")
        params["videoRefArchive"] = archived_refs
        params["videoRefCount"] = len(archived_refs)
    else:
        params["videoRefArchive"] = params.get("videoRefArchive", []) or []
        params["videoRefCount"] = int(params.get("videoRefCount", len(params["videoRefArchive"])))

    source_video_archive = params.get("videoSourceVideoArchive", {}) or {}
    if isinstance(raw_source_video, dict):
        raw_video_url = str(raw_source_video.get("url") or "").strip()
        raw_video_name = os.path.basename(str(raw_source_video.get("name") or "")) or "video-source.mp4"
        raw_video_mime = str(raw_source_video.get("mime_type") or "video/mp4").strip() or "video/mp4"
        local_source_path = resolve_local_video_url_to_path(raw_video_url)
        if local_source_path:
            source_video_archive = {
                "date": os.path.basename(os.path.dirname(local_source_path)),
                "filename": os.path.basename(local_source_path),
                "name": raw_video_name,
                "mime_type": raw_video_mime,
                "url": raw_video_url or f"/videos/{os.path.basename(os.path.dirname(local_source_path))}/{os.path.basename(local_source_path)}",
            }
        elif str(raw_source_video.get("data") or "").strip():
            ext = get_video_extension_for_payload(raw_video_mime, raw_video_name)
            source_meta = dict(asset_meta)
            source_meta["assetFilename"] = sanitize_asset_filename_stem(
                f"{asset_meta.get('assetFilename', fallback_filename)}_source",
                fallback=f"{time_str}_source",
            )
            try:
                archive_dir, archive_relpath, _archive_basename = build_asset_storage_paths(
                    VIDEOS_DIR,
                    source_meta,
                    ext,
                    variant_suffix="source",
                )
                archive_path = os.path.join(VIDEOS_DIR, archive_relpath.replace("/", os.sep))
                with open(archive_path, "wb") as fh:
                    fh.write(base64.b64decode(str(raw_source_video.get("data") or ""), validate=False))
                source_video_archive = {
                    "date": derive_asset_date_key(archive_relpath, now.isoformat()),
                    "filename": os.path.basename(archive_path),
                    "name": raw_video_name,
                    "mime_type": raw_video_mime,
                    "url": f"/videos/{archive_relpath}",
                    "relpath": archive_relpath,
                }
            except Exception:
                source_video_archive = {}
        elif raw_video_url:
            source_video_archive = {
                "date": "",
                "filename": raw_video_name,
                "name": raw_video_name,
                "mime_type": raw_video_mime,
                "url": raw_video_url,
            }
    params["videoSourceVideoArchive"] = source_video_archive

    result["params"] = params

    for idx, video in enumerate(result.get("videos", []) or []):
        video_url = str(video.get("url") or "").strip()
        if not video_url:
            continue
        try:
            raw_bytes, detected_mime = download_remote_binary(video_url, timeout=300)
            ext, mime_type = normalize_video_extension(video.get("mime_type") or detected_mime, video_url)
            abs_dir, relpath, basename = build_asset_storage_paths(
                VIDEOS_DIR,
                asset_meta,
                ext,
                variant_suffix=str(idx + 1) if len(result.get("videos", []) or []) > 1 else "",
            )
            video_path = os.path.join(VIDEOS_DIR, relpath.replace("/", os.sep))
            video_filename = os.path.basename(video_path)
            with open(video_path, "wb") as fh:
                fh.write(raw_bytes)

            poster_url = str(video.get("poster_url") or "").strip()
            poster_filename = ""
            if poster_url:
                try:
                    poster_raw, poster_mime = download_remote_binary(poster_url, timeout=120)
                    poster_b64 = base64.b64encode(poster_raw).decode("utf-8")
                    poster_png_b64, poster_png_mime = convert_image_b64_to_png(poster_b64, poster_mime or "image/png")
                    poster_filename = f"{basename}_poster.png"
                    poster_path = os.path.join(abs_dir, poster_filename)
                    with open(poster_path, "wb") as pfh:
                        pfh.write(base64.b64decode(poster_png_b64))
                    poster_relpath = os.path.join(os.path.dirname(relpath), poster_filename).replace("\\", "/")
                    video["poster_url"] = f"/videos/{poster_relpath}"
                    video["poster_mime_type"] = poster_png_mime
                except Exception:
                    poster_filename = ""

            video["gen_date"] = derive_asset_date_key(relpath, now.isoformat())
            video["gen_filename"] = video_filename
            video["gen_relpath"] = relpath
            video["url"] = f"/videos/{relpath}"
            video["mime_type"] = mime_type

            meta_path = os.path.join(abs_dir, f"{basename}.json")
            video_meta = dict(params)
            video_meta.update({
                "generated_at": now.isoformat(),
                "mime_type": mime_type,
                "filename": video_filename,
                "poster_filename": poster_filename,
                "poster_url": video.get("poster_url", ""),
                "assetRelpath": relpath,
                "text": result.get("text", "") if idx == 0 else "",
            })
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(video_meta, fh, indent=2, ensure_ascii=False)
        except Exception:
            continue
    save_config(config)
    return result


def build_kling_headers(api_token: str) -> dict:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def poll_kling_task(api_token: str, endpoint: str, task_id: str, *, timeout_seconds: int = 900) -> dict:
    headers = build_kling_headers(api_token)
    max_attempts = max(10, int(timeout_seconds / 5))
    for _ in range(max_attempts):
        response = requests.get(f"{KLING_BASE_URL}{endpoint}/{task_id}", headers=headers, timeout=45)
        if response.status_code != 200:
            raise RuntimeError(extract_kling_error(response))
        payload = response.json()
        task_status = str(payload.get("data", {}).get("task_status") or payload.get("task_status") or "").strip().lower()
        if task_status in {"succeed", "success"}:
            return payload
        if task_status in {"failed", "error"}:
            raise RuntimeError(
                str(
                    payload.get("data", {}).get("task_status_msg")
                    or payload.get("message")
                    or payload.get("msg")
                    or "Kling video generation failed."
                )
            )
        threading.Event().wait(5)
    raise TimeoutError("Timeout: Kling video generation took too long.")


def build_kling_video_from_payload(result_payload: dict) -> dict:
    data = result_payload.get("data") if isinstance(result_payload, dict) else {}
    videos = []
    if isinstance(data, dict):
        task_result = data.get("task_result")
        if isinstance(task_result, dict) and isinstance(task_result.get("videos"), list):
            videos = [item for item in task_result.get("videos") if isinstance(item, dict)]
        elif isinstance(data.get("videos"), list):
            videos = [item for item in data.get("videos") if isinstance(item, dict)]
    if not videos:
        raise RuntimeError("Kling returned no video for this request.")
    first = videos[0]
    video_url = str(first.get("url") or "").strip()
    if not video_url:
        raise RuntimeError("Kling returned no video URL for this request.")
    return {
        "url": video_url,
        "mime_type": "video/mp4",
        "poster_url": str(first.get("cover_url") or first.get("poster_url") or first.get("thumbnail_url") or "").strip(),
        "width": int(first.get("width") or 0),
        "height": int(first.get("height") or 0),
    }


def run_native_kling_video_job(body: dict, api_token: str) -> dict:
    body = normalize_video_request(body)
    input_mode = body.get("videoInputMode", "text")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Please enter a video prompt.")

    selected_model_id = str(body.get("model") or KLING_DIRECT_TEXT_DEFAULT_ID).strip() or KLING_DIRECT_TEXT_DEFAULT_ID
    model_info = VIDEO_MODELS_INFO.get(selected_model_id, {})
    model_name = str(model_info.get("native_model_name") or selected_model_id or KLING_DIRECT_TEXT_DEFAULT_ID).strip() or KLING_DIRECT_TEXT_DEFAULT_ID
    duration = normalize_video_duration(body.get("duration", 5))
    aspect_ratio = body.get("aspectRatio", "16:9")
    negative_prompt = str(body.get("negativePrompt") or "").strip()
    source_image = body.get("sourceImage") or {}
    reference_images = list(body.get("referenceImages") or [])
    kling_mode = str(model_info.get("kling_mode") or "pro").strip().lower() or "pro"
    endpoint = str(model_info.get("native_video_endpoint") or "").strip()
    if not endpoint:
        endpoint = "/v1/videos/text2video" if input_mode == "text" else "/v1/videos/image2video"
    native_ref_item_key = str(model_info.get("native_reference_item_key") or "image").strip() or "image"

    def build_native_ref_item(image_payload: dict, item_type: str = "") -> dict:
        raw_value = str(image_payload.get("data") or "").strip()
        item = {native_ref_item_key: raw_value}
        if item_type:
            item["type"] = item_type
        return item

    payload = {
        "model_name": model_name,
        "prompt": prompt,
        "duration": str(duration),
        "mode": kling_mode,
        "sound": "off",
        "aspect_ratio": aspect_ratio,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if input_mode == "image":
        if not source_image.get("data"):
            raise ValueError("Choose a source image for image-to-video.")
        if endpoint == "/v1/videos/omni-video":
            payload["image_list"] = [build_native_ref_item(source_image, "first_frame")]
        else:
            payload["image"] = str(source_image.get("data") or "").strip()
    elif input_mode == "reference":
        reference_payloads = [
            build_native_ref_item(img)
            for img in reference_images
            if str(img.get("data") or "").strip()
        ]
        if endpoint == "/v1/videos/omni-video" and source_image.get("data"):
            reference_payloads.insert(0, build_native_ref_item(source_image, "first_frame"))
        if model_name == "kling-video-o1" and source_image.get("data") and len(reference_payloads) > 2:
            raise ValueError("Kling O1 supports at most one extra reference image when a start image is also used.")
        if model_info.get("reference_images_required") and not reference_payloads:
            raise ValueError("Add at least one reference image for this Kling reference-to-video model.")
        if reference_payloads:
            payload["image_list"] = reference_payloads
    headers = build_kling_headers(api_token)
    try:
        create_response = requests.post(f"{KLING_BASE_URL}{endpoint}", headers=headers, json=payload, timeout=90)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timeout: Kling request took too long to start.") from exc
    except Exception as exc:
        raise RuntimeError(f"Network error: {exc}") from exc
    if create_response.status_code != 200:
        raise RuntimeError(extract_kling_error(create_response))
    create_payload = create_response.json()
    task_id = str(create_payload.get("data", {}).get("task_id") or create_payload.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError("Kling did not return a task id.")
    result_payload = poll_kling_task(api_token, endpoint, task_id)
    video_item = build_kling_video_from_payload(result_payload)
    params_meta = merge_request_settings(merge_asset_metadata({
        "model": selected_model_id,
        "modelFamily": body.get("modelFamily", "kling"),
        "model_label": model_info.get("label", "Kling"),
        "provider": "kling",
        "provider_label": "Kling",
        "videoInputMode": input_mode,
        "duration": duration,
        "aspectRatio": aspect_ratio,
        "negativePrompt": negative_prompt,
        "prompt": prompt,
        "resolution": body.get("resolution", "720p"),
    }, body), body)
    return {
        "ok": True,
        "videos": [video_item],
        "text": "",
        "cost": round(float(VIDEO_PRICING.get(selected_model_id, {}).get(str(duration), 0.0)), 4),
        "model_label": model_info.get("label", "Kling"),
        "params": params_meta,
        "_input_source_image": source_image if str(source_image.get("data") or "").strip() else None,
        "_input_reference_images": reference_images,
    }


def run_fal_kling_video_job(body: dict, api_key: str) -> dict:
    body = normalize_video_request(body)
    input_mode = body.get("videoInputMode", "text")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Please enter a video prompt.")
    duration = normalize_video_duration(body.get("duration", 5))
    aspect_ratio = body.get("aspectRatio", "16:9")
    negative_prompt = str(body.get("negativePrompt") or "").strip()
    source_image = body.get("sourceImage") or {}
    source_video = body.get("sourceVideo") or {}
    reference_images = list(body.get("referenceImages") or [])
    endpoint = str(body.get("model") or "").strip()
    model_info = VIDEO_MODELS_INFO.get(endpoint, {})
    if not endpoint or model_info.get("provider") != "fal" or model_info.get("family") != "kling":
        raise ValueError("Choose a valid Fal Kling model.")
    max_reference_images = max(0, int(model_info.get("max_reference_images", 0) or 0))
    if not model_info.get("supports_reference_images"):
        reference_images = []
    elif max_reference_images:
        reference_images = reference_images[:max_reference_images]
    payload = {
        "prompt": prompt,
        "duration": str(duration),
        "aspect_ratio": aspect_ratio,
        "sync_mode": True,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if input_mode != "text" and model_info.get("supports_start_image"):
        if model_info.get("start_image_required") and not source_image.get("data"):
            raise ValueError("Choose a start image for this Kling video model.")
        if source_image.get("data"):
            start_field = str(model_info.get("start_image_field") or "image_url")
            payload[start_field] = f"data:{source_image.get('mime_type', 'image/png')};base64,{source_image.get('data', '')}"
    if input_mode == "video" and model_info.get("supports_source_video"):
        if model_info.get("source_video_required") and not str(source_video.get("data") or source_video.get("url") or "").strip():
            raise ValueError("Choose a source video for this Kling video-to-video model.")
        if str(source_video.get("data") or source_video.get("url") or "").strip():
            client = fal_client.SyncClient(key=api_key)
            source_field = str(model_info.get("source_video_field") or "video_url")
            payload[source_field] = upload_video_payload_to_fal(client, source_video)
    if input_mode == "reference" and model_info.get("supports_reference_images"):
        if model_info.get("reference_images_required") and not reference_images:
            raise ValueError("Add at least one reference image for this Kling reference-to-video model.")
        if reference_images:
            ref_field = str(model_info.get("reference_images_field") or "image_urls")
            reference_urls = [
                f"data:{img.get('mime_type', 'image/png')};base64,{img.get('data', '')}"
                for img in reference_images
                if str(img.get("data") or "").strip()
            ]
            if model_info.get("reference_images_required") and not reference_urls:
                raise ValueError("Add at least one valid reference image for this Kling reference-to-video model.")
            if reference_urls:
                payload[ref_field] = reference_urls
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(f"{FAL_BASE_URL}/{endpoint}", headers=headers, json=payload, timeout=600)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timeout: Fal Kling generation took too long.") from exc
    except Exception as exc:
        raise RuntimeError(f"Network error: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(extract_fal_error(response))
    result = response.json()
    video_item = extract_fal_video_result(result)
    if not video_item:
        raise RuntimeError("Fal Kling returned no video for this request.")
    params_meta = merge_request_settings(merge_asset_metadata({
        "model": endpoint,
        "modelFamily": body.get("modelFamily", "kling"),
        "model_label": model_info.get("label", "Kling"),
        "provider": "fal",
        "provider_label": "Fal",
        "videoInputMode": input_mode,
        "duration": duration,
        "aspectRatio": aspect_ratio,
        "negativePrompt": negative_prompt,
        "prompt": prompt,
        "resolution": body.get("resolution", "720p"),
    }, body), body)
    return {
        "ok": True,
        "videos": [video_item],
        "text": "",
        "cost": round(float(VIDEO_PRICING.get(endpoint, {}).get(str(duration), 0.0)), 4),
        "model_label": model_info.get("label", "Kling"),
        "params": params_meta,
        "_input_source_image": source_image if str(source_image.get("data") or "").strip() else None,
        "_input_source_video": source_video if str(source_video.get("data") or source_video.get("url") or "").strip() else None,
        "_input_reference_images": reference_images,
    }


def run_fal_wan_video_job(body: dict, api_key: str) -> dict:
    body = normalize_video_request(body)
    input_mode = body.get("videoInputMode", "text")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Please enter a video prompt.")
    duration = normalize_video_duration(body.get("duration", 5))
    num_frames = (duration * 16) + 1
    aspect_ratio = body.get("aspectRatio", "16:9")
    negative_prompt = str(body.get("negativePrompt") or "").strip()
    resolution = normalize_video_resolution(body.get("resolution", "720p"))
    safety_checker = bool(body.get("videoSafetyChecker", True))
    output_safety_checker = bool(body.get("videoOutputSafetyChecker", True))
    source_image = body.get("sourceImage") or {}
    endpoint = FAL_WAN_T2V_ID if input_mode == "text" else FAL_WAN_I2V_ID
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "num_frames": num_frames,
        "frames_per_second": 16,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "enable_safety_checker": safety_checker,
        "enable_output_safety_checker": output_safety_checker,
        "enable_prompt_expansion": True,
        "sync_mode": True,
    }
    if input_mode == "image":
        if not source_image.get("data"):
            raise ValueError("Choose a source image for image-to-video.")
        payload["image_url"] = f"data:{source_image.get('mime_type', 'image/png')};base64,{source_image.get('data', '')}"
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(f"{FAL_BASE_URL}/{endpoint}", headers=headers, json=payload, timeout=900)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timeout: Fal Wan generation took too long.") from exc
    except Exception as exc:
        raise RuntimeError(f"Network error: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(extract_fal_error(response))
    result = response.json()
    video_item = extract_fal_video_result(result)
    if not video_item:
        raise RuntimeError("Fal Wan returned no video for this request.")
    params_meta = merge_request_settings(merge_asset_metadata({
        "model": endpoint,
        "modelFamily": body.get("modelFamily", "wan-video"),
        "model_label": "Wan Video",
        "provider": "fal",
        "provider_label": "Fal",
        "videoInputMode": input_mode,
        "duration": duration,
        "aspectRatio": aspect_ratio,
        "negativePrompt": negative_prompt,
        "prompt": prompt,
        "resolution": resolution,
        "videoSafetyChecker": safety_checker,
        "videoOutputSafetyChecker": output_safety_checker,
    }, body), body)
    return {
        "ok": True,
        "videos": [video_item],
        "text": "",
        "cost": round(float(VIDEO_PRICING.get(FAL_WAN_T2V_ID, {}).get(str(duration), 0.0)), 4),
        "model_label": "Wan Video",
        "params": params_meta,
        "_input_source_image": source_image if str(source_image.get("data") or "").strip() else None,
        "_input_reference_images": [],
    }


def run_fal_seedance_video_job(body: dict, api_key: str) -> dict:
    body = normalize_video_request(body)
    input_mode = body.get("videoInputMode", "text")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Please enter a video prompt.")
    duration = normalize_video_duration(body.get("duration", 5))
    aspect_ratio = body.get("aspectRatio", "16:9")
    negative_prompt = str(body.get("negativePrompt") or "").strip()
    resolution = normalize_video_resolution(body.get("resolution", "720p"))
    safety_checker = bool(body.get("videoSafetyChecker", True))
    source_image = body.get("sourceImage") or {}
    reference_images = list(body.get("referenceImages") or [])
    endpoint = str(body.get("model") or "").strip()
    model_info = VIDEO_MODELS_INFO.get(endpoint, {})
    if not endpoint or model_info.get("provider") != "fal" or model_info.get("family") != "seedance":
        raise ValueError("Choose a valid Fal Seedance model.")
    max_reference_images = max(0, int(model_info.get("max_reference_images", 0) or 0))
    if not model_info.get("supports_reference_images"):
        reference_images = []
    elif max_reference_images:
        reference_images = reference_images[:max_reference_images]
    payload = {
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "enable_safety_checker": safety_checker,
        "sync_mode": True,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if input_mode != "text" and model_info.get("supports_start_image"):
        if model_info.get("start_image_required") and not source_image.get("data"):
            raise ValueError("Choose a start image for this Seedance video model.")
        if source_image.get("data"):
            start_field = str(model_info.get("start_image_field") or "image_url")
            payload[start_field] = f"data:{source_image.get('mime_type', 'image/png')};base64,{source_image.get('data', '')}"
    if input_mode == "reference" and model_info.get("supports_reference_images"):
        if model_info.get("reference_images_required") and not reference_images:
            raise ValueError("Add at least one reference image for this Seedance reference-to-video model.")
        if reference_images:
            ref_field = str(model_info.get("reference_images_field") or "reference_image_urls")
            reference_urls = [
                f"data:{img.get('mime_type', 'image/png')};base64,{img.get('data', '')}"
                for img in reference_images
                if str(img.get("data") or "").strip()
            ]
            if model_info.get("reference_images_required") and not reference_urls:
                raise ValueError("Add at least one valid reference image for this Seedance reference-to-video model.")
            if reference_urls:
                payload[ref_field] = reference_urls
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(f"{FAL_BASE_URL}/{endpoint}", headers=headers, json=payload, timeout=900)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timeout: Fal Seedance generation took too long.") from exc
    except Exception as exc:
        raise RuntimeError(f"Network error: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(extract_fal_error(response))
    result = response.json()
    video_item = extract_fal_video_result(result)
    if not video_item:
        raise RuntimeError("Fal Seedance returned no video for this request.")
    params_meta = merge_request_settings(merge_asset_metadata({
        "model": endpoint,
        "modelFamily": body.get("modelFamily", "seedance"),
        "model_label": model_info.get("label", "Seedance"),
        "provider": "fal",
        "provider_label": "Fal",
        "videoInputMode": input_mode,
        "duration": duration,
        "aspectRatio": aspect_ratio,
        "negativePrompt": negative_prompt,
        "prompt": prompt,
        "resolution": resolution,
        "videoSafetyChecker": safety_checker,
    }, body), body)
    return {
        "ok": True,
        "videos": [video_item],
        "text": "",
        "cost": round(float(VIDEO_PRICING.get(endpoint, {}).get(str(duration), 0.0)), 4),
        "model_label": model_info.get("label", "Seedance"),
        "params": params_meta,
        "_input_source_image": source_image if str(source_image.get("data") or "").strip() else None,
        "_input_reference_images": reference_images,
    }


def run_fal_seedvr_video_job(body: dict, api_key: str) -> dict:
    body = normalize_video_request(body)
    input_mode = body.get("videoInputMode", "video")
    endpoint = str(body.get("model") or FAL_SEEDVR_VIDEO_ID).strip() or FAL_SEEDVR_VIDEO_ID
    model_info = VIDEO_MODELS_INFO.get(endpoint, {})
    if not endpoint or model_info.get("provider") != "fal" or model_info.get("family") != "seedvr-video":
        raise ValueError("Choose a valid Fal SeedVR2 video model.")

    source_video = body.get("sourceVideo") or {}
    if not str(source_video.get("data") or source_video.get("url") or "").strip():
        raise ValueError("Choose or drop a source video for SeedVR2.")

    upscale_mode = normalize_video_upscale_mode(body.get("videoUpscaleMode", "factor"))
    upscale_factor = normalize_video_upscale_factor(body.get("videoUpscaleFactor", 2))
    target_resolution = normalize_video_upscale_target_resolution(
        body.get("videoUpscaleTargetResolution", "1080p")
    )
    noise_scale = normalize_video_upscale_noise_scale(body.get("videoUpscaleNoiseScale", 0.1))
    output_format = normalize_video_upscale_output_format(body.get("videoUpscaleOutputFormat", "X264 (.mp4)"))
    output_quality = normalize_video_upscale_output_quality(body.get("videoUpscaleOutputQuality", "high"))
    output_write_mode = normalize_video_upscale_write_mode(body.get("videoUpscaleOutputWriteMode", "balanced"))
    sync_mode = bool(body.get("videoUpscaleSyncMode", True))
    seed_value = normalize_optional_int(body.get("videoUpscaleSeed"))

    try:
        client = fal_client.SyncClient(key=api_key, default_timeout=1800.0)
        uploaded_video_url = upload_video_payload_to_fal(client, source_video)
        payload = {
            "video_url": uploaded_video_url,
            "upscale_mode": upscale_mode,
            "noise_scale": noise_scale,
            "output_format": output_format,
            "output_quality": output_quality,
            "output_write_mode": output_write_mode,
            "sync_mode": sync_mode,
        }
        if upscale_mode == "target":
            payload["target_resolution"] = target_resolution
        else:
            payload["upscale_factor"] = upscale_factor
        if seed_value is not None:
            payload["seed"] = seed_value
        result = client.run(endpoint, arguments=payload)
    except TimeoutError as exc:
        raise TimeoutError("Timeout: SeedVR2 video upscale took too long.") from exc
    except Exception as exc:
        message = str(exc)
        if "Timeout" in message:
            raise TimeoutError("Timeout: SeedVR2 video upscale took too long.") from exc
        raise RuntimeError(f"SeedVR2 video upscale failed: {message}") from exc

    video_item = extract_fal_video_result(result if isinstance(result, dict) else {})
    if not video_item:
        raise RuntimeError("Fal SeedVR2 returned no video for this request.")

    params_meta = merge_request_settings(merge_asset_metadata({
        "model": endpoint,
        "modelFamily": body.get("modelFamily", "seedvr-video"),
        "model_label": model_info.get("label", "SeedVR2 Video"),
        "provider": "fal",
        "provider_label": "Fal",
        "videoInputMode": input_mode,
        "upscaled": True,
        "upscalerType": "seedvr2-video",
        "upscalerLabel": "SeedVR2 Video",
        "upscaleModel": "seedvr2-video",
        "upscalePreset": "video",
        "prompt": "",
        "negativePrompt": "",
        "duration": body.get("duration", 0),
        "aspectRatio": body.get("aspectRatio", ""),
        "resolution": body.get("resolution", ""),
        "videoUpscaleMode": upscale_mode,
        "videoUpscaleFactor": float(upscale_factor),
        "videoUpscaleTargetResolution": target_resolution,
        "videoUpscaleNoiseScale": float(noise_scale),
        "videoUpscaleOutputFormat": output_format,
        "videoUpscaleOutputQuality": output_quality,
        "videoUpscaleOutputWriteMode": output_write_mode,
        "videoUpscaleSeed": seed_value,
        "videoUpscaleSyncMode": sync_mode,
    }, body), body)
    return {
        "ok": True,
        "videos": [video_item],
        "text": "",
        "cost": 0.0,
        "model_label": model_info.get("label", "SeedVR2 Video"),
        "params": params_meta,
        "_input_source_image": None,
        "_input_source_video": source_video,
        "_input_reference_images": [],
    }


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
    ref_images = normalize_ref_image_payloads(ref_images, max_ref)

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
        payload["image_urls"] = build_seedream_data_uri_ref_inputs(ref_images)

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
    params_meta = merge_request_settings(merge_asset_metadata({
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
    }, body), body)
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
    ref_images = normalize_ref_image_payloads(ref_images, max_ref)

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
    params_meta = merge_request_settings(merge_asset_metadata({
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
    }, body), body)
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
    ref_images = normalize_ref_image_payloads(ref_images, max_ref)

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
    params_meta = merge_request_settings(merge_asset_metadata({
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
    }, body), body)
    return {
        "ok": True,
        "images": images,
        "text": "",
        "cost": round(cost, 4),
        "model_label": model_info["label"],
        "params": params_meta,
        "_input_ref_images": ref_images,
    }


def run_fal_seedvr_upscale_job(body: dict, api_key: str) -> dict:
    upscale_model_key = str(body.get("upscaleModel") or "seedvr2").strip().lower()
    upscaler_info = UPSCALER_MODELS.get(upscale_model_key)
    if not upscaler_info:
        raise ValueError("Invalid upscale model.")

    source_image = body.get("image") if isinstance(body.get("image"), dict) else {}
    image_b64 = str(source_image.get("data") or "").strip()
    mime_type = str(source_image.get("mime_type") or "image/png").strip() or "image/png"
    if not image_b64:
        raise ValueError("Select an image from the gallery to upscale.")

    source_params = dict(body.get("sourceParams") or {})
    source_width, source_height = measure_image_dimensions(image_b64, mime_type)
    preset_value = str(body.get("upscalePreset") or "factor:2").strip().lower()
    target_width = 0
    target_height = 0
    target_anchor = ""
    if preset_value == "custom":
        target_width, target_height, upscale_factor, target_anchor = normalize_seedvr_custom_resolution(
            source_width,
            source_height,
            body.get("upscaleTargetWidth"),
            body.get("upscaleTargetHeight"),
            body.get("upscaleTargetAnchor"),
        )
        upscale_mode = "factor"
        target_resolution = ""
        preset_label = f"{target_width}x{target_height}"
    else:
        upscale_mode, upscale_factor, target_resolution, preset_label = normalize_seedvr_preset(preset_value)

    payload = {
        "image_url": f"data:{mime_type};base64,{image_b64}",
        "upscale_mode": upscale_mode,
        "noise_scale": 0.1,
        "output_format": "png",
        "sync_mode": True,
    }
    if upscale_mode == "factor" and upscale_factor is not None:
        payload["upscale_factor"] = upscale_factor
    if upscale_mode == "target" and target_resolution:
        payload["target_resolution"] = target_resolution

    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(f"{FAL_BASE_URL}/{upscaler_info['id']}", headers=headers, json=payload, timeout=240)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("Timeout: SeedVR upscaling took too long.") from exc
    except Exception as exc:
        raise RuntimeError(f"Network error: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(extract_fal_error(response))

    result = response.json()
    image_item = result.get("image") if isinstance(result, dict) else None
    if not isinstance(image_item, dict):
        items = result.get("images") or result.get("data") or []
        image_item = items[0] if items and isinstance(items[0], dict) else None
    if not isinstance(image_item, dict):
        raise RuntimeError("SeedVR returned no image for this request.")

    decoded = decode_fal_image_result(image_item)
    if not decoded:
        raise RuntimeError("SeedVR returned no image for this request.")

    output_width = int(image_item.get("width") or 0)
    output_height = int(image_item.get("height") or 0)
    if not output_width or not output_height:
        output_width, output_height = measure_image_dimensions(decoded.get("data", ""), decoded.get("mime_type", "image/png"))

    if target_width and target_height and (output_width != target_width or output_height != target_height):
        resized_b64, resized_mime = resize_image_b64_to_exact_png(
            decoded.get("data", ""),
            decoded.get("mime_type", "image/png"),
            target_width,
            target_height,
        )
        decoded = {"mime_type": resized_mime, "data": resized_b64}
        output_width = target_width
        output_height = target_height

    image_size_label = approximate_image_size_label(output_width, output_height) or str(source_params.get("imageSize") or "")
    display_size_label = preset_label or image_size_label
    megapixels = max(0.0, (output_width * output_height) / 1_000_000) if output_width and output_height else 0.0
    cost = round(megapixels * 0.001, 4)

    params_meta = dict(source_params)
    params_meta.update({
        "imageSize": image_size_label,
        "upscaled": True,
        "upscalerType": upscale_model_key,
        "upscalerLabel": upscaler_info["label"],
        "upscaleModel": upscale_model_key,
        "upscalePreset": preset_value,
        "upscaleMode": upscale_mode,
        "upscaleFactor": upscale_factor,
        "upscaleTargetResolution": target_resolution or (f"{target_width}x{target_height}" if target_width and target_height else ""),
        "upscaleTargetWidth": target_width,
        "upscaleTargetHeight": target_height,
        "upscaleTargetAnchor": target_anchor,
        "upscaleDisplaySize": f"Upscaled {str(display_size_label).upper()}" if display_size_label else "Upscaled",
        "upscaleSourceDate": str(source_params.get("gen_date") or ""),
        "upscaleOutputWidth": output_width,
        "upscaleOutputHeight": output_height,
        "upscaleSourceFilename": str(body.get("sourceFilename") or ""),
        "upscaleSourceRelpath": str(source_params.get("gen_relpath") or source_params.get("assetRelpath") or ""),
    })
    params_meta = merge_request_settings(merge_asset_metadata(params_meta, body, fallback_source=source_params), body)

    return {
        "ok": True,
        "images": [decoded],
        "text": "",
        "cost": cost,
        "model_label": params_meta.get("model_label", ""),
        "params": params_meta,
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


def run_video_job(body: dict, config: dict) -> dict:
    payload = normalize_video_request(body)
    provider = payload.get("provider", "kling")
    family = payload.get("modelFamily", "kling")

    if provider == "kling":
        kling_token = (config.get("kling_api_token", "") or "").strip()
        if not kling_token:
            raise ValueError("Kling API token not configured. Go to Settings.")
        return run_native_kling_video_job(payload, kling_token)

    if provider == "fal":
        fal_key = (config.get("fal_api_key", "") or "").strip()
        if not fal_key:
            raise ValueError("Fal API key not configured. Go to Settings.")
        if family == "seedvr-video":
            return run_fal_seedvr_video_job(payload, fal_key)
        if family == "wan-video":
            return run_fal_wan_video_job(payload, fal_key)
        if family == "seedance":
            return run_fal_seedance_video_job(payload, fal_key)
        return run_fal_kling_video_job(payload, fal_key)

    raise ValueError("Unsupported video provider")


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


@app.route("/api/jobs/generate", methods=["POST"])
@login_required
def api_generate_async():
    body = request.get_json(silent=True) or {}
    try:
        job = start_async_generate_job(body)
        return jsonify(job), 202
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/jobs/video", methods=["POST"])
@login_required
def api_video_async():
    body = request.get_json(silent=True) or {}
    try:
        job = start_async_video_job(body)
        return jsonify(job), 202
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/upscale", methods=["POST"])
@login_required
def api_upscale():
    config = load_config()
    fal_key = (config.get("fal_api_key", "") or "").strip()
    if not fal_key:
        return jsonify({"ok": False, "error": "Fal API key not configured. Go to Settings."})

    body = request.get_json(silent=True) or {}
    try:
        result = run_fal_seedvr_upscale_job(body, fal_key)
        persist_generation_result(result)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except TimeoutError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/jobs/upscale", methods=["POST"])
@login_required
def api_upscale_async():
    body = request.get_json(silent=True) or {}
    try:
        job = start_async_upscale_job(body)
        return jsonify(job), 202
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/jobs/<job_id>", methods=["GET"])
@login_required
def api_async_job_status(job_id):
    job = get_async_job(str(job_id or "").strip())
    if not job:
        return jsonify({"ok": False, "error": "Job not found."}), 404
    return jsonify(job)


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
    MAX_LOAD = 100
    result = []
    for item in collect_generation_records(max_load=MAX_LOAD):
        params = item.get("params", {})
        result.append({
            "mime_type": params.get("mime_type", "image/png"),
            "url": item.get("url", ""),
            "generated_at": item.get("generated_at", ""),
            "text": item.get("text", ""),
            "gen_date": item.get("date", ""),
            "gen_filename": item.get("filename", ""),
            "gen_relpath": item.get("relpath", ""),
            "delete_url": item.get("delete_url", ""),
            "folder_open_payload": item.get("folder_open_payload", {}),
            "params": params,
        })
    return jsonify(result)


@app.route("/api/videos")
@login_required
def api_videos():
    max_load = 40
    result = []
    for item in collect_video_asset_records(max_load=max_load):
        result.append({
            "url": item.get("url", ""),
            "generated_at": item.get("generated_at", ""),
            "gen_date": item.get("date", ""),
            "gen_filename": item.get("filename", ""),
            "gen_relpath": item.get("relpath", ""),
            "mime_type": item.get("mime_type", "video/mp4"),
            "poster_url": item.get("poster_url", ""),
            "text": item.get("text", ""),
            "delete_url": item.get("delete_url", ""),
            "folder_open_payload": item.get("folder_open_payload", {}),
            "params": item.get("params", {}),
        })
    return jsonify(result)


@app.route("/api/videos/<path:asset_relpath>", methods=["DELETE"])
@login_required
def api_delete_video(asset_relpath):
    try:
        safe_relpath = resolve_asset_relpath(relpath=asset_relpath)
        safe_root, video_path, _ = resolve_asset_image_path("videos", relpath=safe_relpath)
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    filename = os.path.basename(video_path)
    if os.path.splitext(filename)[1].lower() not in (".mp4", ".webm", ".mov"):
        return jsonify({"ok": False, "error": "Invalid file type"}), 400

    try:
        base_path = os.path.splitext(video_path)[0]
        json_path = base_path + ".json"
        poster_path = base_path + "_poster.png"
        archived_refs = []

        if os.path.exists(json_path):
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if isinstance(meta.get("videoSourceArchive"), dict):
                    archived_refs.append(meta.get("videoSourceArchive"))
                if isinstance(meta.get("videoRefArchive"), list):
                    archived_refs.extend([item for item in meta.get("videoRefArchive", []) if isinstance(item, dict)])
            except Exception:
                archived_refs = []

        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(json_path):
            os.remove(json_path)
        if os.path.exists(poster_path):
            os.remove(poster_path)

        delete_reference_archive_entries(archived_refs)

        day_dir = os.path.dirname(video_path)
        while os.path.isdir(day_dir) and day_dir.startswith(safe_root + os.sep) and not os.listdir(day_dir):
            os.rmdir(day_dir)
            day_dir = os.path.dirname(day_dir)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# API Ã¢â‚¬â€ Delete a generation (image + sidecar JSON only, never loved/)
# ---------------------------------------------------------------------------
@app.route("/api/generations/<path:asset_relpath>", methods=["DELETE"])
@login_required
def api_delete_generation(asset_relpath):
    try:
        safe_relpath = resolve_asset_relpath(relpath=asset_relpath)
        safe_root, img_path, _ = resolve_asset_image_path("history", relpath=safe_relpath)
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    filename = os.path.basename(img_path)
    if os.path.splitext(filename)[1].lower() not in (".jpeg", ".jpg", ".png", ".webp"):
        return jsonify({"ok": False, "error": "Invalid file type"}), 400

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
        while os.path.isdir(day_dir) and day_dir.startswith(safe_root + os.sep) and not os.listdir(day_dir):
            os.rmdir(day_dir)
            day_dir = os.path.dirname(day_dir)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API Ã¢â‚¬â€ Publish (save to loved/)
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

    now = datetime.now()

    try:
        img_b64, mime_type = convert_image_b64_to_png(img_b64, mime_type)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Image conversion error: {e}"})

    fallback_filename = sanitize_asset_filename_stem(
        meta.get("assetFilename", "") or meta.get("prompt", "") or meta.get("model_label", "") or now.strftime("%H%M%S"),
        fallback=now.strftime("%H%M%S"),
    )
    asset_meta = normalize_asset_metadata(meta, require_filename=True, fallback_filename=fallback_filename)
    meta.update(asset_meta)
    config = load_config()
    update_asset_metadata_memory(config, asset_meta)
    save_config(config)

    abs_dir, relpath, basename = build_asset_storage_paths(LOVED_DIR, asset_meta, "png")
    img_path = os.path.join(LOVED_DIR, relpath.replace("/", os.sep))
    meta_path = os.path.join(abs_dir, f"{basename}.json")

    img_bytes = base64.b64decode(img_b64)
    with open(img_path, "wb") as f:
        f.write(img_bytes)

    meta["mime_type"]    = mime_type
    meta["published_at"] = now.isoformat()
    meta["filename"]     = os.path.basename(img_path)
    meta["assetRelpath"] = relpath
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return jsonify({
        "ok":      True,
        "date":    derive_asset_date_key(relpath, now.isoformat()),
        "file":    os.path.basename(img_path),
        "url":     f"/loved/{relpath}",
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
# API Ã¢â‚¬â€ Stats
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


@app.route("/api/video-models-info")
@login_required
def api_video_models_info():
    return jsonify(VIDEO_MODELS_INFO)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    migrate_image_assets_layout()
    os.makedirs(LOVED_DIR, exist_ok=True)
    os.makedirs(GENERATIONS_DIR, exist_ok=True)
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(REFERENCE_ARCHIVE_DIR, exist_ok=True)
    os.makedirs(REFERENCE_MASKS_DIR, exist_ok=True)
    os.makedirs(REFERENCE_RENDERS_DIR, exist_ok=True)
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
    print(f"  AI API Studio {APP_VERSION}")
    print("  http://localhost:5000")
    print("  Login: admin / banana2024")
    print("  Max ref images: NB=0, Pro=8, NB2=14")
    print("="*52 + "\n")
    app.run(debug=True, port=5000)




