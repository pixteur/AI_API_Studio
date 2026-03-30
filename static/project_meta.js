(function () {
  const STORAGE_KEYS = {
    client: "ai_api_asset_client",
    project: "ai_api_asset_project",
    shot: "ai_api_asset_shot",
    filename: "ai_api_asset_filename",
  };

  const DEFAULT_STATE = {
    assetClient: "-",
    assetProject: "-",
    assetShot: "-",
    assetFilename: "",
  };

  const bootstrap = window.__ASSET_META_BOOTSTRAP__ || {};
  let optionsCache = {
    clients: Array.isArray(bootstrap?.options?.clients) && bootstrap.options.clients.length ? bootstrap.options.clients : ["-"],
    projects: Array.isArray(bootstrap?.options?.projects) && bootstrap.options.projects.length ? bootstrap.options.projects : ["-"],
    shots: Array.isArray(bootstrap?.options?.shots) && bootstrap.options.shots.length ? bootstrap.options.shots : ["-"],
    filenames: Array.isArray(bootstrap?.options?.filenames) ? bootstrap.options.filenames : [],
  };

  function getBar() {
    return document.getElementById("projectMetaBar");
  }

  function normalizeSelectValue(value, fallback) {
    const clean = String(value || "").trim();
    return clean || fallback;
  }

  function normalizeFilename(value) {
    return String(value || "").trim();
  }

  function normalizeState(state) {
    return {
      assetClient: normalizeSelectValue(state?.assetClient, "-"),
      assetProject: normalizeSelectValue(state?.assetProject, "-"),
      assetShot: normalizeSelectValue(state?.assetShot, "-"),
      assetFilename: normalizeFilename(state?.assetFilename),
    };
  }

  function mergeUniqueValues() {
    const seen = new Set();
    const merged = [];
    for (const group of arguments) {
      for (const rawValue of group || []) {
        const value = String(rawValue || "").trim();
        if (!value || seen.has(value)) continue;
        seen.add(value);
        merged.push(value);
      }
    }
    return merged;
  }

  function loadState() {
    const state = { ...DEFAULT_STATE };
    try {
      state.assetClient = localStorage.getItem(STORAGE_KEYS.client) || DEFAULT_STATE.assetClient;
      state.assetProject = localStorage.getItem(STORAGE_KEYS.project) || DEFAULT_STATE.assetProject;
      state.assetShot = localStorage.getItem(STORAGE_KEYS.shot) || DEFAULT_STATE.assetShot;
      state.assetFilename = localStorage.getItem(STORAGE_KEYS.filename) || DEFAULT_STATE.assetFilename;
    } catch (error) {}
    return state;
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORAGE_KEYS.client, state.assetClient || "-");
      localStorage.setItem(STORAGE_KEYS.project, state.assetProject || "-");
      localStorage.setItem(STORAGE_KEYS.shot, state.assetShot || "-");
      localStorage.setItem(STORAGE_KEYS.filename, state.assetFilename || "");
    } catch (error) {}
  }

  function getCurrentState() {
    const bar = getBar();
    if (!bar) return loadState();
    return normalizeState({
      assetClient: bar.querySelector("#projectMetaClient")?.value,
      assetProject: bar.querySelector("#projectMetaProject")?.value,
      assetShot: bar.querySelector("#projectMetaShot")?.value,
      assetFilename: bar.querySelector("#projectMetaFilename")?.value,
    });
  }

  function setSelectOptions(select, values, selectedValue, fallback = "-") {
    if (!select) return;
    const merged = mergeUniqueValues(values, [selectedValue]);
    if (!merged.includes(fallback)) merged.unshift(fallback);
    select.innerHTML = "";
    for (const value of merged) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }
    select.value = merged.includes(selectedValue) ? selectedValue : fallback;
  }

  function setFilenameOptions(datalist, values) {
    if (!datalist) return;
    const merged = mergeUniqueValues(values);
    datalist.innerHTML = "";
    for (const value of merged) {
      const option = document.createElement("option");
      option.value = value;
      datalist.appendChild(option);
    }
  }

  function refreshControls(state) {
    const bar = getBar();
    if (!bar) return;
    const normalized = normalizeState(state || getCurrentState());
    setSelectOptions(bar.querySelector("#projectMetaClient"), optionsCache.clients, normalized.assetClient, "-");
    setSelectOptions(bar.querySelector("#projectMetaProject"), optionsCache.projects, normalized.assetProject, "-");
    setSelectOptions(bar.querySelector("#projectMetaShot"), optionsCache.shots, normalized.assetShot, "-");
    const filenameInput = bar.querySelector("#projectMetaFilename");
    if (filenameInput) filenameInput.value = normalized.assetFilename;
    setFilenameOptions(bar.querySelector("#projectMetaFilenames"), mergeUniqueValues(optionsCache.filenames, [normalized.assetFilename]));
    bar.classList.toggle("project-meta-missing-filename", !normalized.assetFilename);
  }

  async function fetchOptions() {
    try {
      const response = await fetch("/api/asset-metadata-options", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) return;
      const payload = await response.json();
      if (!payload?.ok || !payload.options) return;
      optionsCache = {
        clients: Array.isArray(payload.options.clients) && payload.options.clients.length ? payload.options.clients : ["-"],
        projects: Array.isArray(payload.options.projects) && payload.options.projects.length ? payload.options.projects : ["-"],
        shots: Array.isArray(payload.options.shots) && payload.options.shots.length ? payload.options.shots : ["-"],
        filenames: Array.isArray(payload.options.filenames) ? payload.options.filenames : [],
      };
      refreshControls(getCurrentState());
    } catch (error) {}
  }

  let memorySaveTimer = null;
  function queueMemorySave() {
    window.clearTimeout(memorySaveTimer);
    memorySaveTimer = window.setTimeout(async () => {
      try {
        await fetch("/api/asset-metadata-memory", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(getCurrentState()),
        });
        fetchOptions();
      } catch (error) {}
    }, 250);
  }

  function emitState(state) {
    window.dispatchEvent(new CustomEvent("asset-meta-change", { detail: normalizeState(state) }));
  }

  function applyState(state, { emit = true, persist = true } = {}) {
    const normalized = normalizeState(state);
    refreshControls(normalized);
    if (persist) saveState(normalized);
    if (emit) emitState(normalized);
  }

  function bindControls() {
    const bar = getBar();
    if (!bar) return;
    const client = bar.querySelector("#projectMetaClient");
    const project = bar.querySelector("#projectMetaProject");
    const shot = bar.querySelector("#projectMetaShot");
    const filename = bar.querySelector("#projectMetaFilename");

    const commit = () => {
      const state = getCurrentState();
      applyState(state, { emit: true, persist: true });
      queueMemorySave();
    };

    [client, project, shot].forEach((select) => {
      if (!select) return;
      select.addEventListener("focus", fetchOptions);
      select.addEventListener("click", fetchOptions);
      select.addEventListener("change", commit);
    });

    if (filename) {
      filename.addEventListener("focus", fetchOptions);
      filename.addEventListener("change", commit);
      filename.addEventListener("blur", commit);
      filename.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit();
        }
      });
    }
  }

  window.getAssetMetaSelection = function () {
    return getCurrentState();
  };

  window.collectAssetMetaPayload = function () {
    return { ...getCurrentState() };
  };

  window.validateAssetMetaSelection = function () {
    const state = getCurrentState();
    if (!String(state.assetFilename || "").trim()) {
      return "Filename is required before generating or upscaling.";
    }
    return "";
  };

  window.setAssetMetaSelection = function (patch, options = {}) {
    const next = { ...getCurrentState(), ...(patch || {}) };
    applyState(next, options);
    if (options.saveMemory !== false) queueMemorySave();
  };

  function initBar() {
    const bar = getBar();
    if (!bar) return;
    bindControls();
    applyState(loadState(), { emit: false, persist: false });
    fetchOptions().finally(() => {
      applyState(loadState(), { emit: true, persist: false });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBar, { once: true });
  } else {
    initBar();
  }
})();
