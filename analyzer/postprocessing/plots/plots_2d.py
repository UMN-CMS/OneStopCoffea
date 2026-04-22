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

    with np.errstate(divide='ignore', invalid='ignore'):
        pulls = (h2.values()-h1.values())/np.sqrt(h2.variances()+h1.variances())
        pulls_hist = hist.Hist(*h1.axes)
        pulls_hist[...] = pulls

    if color_scale == "log":
        pulls_hist.plot2d(norm=matplotlib.colors.LogNorm(), ax=ax)
    else:
        pulls_hist.plot2d(ax=ax, norm=matplotlib.colors.TwoSlopeNorm(vmin=-5,vmax=5,vcenter=0), cmap='bwr')

    common_meta = commonDict([meta1, meta2], key=lambda x: x)
    import re 
    dataset_name_numbers = re.findall(r'\d+', common_meta["dataset_name"])
    #breakpoint() 
    addCMSBits(
        ax,
        [common_meta],
        extra_text=f"{common_meta["pipeline"]}\n{dataset_name_numbers[-2]}_{dataset_name_numbers[-1]}\nNormalized Pulls\n(Norm Plus-Norm Minus)\n/Sqrt(Var_Sum)",
        text_color="black",
        plot_configuration=pc,
    )

    common_meta = commonDict([meta1, meta2], key=lambda x: x)
    saveFig(fig, output_path, metadata=common_meta, extension=pc.image_type)
    plt.close(fig)

def plotEffRatio(
    num_hists, 
    den_hists,
    output_path,
    style_set,
    plot_configuration=None,
    color_scale="linear",
    override_axis_labels=None,
): 
    import re
    import mplhep as hep
    plt.style.use(hep.style.CMS)
    override_axis_labels = override_axis_labels or {}
    pc = plot_configuration or PlotConfiguration()
    fig, ax = plt.subplots(layout="constrained")
    ratio_eff = [] 
    x_values = [] 
    y_values = []
    metas = []
    labels = []
    for num_hist in num_hists:
        for den_hist in den_hists:
            num_item, num_meta = num_hist 
            den_item, den_meta = den_hist
            den_name_numbers = re.findall(r'\d+', den_meta["dataset_name"])
            num_name_numbers = re.findall(r'\d+', num_meta["dataset_name"])
            if num_name_numbers != den_name_numbers:
                continue
            else:
                metas.append(num_meta)
                x_values.append(int(num_name_numbers[-2]))
                y_values.append(int(num_name_numbers[-1]))

            num = num_item.cutflow           
            den = den_item.cutflow
            with np.errstate(divide='ignore', invalid='ignore'):
                n_init = num["initial"]
                d_init = den["initial"]
                n_count = list(num.values())[-1]
                d_count = list(den.values())[-1]
                num_eff = n_count/n_init 
                den_eff = d_count/d_init
                ratio = num_eff/den_eff

                #Ratio of two binomials is approx log normal, calculate two sided error in 'log space' and then go back.
                log_val = np.log(ratio)
                log_sf_var = (1/n_count) + (1/d_count) - (1/n_init) - (1/d_init)
                log_sf_sigma = np.sqrt(max(0, log_sf_var))
                upper = np.exp(log_val + log_sf_sigma)
                lower = np.exp(log_val - log_sf_sigma)
                err_up = upper - ratio
                err_down = ratio - lower

                ratio_eff.append(num_eff/den_eff)
                label_str = f"${ratio:.3g}^{{+{err_up:.3g}}}_{{-{err_down:.3g}}}$"
                labels.append(label_str)

    viridis_clipped = matplotlib.colors.LinearSegmentedColormap.from_list(
        'viridis_clipped', matplotlib.cm.viridis(np.linspace(0.2, 1.0, 256))
    ) 
    sc = ax.scatter(
        x_values, 
        y_values, 
        c=ratio_eff, 
        cmap=viridis_clipped, 
        marker='s', 
        s=2500,
    )
    for x, y, txt in zip(x_values, y_values, labels):
        ax.text(x, y, txt, ha='center', va='center', fontsize=10, color='black')

    ax.set_xlabel(override_axis_labels.get("x", "$m_{{\\mathit{{\\tilde t_1}}}}$"))
    ax.set_ylabel(override_axis_labels.get("y", "$m_{{\\mathit{{\\tilde \\chi^{{\\pm}}_1}}}}$"))
    fig.colorbar(sc, ax=ax, label="MinusEff/PlusEff")
    addCMSBits(
        ax,
        [num_meta],
        extra_text=f"{num_meta["pipeline"]}",
        text_color="black",
        plot_configuration=pc,
    )

    saveFig(fig, output_path, metadata=num_meta, extension=pc.image_type)
    plt.close(fig)