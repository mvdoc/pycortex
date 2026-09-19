# Tractography visualization — handoff (2026-09-19)

Companion to [tractography-visualization.md](tractography-visualization.md) (the approved plan). Read both before continuing.

## Where things are

- **Branch / worktree:** `claude/tractography-visualization-64d4a0`, checked out at
  `~/repos/pycortex/.claude/worktrees/tractography-visualization-64d4a0`
  (`~/repos/pycortex` resolves to `~/Documents/04Archive/repos/pycortex`; its main checkout is on `main`, which has none of this work).
- **Nothing pushed, no PRs opened.** The user must approve before any PR. Tree was clean at handoff.
- **Commits on top of `main` (0a6bba57), oldest first:**
  1. `775598d6` DOC plan
  2. `a8629fd8` PR1 — `cortex.Tractogram` dataview + TRX loading
  3. `92c813ad` PR3 — `surface_opacity` slider (`surfaceAlpha` uniform)
  4. `ba894cb6` PR2 — streamline rendering (`/tract/` transport, `tractogram.js`)
  5. `ffe17950` review follow-ups (subjects, vectorized colors, `select` groups, Range header, uint32 guard)
  6. `4bb9ed42` / `dc46e753` plan status updates
  7. `1f9ff4f7` trx `(N,1)` dpv fix + browser-test plumbing (JSProxy properties, `n_vertices`)
  8. `59d9e220` + `3aa25d6d` translucent tracts stay under the surface (`renderDepth = 1e6`; r69 walks the transparent list backwards)
  9. `00bc5a50` per-group (bundle) visibility: 4th `groups` uint32 buffer, `groups: {name: [start, stop]}` metadata, `setGroupVisible/showAllGroups/hideAllGroups/groupNames`, `n_segments`
  10. `9708aff1` tract controls moved from dat.gui to a `#tracts` HTML panel under the dataset box (user request: tracts are data)
  11. `bc1dc686` panel controls request a redraw
  12. `d4a0184d` + `59267ec7` PR4 docs: `docs/tractography.rst` (linked from `docs/index.rst`),
      gallery example `examples/tractography/plot_tractogram.py`, a `tracts` visual-regression
      suite, `save_3d_views` accepting a `Dataset`, and the AGENTS.md lines

## What works (verified)

- Python: `cortex.Tractogram(points, offsets, subject, dpv=, dps=, groups=, color=, alpha=, linewidth=)`, `Tractogram.from_trx(path_or_TrxFile, subject, xfm=None)`, `from_streamlines`, `select/get_group/subsample`, `vertex_colors()` (orientation | (r,g,b) | `"dpv:<name>"`/`"dps:<name>"` via cmap), `groups_wire()`, `to_json()`. HDF5 persistence intentionally `NotImplementedError`.
- Viewer: `cortex.webgl.show(cortex.Dataset(overlay=Vertex, af=tract))` (a tractogram alone raises: the viewer needs a Volume/Vertex to boot). Streamlines render as `THREE.Line(LinePieces)` with Uint16/Uint32 index (duplicated-vertex fallback without `OES_element_index_uint`); hidden while the surface is inflated/flat (via the surface `"mix"` event). `make_static` writes `tracts/{name}_{points,offsets,colors,groups}.bin`. `JSMixer.addData` can push tractograms into a running viewer.
- `surface_opacity` slider (surface folder) makes the cortex translucent; tracts render underneath consistently at any tract opacity.
- `#tracts` panel: per tractogram visibility checkbox, opacity slider, collapsible body; if the TRX has groups, `all`/`none` links + one checkbox per bundle with streamline count, `(ungrouped)` pseudo-group last. Inputs stay in sync with Python calls (`handle.tracts.<name>.setGroupVisible(name, False)` etc. through the JSProxy).
- Docs: `docs/tractography.rst` (linked from the user-guide toctree) and the gallery example `examples/tractography/plot_tractogram.py` — three synthetic bundles (transverse/longitudinal/vertical) on S1 over grayscale curvature, rendered headlessly at `surface_opacity=0.35` from an oblique left camera, in orientation and `dpv` coloring. The example's picture was checked in the live viewer, not only in code.
- The static path is browser-verified too, not just byte-counted: `make_static` output served over plain HTTP loads the four `.bin` buffers, reports 7200 points / 7080 segments / 3 groups, renders identically to the live viewer and logs no console errors.
- `cortex.export.save_3d_views` now accepts a `Dataset` (a tractogram never arrives as a lone dataview); the subject is resolved by `_view_subject` and all views must share one.
- Tests: `cortex/tests/test_tractogram.py` (30), `test_webgl_tractogram.py` (8 + 1 headless), `test_surface_opacity.py` (1 + 1 headless), `test_visual_regression.py::test_visual_comparison_tracts` (2, references not yet generated). All passed on the user's machine including headless, as of commit `1f9ff4f7`; the headless tests were **not** re-run by the user after commits 9–12 (they were updated to use `n_segments` and `groupNames()[0]`; the `element` assertion uses `dir()`).

## Remaining work

1. **Generate the tract reference images — blocking.** Until this is done,
   `test_visual_comparison_tracts[opaque]` and `[translucent]` *fail* (a missing
   reference fails rather than skips, by design), so the suite is red on any
   machine with Chromium, CI included. Needs a browser and git LFS:
   `REGENERATE_REFERENCE_IMAGES=1 pytest cortex/tests/test_visual_regression.py -k tracts`
   writes `cortex/tests/reference_images/tracts/webgl_tracts_{opaque,translucent}.webp`.
   Look at them before committing; they are LFS-tracked like the rest.
2. **Re-run the browser tests** after commits 9-12:
   `pytest cortex/tests/test_tractogram.py cortex/tests/test_webgl_tractogram.py cortex/tests/test_surface_opacity.py cortex/tests/test_visual_regression.py`.
   The non-browser suite (157 passed, 60 skipped) is green in the sandbox as of `59267ec7`;
   codespell and mypy are not installed there, so both still need a local run.
3. Real-data check: pyAFQ HCP 16-bundle atlas (MNI, figshare id 11921522, md5 `b071f3e851f21ba1749c02fc6beb3118`) on the user's `fsaverage` (MNI305 ≈ MNI152, see plan). Needs a user-approved download; convert `.trk`→`.trx` with trx-python (groups = bundle names). User's own pyAFQ TRX is 200 GB — unusable for now.
4. When approved: cherry-pick onto branches off `main`: PR1 (`a8629fd8` + relevant fixes), PR3 (`92c813ad`), PR2 stacked on PR1 (`ba894cb6` and later). Commits 5/7 mix PR1 and PR2 fixes — split by file when cherry-picking, or open PR1+PR2 as one stacked pair.

Follow-ups deliberately deferred (all named as limits in `docs/tractography.rst`): HDF5 persistence, `htmlembed` inlining of `.bin`, thick lines/tubes, per-bundle colors from `dpg`, endpoint projection to a `Vertex` for quickflat.

## Environment quirks (Claude sandbox)

- `uv` panics and pypi.org/gh are proxy-blocked inside the sandbox. Use `PY=/Users/mvdoc/bin/miniconda3/envs/pycortex/bin/python` (3.11) with `PYTHONPATH=.pydeps`; `.pydeps/` holds trx-python (installed by the user, git-excluded). Compiled `cortex/*cpython-311*.so` were copied from the main checkout.
- Tests: `PYTHONPATH=.pydeps $PY -m pytest -p no:cacheprovider -o addopts="" <files>` (no pytest-cov/mypy in that env). Headless Chromium cannot launch in the sandbox → the user runs browser tests. Running tests rewrites `filestore/db/S1/overlays.svg`; always `git checkout -- filestore/db/S1/overlays.svg`.
- Live viewer for visual checks: `.claude/launch.json` entries `tracts-viewer` (port 8914, `.claude/launch_tracts.py`: Vertex + 300 synthetic streamlines in groups `even`/`odd` on S1), `opacity-viewer` (8913) and `example-viewer` (8915, `.claude/launch_example.py`, which runs the gallery example's data-building half and shows it). `.claude/launch.json` itself is not writable from the sandbox shell — edit it with the Edit tool. Start via the browser pane's `preview_start`; restart the server after Python/template changes; static JS/CSS are cached by the browser — `fetch(url, {cache:'reload'})` then reload. Browser-tool click coordinates are in the screenshot frame, not CSS px (scale by `800/window.innerWidth`).
- Three.js r69 gotchas learned: `addAttribute`, `THREE.LinePieces`, attributes upload as `gl.FLOAT` only, `renderObjects` iterates the (ascending-z-sorted) transparent list backwards, `svgoverlay.js` depth pass uses `scene.overrideMaterial` (objects opt out with `userData.skipOverrideMaterial`), `dataset.js` is CRLF (never edit).

## Open decisions for the user

- Whether to keep the `(ungrouped)` pseudo-group naming and "visible iff in ≥1 visible group" semantics.
- Panel styling details (currently mirrors the dataset box); collapsed by default above 8 bundles.
- PR granularity given the mixed fix commits (see remaining work item 6).
