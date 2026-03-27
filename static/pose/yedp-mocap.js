const TARGET_ORIGIN = window.location.origin;
const MODULE_BASE_URL = new URL(".", import.meta.url);
const VENDOR_BASE = new URL("./vendor/", MODULE_BASE_URL).href;

const PRESETS = {
  body_only: {
    label: "Body Only",
    tasks: ["pose"],
  },
  face_body: {
    label: "Face + Body",
    tasks: ["face", "pose"],
  },
  full: {
    label: "Full Holistic",
    tasks: ["face", "pose", "hand"],
  },
};

const TASKS = {
  face: {
    file: "face_landmarker.task",
    className: "FaceLandmarker",
    options: {
      numFaces: 1,
      minFaceDetectionConfidence: 0.55,
      minFacePresenceConfidence: 0.55,
      minTrackingConfidence: 0.55,
      outputFaceBlendshapes: false,
    },
  },
  pose: {
    file: "pose_landmarker_full.task",
    className: "PoseLandmarker",
    options: {
      numPoses: 1,
      minPoseDetectionConfidence: 0.65,
      minPosePresenceConfidence: 0.65,
      minTrackingConfidence: 0.65,
    },
  },
  hand: {
    file: "hand_landmarker.task",
    className: "HandLandmarker",
    options: {
      numHands: 2,
      minHandDetectionConfidence: 0.6,
      minHandPresenceConfidence: 0.6,
      minTrackingConfidence: 0.6,
    },
  },
};

const state = {
  visionLib: null,
  filesetResolver: null,
  landmarkers: {},
  landmarkerMode: "",
  sourceMode: "parent",
  parentSource: null,
  parentSourceUrl: "",
  uploadSourceUrl: "",
  videoSourceUrl: "",
  webcamStream: null,
  liveMode: false,
  liveAnimationFrame: 0,
  lastVideoTime: -1,
  detection: null,
  renderedRect: null,
  busy: false,
};

const canvas = document.getElementById("mocapCanvas");
const ctx = canvas.getContext("2d");
const emptyState = document.getElementById("mocapEmpty");
const statusEl = document.getElementById("mocapStatus");
const sourceBadgeEl = document.getElementById("mocapSourceBadge");
const presetBadgeEl = document.getElementById("mocapPresetBadge");
const frameStatEl = document.getElementById("mocapFrameStat");
const outputStatEl = document.getElementById("mocapOutputStat");

const sourceModeSelect = document.getElementById("mocapSourceMode");
const presetSelect = document.getElementById("mocapPresetSelect");
const detectBtn = document.getElementById("mocapDetectBtn");
const captureBtn = document.getElementById("mocapCaptureBtn");
const useAsRefBtn = document.getElementById("mocapUseAsRefBtn");
const saveBtn = document.getElementById("mocapSaveBtn");

const parentPanel = document.getElementById("mocapParentPanel");
const uploadPanel = document.getElementById("mocapUploadPanel");
const videoPanel = document.getElementById("mocapVideoPanel");
const webcamPanel = document.getElementById("mocapWebcamPanel");

const chooseImageBtn = document.getElementById("mocapChooseImageBtn");
const chooseVideoBtn = document.getElementById("mocapChooseVideoBtn");
const toggleVideoBtn = document.getElementById("mocapToggleVideoBtn");
const startCameraBtn = document.getElementById("mocapStartCameraBtn");
const stopCameraBtn = document.getElementById("mocapStopCameraBtn");
const toggleLiveBtn = document.getElementById("mocapToggleLiveBtn");

const uploadNameEl = document.getElementById("mocapUploadName");
const videoNameEl = document.getElementById("mocapVideoName");
const webcamNameEl = document.getElementById("mocapWebcamName");

const imageInput = document.getElementById("mocapImageInput");
const videoInput = document.getElementById("mocapVideoInput");
const imageEl = document.getElementById("mocapImageSource");
const videoEl = document.getElementById("mocapVideoSource");

function postToParent(type, payload = {}) {
  window.parent.postMessage({
    channel: "pixteur-pose-embed",
    type,
    tool: "yedp_mocap",
    payload,
  }, TARGET_ORIGIN);
}

function setStatus(text) {
  if (statusEl) statusEl.textContent = text || "";
}

function presetConfig() {
  return PRESETS[presetSelect?.value] || PRESETS.body_only;
}

function currentMediaSource() {
  if (state.sourceMode === "parent" || state.sourceMode === "upload") {
    if (imageEl.getAttribute("src")) return { type: "image", element: imageEl };
    return null;
  }
  if (state.sourceMode === "video" || state.sourceMode === "webcam") {
    if (videoEl.srcObject || videoEl.getAttribute("src")) return { type: "video", element: videoEl };
    return null;
  }
  return null;
}

function updatePanelVisibility() {
  parentPanel.hidden = state.sourceMode !== "parent";
  uploadPanel.hidden = state.sourceMode !== "upload";
  videoPanel.hidden = state.sourceMode !== "video";
  webcamPanel.hidden = state.sourceMode !== "webcam";
  captureBtn.disabled = !state.detection;
}

function updateStatusChips() {
  const preset = presetConfig();
  if (presetBadgeEl) presetBadgeEl.textContent = preset.label;
  if (sourceBadgeEl) {
    if (state.sourceMode === "parent" && state.parentSource) {
      sourceBadgeEl.textContent = `Current Image - ${(state.parentSource.image?.width || 0)} x ${(state.parentSource.image?.height || 0)}`;
    } else if (state.sourceMode === "upload" && imageEl.getAttribute("src")) {
      sourceBadgeEl.textContent = "Uploaded Image";
    } else if (state.sourceMode === "video" && videoEl.getAttribute("src")) {
      sourceBadgeEl.textContent = "Video File";
    } else if (state.sourceMode === "webcam" && state.webcamStream) {
      sourceBadgeEl.textContent = "Webcam";
    } else {
      sourceBadgeEl.textContent = "Waiting for source";
    }
  }
  if (frameStatEl) {
    const media = currentMediaSource();
    if (!media) {
      frameStatEl.textContent = "No frame";
    } else if (media.type === "image") {
      frameStatEl.textContent = `${imageEl.naturalWidth || 0} x ${imageEl.naturalHeight || 0}`;
    } else {
      frameStatEl.textContent = `${videoEl.videoWidth || 0} x ${videoEl.videoHeight || 0}`;
    }
  }
  if (outputStatEl) {
    outputStatEl.textContent = state.detection ? "Pose captured" : "No pose captured";
  }
}

function stopLiveLoop() {
  state.liveMode = false;
  state.lastVideoTime = -1;
  if (state.liveAnimationFrame) {
    cancelAnimationFrame(state.liveAnimationFrame);
    state.liveAnimationFrame = 0;
  }
  if (toggleLiveBtn) toggleLiveBtn.textContent = "Analyze Live";
  if (toggleVideoBtn) toggleVideoBtn.textContent = "Analyze Live";
}

function cleanupSourceUrls() {
  if (state.uploadSourceUrl) {
    URL.revokeObjectURL(state.uploadSourceUrl);
    state.uploadSourceUrl = "";
  }
  if (state.videoSourceUrl) {
    URL.revokeObjectURL(state.videoSourceUrl);
    state.videoSourceUrl = "";
  }
}

async function ensureVisionLoaded() {
  if (state.visionLib && state.filesetResolver) return;
  const moduleUrl = new URL("./vendor/tasks_vision.js", MODULE_BASE_URL).href;
  state.visionLib = await import(moduleUrl);
  state.filesetResolver = await state.visionLib.FilesetResolver.forVisionTasks(VENDOR_BASE);
}

async function ensureLandmarkers() {
  await ensureVisionLoaded();
  const preset = presetConfig();
  const needed = new Set(preset.tasks);
  const runningMode = state.sourceMode === "video" || state.sourceMode === "webcam" ? "VIDEO" : "IMAGE";
  const mustRecreate = state.landmarkerMode !== runningMode;
  const nextLandmarkers = {};

  for (const key of preset.tasks) {
    if (!mustRecreate && state.landmarkers[key]) {
      nextLandmarkers[key] = state.landmarkers[key];
      continue;
    }
    const task = TASKS[key];
    const klass = state.visionLib[task.className];
    const modelUrl = new URL(`./vendor/${task.file}`, MODULE_BASE_URL).href;
    nextLandmarkers[key] = await klass.createFromOptions(state.filesetResolver, {
      baseOptions: {
        modelAssetPath: modelUrl,
        delegate: "CPU",
      },
      runningMode,
      ...task.options,
    });
  }

  Object.entries(state.landmarkers).forEach(([key, landmarker]) => {
    if ((!needed.has(key) || mustRecreate) && landmarker?.close) {
      try { landmarker.close(); } catch (e) {}
    }
  });
  state.landmarkers = nextLandmarkers;
  state.landmarkerMode = runningMode;
}

function fittedRect(sourceWidth, sourceHeight, targetWidth, targetHeight) {
  const scale = Math.min(targetWidth / sourceWidth, targetHeight / sourceHeight) || 1;
  const width = sourceWidth * scale;
  const height = sourceHeight * scale;
  return {
    x: (targetWidth - width) / 2,
    y: (targetHeight - height) / 2,
    width,
    height,
  };
}

function resizeCanvas() {
  const bounds = canvas.parentElement.getBoundingClientRect();
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(bounds.width * ratio));
  canvas.height = Math.max(1, Math.round(bounds.height * ratio));
  canvas.style.width = `${bounds.width}px`;
  canvas.style.height = `${bounds.height}px`;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(ratio, ratio);
}

function currentFrameSize() {
  const media = currentMediaSource();
  if (!media) return { width: 0, height: 0 };
  if (media.type === "image") {
    return {
      width: imageEl.naturalWidth || 0,
      height: imageEl.naturalHeight || 0,
    };
  }
  return {
    width: videoEl.videoWidth || 0,
    height: videoEl.videoHeight || 0,
  };
}

function mapLandmark(landmark, rect) {
  return {
    x: rect.x + landmark.x * rect.width,
    y: rect.y + landmark.y * rect.height,
  };
}

function drawConnections(targetCtx, landmarks, connections, rect, color, width) {
  if (!Array.isArray(landmarks) || !Array.isArray(connections)) return;
  targetCtx.strokeStyle = color;
  targetCtx.lineWidth = width;
  targetCtx.lineCap = "round";
  connections.forEach((pair) => {
    const start = landmarks[pair.start];
    const end = landmarks[pair.end];
    if (!start || !end) return;
    const p1 = mapLandmark(start, rect);
    const p2 = mapLandmark(end, rect);
    targetCtx.beginPath();
    targetCtx.moveTo(p1.x, p1.y);
    targetCtx.lineTo(p2.x, p2.y);
    targetCtx.stroke();
  });
}

function drawLandmarks(targetCtx, landmarks, rect, color, radius) {
  if (!Array.isArray(landmarks)) return;
  targetCtx.fillStyle = color;
  landmarks.forEach((landmark) => {
    const p = mapLandmark(landmark, rect);
    targetCtx.beginPath();
    targetCtx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    targetCtx.fill();
  });
}

function drawDetectionToContext(targetCtx, rect) {
  if (!state.detection) return;
  const vision = state.visionLib;
  const faceLineWidth = Math.max(1, rect.width / 480);
  const poseLineWidth = Math.max(2, rect.width / 180);
  const handLineWidth = Math.max(1.5, rect.width / 240);
  const pointRadius = Math.max(2, rect.width / 180);

  if (state.detection.face?.length && vision?.FaceLandmarker) {
    drawConnections(targetCtx, state.detection.face, vision.FaceLandmarker.FACE_LANDMARKS_TESSELATION || [], rect, "rgba(255,255,255,0.15)", faceLineWidth);
    drawConnections(targetCtx, state.detection.face, vision.FaceLandmarker.FACE_LANDMARKS_RIGHT_EYE || [], rect, "rgba(255,80,80,0.88)", faceLineWidth);
    drawConnections(targetCtx, state.detection.face, vision.FaceLandmarker.FACE_LANDMARKS_LEFT_EYE || [], rect, "rgba(80,255,120,0.88)", faceLineWidth);
    drawConnections(targetCtx, state.detection.face, vision.FaceLandmarker.FACE_LANDMARKS_LIPS || [], rect, "rgba(255,240,160,0.88)", faceLineWidth);
  }

  if (state.detection.pose?.length && vision?.PoseLandmarker) {
    drawConnections(targetCtx, state.detection.pose, vision.PoseLandmarker.POSE_CONNECTIONS || [], rect, "rgba(0,255,120,0.94)", poseLineWidth);
    drawLandmarks(targetCtx, state.detection.pose, rect, "rgba(255,255,255,0.95)", pointRadius);
  }

  if (Array.isArray(state.detection.hands) && vision?.HandLandmarker) {
    state.detection.hands.forEach((hand) => {
      if (!hand?.length) return;
      drawConnections(targetCtx, hand, vision.HandLandmarker.HAND_CONNECTIONS || [], rect, "rgba(0,210,255,0.92)", handLineWidth);
      drawLandmarks(targetCtx, hand, rect, "rgba(0,210,255,0.98)", pointRadius * 0.85);
    });
  }
}

function renderCanvas(options = {}) {
  const bounds = canvas.parentElement.getBoundingClientRect();
  const sourceSize = currentFrameSize();
  ctx.clearRect(0, 0, bounds.width, bounds.height);
  ctx.fillStyle = "#050506";
  ctx.fillRect(0, 0, bounds.width, bounds.height);

  if (!sourceSize.width || !sourceSize.height) {
    if (emptyState) emptyState.style.display = "flex";
    updateStatusChips();
    return;
  }

  if (emptyState) emptyState.style.display = "none";
  const rect = fittedRect(sourceSize.width, sourceSize.height, bounds.width, bounds.height);
  state.renderedRect = rect;

  if (!options.hideSource) {
    ctx.save();
    ctx.globalAlpha = 0.72;
    const media = currentMediaSource();
    if (media?.type === "image") {
      ctx.drawImage(imageEl, rect.x, rect.y, rect.width, rect.height);
    } else if (media?.type === "video") {
      ctx.drawImage(videoEl, rect.x, rect.y, rect.width, rect.height);
    }
    ctx.restore();
  }

  drawDetectionToContext(ctx, rect);
  updateStatusChips();
}

function normalizeLandmarkArray(items) {
  if (!Array.isArray(items)) return [];
  return items.map((point) => ({
    x: Number(point?.x) || 0,
    y: Number(point?.y) || 0,
    z: Number(point?.z) || 0,
    visibility: Number(point?.visibility) || 0,
  }));
}

async function detectCurrentFrame() {
  const media = currentMediaSource();
  if (!media) {
    setStatus("Load or select a source first.");
    return;
  }
  try {
    state.busy = true;
    detectBtn.disabled = true;
    await ensureLandmarkers();
    const output = {
      pose: [],
      poseWorld: [],
      face: [],
      hands: [],
      preset: presetSelect.value,
    };
    if (state.landmarkers.pose) {
      const poseResult = media.type === "video"
        ? state.landmarkers.pose.detectForVideo(media.element, performance.now())
        : state.landmarkers.pose.detect(media.element);
      output.pose = normalizeLandmarkArray((poseResult?.landmarks || [])[0] || []);
      output.poseWorld = normalizeLandmarkArray((poseResult?.worldLandmarks || [])[0] || []);
    }
    if (state.landmarkers.face) {
      const faceResult = media.type === "video"
        ? state.landmarkers.face.detectForVideo(media.element, performance.now())
        : state.landmarkers.face.detect(media.element);
      output.face = normalizeLandmarkArray((faceResult?.faceLandmarks || [])[0] || []);
    }
    if (state.landmarkers.hand) {
      const handResult = media.type === "video"
        ? state.landmarkers.hand.detectForVideo(media.element, performance.now())
        : state.landmarkers.hand.detect(media.element);
      output.hands = Array.isArray(handResult?.landmarks)
        ? handResult.landmarks.map((hand) => normalizeLandmarkArray(hand))
        : [];
    }
    state.detection = output;
    renderCanvas();
    const size = currentFrameSize();
    setStatus(`Pose captured at ${size.width} x ${size.height}.`);
  } catch (error) {
    setStatus(`Detection failed: ${error.message}`);
  } finally {
    state.busy = false;
    detectBtn.disabled = false;
  }
}

async function liveDetectLoop() {
  if (!state.liveMode) return;
  const media = currentMediaSource();
  if (!media || media.type !== "video") {
    stopLiveLoop();
    return;
  }
  if (videoEl.readyState >= 2 && videoEl.currentTime !== state.lastVideoTime) {
    state.lastVideoTime = videoEl.currentTime;
    await detectCurrentFrame();
  }
  state.liveAnimationFrame = requestAnimationFrame(liveDetectLoop);
}

async function toggleLiveAnalysis() {
  if (state.liveMode) {
    stopLiveLoop();
    setStatus("Live analysis stopped.");
    return;
  }
  const media = currentMediaSource();
  if (!media || media.type !== "video") {
    setStatus("Choose a video or start the webcam first.");
    return;
  }
  state.liveMode = true;
  state.lastVideoTime = -1;
  if (state.sourceMode === "video" && toggleVideoBtn) toggleVideoBtn.textContent = "Stop Live";
  if (state.sourceMode === "webcam" && toggleLiveBtn) toggleLiveBtn.textContent = "Stop Live";
  try {
    await videoEl.play();
  } catch (error) {}
  liveDetectLoop();
  setStatus("Live mocap analysis is running.");
}

async function loadParentSource(payload) {
  state.parentSource = payload || null;
  if (state.sourceMode !== "parent") {
    updateStatusChips();
    return;
  }
  const image = payload?.image || {};
  const src = image.data
    ? `data:${image.mimeType || "image/png"};base64,${image.data}`
    : (image.url || "");
  if (!src) {
    imageEl.removeAttribute("src");
    state.detection = null;
    renderCanvas();
    setStatus("Waiting for a current image from Pixteur AI Studio.");
    return;
  }
  state.parentSourceUrl = src;
  imageEl.onload = async () => {
    renderCanvas();
    await detectCurrentFrame();
  };
  imageEl.src = src;
}

function normalizeJsonPayload(payload) {
  return {
    preset: presetSelect.value,
    source_mode: state.sourceMode,
    width: currentFrameSize().width,
    height: currentFrameSize().height,
    pose: state.detection?.pose || [],
    poseWorld: state.detection?.poseWorld || [],
    face: state.detection?.face || [],
    hands: state.detection?.hands || [],
  };
}

function renderRigToPng() {
  const sourceSize = currentFrameSize();
  const width = Math.max(64, sourceSize.width || 512);
  const height = Math.max(64, sourceSize.height || 512);
  const exportCanvas = document.createElement("canvas");
  exportCanvas.width = width;
  exportCanvas.height = height;
  const exportCtx = exportCanvas.getContext("2d");
  exportCtx.fillStyle = "#050506";
  exportCtx.fillRect(0, 0, width, height);
  drawDetectionToContext(exportCtx, { x: 0, y: 0, width, height });
  return exportCanvas.toDataURL("image/png");
}

function emitExport(action) {
  if (!state.detection) {
    setStatus("Run a pose capture first.");
    return;
  }
  const pngDataUrl = renderRigToPng();
  const imageData = pngDataUrl.split(",")[1] || "";
  const sourceSize = currentFrameSize();
  postToParent("pose-export", {
    action,
    imageData,
    mimeType: "image/png",
    filename: `yedp_mocap_${Date.now()}.png`,
    jsonData: normalizeJsonPayload(),
    meta: {
      label: "Yedp MoCap",
      source_kind: state.sourceMode,
      width: sourceSize.width,
      height: sourceSize.height,
      preset: presetSelect.value,
      kind: "mocap_rig",
    },
  });
}

async function startCamera() {
  if (state.webcamStream) return;
  try {
    state.webcamStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    videoEl.srcObject = state.webcamStream;
    videoEl.removeAttribute("src");
    await videoEl.play();
    if (webcamNameEl) webcamNameEl.textContent = "Camera live";
    if (stopCameraBtn) stopCameraBtn.disabled = false;
    if (toggleLiveBtn) toggleLiveBtn.disabled = false;
    renderCanvas();
    setStatus("Webcam started.");
  } catch (error) {
    setStatus(`Could not start the webcam: ${error.message}`);
  }
}

function stopCamera() {
  stopLiveLoop();
  if (state.webcamStream) {
    state.webcamStream.getTracks().forEach((track) => track.stop());
    state.webcamStream = null;
  }
  videoEl.pause();
  videoEl.srcObject = null;
  if (webcamNameEl) webcamNameEl.textContent = "Camera is off";
  if (stopCameraBtn) stopCameraBtn.disabled = true;
  if (toggleLiveBtn) toggleLiveBtn.disabled = true;
  if (state.sourceMode === "webcam") {
    state.detection = null;
    renderCanvas();
  }
}

function captureCurrentFrame() {
  if (!state.detection) {
    setStatus("Capture or detect a pose first.");
    return;
  }
  renderCanvas();
  setStatus("Current mocap frame captured.");
}

function bindEvents() {
  sourceModeSelect?.addEventListener("change", async () => {
    state.sourceMode = sourceModeSelect.value || "parent";
    stopLiveLoop();
    updatePanelVisibility();
    updateStatusChips();
    renderCanvas();
    if (state.sourceMode === "parent") {
      await loadParentSource(state.parentSource);
    } else if (state.sourceMode === "upload" && imageEl.getAttribute("src")) {
      await detectCurrentFrame();
    } else {
      state.detection = null;
      renderCanvas();
    }
  });

  presetSelect?.addEventListener("change", async () => {
    updateStatusChips();
    if (currentMediaSource()) {
      Object.values(state.landmarkers).forEach((landmarker) => {
        try { landmarker.close?.(); } catch (e) {}
      });
      state.landmarkers = {};
      await detectCurrentFrame();
    }
  });

  chooseImageBtn?.addEventListener("click", () => imageInput.click());
  chooseVideoBtn?.addEventListener("click", () => videoInput.click());
  detectBtn?.addEventListener("click", detectCurrentFrame);
  captureBtn?.addEventListener("click", captureCurrentFrame);
  useAsRefBtn?.addEventListener("click", () => emitExport("add_ref"));
  saveBtn?.addEventListener("click", () => emitExport("save"));
  toggleVideoBtn?.addEventListener("click", toggleLiveAnalysis);
  toggleLiveBtn?.addEventListener("click", toggleLiveAnalysis);
  startCameraBtn?.addEventListener("click", startCamera);
  stopCameraBtn?.addEventListener("click", stopCamera);

  imageInput?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (state.uploadSourceUrl) {
      URL.revokeObjectURL(state.uploadSourceUrl);
      state.uploadSourceUrl = "";
    }
    state.uploadSourceUrl = URL.createObjectURL(file);
    imageEl.onload = async () => {
      renderCanvas();
      await detectCurrentFrame();
    };
    imageEl.src = state.uploadSourceUrl;
    if (uploadNameEl) uploadNameEl.textContent = file.name;
    event.target.value = "";
  });

  videoInput?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    stopLiveLoop();
    if (state.videoSourceUrl) {
      URL.revokeObjectURL(state.videoSourceUrl);
      state.videoSourceUrl = "";
    }
    state.videoSourceUrl = URL.createObjectURL(file);
    videoEl.srcObject = null;
    videoEl.src = state.videoSourceUrl;
    videoEl.onloadeddata = async () => {
      if (toggleVideoBtn) toggleVideoBtn.disabled = false;
      if (videoNameEl) videoNameEl.textContent = file.name;
      renderCanvas();
      await detectCurrentFrame();
    };
    event.target.value = "";
  });

  videoEl.addEventListener("play", () => {
    renderCanvas();
  });

  window.addEventListener("message", (event) => {
    if (event.origin !== TARGET_ORIGIN) return;
    const data = event.data || {};
    if (data.channel !== "pixteur-pose-embed") return;
    if (data.type === "set-source") {
      loadParentSource(data.payload || {});
    }
  });

  const resizeObserver = new ResizeObserver(() => {
    resizeCanvas();
    renderCanvas();
  });
  resizeObserver.observe(canvas.parentElement);

  window.addEventListener("beforeunload", () => {
    stopLiveLoop();
    stopCamera();
    cleanupSourceUrls();
  });
}

function init() {
  resizeCanvas();
  updatePanelVisibility();
  updateStatusChips();
  renderCanvas();
  bindEvents();
  postToParent("tool-ready", {
    label: "Yedp MoCap",
    acceptsParentSource: true,
  });
  postToParent("request-source");
}

init();
