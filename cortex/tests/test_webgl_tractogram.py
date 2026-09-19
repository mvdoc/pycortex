"""Tests for shipping a `cortex.Tractogram` to the WebGL viewer.

Covers the python transport (`cortex.webgl.data.Package`, `make_static`) and,
when playwright + Chromium are available, the javascript side
(`resources/js/tractogram.js`).
"""

import os

import numpy as np
import pytest

import cortex
from cortex.webgl.data import Package

from .testing_utils import has_playwright
from .test_tractogram import _make_tractogram

subj = "S1"


def _vertex():
    """A small Vertex dataview for S1, to accompany the tractogram."""
    pts, _ = cortex.db.get_surf(subj, "fiducial", merge=True)
    return cortex.Vertex(np.zeros(pts.shape[0], dtype=np.float32), subj)


def _dataset():
    tract = _make_tractogram(n_streamlines=8, n_points=15)
    return cortex.Dataset(overlay=_vertex(), af=tract), tract


# ---------------------------------------------------------------------------
# Package: wire format
# ---------------------------------------------------------------------------


def test_package_tract_metadata_and_buffers():
    ds, tract = _dataset()
    pkg = Package(ds)

    meta = pkg.metadata()
    assert "af" in meta["tracts"]
    tmeta = meta["tracts"]["af"]

    assert tmeta["subject"] == subj
    assert tmeta["n_points"] == tract.n_points
    assert tmeta["n_streamlines"] == tract.n_streamlines
    assert tmeta["alpha"] == tract.alpha
    assert tmeta["linewidth"] == tract.linewidth
    assert tmeta["visible"] is True
    assert set(tmeta["urls"]) == {"points", "offsets", "colors"}
    assert tmeta["urls"]["points"] == "/tract/af/points/"

    bufs = pkg.tracts["af"]
    n, m = tract.n_points, tract.n_streamlines
    assert len(bufs["points"]) == 12 * n
    assert len(bufs["offsets"]) == 4 * (m + 1)
    assert len(bufs["colors"]) == 3 * n

    # The buffers must round-trip as little-endian arrays of the right dtype.
    points = np.frombuffer(bufs["points"], dtype="<f4").reshape(-1, 3)
    assert np.allclose(points, tract.points)
    offsets = np.frombuffer(bufs["offsets"], dtype="<u4")
    assert np.array_equal(offsets, tract.offsets)
    assert offsets[-1] == n


def test_package_keeps_tracts_out_of_views_and_data():
    """Every existing javascript path must see exactly what it saw before."""
    ds, tract = _dataset()
    pkg = Package(ds)
    meta = pkg.metadata()

    assert [view["name"] for view in meta["views"]] == ["overlay"]
    assert "af" not in meta["data"]
    assert "af" not in meta["images"]
    assert tract.name not in meta["data"]
    # ... and the tractogram is not among the BrainData that get reordered.
    assert all(not isinstance(u, cortex.Tractogram) for u in pkg.uniques)


def test_package_reorder_ignores_tracts():
    tract = _make_tractogram(n_streamlines=8, n_points=15)
    pkg = Package(cortex.Dataset(af=tract), require_brains=False)
    before = pkg.tracts["af"]["points"]
    # reorder() needs a per-subject CTM index for every BrainData it holds;
    # with only a tractogram there is nothing to reorder, so no index is
    # needed and the buffers must come out untouched.
    pkg.reorder({})
    assert pkg.tracts["af"]["points"] == before


def test_package_tractogram_only_raises():
    tract = _make_tractogram(n_streamlines=4, n_points=10)
    with pytest.raises(ValueError, match="cannot be displayed on its own"):
        Package(cortex.Dataset(af=tract))
    with pytest.raises(ValueError, match="cannot be displayed on its own"):
        Package(tract)

    # A running viewer can still be handed a tractogram alone.
    pkg = Package(cortex.Dataset(af=tract), require_brains=False)
    assert "af" in pkg.tracts


# ---------------------------------------------------------------------------
# make_static
# ---------------------------------------------------------------------------


def test_make_static_writes_tract_buffers(tmp_path):
    ds, tract = _dataset()
    outpath = str(tmp_path / "static")
    cortex.webgl.make_static(outpath, ds, recache=False)

    n, m = tract.n_points, tract.n_streamlines
    expected = {
        "af_points.bin": 12 * n,
        "af_offsets.bin": 4 * (m + 1),
        "af_colors.bin": 3 * n,
    }
    for fname, size in expected.items():
        path = os.path.join(outpath, "tracts", fname)
        assert os.path.exists(path), "%s was not written" % fname
        assert os.path.getsize(path) == size

    with open(os.path.join(outpath, "index.html")) as fp:
        html = fp.read()
    assert "tracts/af_points.bin" in html


# ---------------------------------------------------------------------------
# Headless browser
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not has_playwright, reason="playwright + Chromium not available"
)
def test_tractogram_renders_in_headless_viewer():
    ds, tract = _dataset()

    with cortex.export.headless_viewer(ds, viewer_params={}) as handle:
        # `handle` is a JSProxy rooted at window.viewer: attribute access
        # queries the live javascript object graph over the websocket.
        # The tracts load asynchronously and deliberately do not block
        # viewer.loaded, so poll until the geometry has been built
        # (Tractogram.n_points stays 0 until then).
        import time

        deadline = time.monotonic() + 30
        n_points = 0
        while time.monotonic() < deadline:
            n_points = handle.tracts.af.n_points
            if n_points:
                break
            time.sleep(0.2)

        n, m = tract.n_points, tract.n_streamlines
        assert n_points == n
        assert handle.tracts.af.n_streamlines == m
        assert handle.tracts.af.object.visible is True
        # Either the indexed geometry (one vertex per point) or the
        # duplicated-vertex fallback (two per segment).
        assert handle.tracts.af.n_vertices in (n, 2 * (n - m))
