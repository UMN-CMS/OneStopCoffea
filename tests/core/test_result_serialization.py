import io
import json
import pickle as pkl
import pickletools

import awkward as ak
import hist
import lz4.frame
import numpy as np
import pytest

from analyzer.core import results as R
from analyzer.core.results import (
    FORMAT_VERSION,
    Histogram,
    RawArray,
    ResultGroup,
    SavedColumns,
    ScaledEventCount,
)
from analyzer.core.serialization import converter
from analyzer.modules.common.axis import RegularAxis


def makeHist(name="HT", unit=None, storage=None, nbins=6):
    axis = RegularAxis(bins=nbins, start=0, stop=3000, name=name, unit=unit).toHist()
    h = hist.Hist(
        hist.axis.StrCategory(["central", "up", "down"], name="variation"),
        axis,
        storage=storage or hist.storage.Weight(),
    )
    view = h.view(flow=True)
    rng = np.random.default_rng(0)
    view["value"][...] = rng.random(view.shape)
    view["variance"][...] = rng.random(view.shape)
    return h


def makeGroup():
    group = ResultGroup("ROOT")
    group.addResult(Histogram("hist_ht", axes=["variation", "HT"], histogram=makeHist()))
    group.addResult(RawArray("arr", array=ak.Array([[1.0, 2.0], [], [3.0]])))
    group.addResult(ScaledEventCount("count", count=17.5))
    group.addResult(
        SavedColumns("cols", data={"pt": np.arange(5.0), "eta": np.linspace(-2, 2, 5)})
    )
    return group


def pickleClassRefs(blob):
    ops = list(pickletools.genops(blob))
    refs = set()
    for i, (op, arg, _) in enumerate(ops):
        if op.name == "STACK_GLOBAL":
            refs.add(f"{ops[i - 2][1]}.{ops[i - 1][1]}")
        elif op.name == "GLOBAL" and isinstance(arg, str):
            refs.add(arg.replace(" ", "."))
    return refs


class TestPortableEncoding:
    def testHistogramRoundTrips(self):
        original = makeHist()
        restored = R.histFromPortable(R.histToPortable(original))
        assert np.array_equal(
            original.view(flow=True)["value"], restored.view(flow=True)["value"]
        )
        assert np.array_equal(
            original.view(flow=True)["variance"], restored.view(flow=True)["variance"]
        )
        assert [a.name for a in original.axes] == [a.name for a in restored.axes]
        assert original.storage_type.__name__ == restored.storage_type.__name__

    def testAxisUnitSurvives(self):
        h = makeHist(unit="GeV")
        assert h.axes[1].unit == "GeV"
        restored = R.histFromPortable(R.histToPortable(h))
        assert restored.axes[1].unit == "GeV"
        assert restored.axes[1].name == "HT"

    @pytest.mark.parametrize(
        "storage",
        [hist.storage.Double(), hist.storage.Int64(), hist.storage.Weight()],
    )
    def testStoragesAreDescribed(self, storage):
        h = hist.Hist(hist.axis.Regular(4, 0, 4, name="x"), storage=storage)
        portable = R.histToPortable(h)
        assert R.isPortable(portable, "hist")
        assert R.histFromPortable(portable).storage_type.__name__ == (
            h.storage_type.__name__
        )

    @pytest.mark.parametrize("storage", [hist.storage.Mean(), hist.storage.WeightedMean()])
    def testMeanStoragesFallBackToLiveObject(self, storage):
        h = hist.Hist(hist.axis.Regular(4, 0, 4, name="x"), storage=storage)
        assert R.histToPortable(h) is h

    def testAwkwardRoundTrips(self):
        array = ak.Array([[1.0, 2.0], [], [3.0, 4.0, 5.0]])
        restored = R.awkwardFromPortable(R.awkwardToPortable(array))
        assert ak.to_list(restored) == ak.to_list(array)

    def testAwkwardRecordsRoundTrip(self):
        array = ak.Array({"pt": [[1.0], [2.0, 3.0]], "eta": [[0.5], [1.5, 2.5]]})
        restored = R.awkwardFromPortable(R.awkwardToPortable(array))
        assert ak.to_list(restored) == ak.to_list(array)

    def testNoCompiledClassesInPayload(self):
        blob = pkl.dumps(converter.unstructure(makeGroup()))
        refs = pickleClassRefs(blob)
        assert not [r for r in refs if "boost" in r or "Hist" in r or "awkward" in r], (
            f"compiled/third-party classes leaked into the payload: {sorted(refs)}"
        )


class TestFileFormat:
    def testRoundTripThroughBytes(self):
        group = makeGroup()
        restored = ResultGroup.fromBytes(group.toBytes())
        assert np.array_equal(
            group["hist_ht"].histogram.view(flow=True)["value"],
            restored["hist_ht"].histogram.view(flow=True)["value"],
        )
        assert ak.to_list(restored["arr"].array) == ak.to_list(group["arr"].array)
        assert restored["count"].count == group["count"].count
        assert np.array_equal(restored["cols"].data["pt"], group["cols"].data["pt"])

    def testLoadedHistogramIsARealHist(self):
        restored = ResultGroup.fromBytes(makeGroup().toBytes())
        assert isinstance(restored["hist_ht"].histogram, hist.Hist)
        assert isinstance(restored["arr"].array, ak.Array)

    def testHeaderIsReadableWithoutUnpickling(self):
        data = makeGroup().toBytes()
        header = ResultGroup.readHeader(data)
        assert header["format_version"] == FORMAT_VERSION
        assert header["writer"] == "OneStopCoffea"
        assert "hist" in header["packages"]
        assert "awkward" in header["packages"]
        start = data.index(b"{")
        assert json.loads(data[start : start + len(json.dumps(header))])

    def testPeekBytesMatchesPeekFile(self):
        data = makeGroup().toBytes()
        by_bytes = ResultGroup.peekBytes(data)
        by_file = ResultGroup.peekFile(io.BytesIO(data))
        assert set(by_bytes.keys()) == set(by_file.keys())
        assert set(by_bytes.keys()) == set(makeGroup().keys())

    def testPeekDoesNotCarryHistograms(self):
        peeked = ResultGroup.peekBytes(makeGroup().toBytes())
        entry = peeked["hist_ht"]
        assert not hasattr(entry, "histogram")
        assert entry.axes == ["variation", "HT"]
        assert entry.approxSize() > 0

    def testSummaryTagsCollide(self):
        from analyzer.core.results import UnscaledHistogram

        assert Histogram.Summary.__name__ == UnscaledHistogram.Summary.__name__
        peeked = ResultGroup.peekBytes(makeGroup().toBytes())
        assert type(peeked["hist_ht"]).__name__ == "Summary"

    def testUnpackedModeRoundTrips(self):
        """``packed_mode=False`` used to produce files that could not be peeked."""

        data = makeGroup().toBytes(packed_mode=False)
        assert ResultGroup.fromBytes(data)["count"].count == 17.5
        assert set(ResultGroup.peekBytes(data).keys()) == set(makeGroup().keys())
        assert ResultGroup.readHeader(data) == {}


class TestBackwardCompatibility:
    @staticmethod
    def writeLegacyV1(group):
        """Reproduce the pre-version-2 layout, with live objects in the payload."""

        def legacyUnstructure(g):
            out = {"name": g.name, "_metadata": dict(g._metadata), "results": {}}
            for key, value in g.results.items():
                if isinstance(value, ResultGroup):
                    out["results"][key] = legacyUnstructure(value)
                else:
                    out["results"][key] = converter.unstructure(value)
            out["result_type"] = "ResultGroup"
            return out

        # Deliberately bypass the portable hooks to embed live objects.
        payload = legacyUnstructure(group)
        payload["results"]["hist_ht"]["histogram"] = group["hist_ht"].histogram
        payload["results"]["arr"]["array"] = group["arr"].array

        peek = pkl.dumps(converter.unstructure(group.summary()))
        core = lz4.frame.compress(pkl.dumps(payload))
        return (
            ResultGroup._MAGIC_ID
            + len(peek).to_bytes(ResultGroup._HEADER_SIZE, byteorder="big")
            + peek
            + core
        )

    def testLegacyV1FileStillLoads(self):
        group = makeGroup()
        data = self.writeLegacyV1(group)
        assert ResultGroup._parseBytes(data).format_version == 1

        restored = ResultGroup.fromBytes(data)
        assert isinstance(restored["hist_ht"].histogram, hist.Hist)
        assert np.array_equal(
            restored["hist_ht"].histogram.view(flow=True)["value"],
            group["hist_ht"].histogram.view(flow=True)["value"],
        )
        assert ak.to_list(restored["arr"].array) == ak.to_list(group["arr"].array)

    def testLegacyV1PeeksAndHasNoHeader(self):
        data = self.writeLegacyV1(makeGroup())
        assert ResultGroup.readHeader(data) == {}
        assert set(ResultGroup.peekBytes(data).keys()) == set(makeGroup().keys())
        assert set(ResultGroup.peekFile(io.BytesIO(data)).keys()) == set(
            makeGroup().keys()
        )

    def testLegacyV0BarePickleStillLoads(self):
        group = makeGroup()
        data = pkl.dumps(converter.unstructure(group))
        assert ResultGroup._parseBytes(data).format_version == 0
        assert ResultGroup.fromBytes(data)["count"].count == 17.5

    def testVersionDetectionIsNotFooledByLargePeek(self):
        peek = pkl.dumps(converter.unstructure(makeGroup().summary()))
        forged = (
            ResultGroup._MAGIC_ID
            + (0x02 << 24).to_bytes(ResultGroup._HEADER_SIZE, byteorder="big")
            + peek
        )
        assert ResultGroup._parseBytes(forged).format_version == 1
