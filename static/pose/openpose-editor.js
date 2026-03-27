const TARGET_ORIGIN = window.location.origin;

const CONNECT_KEYPOINTS = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [1, 5], [5, 6], [6, 7], [1, 8],
  [8, 9], [9, 10], [1, 11], [11, 12],
  [12, 13], [14, 0], [14, 16], [15, 0],
  [15, 17],
];

const CONNECT_COLOR = [
  [0, 0, 255],
  [255, 0, 0],
  [255, 170, 0],
  [255, 255, 0],
  [255, 85, 0],
  [170, 255, 0],
  [85, 255, 0],
  [0, 255, 0],
  [0, 255, 85],
  [0, 255, 170],
  [0, 255, 255],
  [0, 170, 255],
  [0, 85, 255],
  [85, 0, 255],
  [170, 0, 255],
  [255, 0, 255],
  [255, 0, 170],
  [255, 0, 85],
];

const DEFAULT_KEYPOINTS = [
  [241, 77], [241, 120], [191, 118], [177, 183],
  [163, 252], [298, 118], [317, 182], [332, 245],
  [225, 241], [213, 359], [215, 454], [270, 240],
  [282, 360], [286, 456], [232, 59], [253, 60],
  [225, 70], [260, 72],
];

const state = {
  people: [],
  source: null,
  sourceImage: null,
  canvasWidth: 512,
  canvasHeight: 512,
  fitScale: 1,
  fitOffsetX: 0,
  fitOffsetY: 0,
  viewScale: 1,
  panX: 0,
  panY: 0,
  dragging: null,
  isPanning: false,
  spaceHeld: false,
  lastPointerX: 0,
  lastPointerY: 0,
};

const canvas = document.getElementById("openposeCanvas");
const ctx = canvas.getContext("2d");
const emptyState = document.getElementById("openposeEmpty");
const statusEl = document.getElementById("openposeStatus");
const sourceBadgeEl = document.getElementById("openposeSourceBadge");
const canvasBadgeEl = document.getElementById("openposeCanvasBadge");
const peopleStatEl = document.getElementById("openposePeopleStat");
const zoomStatEl = document.getElementById("openposeZoomStat");
const jsonInput = document.getElementById("openposeJsonInput");

function postToParent(type, payload = {}) {
  window.parent.postMessage({
    channel: "pixteur-pose-embed",
    type,
    tool: "openpose_editor",
    payload,
  }, TARGET_ORIGIN);
}

function setStatus(text) {
  if (statusEl) statusEl.textContent = text || "";
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function getSourceDimensions() {
  const width = Math.max(64, Math.round(state.source?.image?.width || state.sourceImage?.naturalWidth || 512));
  const height = Math.max(64, Math.round(state.source?.image?.height || state.sourceImage?.naturalHeight || 512));
  return { width, height };
}

function updateFitMetrics() {
  const stage = canvas.parentElement;
  const bounds = stage.getBoundingClientRect();
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(bounds.width * ratio));
  canvas.height = Math.max(1, Math.round(bounds.height * ratio));
  canvas.style.width = `${bounds.width}px`;
  canvas.style.height = `${bounds.height}px`;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(ratio, ratio);

  const { width, height } = getSourceDimensions();
  state.canvasWidth = width;
  state.canvasHeight = height;
  const fitScale = Math.min(bounds.width / width, bounds.height / height) || 1;
  state.fitScale = fitScale;
  state.fitOffsetX = (bounds.width - width * fitScale) / 2;
  state.fitOffsetY = (bounds.height - height * fitScale) / 2;
  if (canvasBadgeEl) canvasBadgeEl.textContent = `${width} x ${height}`;
}

function getScreenTransform() {
  return {
    scale: state.fitScale * state.viewScale,
    offsetX: state.fitOffsetX + state.panX,
    offsetY: state.fitOffsetY + state.panY,
  };
}

function imageToScreen(point) {
  const tf = getScreenTransform();
  return {
    x: tf.offsetX + point.x * tf.scale,
    y: tf.offsetY + point.y * tf.scale,
  };
}

function screenToImage(x, y) {
  const tf = getScreenTransform();
  return {
    x: (x - tf.offsetX) / tf.scale,
    y: (y - tf.offsetY) / tf.scale,
  };
}

function createDefaultPose(offsetIndex = 0) {
  const { width, height } = getSourceDimensions();
  const scale = Math.min(width / 512, height / 512) * 0.82;
  const span = width * 0.12;
  const offsetX = (width - 512 * scale) / 2 + offsetIndex * span;
  const offsetY = (height - 512 * scale) / 2 + height * 0.04;
  return DEFAULT_KEYPOINTS.map(([x, y]) => ({
    x: offsetX + x * scale,
    y: offsetY + y * scale,
  }));
}

function setDefaultPeople() {
  state.people = [createDefaultPose(0)];
}

function fitView() {
  state.viewScale = 1;
  state.panX = 0;
  state.panY = 0;
  render();
}

function updateStats() {
  if (peopleStatEl) {
    peopleStatEl.textContent = `${state.people.length} ${state.people.length === 1 ? "person" : "people"}`;
  }
  if (zoomStatEl) {
    zoomStatEl.textContent = `${Math.round(state.viewScale * 100)}%`;
  }
}

function drawBackground(stageWidth, stageHeight) {
  ctx.clearRect(0, 0, stageWidth, stageHeight);
  ctx.fillStyle = "#050506";
  ctx.fillRect(0, 0, stageWidth, stageHeight);
  if (!state.sourceImage) return;
  const tf = getScreenTransform();
  ctx.save();
  ctx.globalAlpha = 0.48;
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(
    state.sourceImage,
    tf.offsetX,
    tf.offsetY,
    state.canvasWidth * tf.scale,
    state.canvasHeight * tf.scale,
  );
  ctx.restore();
}

function getLineWidth(scaleBoost = 1) {
  return Math.max(1.5, (Math.min(state.canvasWidth, state.canvasHeight) / 512) * 3.2 * scaleBoost);
}

function getPointRadius(scaleBoost = 1) {
  return Math.max(4, (Math.min(state.canvasWidth, state.canvasHeight) / 512) * 5.5 * scaleBoost);
}

function render() {
  const stage = canvas.parentElement.getBoundingClientRect();
  drawBackground(stage.width, stage.height);

  const lineWidth = getLineWidth();
  const pointRadius = getPointRadius();

  state.people.forEach((person) => {
    CONNECT_KEYPOINTS.forEach(([startIdx, endIdx], idx) => {
      const start = imageToScreen(person[startIdx]);
      const end = imageToScreen(person[endIdx]);
      ctx.beginPath();
      ctx.moveTo(start.x, start.y);
      ctx.lineTo(end.x, end.y);
      ctx.strokeStyle = `rgba(${CONNECT_COLOR[idx].join(",")}, 0.82)`;
      ctx.lineWidth = lineWidth;
      ctx.lineCap = "round";
      ctx.stroke();
    });

    person.forEach((point, idx) => {
      const screen = imageToScreen(point);
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, pointRadius, 0, Math.PI * 2);
      ctx.fillStyle = `rgb(${CONNECT_COLOR[idx].join(",")})`;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "rgba(0,0,0,0.72)";
      ctx.stroke();
    });
  });

  if (emptyState) {
    emptyState.style.display = state.sourceImage ? "none" : "flex";
  }
  canvas.classList.toggle("is-panning", state.spaceHeld || state.isPanning);
  updateStats();
}

function getPointerPosition(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
}

function findNearestJoint(pointerX, pointerY) {
  let best = null;
  let bestDistance = Infinity;
  const threshold = Math.max(10, getPointRadius(1.15) * 1.8);
  state.people.forEach((person, personIndex) => {
    person.forEach((point, pointIndex) => {
      const screen = imageToScreen(point);
      const distance = Math.hypot(screen.x - pointerX, screen.y - pointerY);
      if (distance < threshold && distance < bestDistance) {
        bestDistance = distance;
        best = { personIndex, pointIndex };
      }
    });
  });
  return best;
}

function zoomAt(pointerX, pointerY, zoomDelta) {
  const before = screenToImage(pointerX, pointerY);
  state.viewScale = clamp(state.viewScale * zoomDelta, 0.3, 8);
  const tf = getScreenTransform();
  const afterScreenX = tf.offsetX + before.x * tf.scale;
  const afterScreenY = tf.offsetY + before.y * tf.scale;
  state.panX += pointerX - afterScreenX;
  state.panY += pointerY - afterScreenY;
  render();
}

function serializePoseJson() {
  return {
    width: state.canvasWidth,
    height: state.canvasHeight,
    keypoints: state.people.map((person) => person.map((point) => [
      Math.round(point.x),
      Math.round(point.y),
    ])),
  };
}

function loadPoseJson(jsonPayload) {
  const payload = typeof jsonPayload === "string" ? JSON.parse(jsonPayload) : jsonPayload;
  const width = Math.max(64, Number(payload?.width) || state.canvasWidth || 512);
  const height = Math.max(64, Number(payload?.height) || state.canvasHeight || 512);
  state.canvasWidth = width;
  state.canvasHeight = height;
  const keypoints = Array.isArray(payload?.keypoints) ? payload.keypoints : [];
  const nextPeople = [];
  keypoints.forEach((group) => {
    if (!Array.isArray(group) || group.length !== 18) return;
    const normalized = group.map((entry) => ({
      x: Number(Array.isArray(entry) ? entry[0] : entry?.x) || 0,
      y: Number(Array.isArray(entry) ? entry[1] : entry?.y) || 0,
    }));
    nextPeople.push(normalized);
  });
  state.people = nextPeople.length ? nextPeople : [createDefaultPose(0)];
  render();
}

function exportPoseMapPng() {
  const outputCanvas = document.createElement("canvas");
  outputCanvas.width = state.canvasWidth;
  outputCanvas.height = state.canvasHeight;
  const outputCtx = outputCanvas.getContext("2d");
  outputCtx.fillStyle = "#000";
  outputCtx.fillRect(0, 0, outputCanvas.width, outputCanvas.height);

  const lineWidth = Math.max(3, (Math.min(outputCanvas.width, outputCanvas.height) / 512) * 4);
  const pointRadius = Math.max(5, (Math.min(outputCanvas.width, outputCanvas.height) / 512) * 6);

  state.people.forEach((person) => {
    CONNECT_KEYPOINTS.forEach(([startIdx, endIdx], idx) => {
      const start = person[startIdx];
      const end = person[endIdx];
      outputCtx.beginPath();
      outputCtx.moveTo(start.x, start.y);
      outputCtx.lineTo(end.x, end.y);
      outputCtx.strokeStyle = `rgba(${CONNECT_COLOR[idx].join(",")}, 0.84)`;
      outputCtx.lineWidth = lineWidth;
      outputCtx.lineCap = "round";
      outputCtx.stroke();
    });
    person.forEach((point, idx) => {
      outputCtx.beginPath();
      outputCtx.arc(point.x, point.y, pointRadius, 0, Math.PI * 2);
      outputCtx.fillStyle = `rgb(${CONNECT_COLOR[idx].join(",")})`;
      outputCtx.fill();
    });
  });

  return outputCanvas.toDataURL("image/png");
}

function emitExport(action) {
  const pngDataUrl = exportPoseMapPng();
  const imageData = pngDataUrl.split(",")[1] || "";
  const jsonPayload = serializePoseJson();
  const sourceName = state.source?.image?.name || state.source?.meta?.filename || "pose";
  postToParent("pose-export", {
    action,
    imageData,
    mimeType: "image/png",
    filename: `openpose_${sourceName || Date.now()}.png`,
    jsonData: jsonPayload,
    meta: {
      label: "OpenPose Editor",
      source_kind: state.source?.sourceKind || "selected_image",
      width: state.canvasWidth,
      height: state.canvasHeight,
      people: state.people.length,
      kind: "openpose_control_map",
    },
  });
}

function handleWheel(event) {
  event.preventDefault();
  const pointer = getPointerPosition(event);
  const zoomDelta = event.deltaY < 0 ? 1.1 : 1 / 1.1;
  zoomAt(pointer.x, pointer.y, zoomDelta);
}

function handlePointerDown(event) {
  const pointer = getPointerPosition(event);
  state.lastPointerX = pointer.x;
  state.lastPointerY = pointer.y;
  if (state.spaceHeld || event.button === 1) {
    state.isPanning = true;
    canvas.setPointerCapture?.(event.pointerId);
    render();
    return;
  }
  const joint = findNearestJoint(pointer.x, pointer.y);
  if (joint) {
    state.dragging = joint;
    canvas.setPointerCapture?.(event.pointerId);
  }
}

function handlePointerMove(event) {
  const pointer = getPointerPosition(event);
  if (state.isPanning) {
    state.panX += pointer.x - state.lastPointerX;
    state.panY += pointer.y - state.lastPointerY;
    state.lastPointerX = pointer.x;
    state.lastPointerY = pointer.y;
    render();
    return;
  }
  if (!state.dragging) return;
  const point = screenToImage(pointer.x, pointer.y);
  const person = state.people[state.dragging.personIndex];
  if (!person) return;
  person[state.dragging.pointIndex] = {
    x: clamp(point.x, 0, state.canvasWidth),
    y: clamp(point.y, 0, state.canvasHeight),
  };
  render();
}

function handlePointerUp(event) {
  if (state.dragging || state.isPanning) {
    canvas.releasePointerCapture?.(event.pointerId);
  }
  state.dragging = null;
  state.isPanning = false;
  render();
}

async function loadSourceImage(payload) {
  const image = payload?.image || {};
  const candidateSrc = image.data
    ? `data:${image.mimeType || "image/png"};base64,${image.data}`
    : (image.url || "");

  state.source = payload || null;
  if (!candidateSrc) {
    state.sourceImage = null;
    state.canvasWidth = Math.max(64, Number(image.width) || 512);
    state.canvasHeight = Math.max(64, Number(image.height) || 512);
    updateFitMetrics();
    setDefaultPeople();
    fitView();
    if (sourceBadgeEl) sourceBadgeEl.textContent = "Waiting for source";
    setStatus("Waiting for a pose source from Pixteur AI Studio.");
    render();
    return;
  }

  const img = new Image();
  img.decoding = "async";
  img.onload = () => {
    state.sourceImage = img;
    state.canvasWidth = Math.max(64, Number(image.width) || img.naturalWidth || 512);
    state.canvasHeight = Math.max(64, Number(image.height) || img.naturalHeight || 512);
    updateFitMetrics();
    setDefaultPeople();
    fitView();
    if (sourceBadgeEl) {
      sourceBadgeEl.textContent = `${payload.sourceKind === "selected_image" ? "History" : "Source"} - ${state.canvasWidth} x ${state.canvasHeight}`;
    }
    setStatus("Source image loaded. Drag joints to pose the skeleton.");
    render();
  };
  img.onerror = () => {
    state.sourceImage = null;
    setStatus("Could not load the pose source image.");
    render();
  };
  img.src = candidateSrc;
}

function downloadJson() {
  const payload = JSON.stringify(serializePoseJson(), null, 2);
  const blob = new Blob([payload], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `openpose_${Date.now()}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 250);
}

function bindUi() {
  document.getElementById("openposeAddBtn")?.addEventListener("click", () => {
    state.people.push(createDefaultPose(state.people.length));
    render();
    setStatus("Added a new pose skeleton.");
  });
  document.getElementById("openposeResetBtn")?.addEventListener("click", () => {
    setDefaultPeople();
    fitView();
    setStatus("Pose reset to the default skeleton.");
  });
  document.getElementById("openposeFitBtn")?.addEventListener("click", () => {
    fitView();
    setStatus("Canvas fitted to the stage.");
  });
  document.getElementById("openposeDownloadJsonBtn")?.addEventListener("click", downloadJson);
  document.getElementById("openposeLoadJsonBtn")?.addEventListener("click", () => jsonInput.click());
  document.getElementById("openposeUseAsRefBtn")?.addEventListener("click", () => emitExport("add_ref"));
  document.getElementById("openposeSaveBtn")?.addEventListener("click", () => emitExport("save"));

  jsonInput?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      loadPoseJson(text);
      setStatus("Pose JSON loaded.");
    } catch (error) {
      setStatus(`Could not load pose JSON: ${error.message}`);
    } finally {
      event.target.value = "";
    }
  });

  canvas.addEventListener("wheel", handleWheel, { passive: false });
  canvas.addEventListener("pointerdown", handlePointerDown);
  canvas.addEventListener("pointermove", handlePointerMove);
  canvas.addEventListener("pointerup", handlePointerUp);
  canvas.addEventListener("pointercancel", handlePointerUp);

  window.addEventListener("keydown", (event) => {
    if (event.code === "Space") {
      state.spaceHeld = true;
      render();
    }
  });
  window.addEventListener("keyup", (event) => {
    if (event.code === "Space") {
      state.spaceHeld = false;
      state.isPanning = false;
      render();
    }
  });

  window.addEventListener("message", (event) => {
    if (event.origin !== TARGET_ORIGIN) return;
    const data = event.data || {};
    if (data.channel !== "pixteur-pose-embed") return;
    if (data.type === "set-source") {
      loadSourceImage(data.payload || {});
    }
  });

  const resizeObserver = new ResizeObserver(() => {
    updateFitMetrics();
    render();
  });
  resizeObserver.observe(canvas.parentElement);
}

function init() {
  bindUi();
  updateFitMetrics();
  setDefaultPeople();
  render();
  postToParent("tool-ready", {
    label: "OpenPose Editor",
    acceptsParentSource: true,
  });
  postToParent("request-source");
}

init();
