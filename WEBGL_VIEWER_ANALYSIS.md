# PyCortex WebGL Viewer — Architecture Analysis & Improvement Roadmap

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Python-Side Data Pipeline](#2-python-side-data-pipeline)
3. [JavaScript Viewer Architecture](#3-javascript-viewer-architecture)
4. [Shader System](#4-shader-system)
5. [Speed & Optimization Opportunities](#5-speed--optimization-opportunities)
6. [UI Improvement Opportunities](#6-ui-improvement-opportunities)
7. [Multi-View Capability Analysis](#7-multi-view-capability-analysis)
8. [Key File Reference](#8-key-file-reference)

---

## 1. Architecture Overview

### End-to-End Data Flow

```
Python Input Data (numpy arrays, NIfTI, etc.)
    │
    ▼
cortex.webgl.show(data)                    [cortex/webgl/view.py:284]
    │
    ├─ dataset.normalize(data)             [cortex/dataset/__init__.py]
    │      → Dataset (dict of Dataview objects)
    │
    ├─ Package(dataset)                    [cortex/webgl/data.py:20]
    │      ├─ Extract unique BrainData objects
    │      ├─ Generate JSON metadata (subjects, colormaps, vmin/vmax, etc.)
    │      └─ Serialize image data:
    │            ├─ Volumes → mosaic() → _pack_png() → PNG bytes
    │            └─ Vertices → raw numpy binary (.npy)
    │
    ├─ utils.get_ctmpack(subject)          [cortex/utils.py:55]
    │      → CTM-compressed surface geometry + index mapping
    │
    ├─ package.reorder(ctms)               [cortex/webgl/data.py:65]
    │      → Reorder vertex data to match CTM mesh indices
    │
    └─ Tornado WebApp                      [cortex/webgl/serve.py:258]
           ├─ MixerHandler   → HTML + embedded JSON metadata
           ├─ CTMHandler     → Surface geometry (CTM binary)
           ├─ DataHandler    → Volume PNGs / vertex .npy (with HTTP Range)
           ├─ StimHandler    → Stimulus files
           ├─ PickerHandler  → Click callback events
           └─ StaticHandler  → JS/CSS/resources
                │
                ▼
        Browser (WebGL Viewer)
           ├─ Load CTM surfaces → THREE.SurfGeometry
           ├─ Load data textures (PNG → WebGL textures, .npy → vertex attributes)
           ├─ Compile GLSL shaders with preprocessor defines
           ├─ Render via THREE.js r69
           └─ Interactive controls (dat.GUI, w2ui, jQuery)
                │
                ▼
        Python client (JSProxy)            [cortex/webgl/serve.py:317]
           └─ WebSocket bridge for programmatic viewer control
```

### Technology Stack

| Layer | Technology | Version | Status |
|-------|-----------|---------|--------|
| Server | Tornado | current | OK |
| 3D Engine | THREE.js | r69 (2014) | Very outdated (current: r160+) |
| UI Controls | dat.GUI | ~2014 | Unmaintained |
| Layout | w2ui | 1.4.2 (2017) | Outdated |
| DOM | jQuery | 2.1.1 (2014) | Outdated |
| Dropdowns | Select2 | 4.0.3 | Outdated |
| Surface Compression | OpenCTM | — | Stable |
| Python↔JS | WebSocket (Tornado) | — | OK |

---

## 2. Python-Side Data Pipeline

### Dataset Hierarchy

```
Dataset (dict-like container)              [cortex/dataset/dataset.py:12]
  └─ Dataview (abstract visualization)     [cortex/dataset/views.py]
       ├─ Volume       → 3D/4D volumetric data + colormap
       ├─ Vertex       → per-vertex surface data + colormap
       ├─ VolumeRGB    → 3-channel volumetric (no colormap)
       ├─ VertexRGB    → 3-channel vertex (no colormap)
       ├─ Volume2D     → dual-channel volumetric (2D colormap)
       ├─ Vertex2D     → dual-channel vertex (2D colormap)
       └─ Multiview    → NOT IMPLEMENTED (raises NotImplementedError)
```

### Package Serialization (`cortex/webgl/data.py`)

The `Package` class serializes a `Dataset` for the browser:

- **Metadata** (JSON): view definitions (name, colormap, vmin/vmax), brain data descriptors (subject, shape, dtype), and image URL mappings.
- **Volume data**: Each 3D volume slice stack is converted to a 2D mosaic grid via `volume.mosaic()` (`cortex/volume.py:87`), then packed into RGBA PNG via `_pack_png()`. Float32 values are reinterpreted as RGBA bytes.
- **Vertex data**: Raw numpy arrays, reordered to match CTM mesh vertex indices, served as `.npy` binary.

### Surface Geometry (`cortex/utils.py:55`)

- `get_ctmpack()` generates or caches CTM-compressed surface files.
- Supports multiple surface types: fiducial, pial, white matter, inflated, flat.
- Compression methods: "raw" (uncompressed) or "mg2" (MG2 compressed, level 1-9).
- Output: JSON manifest + CTM binary files + `.npz` index mapping files.

### Static Export (`cortex/webgl/view.py:43`)

`make_static()` creates a self-contained HTML viewer by embedding all data inline, suitable for sharing without a running server.

---

## 3. JavaScript Viewer Architecture

### Class Hierarchy

```
jsplot.Axes                                [resources/js/figure.js]
  └─ jsplot.Axes3D                         [resources/js/axes3d.js]
       └─ module.Viewer (mriview)          [resources/js/mriview.js]

jsplot.Figure                              [resources/js/figure.js]
  ├─ jsplot.W2Figure (w2ui layout)
  └─ jsplot.GridFigure (table grid)
       └─ module.MultiView                 [resources/js/mriview_utils.js]
```

### Initialization Flow (`mriview.js`)

1. `Viewer` constructor calls `Axes3D.call()` for base THREE.js setup
2. HTML template injected from `$("#mriview_html")`
3. Colormap textures loaded from `<img>` elements in `.cmap` divs
4. Canvas bound: `this.canvas = $(this.object).find("#brain")`
5. THREE.js scene, camera (`PerspectiveCamera`, 45° FOV), renderer (`WebGLRenderer`) initialized
6. 3 directional lights added to camera
7. `this.loaded = $.Deferred()` manages async surface/data loading
8. CTM surfaces loaded → `THREE.SurfGeometry` created
9. Data textures loaded → shader materials compiled → rendering begins

### Render Loop (`axes3d.js:95-139`)

```javascript
schedule() {
    if (!this._scheduled) {
        this._scheduled = true;
        requestAnimationFrame(this._schedule);
    }
}

draw() {
    // Update camera controls
    // For each grid view: set viewport/scissor, render scene
    renderer.render(scene, camera);
}
```

- Single `requestAnimationFrame` at a time (no redundant renders)
- Auto-pauses when no changes detected
- Multi-view support via scissor/viewport partitioning

### Data Loading (`resources/js/datamodel.js`, `dataset.js`)

- **NParray**: Parses `.npy` files (NumPy binary format) in the browser. Supports typed arrays (Float32, Int32, Uint32, etc.). Streaming via HTTP Range requests.
- **VolumeData**: Loads mosaic-packed PNG textures, uploads to GPU as 2D textures.
- **VertexData**: Loads `.npy` vertex arrays, sets as buffer attributes.
- **DataView**: Unified view combining 1-2 datasets with colormap reference.

### Surface System (`resources/js/mriview_surface.js`, `surfload.js`)

- `THREE.BinSurfLoader` → `parseSurf()` → `THREE.SurfGeometry`
- Binary format with optional Uint16 quantization for compression
- Multiple surface morphing via `mixSurfs{i}` vertex attributes
- Smooth interpolation between surfaces (fiducial ↔ inflated ↔ flat)
- Equivolume sampling with `wmarea`/`pialarea` attributes

### Python↔JS Bridge (`resources/js/python_interface.js`, `cortex/webgl/serve.py`)

- WebSocket communication via `Websock` class
- JSON-serialized method invocation: `ws.run("module.Viewer.addData", [...])`
- `JSProxy` on Python side provides programmatic viewer control
- Enables: `viewer.setView()`, `viewer.makeMovie()`, etc.

---

## 4. Shader System

### Architecture (`resources/js/shaderlib.js` — 1,038 lines)

Shaders are dynamically constructed via string concatenation with preprocessor `#define` flags. The `Shaderlib` class builds vertex and fragment shaders based on data type and rendering options.

### Key Preprocessor Defines

| Define | Effect |
|--------|--------|
| `RGBCOLORS` | Raw RGB data instead of colormap lookup |
| `VOXLINE` | Draw voxel grid lines on surface |
| `TWOD` | 2D colormap (two input datasets) |
| `CORTSHEET` | Multi-layer cortical sheet sampling |
| `EQUIVOLUME` | Equal-volume depth sampling through cortex |
| `ROI_RENDER` | Region-of-interest overlay |
| `EXTRATEX` | Extra texture overlay |
| `HALO_RENDER` | Volume integration with halos |
| `HASFLAT` | Include flatmap surface morph target |
| `NOLIGHTS` | Disable Phong lighting |
| `SAMPLE_WORLD` | Sample in world space (vs view space) |

### Key Uniforms

**Vertex Shader:**
- `volxfm[2]` — volume-to-texture transform matrices (one per dataset)
- `mixSurfs{i}` — morph target positions (fiducial, inflated, flat, etc.)
- `mixNorms{i}` — corresponding normals
- `wmarea`, `pialarea` — white matter / pial surface areas (equivolume)
- `auxdat` — auxiliary per-vertex data (medial wall mask, curvature)

**Fragment Shader:**
- `colormap` — 1D or 2D colormap lookup texture
- `data[4]` — up to 4 mosaic data textures (2 datasets × 2 time frames for interpolation)
- `vmin[2]`, `vmax[2]` — value range per dataset
- `framemix` — time-series frame interpolation factor (0–1)
- `mosaic[2]`, `dshape[2]` — mosaic grid and slice dimensions
- `thickmix` — cortical depth (0 = white matter, 1 = pial)
- `slicexn/yn/zn`, `slicexc/yc/zc` — slice plane normals and centers

### Sampling Functions

- `trilinear_x/y(data, coord)` — trilinear interpolation in mosaic texture
- `nearest_x/y(data, coord)` — nearest-neighbor sampling
- `debug_x/y(data, coord)` — debug visualization
- `colorlut(value)` — normalize value and sample colormap texture
- `mixfunc()` — smooth surface morphing interpolation
- `edgeFactor()` — voxel wireframe via `fwidth()`

---

## 5. Speed & Optimization Opportunities

### 5.1 THREE.js Upgrade (r69 → r160+)

**Current state:** THREE.js r69 (2014) — 10+ years behind.

**Impact:**
- Missing WebGL 2.0 support (3D textures would eliminate mosaic hacking)
- No `BufferGeometry`-only path (deprecated `Geometry` still used)
- No instanced rendering, compute shaders, or modern material system
- Missing performance features: frustum culling improvements, draw call batching
- Security: no WebGL context loss recovery

**Risk:** High — shaders and geometry code depend on r69 API. The custom `SurfGeometry`, `ShaderMaterial` usage, and all uniform/attribute binding code would need updating. This is the single largest modernization effort but also the highest-impact.

**Recommendation:** Incremental upgrade through intermediate versions (r69 → r100 → r130 → r160+), testing rendering fidelity at each step. Prioritize `Geometry` → `BufferGeometry` migration first.

### 5.2 PNG-to-Binary Data Transfer

**Current state:** Volume data is packed as RGBA PNG images (`_pack_png()` in `data.py`). Float32 values are reinterpreted as RGBA bytes, compressed as PNG, then decoded in the browser.

**Impact:**
- PNG encode/decode overhead on every data load
- Lossy for edge cases (PNG filtering can corrupt float bit patterns)
- Extra CPU work on both Python and browser sides

**Recommendation:** Switch to raw binary transfer (Float32 ArrayBuffer) with optional gzip compression via HTTP Content-Encoding. This is simpler, faster, and lossless. The browser already handles `.npy` for vertex data — extend this to volumes.

### 5.3 Texture Memory & Lifecycle

**Current state:** No explicit texture disposal. Mosaic textures for all datasets are kept in GPU memory. `texture.needsUpdate = true` triggers re-upload but old textures aren't freed.

**Impact:** Memory pressure with large datasets or many time frames. GPU memory exhaustion causes silent rendering failures.

**Recommendation:** Implement LRU texture cache. Dispose textures for inactive datasets. Use `texture.dispose()` and `material.dispose()` when switching datasets.

### 5.4 Shader Recompilation

**Current state:** Shaders are rebuilt via string concatenation whenever preprocessor defines change (e.g., toggling voxel lines, switching between volume/vertex mode). Each rebuild triggers a full GLSL compile + link.

**Impact:** UI stutters when toggling rendering options. Shader compilation is one of the most expensive GPU operations.

**Recommendation:** Pre-compile common shader variants at startup. Cache compiled programs by define-set hash. Use uniform toggles instead of `#define` where possible (e.g., `uniform bool doVoxLine` instead of `#ifdef VOXLINE`).

### 5.5 Main-Thread CPU Blocking

**Current state:** Data parsing (NParray, PNG decoding) and surface loading happen on the main thread. Large datasets block the UI during loading.

**Impact:** Browser freezes during initial load and dataset switching.

**Recommendation:** Move data parsing to Web Workers. Use `OffscreenCanvas` (if available) or `createImageBitmap()` for PNG decoding. Stream large datasets with progress callbacks (partially implemented via `$.Deferred`).

### 5.6 Module Bundling

**Current state:** 15+ separate `<script>` tags loaded sequentially. No module bundler, no tree-shaking, no minification (except dat.gui).

**Impact:** Slow initial page load. No code splitting. Global namespace pollution.

**Recommendation:** Introduce a module bundler (esbuild or Rollup) for the JS resources. Convert IIFE modules to ES modules. Tree-shake unused THREE.js components. This is a prerequisite for the THREE.js upgrade (modern THREE is distributed as ES modules).

### 5.7 Morph Target Memory

**Current state:** All surface morph targets (fiducial, inflated, flat, pial, white matter) are stored as separate vertex attribute arrays. Each is a full copy of vertex positions + normals.

**Impact:** 5-6x memory usage per surface mesh. For high-resolution cortical meshes (100k+ vertices), this is significant.

**Recommendation:** Store morph targets as deltas from a base mesh. Use vertex texture fetch for morph targets (requires THREE.js upgrade for `DataTexture` attribute support). Alternatively, compute intermediate surfaces on-demand rather than storing all targets.

---

## 6. UI Improvement Opportunities

### 6.1 Library Modernization

**Current state:** dat.GUI (~2014, unmaintained), jQuery 2.1.1 (2014), w2ui 1.4.2 (2017), Select2 4.0.3.

**Recommendation:**
- Replace dat.GUI with [lil-gui](https://lil-gui.georgealways.com/) (modern, maintained, API-compatible drop-in)
- Remove jQuery dependency — modern DOM APIs (`querySelector`, `fetch`, `addEventListener`) cover all use cases
- Replace w2ui with CSS Grid/Flexbox layouts (or a lightweight alternative)
- Replace Select2 with native `<select>` + CSS styling or a framework-free dropdown

### 6.2 Dataset Switcher

**Current state:** Dataset switching via dat.GUI dropdown. No visual preview, no drag-to-reorder, no grouping.

**Recommendation:**
- Thumbnail previews for each dataset in the switcher
- Drag-and-drop reordering
- Dataset grouping by subject
- Quick-compare mode (side-by-side with linked cameras)

### 6.3 Colorbar / Legend

**Current state:** Colorbar is a static image. No interactive range adjustment. vmin/vmax only adjustable via dat.GUI sliders.

**Recommendation:**
- Interactive colorbar with drag handles for vmin/vmax
- Click-to-set-threshold on the colorbar
- Hover-to-see-value on the brain surface (already partially implemented via picker)
- Histogram overlay on colorbar showing data distribution

### 6.4 Loading Feedback

**Current state:** No loading indicator. Browser appears frozen during large data loads.

**Recommendation:**
- Progress bar for surface and data loading
- Skeleton/placeholder rendering while data loads
- Progressive rendering (show surface first, then overlay data)

### 6.5 Keyboard Shortcuts

**Current state:** Limited keyboard support. Mostly mouse-driven.

**Recommendation:**
- `←`/`→` for dataset cycling
- `Space` for play/pause (time series)
- `F` for fullscreen
- `R` for reset view
- `1-9` for preset views (lateral, medial, dorsal, ventral, etc.)
- `?` for shortcut help overlay

### 6.6 Mobile / Touch Support

**Current state:** No explicit touch handling. dat.GUI is not touch-friendly.

**Recommendation:**
- Touch events for rotation, zoom, pan (pinch-to-zoom, two-finger-rotate)
- Responsive layout for smaller screens
- Touch-friendly UI controls

### 6.7 Export / Sharing

**Current state:** Screenshot via `saveIMG()` (canvas to PNG). Movie export via `makeMovie()` (Python-side frame capture).

**Recommendation:**
- One-click screenshot with annotation options
- GIF/WebM export for animations (client-side)
- Shareable URL with embedded view state (camera position, dataset, colormap, etc.)
- Copy-to-clipboard for view state

---

## 7. Multi-View Capability Analysis

### What Already Exists

1. **`MultiView` class** (`mriview_utils.js:6`):
   - Creates a grid of independent `Viewer` instances via `jsplot.GridFigure`
   - `addData(dataviews)` distributes datasets by subject
   - Method multiplexing: calls like `setColormap()` propagate to all viewers
   - `saveIMG()` composites all views into a single canvas

2. **`setGrid(m, n, idx)`** (`axes3d.js:249`):
   - Viewport/scissor partitioning for m×n grid within a single renderer
   - Each grid cell gets independent camera aspect ratio
   - Used for split-view within a single viewer instance

3. **Python-side `layout` parameter** (`view.py`):
   - `show(data, layout=(2,2))` creates a 2×2 grid
   - Passes through to `MultiView` on the JS side

4. **Multi-subject support**:
   - `CTMHandler` serves per-subject surface geometry (`/ctm/{subject}/`)
   - Vertex data reordered per-subject using subject-specific index mappings
   - `Dataset` can contain views from different subjects

### What's Missing for Full Multi-View

1. **Simultaneous multi-volume rendering**:
   - Current shader supports at most 2 datasets (`data[4]` = 2 datasets × 2 time frames)
   - No support for overlaying 3+ volumes with independent colormaps
   - Would require: additional texture samplers, per-layer alpha blending, and UI for layer management

2. **Linked vs. independent camera controls**:
   - `MultiView` has independent cameras per viewer
   - No "linked rotation" mode (rotate one → all follow)
   - Would require: shared camera state with optional sync toggle

3. **Cross-view interaction**:
   - No crosshair synchronization between views
   - No linked cursor (hover on one view → highlight on others)
   - Would require: event bus between viewer instances

4. **`Multiview` Dataview** (Python-side):
   - `cortex/dataset/views.py:243-254` — class exists but raises `NotImplementedError`
   - Intended to be a first-class Dataview type for multi-layer visualization
   - Would need: layer ordering, per-layer opacity, blend modes

5. **Performance at scale**:
   - Each viewer in `MultiView` has its own full rendering pipeline
   - No shared geometry or texture resources between viewers
   - 4+ views would strain GPU memory and fill rate
   - Would need: shared surface geometry, instanced rendering, render-on-demand per view

### Recommended Multi-View Roadmap

**Phase 1 — Linked cameras**: Add camera sync toggle to existing `MultiView`. Propagate camera quaternion and position changes via event dispatch.

**Phase 2 — Cross-view cursor**: Add crosshair sync. When user hovers/clicks on one view, broadcast the 3D position to other views for highlighting.

**Phase 3 — Layer stack in single view**: Extend the shader to support N overlay layers with independent colormaps and alpha. This avoids the overhead of multiple full viewers.

**Phase 4 — Implement `Multiview` Dataview**: Complete the Python-side `Multiview` class to define multi-layer datasets declaratively.

---

## 8. Key File Reference

### Python

| File | Purpose |
|------|---------|
| `cortex/webgl/__init__.py` | Entry point, DocLoader for `show()` |
| `cortex/webgl/view.py` | `show()`, `make_static()`, Tornado handlers |
| `cortex/webgl/data.py` | `Package` class — data serialization |
| `cortex/webgl/serve.py` | `WebApp`, `JSProxy`, `ClientSocket` |
| `cortex/webgl/FallbackLoader.py` | Template loader with fallback paths |
| `cortex/webgl/htmlembed.py` | HTML embedding utilities |
| `cortex/dataset/dataset.py` | `Dataset` container class |
| `cortex/dataset/views.py` | `Volume`, `Vertex`, `Multiview` (stub) |
| `cortex/dataset/braindata.py` | Base `BrainData` classes |
| `cortex/dataset/viewRGB.py` | `VolumeRGB`, `VertexRGB` |
| `cortex/dataset/view2D.py` | `Volume2D`, `Vertex2D` |
| `cortex/volume.py` | `mosaic()` — 3D-to-2D grid conversion |
| `cortex/utils.py` | `get_ctmpack()` — surface geometry |

### JavaScript

| File | Lines | Purpose |
|------|-------|---------|
| `resources/js/mriview.js` | 1,347 | Main viewer class |
| `resources/js/axes3d.js` | ~300 | 3D rendering base, render loop, grid |
| `resources/js/shaderlib.js` | 1,038 | GLSL shader generation |
| `resources/js/mriview_surface.js` | 873 | Surface rendering, morphing |
| `resources/js/mriview_utils.js` | ~200 | `MultiView`, utilities |
| `resources/js/dataset.js` | ~400 | `VolumeData`, `VertexData`, `DataView` |
| `resources/js/datamodel.js` | ~300 | `NParray` — .npy parser |
| `resources/js/sliceplane.js` | ~200 | 3D slice plane visualization |
| `resources/js/figure.js` | ~250 | Figure/axes/layout abstraction |
| `resources/js/menu.js` | ~150 | Menu/GUI wrapper |
| `resources/js/surfload.js` | ~150 | Surface binary loader |
| `resources/js/surfgeometry.js` | ~100 | Custom THREE.js geometry |
| `resources/js/python_interface.js` | ~100 | WebSocket bridge to Python |
| `resources/js/LandscapeControls.js` | ~200 | Camera orbit/pan/zoom |
| `resources/js/three.js` | 34,731 | THREE.js r69 |
| `resources/js/w2ui-1.4.2.js` | 13,698 | w2ui layout framework |
| `resources/js/dat.gui.min.js` | — | dat.GUI (minified) |
