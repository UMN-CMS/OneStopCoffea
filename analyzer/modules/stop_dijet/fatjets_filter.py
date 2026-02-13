from analyzer.core.analysis_modules import AnalyzerModule
import re

from analyzer.core.columns import addSelection
from analyzer.core.columns import Column
from analyzer.utils.structure_tools import flatten
from analyzer.core.analysis_modules import ParameterSpec, ModuleParameterSpec
import awkward as ak
import itertools as it
from attrs import define, field, evolve


import correctionlib
import logging

from analyzer.modules.common.axis import RegularAxis
from analyzer.modules.common.histogram_builder import makeHistogram

from analyzer.core.analysis_modules import (
    MetadataExpr,
    MetadataAnd,
    IsRun,
    IsSampleType,
)

logger = logging.getLogger("analyzer.modules")

@define
class JetFilterBoosted(AnalyzerModule):
    """
    This analyzer filters an input jet collection according to transverse
    momentum and pseudorapidity requirements, with optional jet ID and pileup
    ID selections. The resulting filtered jet collection is written to a new
    output column.

    Parameters
    ----------
    input_col : Column
        Column containing the input jet collection to be filtered.
    output_col : Column
        Column where the filtered jet collection will be stored.
    """

    input_col: Column
    output_col: Column

    def run(self, columns, params):
        metadata = columns.metadata
        jets = columns[self.input_col]
        sorted_jets = jets[ak.argsort(jets["msoftdrop"], ascending=False)]

        tau32_mask = (sorted_jets["tau3"]/sorted_jets["tau2"]) < 0.7
        good_jets = sorted_jets[tau32_mask]

        columns[self.output_col] = good_jets
        return columns, []

    def inputs(self, metadata):
        return [self.input_col]

    def outputs(self, metadata):
        return [self.output_col]
    
@define
class DijetMaker(AnalyzerModule):

    input_col_1: Column
    input_col_2: Column
    output_col: Column

    def run(self, columns, params):
       columns[self.output_col] = ak.pad_none(columns[self.input_col_1], 1, axis=1)[:,0] + ak.pad_none(columns[self.input_col_2], 1, axis=1)[:,0]
       return columns, []
    
    def inputs(self, metadata):
        return [self.input_col_1, self.input_col_2]

    def outputs(self, metadata):
        return [self.output_col]
    

@define
class DijetHistograms(AnalyzerModule):
    r"""
    Parameters
    ----------
    prefix : str
        Prefix used for naming the generated histograms.
    input_col : Column
        Column containing the dijet collection.
    """

    prefix: str
    input_col_b_jet: Column
    input_col_fat_jet: Column

    def run(self, columns, params):
        fatjets = columns[self.input_col_fat_jet][:,0]
        b_jets = columns[self.input_col_b_jet][:,0]
        dijets = fatjets + b_jets
        jet_dict = {
            "AK8": fatjets,
            "AK4": b_jets
        }
        ret = []

        ret.append(
            makeHistogram(
                f"{self.prefix}_pt",
                columns,
                RegularAxis(100, 0, 5000, f"$p_{{T, jj}}$", unit="GeV"),
                dijets.pt,
                description=f"$p_T$ of dijet",
            )
        )
        ret.append(
            makeHistogram(
                f"{self.prefix}_eta",
                columns,
                RegularAxis(20, -4, 4, f"$\\eta_{{jj}}$"),
                dijets.eta,
                description=f"$\\eta$ of dijet",
            )
        )
        ret.append(
            makeHistogram(
                f"{self.prefix}_deta",
                columns,
                RegularAxis(20, 0, 4, f"$|\\Delta\\eta_{{jj}}|$"),
                abs(fatjets.eta-b_jets.eta),
            )
        )
        ret.append(
            makeHistogram(
                f"{self.prefix}_phi",
                columns,
                RegularAxis(20, -4, 4, f"$\\phi_{{jj}}$"),
                dijets.phi,
                description=f"$\\phi$ of dijet",
            )
        )
        ret.append(
            makeHistogram(
                f"{self.prefix}_dphi",
                columns,
                RegularAxis(20, 0, 4, f"$|\\Delta\\phi_{{jj}}|$"),
                abs(fatjets.phi-b_jets.phi),
            )
        )
        ret.append(
            makeHistogram(
                f"{self.prefix}_dr",
                columns,
                RegularAxis(50, 0, 5, f"$\\Delta R_{{jj}}$"),
                fatjets.delta_r(b_jets),
            )
        )
        ret.append(
            makeHistogram(
                f"{self.prefix}_mass",
                columns,
                RegularAxis(100, 0, 5000, f"$m_{{jj}}$", unit="GeV"),
                dijets.mass,
                description=f"Mass of dijet",
            )
        )

        ret.append(
            makeHistogram(
                f"AK8_mass_sd",
                columns,
                RegularAxis(100, 0, 1000, f"AK8 $m_{{SD}}$", unit="GeV"),
                fatjets.msoftdrop,
                description=f"Softdrop Mass of AK8 jet",
            )
        )

        ret.append(
            makeHistogram(
                f"AK8_tau32",
                columns,
                RegularAxis(50, 0, 1, f"AK8 $\\tau_{{32}}$"),
                fatjets["tau3"]/fatjets["tau2"],
                description=f"Tau3/Tau2 of AK8 jet",
            )
        )

        for i in [1,2,3]:
            ret.append(
                makeHistogram(
                    f"AK8_tau{i}",
                    columns,
                    RegularAxis(50, 0, 1, f"AK8 $\\tau_{i}$"),
                    fatjets[f"tau{i}"],
                    description=f"Tau{i} of AK8 jet",
                )
            )

        ret.append(
            makeHistogram(
                f"AK8_v_AK4_pt",
                columns,
                [RegularAxis(125, 0, 3000, f"AK8 $p_T$", unit="GeV"),
                RegularAxis(125, 0, 3000, f"AK4 $p_T$", unit="GeV")],
                [fatjets.pt, b_jets.pt],
                description=f"$p_T$ plane of AK8 and AK4 jets",
            )
        )
        ret.append(
            makeHistogram(
                f"dijet_vs_AK8_mass_softdrop",
                columns,
                [RegularAxis(100, 0, 5000, f"$m_{{jj}}$", unit="GeV"),
                RegularAxis(100, 0, 1000, f"AK8 $m_{{SD}}$", unit="GeV")],
                [dijets.mass, fatjets.msoftdrop],
                description=f"Mass plane",
            )
        )
        for key, value in jet_dict.items(): 
            ret.append(
                makeHistogram(
                    f"{key}_pt",
                    columns,
                    RegularAxis(125, 0, 3000, f"{key} $p_T$", unit="GeV"),
                    value.pt,
                    description=f"$p_T$ of {key} jet",
                )
            )
            ret.append(
                makeHistogram(
                    f"{key}_eta",
                    columns,
                    RegularAxis(20, -4, 4, f"${key} \\eta$"),
                    value.eta,
                    description=f"$\\eta$ of {key} jet",
                )
            )
            ret.append(
                makeHistogram(
                    f"{key}_phi",
                    columns,
                    RegularAxis(20, -4, 4, f"{key} $\\phi$"),
                    value.phi,
                    description=f"$\\phi$ of {key} jet",
                )
            )
            ret.append(
                makeHistogram(
                    f"{key}_mass",
                    columns,
                    RegularAxis(100, 0, 1000, f"{key} m", unit="GeV"),
                    value.mass,
                    description=f"Mass of {key} jet",
                )
            )

        return columns, ret

    def outputs(self, metadata):
        return []

    def inputs(self, metadata):
        return [self.input_col_b_jet, self.input_col_fat_jet]