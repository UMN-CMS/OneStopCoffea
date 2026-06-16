from __future__ import annotations

from pathlib import Path
import functools as ft
from typing import Literal
from .style import StyleSet
from analyzer.utils.structure_tools import (
    commonDict,
    dictToDot,
    dotFormat,
)
from .processors import BasePostprocessor
from .plots.plots_1d import plotDictAsBars
from attrs import define, field


def _getCutflow(x):
    return getattr(x, "cutflow")


@define
class PlotSelectionFlow(BasePostprocessor):
    output_name: str
    style_set: str | StyleSet = field(factory=StyleSet)
    scale: Literal["log", "linear"] = "linear"
    normalize: bool = False

    def getRunFuncs(self, group, prefix=None):
        common_meta = commonDict(group)
        output_path = dotFormat(
            self.output_name, **dict(dictToDot(common_meta)), prefix=prefix
        )
        pc = self.plot_configuration.makeFormatted(common_meta)

        yield ft.partial(
            plotDictAsBars,
            group,
            common_meta,
            output_path,
            getter=_getCutflow,
            style_set=self.style_set,
            normalize=self.normalize,
            plot_configuration=pc,
        )


@define
class CutflowTable(BasePostprocessor):
    output_name: str
    format: Literal["markdown", "csv", "latex"] = "csv"
    key: str = "{dataset_name}"
    standalone: bool = False
    highlight_rows: list[tuple[int,str]] | None  = None

    def getRunFuncs(self, group, prefix=None):
        common_meta = commonDict(group)
        output_path = dotFormat(
            self.output_name, **dict(dictToDot(common_meta)), prefix=prefix
        )

        yield ft.partial(
            makeAndSaveCutflowTable,
            group,
            common_meta,
            output_path,
            format=self.format,
            key=self.key,
            standalone=self.standalone,
            highlight_rows=self.highlight_rows
        )


def makeCutflowDf(group, key="{dataset_name}"):
    import pandas as pd

    dataset_cutflows = {}
    cut_order = None
    for selection_flow, metadata in group:
        k = dotFormat(key, **dict(dictToDot(metadata)))
        dataset_cutflows[k] = _getCutflow(selection_flow)
        if cut_order is None:
            cut_order = list(selection_flow.cuts)
        else:
            if cut_order != list(selection_flow.cuts):
                raise ValueError("Cutflows are not consistent across datasets.")
    all_data = {}
    for dataset_name, cutflow in dataset_cutflows.items():
        all_data[dataset_name, "Events"] = cutflow

    df = pd.DataFrame(all_data)
    for col in df.columns:
        df.loc[:, (col[0], "Eff. Abs.")] = (
            df.loc[:, (col[0], "Events")] / df.loc[:, (col[0], "Events")].iloc[0]
        )
        df.loc[:, (col[0], "Eff. Rel.")] = (
            df.loc[:, (col[0], "Events")] / df.loc[:, (col[0], "Events")].shift(1)
        ).fillna(1)
    df.sort_index(axis=1, level=[0, 1], ascending=[True, False], inplace=True)
    return df


STANDALONE_TOP = r"""\documentclass{standalone}
\usepackage{booktabs}
\usepackage[table,usenames,svgnames]{xcolor}
\begin{document}
"""

STANDALONE_BOTTOM = r"""
\end{document}
"""


def makeAndSaveCutflowTable(
    group,
    common_meta,
    output_path,
    format="csv",
    key="{dataset_name}",
    standalone=False,
    highlight_rows=None,
):
    import numpy as np

    highlight_rows = highlight_rows or []

    df = makeCutflowDf(group, key=key)
    output_path = Path(output_path)
    output_path.parent.mkdir(exist_ok=True, parents=True)

    s = (
        df.style.apply(
            lambda x: np.where(
                (np.arange(len(x)) % 6 > 2), "background-color: lightgray", ""
            ),
            axis=1,
        )
        .format("{:0.2f}", escape="latex")
        .format_index(escape="latex", axis=0)
        # .format_index(escape="latex",axis=1)
    )
    for row,color in highlight_rows:
        s = s.apply(
            lambda x: np.where(
                (np.arange(len(x)) == row), f"background-color: {color}", ""
            ),
            axis=0,
        )

    if format == "csv":
        df.to_csv(output_path)
    elif format == "markdown":
        s.to_markdown(output_path, convert_css=True, **kwargs)
    elif format == "latex":
        text = s.to_latex(None, convert_css=True)
        if standalone:
            text = STANDALONE_TOP + text + STANDALONE_BOTTOM

        with open(output_path, "w") as f:
            f.write(text)
