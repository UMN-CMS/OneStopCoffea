from __future__ import annotations

import functools as ft
from typing import Literal
import itertools as it
from .style import Style
from analyzer.utils.structure_tools import (
    commonDict,
    dictToDot,
    dotFormat,
)
from rich import print
from itertools import zip_longest
from .processors import BasePostprocessor
from analyzer.utils.querying import deepLookup
from attrs import define, field
import numpy as np
import enum
import awkward as ak
import matplotlib.pyplot as plt
from .grouping import GroupBuilder

def efficiency(passing, all_events):
    return passing/all_events

def makeEfficiency2D(
    total_group,
    passing_group,
    common_metadata,
    output_path,
    xy_pattern,
    xyz_labels,
    style,
    plot_configuration=None,
    **kwargs,
):
    from .plots.annotations import addCMSBits
    from .plots.common import PlotConfiguration
    from .plots.utils import saveFig

    passing_lookup = {}
    effs = []
    print(type(passing_group))
    for item, meta in passing_group:
        #print(deepLookup(meta, xy_pattern[0]), deepLookup(meta, xy_pattern[1]))
        xy = (float(deepLookup(meta, xy_pattern[0])), float(deepLookup(meta, xy_pattern[1])))
        passing_lookup[xy] = item.histogram
    print(len(passing_group))
    for item, meta in total_group:
        xy = (float(deepLookup(meta, xy_pattern[0])), float(deepLookup(meta, xy_pattern[1])))
        total_h = item.histogram
        pass_h = passing_lookup.get(xy)
        if pass_h is None:
            print(f"Warning: no matching passing hists for {xy}, skipping")
            continue
        eff = efficiency(pass_h.values().sum(), total_h.values().sum())
        effs.append((*xy, eff))

    #print(xy_pattern[0])
    #print(len(passing_lookup))
    effs = ak.Array(effs)
    xs = effs["0"]
    ys = effs["1"]
    eff_values = effs["2"]
    
    print("xs:", xs)
    print("ys:", ys)
    print("eff_values:", eff_values)
    fig, ax = plt.subplots()

    xvals = np.unique(ak.to_numpy(xs))
    yvals = np.unique(ak.to_numpy(ys))

    xs_np = ak.to_numpy(xs)
    ys_np = ak.to_numpy(ys)
    eff_values_np = ak.to_numpy(eff_values)

# Create empty grid
    Z = np.full((len(yvals), len(xvals)), np.nan)

# Fill existing (x, y) bins
    for x, y, eff in zip(xs_np, ys_np, eff_values_np):
        ix = np.where(xvals == x)[0][0]
        iy = np.where(yvals == y)[0][0]
        Z[iy, ix] = eff

    # Build bin edges
    dx = np.diff(xvals).mean()
    dy = np.diff(yvals).mean()

    xedges = np.concatenate(
        ([xvals[0] - dx / 2], xvals[:-1] + dx / 2, [xvals[-1] + dx / 2])
    )
    yedges = np.concatenate(
        ([yvals[0] - dy / 2], yvals[:-1] + dy / 2, [yvals[-1] + dy / 2])
    )

    pcm = ax.pcolormesh(
        xedges,
        yedges,
        Z,
        cmap="viridis",
        shading="auto",
        vmin=0,
        vmax=1,
    )

    fig.colorbar(pcm, ax=ax, label="Efficiency")

    pc = plot_configuration or PlotConfiguration()

    addCMSBits(
        ax,
        [x.metadata for x in total_group],
        plot_configuration=pc,
    )

    ax.set_xlabel(xyz_labels[0])
    ax.set_ylabel(xyz_labels[1])

    saveFig(fig, output_path, extension=pc.image_type)


    plt.close(fig)
@define
class Efficiency2D(BasePostprocessor):
    output_name: str
    group_xy_patterns: tuple[list[str], list[str]]
    xyz_labels: tuple[str, str, str]
    style: Style = field(factory=Style)


    def getRunFuncs(self, Group, prefix=None):
        passing_group = []
        total_group = []
        for dataset_group in Group["name_grouping"]:
            passing_group.extend(dataset_group["passing"])
            total_group.extend(dataset_group["total"])

        common_meta = commonDict(it.chain(total_group, passing_group))
        output_path = dotFormat(
        self.output_name, **dict(dictToDot(common_meta)), prefix=prefix
    )
        pc = self.plot_configuration.makeFormatted(common_meta)

        yield ft.partial(
            makeEfficiency2D,
            total_group=total_group,
            passing_group=passing_group,
            common_metadata=common_meta,
            output_path=output_path,
            xy_pattern=self.group_xy_patterns,
            xyz_labels=self.xyz_labels,
            plot_configuration=pc,
            style=self.style,
        )
