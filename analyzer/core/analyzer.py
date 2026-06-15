from __future__ import annotations
import copy

from attrs import define, field, asdict


from collections import deque, OrderedDict, ChainMap
import functools as ft

from analyzer.core.analysis_modules import (
    AnalyzerModule,
    ModuleAddition,
)
from analyzer.core.run_builders import DEFAULT_RUN_BUILDER, CompleteSysts, RunBuilder
from analyzer.core.results import (
    ResultProvenance,
    ResultGroup,
    ResultBase,
)
from analyzer.core.param_specs import getWithValues
from collections import ChainMap
from analyzer.modules.common.load_columns import LoadColumns
import logging
from analyzer.core.adl import ADLEmitter, ADLBlock, ADLStatement
import re

from analyzer.utils.structure_tools import SimpleCache, freeze, flatten


logger = logging.getLogger("analyzer.core")


def getPipelineSpecs(pipeline, metadata):
    ret = {}
    for module in pipeline:
        new_specs = module.getParameterSpec(metadata)
        if set(ret) & set(new_specs):
            raise RuntimeError("Duplicate module parameter names")
        ret.update(new_specs)
    return ret


@define
class Analyzer:
    all_modules: list = field(factory=list)
    base_pipelines: dict[str, list[AnalyzerModule]] = field(factory=dict)

    default_run_builder: RunBuilder = field(factory=CompleteSysts)

    _cache: SimpleCache = field(factory=SimpleCache)

    def __rich_repr__(self):
        modules_ids = [(id(x), x) for x in self.all_modules]
        pipelines_ids = {
            k: [(id(z), z) for z in x] for k, x in self.base_pipelines.items()
        }
        yield "modules", modules_ids
        yield "pipelines", pipelines_ids

    def initModules(self, metadata):
        pass
        # for m in self.all_modules:
        #     m.preloadForMeta(metadata)

    def clearCaches(self):
        self._cache.clear()
        for m in self.all_modules:
            m.clearCache()

    def exportAdl(self, metadata, ignore_pattern=None, title=None, config_path=None):

        emitter = ADLEmitter(
            title=title,
            config_path=config_path,
            context_name=metadata.get("dataset_name"),
        )

        for pipeline_name, pipeline in self.base_pipelines.items():
            region_statements = []

            for module in pipeline:
                if ignore_pattern and re.match(
                    ignore_pattern, module.__class__.__name__
                ):
                    continue

                if (
                    hasattr(module, "should_run")
                    and module.should_run
                    and not module.should_run.evaluate(metadata)
                ):
                    continue

                blocks = module.adlExport(metadata)
                if blocks:
                    for block in blocks:
                        if block.block_type == "region_statement":
                            if block.comment:
                                region_statements.append(
                                    ADLStatement("#", block.comment)
                                )
                            region_statements.extend(block.statements)
                        else:
                            emitter.addBlock(block)

            if region_statements:
                emitter.addBlock(
                    ADLBlock(
                        block_type="region",
                        name=pipeline_name,
                        statements=region_statements,
                    )
                )

        return emitter.render()

    def getUniqueModule(self, module):
        found = next((x for x in self.all_modules if x == module), None)
        if found is not None:
            return found
        else:
            self.all_modules.append(module)
            return module

    def neededResources(self, metadata):
        needed_resources = []
        for module in self.all_modules:
            needed_resources.extend(module.neededResources(metadata))
        return needed_resources

    def addPipeline(self, name, pipeline):
        ret = []
        ret.append(self.getUniqueModule(LoadColumns()))
        for module in pipeline:
            ret.append(self.getUniqueModule(module))
        self.base_pipelines[name] = ret

    def runPipelineWithParameters(
        self,
        pipeline,
        params,
        freeze_pipeline=False,
        result_container_name=None,
        *,
        tracing_vis=True,
    ):
        vis_modules, vis_edges, vis_last_mod = OrderedDict(), set(), None

        module_keys = [x.selfkey for x in pipeline]
        key = hash(freeze((module_keys, params)))

        logger.debug(f"Pipeline execution key is {key}")
        if key in self._cache:
            logger.debug(f"Found key {key}, using cached columns")
            return self._cache[key], None
        else:
            logger.debug(f"Did not find key {key}, recomputing")
        params = copy.deepcopy(params)
        complete_pipeline = []
        to_add = deque(pipeline)
        current_spec, columns = None, None

        if result_container_name is None:
            result_container = None
        else:
            result_container = ResultGroup(
                result_container_name, metadata={"pipeline": result_container_name}
            )

        while to_add:
            head = to_add.popleft()
            if (
                columns is not None
                and head.should_run is not None
                and not head.should_run.evaluate(columns.metadata)
            ):
                continue
            complete_pipeline.append(head)
            if columns is not None:
                columns = columns.copy()
                current_spec = getPipelineSpecs(complete_pipeline, columns.metadata)
                columns, results = head(columns, params)

                if tracing_vis:
                    p = head.filterParams(columns.metadata, params)
                    vis_key = head.getKey(columns, p)
            else:
                if tracing_vis:
                    s = head.getParameterSpec(None)
                    p = {x: y for x, y in params.items() if x in s}
                    vis_key = head.getKey(p)
                columns, results = head(params), []

            if tracing_vis:
                vis_modules[vis_key] = (head.name(), p)
                if vis_last_mod is not None:
                    vis_edges.add((vis_last_mod, vis_key))
                vis_last_mod = vis_key

            if not result_container:
                continue

            results = deque(results)

            while results:
                res = results.popleft()
                if isinstance(res, ResultBase):
                    result_container.addResult(res)
                elif isinstance(res, ModuleAddition) and not freeze_pipeline:
                    module = res.analyzer_module
                    if res.run_builder is None:
                        raise NotImplementedError()
                        module = self.getUniqueModule(module)
                        if module.should_run is None or module.should_run.evaluate(
                            columns.metadata
                        ):
                            logger.debug(f"Adding new module {module} to pipeline")
                            complete_pipeline.append(module)
                        params = ChainMap(params, res.this_module_parameters)
                    else:
                        logger.debug("RUNNING MULTI PARAMETER PIPELINE!!")
                        if res.run_builder is DEFAULT_RUN_BUILDER:
                            run_builder = self.default_run_builder
                        else:
                            run_builder = res.run_builder

                        param_dicts = run_builder(current_spec, columns.metadata)
                        to_run = [
                            (x, getWithValues(current_spec, params | y))
                            for x, y in param_dicts
                        ]

                        everything = []
                        multi_vis_info = []
                        for name, params_set in to_run:
                            c, _, vis_info = self.runPipelineWithParameters(
                                complete_pipeline,
                                params_set,
                                freeze_pipeline=True,
                                result_container_name=None,
                                tracing_vis=tracing_vis,
                            )
                            everything.append((name, c))
                            multi_vis_info.append(vis_info)

                        if tracing_vis:
                            s = module.getParameterSpec(None)
                            p = {x: y for x, y in params.items() if x in s}
                            vis_key = module.getKey(everything, p)
                            vis_modules[vis_key] = (module.name(), p)
                            for vi in multi_vis_info:
                                vis_edges.add((next(reversed(vi[0])), vis_key))
                                vis_modules = vi[0] | vis_modules
                                vis_edges |= vi[1]

                        logger.debug(
                            f"Running node {module} with {len(everything)} parameter sets"
                        )
                        r = module(everything, res.this_module_parameters or {})
                        results.extendleft(r)
                        logger.debug("FINISHED RUNNING MULTIPARAMETER PIPELINE!")
                else:
                    raise RuntimeError(
                        f"Invalid object type returned from analyzer module. {res}"
                    )
        self._cache[key] = columns
        return columns, result_container, (vis_modules, vis_edges)

    def run(self, chunk, metadata, pipelines=None):
        pipelines = pipelines or list(self.base_pipelines)

        root_container = ResultGroup("ROOT")
        dataset_container = ResultGroup(metadata["dataset_name"])
        sample_container = ResultGroup(metadata["sample_name"], metadata=metadata)
        pipeline_container = ResultGroup("pipelines")

        root_container.addResult(dataset_container)
        dataset_container.addResult(sample_container)
        sample_container.addResult(ResultProvenance("_provenance", chunk.toFileSet()))
        sample_container.addResult(pipeline_container)
        metadata = copy.deepcopy(metadata)
        metadata["chunk"] = asdict(chunk)
        all_vis_info = []
        for k, pipeline in self.base_pipelines.items():
            if k not in pipelines:
                continue
            spec = getPipelineSpecs(pipeline, metadata)
            vals = getWithValues(spec, {"chunk": chunk, "metadata": metadata})
            _, result, vis_info = self.runPipelineWithParameters(
                pipeline,
                vals,
                result_container_name=k,
                tracing_vis=True,
            )
            pipeline_container.addResult(result)
            all_vis_info.append(vis_info)
        vis_all_modules = ft.reduce(lambda x, y: x | y, (x[0] for x in all_vis_info))
        vis_all_edges = ft.reduce(lambda x, y: x | y, (x[1] for x in all_vis_info))
        renderGraph(vis_all_modules, vis_all_edges)

        return root_container

    @classmethod
    def _structure(cls, data: dict, conv) -> Analyzer:
        analyzer = cls()
        builder = data.pop("default_run_builder", None)
        if builder is not None:
            analyzer.default_run_builder = conv.structure(builder, RunBuilder)

        for k, v in data.items():
            analyzer.addPipeline(
                k, [conv.structure(x, AnalyzerModule) for x in flatten(v)]
            )
        return analyzer

    def _unstructure(self, conv) -> dict:
        return {
            x: conv.unstructure([z.analyzer_module for z in y])
            for x, y in self.base_pipelines.items()
        }


def intToAlpaStr(x, char_base="A"):
    ret = ""
    b = ord(char_base)
    while x != 0:
        x, r = divmod(x, 26)
        ret += chr(b + r)
    return ret[::-1]


def renderGraph(modules, edges):
    import graphviz

    dot = graphviz.Digraph("Analyzer")
    for m, (name, params) in modules.items():
        dot.node(intToAlpaStr(abs(m)), label=name)
    for v1, v2 in edges:
        dot.edge(intToAlpaStr(abs(v1)), intToAlpaStr(abs(v2)))

    print(dot.source)
