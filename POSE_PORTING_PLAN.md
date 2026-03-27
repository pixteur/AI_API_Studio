# Pose Tool Porting Plan

## Goal

Investigate whether the current Pose-mode toolchain can be bundled directly into AI API Studio without requiring ComfyUI.

The short answer is:

- `OpenPose Editor`: yes, and it is the easiest
- `Yedp MoCap`: yes, but as a browser-side bundle more than a Python rewrite
- `Yedp Action Director`: possible as an embedded web app, not realistic as a clean Python-only port

## What the upstream tools actually are

### OpenPose Editor

Upstream:

- [ComfyUI-OpenPose-Editor](https://github.com/space-nuko/ComfyUI-OpenPose-Editor)

Key finding:

- the Python side is tiny
- the real editor is browser JavaScript in `js/openpose.js` with `fabric.min.js`
- the ComfyUI node wrapper mainly exposes a string input and reloads the saved image from ComfyUI's input folder

Implication:

- this should not be "ported to Python"
- it should be embedded directly into our existing browser UI and backed by Flask routes for save/load/export

Recommendation:

- implement this as the first direct bundled pose tool inside AI API Studio

### Yedp MoCap

Upstream:

- [ComfyUI-Yedp-MoCap](https://github.com/yedp123/ComfyUI-Yedp-Mocap)

Key finding:

- the heavy lifting is already browser-side
- `web/js/yedp_webcam.js` uses MediaPipe Tasks, WASM, and browser video/webcam APIs
- the Python node mostly loads previously captured files and pose JSON from disk

Implication:

- this is not primarily a Python algorithm we can simply extract
- the right direct integration path is to bundle the MediaPipe task assets and browser UI inside this app
- Flask should receive the captured frames / pose JSON and save them in the app's own project structure

Recommendation:

- make this the second direct bundled tool after OpenPose Editor
- support:
  - webcam snapshot
  - webcam recording
  - image pose extraction
  - video frame extraction
  - OpenPose map export
  - pose JSON export

### Yedp Action Director

Upstream:

- [ComfyUI-Yedp-Action-Director](https://github.com/yedp123/ComfyUI-Yedp-Action-Director)

Key finding:

- the frontend is large and highly interactive
- it depends on a substantial WebGL / Three.js stack:
  - `three.module.js`
  - `OrbitControls`
  - `TransformControls`
  - model loaders
  - splat rendering
  - MediaPipe assets
  - custom browser UX for staging, rigs, and camera choreography
- the Python node mainly receives a baked `client_data` payload and turns it into output batches

Implication:

- a direct Python rewrite is the wrong target
- the realistic path is to embed the existing web experience or a reduced derivative of it
- the Python backend should handle persistence, project state, and render/export orchestration

Recommendation:

- do not attempt a full Python rewrite first
- if we bring it in, treat it as a self-contained browser module inside Pose mode

## Recommended architecture for AI API Studio

### Better than a full Python rewrite

Use a hybrid architecture:

- browser UI for:
  - editable pose keypoints
  - webcam/video capture
  - 3D viewport interaction
  - drag handles and visual authoring
- Python backend for:
  - file management
  - metadata
  - export formats
  - job orchestration
  - image rendering helpers
  - pose-control map generation

This matches how the upstream tools already work.

## Direct bundle roadmap

### Phase 1: Embedded OpenPose Editor

Scope:

- import or derive pose from a selected image
- edit keypoints directly inside AI API Studio
- export:
  - OpenPose PNG control map
  - pose JSON
  - transparent overlay

Difficulty:

- low to medium

### Phase 2: Embedded MoCap

Scope:

- webcam snapshot
- webcam video recording
- image pose extraction
- video file pose extraction
- OpenPose JSON + map output

Difficulty:

- medium

Notes:

- bundle the MediaPipe task files and WASM assets locally
- keep processing browser-side where possible

### Phase 3: Native Python fallback pipeline

Scope:

- non-interactive batch pose extraction for images and videos
- server-side generation of:
  - keypoint JSON
  - OpenPose map PNG
  - masks

Possible stack:

- MediaPipe Python Tasks
- OpenCV
- Pillow
- NumPy

Difficulty:

- medium

Notes:

- this is useful for automation and batch jobs
- it does not replace the interactive browser editor

### Phase 4: Embedded Action Director

Scope:

- 3D staging
- camera blocking
- action sequencing
- batch pass export

Difficulty:

- high

Notes:

- better treated as an embedded specialized browser workspace
- not a good first candidate for pure Python extraction

## Product recommendation

If the goal is "make Pose mode feel native to AI API Studio without depending on ComfyUI", the best sequence is:

1. embed OpenPose Editor directly
2. embed Yedp MoCap directly
3. add a Python batch pose backend for automation
4. only then evaluate whether Action Director should be embedded

## Conclusion

The good news is that direct integration is very realistic.

The important correction is architectural:

- do not aim for a full Python rewrite first
- aim for a bundled local pose stack with:
  - browser-side interaction
  - Python-side orchestration and persistence

That gives us the best chance of making Pose mode feel native, fast, and maintainable inside AI API Studio.
