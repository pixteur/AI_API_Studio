(function () {
  const STORAGE_KEYS = {
    client: "ai_api_asset_client",
    project: "ai_api_asset_project",
    shot: "ai_api_asset_shot",
    filename: "ai_api_asset_filename",
  };

  const DEFAULT_STATE = {
    assetClient: "uncategorized",
    assetProject: "uncategorized",
    assetShot: "uncategorized",
    assetFilename: "",
  };

  const bootstrap = window.__ASSET_META_BOOTSTRAP__ || {};
  let optionsCache = {
    clients: Array.isArray(bootstrap?.options?.clients) && bootstrap.options.clients.length ? bootstrap.options.clients : ["uncategorized"],
    projects: Array.isArray(bootstrap?.options?.projects) && bootstrap.options.projects.length ? bootstrap.options.projects : ["uncategorized"],
    shots: Array.isArray(bootstrap?.options?.shots) && bootstrap.options.shots.length ? bootstrap.options.shots : ["uncategorized"],
    filenames: Array.isArray(bootstrap?.options?.filenames) ? bootstrap.options.filenames : [],
  };

  function getBar() {
    return document.getElementById("projectMetaBar");
  }

  function normalizeSelectValue(value, fallback) {
    const clean = String(value || "").trim();
    if (!clean || clean === "-") return fallback;
    return clean;
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

  function setInputOptions(input, datalist, values, selectedValue, fallback = "uncategorized") {
    if (!input) return;
    const merged = mergeUniqueValues(values, [selectedValue]);
    if (!merged.includes(fallback)) merged.unshift(fallback);
    if (datalist) datalist.innerHTML = "";
    for (const value of merged) {
      if (!datalist) continue;
      const option = document.createElement("option");
      option.value = value;
      datalist.appendChild(option);
    }
    input.value = merged.includes(selectedValue) ? selectedValue : fallback;
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
    setInputOptions(
      bar.querySelector("#projectMetaClient"),
      bar.querySelector("#projectMetaClients"),
      optionsCache.clients,
      normalized.assetClient,
        "uncategorized"
      );
    setInputOptions(
      bar.querySelector("#projectMetaProject"),
      bar.querySelector("#projectMetaProjects"),
      optionsCache.projects,
      normalized.assetProject,
        "uncategorized"
      );
    setInputOptions(
      bar.querySelector("#projectMetaShot"),
      bar.querySelector("#projectMetaShots"),
      optionsCache.shots,
      normalized.assetShot,
        "uncategorized"
      );
    const filenameInput = bar.querySelector("#projectMetaFilename");
    if (filenameInput) filenameInput.value = normalized.assetFilename;
    setFilenameOptions(bar.querySelector("#projectMetaFilenames"), mergeUniqueValues(optionsCache.filenames, [normalized.assetFilename]));
    bar.classList.toggle("project-meta-missing-filename", !normalized.assetFilename);
  }

  function getMenuValuesForInput(input) {
    if (!input) return [];
    if (input.id === "projectMetaClient") return mergeUniqueValues(optionsCache.clients);
    if (input.id === "projectMetaProject") return mergeUniqueValues(optionsCache.projects);
    if (input.id === "projectMetaShot") return mergeUniqueValues(optionsCache.shots);
    if (input.id === "projectMetaFilename") return mergeUniqueValues(optionsCache.filenames, [input.value]);
    return [];
  }

  function ensureMenu(input) {
    const field = input?.closest(".project-meta-field");
    if (!field) return null;
    let menu = field.querySelector(".project-meta-menu");
    if (!menu) {
      menu = document.createElement("div");
      menu.className = "project-meta-menu";
      field.appendChild(menu);
    }
    return menu;
  }

  function closeAllMenus() {
    document.querySelectorAll(".project-meta-menu").forEach((menu) => {
      menu.classList.remove("is-open");
      menu.innerHTML = "";
    });
    document.querySelectorAll(".project-meta-field").forEach((field) => {
      field.classList.remove("project-meta-field-open");
    });
  }

  function renderMenuForInput(input, { filterWithValue = true } = {}) {
    const menu = ensureMenu(input);
    const field = input?.closest(".project-meta-field");
    if (!menu || !field) return;
    const query = filterWithValue ? String(input.value || "").trim().toLowerCase() : "";
    const values = getMenuValuesForInput(input).filter((value) => {
      if (!query) return true;
      return String(value).toLowerCase().includes(query);
    });
    if (!values.length) {
      closeAllMenus();
      return;
    }
    menu.innerHTML = "";
    values.forEach((value) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "project-meta-menu-option";
      option.textContent = value;
      option.addEventListener("mousedown", (event) => {
        event.preventDefault();
        input.value = value;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        closeAllMenus();
      });
      menu.appendChild(option);
    });
    field.classList.add("project-meta-field-open");
    menu.classList.add("is-open");
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
          clients: Array.isArray(payload.options.clients) && payload.options.clients.length ? payload.options.clients : ["uncategorized"],
          projects: Array.isArray(payload.options.projects) && payload.options.projects.length ? payload.options.projects : ["uncategorized"],
          shots: Array.isArray(payload.options.shots) && payload.options.shots.length ? payload.options.shots : ["uncategorized"],
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

    [client, project, shot].forEach((input) => {
      if (!input) return;
      input.addEventListener("focus", async () => {
        await fetchOptions();
        renderMenuForInput(input, { filterWithValue: false });
      });
      input.addEventListener("click", async () => {
        await fetchOptions();
        renderMenuForInput(input, { filterWithValue: false });
      });
      input.addEventListener("input", () => {
        renderMenuForInput(input, { filterWithValue: true });
      });
      input.addEventListener("change", commit);
      input.addEventListener("blur", () => {
        window.setTimeout(() => {
          closeAllMenus();
          commit();
        }, 120);
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit();
          closeAllMenus();
        }
        if (event.key === "Escape") {
          closeAllMenus();
        }
      });
    });

    if (filename) {
      filename.addEventListener("change", commit);
      filename.addEventListener("blur", commit);
      filename.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit();
        }
      });
    }

    document.addEventListener("pointerdown", (event) => {
      if (!event.target.closest(".project-meta-field")) {
        closeAllMenus();
      }
    });
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
