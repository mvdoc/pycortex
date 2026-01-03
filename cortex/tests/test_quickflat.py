import cortex
import numpy as np
import tempfile
import pytest

from cortex.testing_utils import has_installed

no_inkscape = not has_installed('inkscape')


@pytest.mark.skipif(no_inkscape, reason='Inkscape required')
def test_quickflat():
    tf = tempfile.NamedTemporaryFile(suffix=".png")
    view = cortex.Volume.random("S1", "fullhead", cmap="hot")
    cortex.quickflat.make_png(tf.name, view)


@pytest.mark.skipif(no_inkscape, reason='Inkscape required')
def test_colorbar_location():
    view = cortex.Volume.random("S1", "fullhead", cmap="hot")
    for colorbar_location in ['left', 'center', 'right', (0, 0.2, 0.4, 0.3)]:
        cortex.quickflat.make_figure(view, with_colorbar=True,
                                     colorbar_location=colorbar_location)

    with pytest.raises(ValueError):
        cortex.quickflat.make_figure(view, with_colorbar=True,
                                     colorbar_location='unknown_location')


def test_colorbar_placement_with_subplot():
    """Test that colorbar is placed within subplot bounds when axis is passed."""
    import matplotlib.pyplot as plt

    # Create a figure with 1x2 subplots
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    vol1 = cortex.Volume.random("S1", "fullhead", cmap="hot", vmin=0, vmax=1)
    vol2 = cortex.Volume.random("S1", "fullhead", cmap="viridis", vmin=0, vmax=1)

    # Plot to both subplots (with_rois=False to avoid inkscape dependency)
    cortex.quickshow(vol1, fig=axes[0], with_colorbar=True,
                     colorbar_location='center', with_rois=False)
    cortex.quickshow(vol2, fig=axes[1], with_colorbar=True,
                     colorbar_location='center', with_rois=False)

    # Get bounds of subplots and colorbars
    all_axes = fig.get_axes()
    # Should have 4 axes: 2 subplots + 2 colorbars
    assert len(all_axes) == 4, f"Expected 4 axes, got {len(all_axes)}"

    left_subplot_bounds = axes[0].get_position().bounds
    right_subplot_bounds = axes[1].get_position().bounds
    cb1_bounds = all_axes[2].get_position().bounds
    cb2_bounds = all_axes[3].get_position().bounds

    # Verify colorbar 1 is within left subplot horizontal bounds
    assert cb1_bounds[0] >= left_subplot_bounds[0] - 0.001, \
        "Colorbar 1 left edge is outside left subplot"
    assert cb1_bounds[0] + cb1_bounds[2] <= left_subplot_bounds[0] + left_subplot_bounds[2] + 0.001, \
        "Colorbar 1 right edge is outside left subplot"

    # Verify colorbar 2 is within right subplot horizontal bounds
    assert cb2_bounds[0] >= right_subplot_bounds[0] - 0.001, \
        "Colorbar 2 left edge is outside right subplot"
    assert cb2_bounds[0] + cb2_bounds[2] <= right_subplot_bounds[0] + right_subplot_bounds[2] + 0.001, \
        "Colorbar 2 right edge is outside right subplot"

    plt.close(fig)


@pytest.mark.skipif(no_inkscape, reason='Inkscape required')
@pytest.mark.parametrize("type_", ["thick", "thin"])
@pytest.mark.parametrize("nanmean", [True, False])
def test_make_flatmap_image_nanmean(type_, nanmean):
    mask = cortex.db.get_mask("S1", "fullhead", type=type_)
    data = np.ones(mask.sum())
    # set 50% of the values in the dataset to NaN
    data[np.random.rand(*data.shape) > 0.5] = np.nan
    vol = cortex.Volume(data, "S1", "fullhead", vmin=0, vmax=1)
    img, extents = cortex.quickflat.utils.make_flatmap_image(
        vol, nanmean=nanmean)
    # assert that the nanmean only returns NaNs and 1s
    assert np.nanmin(img) == 1
