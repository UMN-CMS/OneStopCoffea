from __future__ import annotations
import awkward as ak
from collections import ChainMap


from analyzer.utils.pretty import progbar
from analyzer.core.exceptions import ResultIntegrityError
from analyzer.utils.file_tools import iterPaths
import numpy as np


import numbers
import pickle as pkl
import lz4.frame
import dask_awkward as dak
import functools as ft
import json
import datetime
from cattrs.strategies import include_subclasses, configure_tagged_union
from analyzer.core.event_collection import FileSet
from analyzer.core.serialization import converter
import hist
from analyzer.utils.structure_tools import globWithMeta, commonDict, getWithMeta

from attrs import define, field


import copy
import abc
from typing import Any, Literal, ClassVar
import logging

logger = logging.getLogger("analyzer")

FORMAT_VERSION = 2

@ft.cache
def buildFileHeader():
    import sys
    from importlib.metadata import version, PackageNotFoundError

    def ver(dist):
        try:
            return version(dist)
        except PackageNotFoundError:
            return None

    return {
        "format_version": FORMAT_VERSION,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "writer": "OneStopCoffea",
        "writer_version": ver("OneStopCoffea"),
        "python": sys.version.split()[0],
        "packages": {
            name: ver(name)
            for name in (
                "hist",
                "boost-histogram",
                "uhi",
                "awkward",
                "numpy",
                "coffea",
                "dask-awkward",
                "lz4",
            )
        },
    }


def getArrayMem(array):
    from dask.sizeof import sizeof

    if isinstance(array, ak.highlevel.Array):
        return array.nbytes
    return sizeof(array)


@define
class ResultBase(abc.ABC):
    name: str
    _metadata: dict[str, Any] = field(factory=dict, kw_only=True)

    @property
    def metadata(self):
        return ChainMap(self.getMetadata(), {"type": self.__class__.__name__})

    def getMetadata(self):
        return self._metadata

    @abc.abstractmethod
    def __iadd__(self, other) -> ResultBase:
        pass

    @abc.abstractmethod
    def iscale(self, value) -> ResultBase:
        pass

    @abc.abstractmethod
    def approxSize(self) -> int:
        pass

    @abc.abstractmethod
    def finalize(self) -> ResultBase: ...

    def summary(self):
        return self

    def __add__(self, other):
        ret = copy.deepcopy(self)
        ret += other
        return ret

    def scale(self, value):
        ret = copy.deepcopy(self)
        return ret.iscale(value)

    def widget(self, *args, **kwargs):
        return None

    def addMetadataRecursive(self, metadata):
        for r in self.results.values():
            r._metadata.update(metadata)
            if isinstance(r, ResultGroup):
                r.addMetadataRecursive(metadata)


@define
class ResultFileParts:
    """The blocks of a result file, before any of them are decoded."""

    format_version: int
    header: dict[str, Any]
    peek: bytes | None
    core: bytes
    compressed: bool


@define
class ResultGroup(ResultBase):
    """
    version 0: a bare pickle, with no magic bytes.
    version 1: ``MAGIC | peek_len:u32 | peek | lz4(payload)``.
    version 2: ``MAGIC | version:u8 | header_len:u32 | header | peek_len:u32 | peek | lz4(payload)``, where ``header`` is JSON.
    """

    _MAGIC_ID: ClassVar[Literal[b"sstopresult"]] = b"sstopresult"
    _HEADER_SIZE: ClassVar[Literal[4]] = 4

    results: dict[str, ResultBase] = field(factory=dict)

    def globWithMeta(self, pattern):
        from analyzer.utils.structure_tools import globWithMeta

        return globWithMeta(self, pattern)

    @classmethod
    def _encodeLength(cls, value: int) -> bytes:
        if (value.bit_length() + 7) // 8 > cls._HEADER_SIZE:
            raise RuntimeError(
                f"Block of {value} bytes does not fit in a "
                f"{cls._HEADER_SIZE} byte length field"
            )
        return value.to_bytes(cls._HEADER_SIZE, byteorder="big")

    @classmethod
    def _parseVersioned(cls, data: bytes, pos: int) -> ResultFileParts:
        version = data[pos]
        pos += 1
        header_size = int.from_bytes(data[pos : pos + cls._HEADER_SIZE], byteorder="big")
        pos += cls._HEADER_SIZE
        header = json.loads(data[pos : pos + header_size])
        pos += header_size
        if not isinstance(header, dict) or "format_version" not in header:
            raise ValueError("Block is not a result file header")
        peek_size = int.from_bytes(data[pos : pos + cls._HEADER_SIZE], byteorder="big")
        pos += cls._HEADER_SIZE
        return ResultFileParts(
            format_version=version,
            header=header,
            peek=data[pos : pos + peek_size],
            core=data[pos + peek_size :],
            compressed=True,
        )

    @classmethod
    def _parseBytes(cls, data: bytes) -> ResultFileParts:
        if data[: len(cls._MAGIC_ID)] != cls._MAGIC_ID:
            return ResultFileParts(0, {}, None, data, False)

        pos = len(cls._MAGIC_ID)
        if data[pos]:
            try:
                return cls._parseVersioned(data, pos)
            except Exception:
                logger.debug(
                    "Versioned header parse failed, falling back to format version 1",
                    exc_info=True,
                )

        peek_size = int.from_bytes(data[pos : pos + cls._HEADER_SIZE], byteorder="big")
        pos += cls._HEADER_SIZE
        return ResultFileParts(
            format_version=1,
            header={},
            peek=data[pos : pos + peek_size],
            core=data[pos + peek_size :],
            compressed=True,
        )

    @classmethod
    def readHeader(cls, data: bytes) -> dict[str, Any]:
        return cls._parseBytes(data).header

    @classmethod
    def peekFile(cls, f):
        magic = f.read(len(cls._MAGIC_ID))
        if magic != cls._MAGIC_ID:
            return cls.peekBytes(magic + f.read())

        marker = f.read(1)
        if marker and marker[0]:
            header_size = int.from_bytes(f.read(cls._HEADER_SIZE), byteorder="big")
            raw_header = f.read(header_size)
            try:
                header = json.loads(raw_header)
                if not isinstance(header, dict) or "format_version" not in header:
                    raise ValueError("Block is not a result file header")
            except Exception:
                logger.debug(
                    "Versioned header parse failed, re-reading whole file",
                    exc_info=True,
                )
                f.seek(0)
                return cls.peekBytes(f.read())
            peek_size = int.from_bytes(f.read(cls._HEADER_SIZE), byteorder="big")
            return converter.structure(pkl.loads(f.read(peek_size)), cls)

        peek_size = int.from_bytes(
            marker + f.read(cls._HEADER_SIZE - 1), byteorder="big"
        )
        return converter.structure(pkl.loads(f.read(peek_size)), cls)

    @classmethod
    def peekBytes(cls, data: bytes):
        parts = cls._parseBytes(data)
        if parts.peek is None:
            return cls.fromBytes(data).summary()
        return converter.structure(pkl.loads(parts.peek), cls)

    @classmethod
    def fromBytes(cls, data: bytes):
        parts = cls._parseBytes(data)
        core = lz4.frame.decompress(parts.core) if parts.compressed else parts.core
        return converter.structure(pkl.loads(core), cls)

    def toBytes(self, packed_mode=True) -> bytes:
        if not packed_mode:
            return pkl.dumps(converter.unstructure(self))

        header = json.dumps(buildFileHeader()).encode()
        peek = pkl.dumps(converter.unstructure(self.summary()))
        core = lz4.frame.compress(pkl.dumps(converter.unstructure(self)))
        return b"".join(
            (
                self._MAGIC_ID,
                bytes([FORMAT_VERSION]),
                self._encodeLength(len(header)),
                header,
                self._encodeLength(len(peek)),
                peek,
                core,
            )
        )

    def summary(self):
        return ResultGroup(
            name=self.name,
            results={x: y.summary() for x, y in self.results.items()},
            metadata=self.metadata,
        )

    def approxSize(self):
        return sum(x.approxSize() for x in self.results.values())

    def addResult(self, res):
        self.results[res.name] = res

    # def __setitem__(self, key, value):
    #     self.results[key] = value

    def __getitem__(self, key):
        return self.results[key]

    def __iter__(self):
        return iter(self.results)

    def keys(self):
        return self.results.keys()

    def checkOk(self, other):
        if "_provenance" in self.results:
            if "_provenance" not in other.results:
                raise RuntimeError()
            intersection = self["_provenance"].file_set.intersection(other["_provenance"].file_set)
            if (
                not intersection.empty
            ):
                raise ResultIntegrityError(f"Overlapping Provenance.\n{intersection}")

    def __iadd__(self, other):
        self.checkOk(other)
        for k in other.results:
            if k in self.results:
                self.results[k] += other.results[k]
            else:
                self.addResult(other.results[k])
        return self

    def iscale(self, value):
        for k in self.results:
            self.results[k].iscale(value)
        return self

    def finalize(self, finalizer):
        for result in self.results.values():
            result.finalize(finalizer)


@define
class ResultProvenance(ResultBase):
    file_set: FileSet

    def approxSize(self):
        return 200 * len(self.file_set.files)

    def __iadd__(self, other):
        self.file_set += other.file_set
        return self

    def iscale(self, value):
        return self

    @property
    def chunked_events(self):
        return self.file_set.chunked_events

    def finalize(self, finalizer):
        pass


@define
class Histogram(ResultBase):
    @define
    class Summary(ResultBase):
        axes: Any
        _approx_size: int = 0

        def __iadd__(self, other):
            return self

        def iscale(self, value):
            return self

        def approxSize(self):
            return self._approx_size

        def finalize(self, finalizer):
            return self

    axes: Any
    histogram: hist.Hist

    def summary(self):
        return Histogram.Summary(
            name=self.name, axes=self.axes, approx_size=self.approxSize()
        )

    def approxSize(self):
        from dask.sizeof import sizeof

        return sizeof(self.histogram.view(flow=True))

    def __iadd__(self, other):
        self.histogram += other.histogram
        return self

    def iscale(self, value):
        self.histogram *= value
        return self

    def finalize(self, finalizer):
        return self


@define
class UnscaledHistogram(ResultBase):
    @define
    class Summary(ResultBase):
        axes: Any
        _approx_size: int = 0

        def __iadd__(self, other):
            return self

        def iscale(self, value):
            return self

        def approxSize(self):
            return self._approx_size

        def finalize(self, finalizer):
            return self

    axes: Any
    histogram: hist.Hist

    def summary(self):
        return UnscaledHistogram.Summary(
            name=self.name, axes=self.axes, approx_size=self.approxSize()
        )

    def approxSize(self):
        from dask.sizeof import sizeof

        return sizeof(self.histogram.view(flow=True))

    def __iadd__(self, other):
        self.histogram += other.histogram
        return self

    def iscale(self, value):
        return self

    def finalize(self, finalizer):
        return self


Array = ak.Array | dak.Array | np.ndarray


@define
class BasicSummary(ResultBase):
    _approx_size: int = 0

    def __iadd__(self, other):
        return self

    def iscale(self, value):
        return self

    def approxSize(self):
        return self._approx_size

    def finalize(self, finalizer):
        return self


@define
class ScalableArray(ResultBase):
    array: ak.Array | dak.Array | np.ndarray

    def __iadd__(self, other):
        if isinstance(self.array, np.ndarray):
            self.array = np.concatenate([self.array, other.array], axis=0)
        return self

    def summary(self):
        return BasicSummary(name=self.name, approx_size=self.approxSize())

    def approxSize(self):
        return getArrayMem(self.array)

    def iscale(self, value):
        self.array *= value
        return self

    def finalize(self, finalizer):
        self.array = finalizer(self.array)


@define
class RawArray(ResultBase):
    array: ak.Array | dak.Array | np.ndarray

    def __iadd__(self, other):
        if isinstance(self.array, np.ndarray):
            self.array = np.concatenate([self.array, other.array], axis=0)
        return self

    def iscale(self, value):
        return self

    def finalize(self, finalizer):
        self.array = finalizer(self.array)

    def summary(self):
        return BasicSummary(name=self.name, approx_size=self.approxSize())

    def approxSize(self):
        return getArrayMem(self.array)


@define
class SavedColumns(ResultBase):
    data: dict[str, ak.Array | dak.Array | np.ndarray]

    def __iadd__(self, other):
        if set(self.data) != set(other.data):
            raise RuntimeError()
        for k in self.data:
            self.data[k] = np.concatenate([self.data[k], other.data[k]], axis=0)
        return self

    def iscale(self, value):
        self.data["Scale"] = np.ones_like(next(iter(self.data.values()))) * value
        return self

    def finalize(self, finalizer):
        for k in self.data:
            self.data[k] = finalizer(self.data[k])
        return self

    def summary(self):
        return BasicSummary(name=self.name, approx_size=self.approxSize())

    def approxSize(self):
        return sum(getArrayMem(x) for x in self.data.values())


Scalar = dak.Scalar | numbers.Real


@define
class SelectionFlow(ResultBase):
    cuts: list[str]

    cutflow: dict[str, Scalar]
    n_minus_one: dict[str, Scalar] | None = None
    one_cut: dict[str, Scalar] | None = None

    def approxSize(self):
        return 30 * len(self.cuts)

    def __iadd__(self, other):
        if self.cuts != other.cuts:
            raise RuntimeError()
        for x in self.cutflow:
            self.cutflow[x] = self.cutflow[x] + other.cutflow[x]
        if self.n_minus_one is not None:
            for x in self.n_minus_one:
                self.n_minus_one[x] = self.n_minus_one[x] + other.n_minus_one[x]
        if self.one_cut is not None:
            for x in self.one_cut:
                self.one_cut[x] = self.one_cut[x] + other.one_cut[x]
        return self

    def iscale(self, value):
        for x in self.cutflow:
            self.cutflow[x] = value * self.cutflow[x]
        if self.n_minus_one is not None:
            for x in self.n_minus_one:
                self.n_minus_one[x] = value * self.n_minus_one[x]
        if self.one_cut is not None:
            for x in self.one_cut:
                self.one_cut[x] = value * self.one_cut[x]
        return self

    def finalize(self, finalizer):
        pass


@define
class SavedEventFile:
    file_path: str
    nevents: int
    metadata: dict


@define
class SavedFiles(ResultBase):
    saved_files: list[SavedEventFile]

    def approxSize(self):
        return 200 * len(self.saved_files)

    def __iadd__(self, other):
        self.saved_files += other.saved_files
        return self

    def iscale(self, value):
        return self

    def finalize(self, finalizer):
        pass


@define
class RawEventCount(ResultBase):
    count: float

    def __iadd__(self, other):
        self.count += other.count
        return self

    def approxSize(self):
        return 8

    def iscale(self, value):
        return self

    def finalize(self, finalizer):
        pass


@define
class ScaledEventCount(ResultBase):
    count: float

    def approxSize(self):
        return 8

    def __iadd__(self, other):
        self.count += other.count
        return self

    def iscale(self, value):
        self.count *= value
        return self

    def finalize(self, finalizer):
        pass


@define
class RawSelectionFlow(ResultBase):
    cuts: list[str]

    cutflow: dict[str, Scalar]
    n_minus_one: dict[str, Scalar]
    one_cut: dict[str, Scalar]

    def approxSize(self):
        return 30 * len(self.cuts)

    def __iadd__(self, other):
        if self.cuts != other.cuts:
            raise RuntimeError()
        for x in self.cutflow:
            self.cutflow[x] = self.cutflow[x] + other.cutflow[x]
        for x in self.n_minus_one:
            self.n_minus_one[x] = self.n_minus_one[x] + other.n_minus_one[x]
        for x in self.one_cut:
            self.one_cut[x] = self.one_cut[x] + other.one_cut[x]
        return self

    def iscale(self, value):
        return self

    def finalize(self, finalizer):
        pass


PORTABLE_TAG = "__osca_portable__"
UNPORTABLE_STORAGES = ("Mean", "WeightedMean")

def histToPortable(histogram):
    storage = histogram.storage_type.__name__
    if storage in UNPORTABLE_STORAGES or not hasattr(histogram, "_to_uhi_"):
        logger.warning(
            f"Pickling a live histogram object ({storage} storage): reading this "
            "result will require a compatible build of hist."
        )
        return histogram
    return {PORTABLE_TAG: "hist", "ir": histogram._to_uhi_()}


def histFromPortable(data):
    return hist.Hist._from_uhi_(data["ir"])


def awkwardToPortable(array):
    form, length, container = ak.to_buffers(array)
    return {
        PORTABLE_TAG: "awkward",
        "form": form.to_json(),
        "length": length,
        "container": container,
    }


def awkwardFromPortable(data):
    return ak.from_buffers(data["form"], data["length"], data["container"])


def isPortable(value, kind):
    return isinstance(value, dict) and value.get(PORTABLE_TAG) == kind

def configureConverter(conv):
    @conv.register_structure_hook
    def _(val: Any, _) -> hist.Hist:
        return histFromPortable(val) if isPortable(val, "hist") else val

    @conv.register_unstructure_hook
    def _(val: hist.Hist) -> hist.Hist:
        return histToPortable(val)

    @conv.register_structure_hook
    def _(val: Scalar, _) -> Scalar:
        return val

    @conv.register_unstructure_hook
    def _(val: Scalar) -> Scalar:
        return val

    @conv.register_structure_hook
    def _(val: Array, _) -> Array:
        return awkwardFromPortable(val) if isPortable(val, "awkward") else val

    @conv.register_unstructure_hook
    def _(val: Array) -> Array:
        if isinstance(val, ak.highlevel.Array):
            return awkwardToPortable(val)
        return val

    union_strategy = ft.partial(configure_tagged_union, tag_name="result_type")
    include_subclasses(ResultBase, conv, union_strategy=union_strategy)


configureConverter(converter)


def iFilterResultGroup(rg, keep_patterns, current_path=None):
    from fnmatch import fnmatch

    if current_path is None:
        current_path = ()
    new_results = {}
    for k, v in rg.results.items():
        sub_path = current_path + (k,)
        if k.startswith("_"):
            new_results[k] = v
            continue

        if isinstance(v, ResultGroup):
            filtered_v = iFilterResultGroup(v, keep_patterns, sub_path)
            if filtered_v.results:
                new_results[k] = filtered_v
        else:
            keep = False
            for pattern in keep_patterns:
                if len(sub_path) == len(pattern) and all(
                    fnmatch(sp, p) for sp, p in zip(sub_path, pattern)
                ):
                    keep = True
                    break
            if keep:
                new_results[k] = v

    rg.results = new_results
    return rg


def loadResults(paths, peek_only=False, keep_patterns=None, return_file_sizes=False):
    all_paths = paths
    ret = None
    file_sizes = {}
    func = ResultGroup.peekBytes if peek_only else ResultGroup.fromBytes
    used_paths = set()
    for p in progbar(iterPaths(all_paths)):
        if p in used_paths:
            continue
        used_paths.add(p)

        with open(p, "rb") as f:
            result = func(f.read())

        if keep_patterns is not None:
            iFilterResultGroup(result, keep_patterns)

        for r in result.results.values():
            r.addMetadataRecursive({"source_file": str(p)})

        if return_file_sizes:
            file_sizes[str(p)] = result.approxSize()

        if ret is None:
            ret = result
        else:
            ret += result
    if return_file_sizes:
        return ret, file_sizes
    else:
        return ret


def mergeAndScale(results, drop_sample_pattern=None):
    for dataset, meta in globWithMeta(results, ["*"]):
        total = None
        for s in dataset:
            if drop_sample_pattern is not None:
                item, meta = getWithMeta(results, [dataset.name, s])
                if drop_sample_pattern.match(meta):
                    logger.info(
                        f"Dropping sample {meta['dataset_name']}--{meta['sample_name']}"
                    )
                    continue
            sample_data = dataset[s]
            s_meta = sample_data.metadata
            provenance = sample_data["_provenance"]
            processed_events = provenance.chunked_events
            # print(f"{s_meta['sample_name'] = }")
            # print(f"{processed_events = }")
            # print(f"{s_meta['n_events'] = }")
            if s_meta["sample_type"] == "MC":
                lumi = s_meta["era"]["lumi"]
                xs = s_meta["x_sec"]
                scale = lumi * xs / processed_events
                sample_data.iscale(scale)
            elif s_meta["sample_type"] == "Data":
                expected_nevents = s_meta["n_events"]
                sample_data.iscale(expected_nevents / processed_events)
            if total is None:
                total = sample_data
            else:
                total += sample_data

        merged_metadata = commonDict(dataset[x] for x in dataset)
        total.name = dataset.name
        total._metadata = merged_metadata
        results.addResult(total)
    return results


@define
class ResultStatus:
    dataset_name: str
    sample_name: str
    events_expected: int
    events_found: int

    @property
    def frac_complete(self):
        return self.events_found / self.events_expected


def checkResults(paths):
    results = loadResults(paths, peek_only=True)
    ret = []
    for prov, meta in globWithMeta(results, ["*", "*", "_provenance"]):
        expected = meta["n_events"]
        found = prov.chunked_events
        dataset_name = meta["dataset_name"]
        sample_name = meta["sample_name"]
        ret.append(ResultStatus(dataset_name, sample_name, expected, found))
    return ret
