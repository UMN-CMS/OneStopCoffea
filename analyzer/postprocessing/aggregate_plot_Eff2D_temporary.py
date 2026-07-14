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

    for item, meta in passing_group:
        pass_h = item.histogram

        xy = (
         float(deepLookup(meta, xy_pattern[0])),
         float(deepLookup(meta, xy_pattern[1])),
        )
        passing_lookup[xy] = item.histogram

    effs = []
    for item, meta in total_group:
        xy = (
            float(deepLookup(meta, xy_pattern[0])),
            float(deepLookup(meta, xy_pattern[1])),
        )
        total_h = item.histogram

        eff = (efficiency(pass_h.values(), total_h.values())
        )
        effs.append((*xy, eff))
    
    print(effs)
    effs = np.array(effs)

    fig, ax = plt.subplots()
    sc = ax.scatter(
        effs[:, 0],
        effs[:, 1],
        c=effs[:, 2],
        **style.get("scatter_z", include_type=False),
    )
    fig.colorbar(sc, ax=ax, label=xyz_labels[2])

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
        total = Group["name_grouping"][1]["total"]
        passing = Group["name_grouping"][1]["passing"]
        common_meta = commonDict(it.chain(total, passing))
        output_path = dotFormat(
            self.output_name, **dict(dictToDot(common_meta)), prefix=prefix
        )
        pc = self.plot_configuration.makeFormatted(common_meta)

        yield ft.partial(
            makeEfficiency2D,
            total_group=total,
            passing_group=passing,
            common_metadata=common_meta,
            output_path=output_path,
            xy_pattern=self.group_xy_patterns,
            xyz_labels=self.xyz_labels,
            plot_configuration=pc,
            style=self.style,
        )
