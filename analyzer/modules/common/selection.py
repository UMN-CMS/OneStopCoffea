from analyzer.core.analysis_modules import AnalyzerModule, MetadataExpr
import awkward as ak
from analyzer.core.columns import Column
from attrs import define
from analyzer.core.columns import addSelection
from analyzer.core.results import SelectionFlow


@define
class SelectOnColumns(AnalyzerModule):
    """
    Apply a selection based on one or more boolean selection columns and
    optionally save the cutflow.

    This analyzer performs an AND of the specified selection columns (or
    all default selections if none are provided) and filters the events
    accordingly. Optionally, it stores a cutflow summary for monitoring.

    Parameters
    ----------
    sel_name : str
        Name of the selection to be saved in the cutflow summary, eg
        ``selection`` or ``preselection``.
    selection_names : list of str or None, optional
        List of selection column names to use. If None, defaults to all
        selections in ``columns.pipeline_data["Selections"]`` that have not
        yet been processed.
    save_cutflow : bool, optional
        If True, stores cutflow information for monitoring, by default True.
    """

    sel_name: str
    selection_names: list[str] | None = None
    save_cutflow: bool = True

    def run(self, columns, params):

        if self.selection_names is not None:
            cuts = self.selection_names
        else:
            cuts = [
                x
                for x, y in columns.pipeline_data.get("Selections", {}).items()
                if not y
            ]
        if not cuts:
            return columns, []

        def getCol(name):
            return columns[Column(("Selection", name))]

        def andCuts(all_cuts):
            if not all_cuts:
                return ak.ones_like(cuts[0])
            ret = getCol(all_cuts[0])
            for cut in all_cuts[1:]:
                ret = ret & getCol(cut)
            return ret


        for s in columns.pipeline_data.get("Selections", {}):
            columns.pipeline_data["Selections"][s] = True

        initial = ak.num(columns.events, axis=0)

        ret = columns[Column("Selection") + cuts[0]]
        cutflow = {"initial": initial, cuts[0]: ak.count_nonzero(ret, axis=0)}
        for name in cuts[1:]:
            ret = ret & getCol(name)
            cutflow[name] = ak.count_nonzero(ret, axis=0)


        onecut = {cut : ak.count_nonzero(getCol(cut)) for cut in cuts}
        n_minus_one = {cut: ak.count_nonzero(andCuts(cuts[:i] + cuts[i+1:]),axis=0) for i,cut in enumerate(cuts)}
        columns.filter(ret)

        if self.save_cutflow:
            return columns, [SelectionFlow(self.sel_name, cuts=cuts, cutflow=cutflow, one_cut=onecut,n_minus_one=n_minus_one)]
        else:
            return columns, []

        

    def inputs(self, metadata):
        if self.selection_names is None:
            return [Column(("Selection"))]
        else:
            return [Column("Selection") + x for x in self.selection_names]

    def outputs(self, metadata):
        return "EVENTS"


@define
class NObjFilter(AnalyzerModule):
    """
    Select events based on the number of objects in a collection.

    This analyzer filters events according to the number of objects
     in a given column, requiring the count to be within specified limits.

    Parameters
    ----------
    selection_name : str
        Name of the selection to store the result.
    input_col : Column
        Column containing the collection of objects to count.
    min_count : int or None, optional
        Minimum number of objects required to pass, by default None.
    max_count : int or None, optional
        Maximum number of objects allowed to pass, by default None.
    """

    selection_name: str
    input_col: Column
    min_count: int | None = None
    max_count: int | None = None

    def run(self, columns, params):
        objs = columns[self.input_col]
        count = ak.num(objs, axis=1)
        sel = None
        if self.min_count is not None:
            sel = count >= self.min_count
        if self.max_count is not None:
            if sel is not None:
                sel = sel & (count <= self.max_count)
            else:
                sel = count <= self.max_count
        addSelection(columns, self.selection_name, sel)
        return columns, []

    def inputs(self, metadata):
        return [self.input_col]

    def outputs(self, metadata):
        return [Column(("Selection", self.selection_name))]

@define
class ObjCompareFilter(AnalyzerModule):
    """
    Select events based on a comparison to a set value.

    This analyzer filters events according to a value (ex HT)
      in a given column that is above, below, or equal to a specified value.
    
    Parameters
    ----------

    selection_name : str
    input_col : Column
    equal_value : float or None, optional
    min_value : float or None, optional
    max_value : float or None, optional
    """

    selection_name: str
    input_col: Column
    key: str | None=None
    equal_value: float | None=None
    min_value: float | None=None
    max_value: float | None=None

    def run(self, columns, params):
        if self.key is not None:
            values = columns[self.input_col][self.key]
        else:
            values = columns[self.input_col]
        sel = None

        if self.min_value is not None:
            sel = ak.fill_none(values >= self.min_value, False, axis=0)
        if self.max_value is not None:
            if sel is not None:
                sel = sel & ak.fill_none((values <= self.max_value), False, axis=0)
            else:
                sel = ak.fill_none(values <= self.max_value, False, axis=0)
        if self.equal_value is not None and sel is None:
            sel = ak.fill_none((values == self.equal_value), False, axis=0)
        elif self.equal_value is not None and sel is not None:
            print("Equal value being used while comparison is being used. Using comparison to select events.")

        addSelection(columns, self.selection_name, sel)
        return columns, []

    def inputs(self, metadata):
        return [self.input_col]

    def outputs(self, metadata):
        return [Column(("Selection", self.selection_name))]
    
@define
class SelectAllTriggers(AnalyzerModule):
    """
    Selection trigger by trigger for each dataset. Takes advantage of the selection flow to get the yield.
    Parameters
    ----------
    sel_name : str
        Name of the selection to be saved in the cutflow summary, eg
        ``selection`` or ``preselection``.
    """

    sel_name: str

    def run(self, columns, params):
        all_triggers = columns["HLT"].fields
        initial = ak.num(columns._events, axis=0)
        
        cutflow = {"initial": initial}
        for trigger_name in all_triggers:
            ret = columns["HLT"][trigger_name]
            cutflow[trigger_name] = ak.count_nonzero(ret, axis=0)
        return columns, [SelectionFlow(self.sel_name, cuts=all_triggers, cutflow=cutflow)]

    def inputs(self, metadata):
        return [Column(("HLT"))]

    def outputs(self, metadata):
        return "EVENTS"
