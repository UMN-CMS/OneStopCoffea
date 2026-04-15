import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import hist

from analyzer.postprocessing.style import Styler

from analyzer.utils.structure_tools import commonDict
from .annotations import labelAxis
from .common import PlotConfiguration
from .utils import saveFigVariants
import mplhep


def plot2D(
    histogram,
    common_meta,
    output_path,
    style_set,
    normalize=False,
    plot_configuration=None,
    color_scale="linear",
    cbar_title="Events",
):
    pc = plot_configuration or PlotConfiguration()

    fig, ax = plt.subplots(layout="constrained")
    item, meta = histogram
    h = item.histogram

    if normalize:
        h = h / np.sum(h.values())
    if color_scale == "log":
        objs = mplhep.hist2dplot(h, norm=matplotlib.colors.LogNorm(), ax=ax)
    else:
        objs = mplhep.hist2dplot(h, ax=ax)
    cbar = objs.cbar
    if cbar_title and cbar is not None:
        cbar.set_label(cbar_title)

    labelAxis(ax, "y", h.axes)

    labelAxis(ax, "x", h.axes)
    saveFigVariants(
        fig,
        ax,
        output_path,
        [meta],
        plot_configuration=pc,
        metadata=common_meta,
        extra_text=f"{common_meta['sample_name']}\n{common_meta['pipeline']}",
        text_color="white",
    )
    plt.close(fig)


def getContour(HH, val):
    total = np.sum(HH)
    for i in range(round(np.max(HH))):
        if np.sum(HH[HH > i]) < (total * val):
            return i
    return None


def plot2DSigBkg(
    bkg_hist,
    sig_hist,
    output_path,
    style_set,
    normalize=False,
    plot_configuration=None,
    color_scale="linear",
    override_axis_labels=None,
):
    override_axis_labels = override_axis_labels or {}
    pc = plot_configuration or PlotConfiguration()
    styler = Styler(style_set)
    fig, ax = plt.subplots(layout="constrained")
    styler.getStyle(bkg_hist.sector_parameters)
    h = bkg_hist.histogram

    if normalize:
        h = h / np.sum(h.values())
    if color_scale == "log":
        h.plot2d(norm=matplotlib.colors.LogNorm(), ax=ax)
    else:
        h.plot2d(ax=ax)

    from scipy.ndimage import gaussian_filter

    sh = sig_hist.histogram

    HH, xe, ye = sh.to_numpy()
    HH = gaussian_filter(HH, 1.2)
    midpoints = (xe[1:] + xe[:-1]) / 2, (ye[1:] + ye[:-1]) / 2
    grid = HH.transpose()
    h.sum().value

    sig_style = sig_hist.style or styler.getStyle(sig_hist.sector_parameters)

    ax.contour(
        *midpoints,
        grid,
        [getContour(HH, x) for x in (0.75, 0.5, 0.25)],
        linewidths=sig_style.line_width,
        colors=[sig_style.color],
    )

    labelAxis(ax, "y", h.axes, label=override_axis_labels.get("y"))
    labelAxis(ax, "x", h.axes, label=override_axis_labels.get("x"))

    proxy = [
        plt.Line2D(
            [0],
            [0],
            lw=sig_style.line_width or 2,
            color=sig_style.color,
            label=sig_hist.title,
        )
    ]

    sp = bkg_hist.sector_parameters
    ax.legend(
        handles=proxy,
        facecolor=pc.legend_fill_color,
        framealpha=pc.legend_fill_alpha,
        frameon=True,
    )

    common_meta = commonDict([bkg_hist.metadata, sig_hist.metadata], key=lambda x: x)
    saveFigVariants(
        fig,
        ax,
        output_path,
        [sp],
        plot_configuration=pc,
        metadata=common_meta,
        extra_text=f"{sp.region_name}\n{bkg_hist.title}",
        text_color="white",
    )
    plt.close(fig)

def plot2DPulls(
    hist1, 
    hist2,
    output_path,
    style_set,
    normalize=False,
    plot_configuration=None,
    color_scale="linear",
    override_axis_labels=None
    ):


    override_axis_labels = override_axis_labels or {}
    pc = plot_configuration or PlotConfiguration()
    fig, ax = plt.subplots(layout="constrained")
    item1, meta1 = hist1
    item2, meta2 = hist2
    h1 = item1.histogram
    h2 = item2.histogram

    if normalize:
        h1 = h1 / np.sum(h1.values())
        h2 = h2 / np.sum(h2.values())

    pulls = (h2.values()-h1.values())/np.sqrt(h2.variances())
    pulls_hist = hist.Hist(*h1.axes)
    pulls_hist[...] = pulls

    if color_scale == "log":
        pulls_hist.plot2d(norm=matplotlib.colors.LogNorm(), ax=ax)
    else:
        pulls_hist.plot2d(ax=ax, norm=matplotlib.colors.TwoSlopeNorm(vmin=-10,vmax=10,vcenter=0), cmap='RdYlGn')

    common_meta = commonDict([meta1, meta2], key=lambda x: x)
    #breakpoint() 
    addCMSBits(
        ax,
        [common_meta],
        extra_text=f"{common_meta["pipeline"]}\n{common_meta["dataset_name"]}\nNormalized Pulls\n(Norm Plus-Norm Minus)/Norm Plus_Unc",
        text_color="black",
        plot_configuration=pc,
    )

    common_meta = commonDict([meta1, meta2], key=lambda x: x)
    saveFig(fig, output_path, metadata=common_meta, extension=pc.image_type)
    plt.close(fig) 

