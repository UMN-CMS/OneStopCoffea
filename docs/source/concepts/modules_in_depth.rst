Modules in Depth
=================

In this framework, modules are the fundamental building blocks of an analysis.
Each module should implement a single, well-defined operation.
Understanding the module system is essential for both using existing modules and writing your own.


Module Types
------------

There are three types of modules, each serving a different purpose:

``AnalyzerModule``
^^^^^^^^^^^^^^^^^^

The standard module type.
It receives a ``TrackedColumns`` object and a parameter dictionary, and returns the potentially modified columns along with a list of results.

This is what you will use for the vast majority of analysis logic: filtering objects, computing new quantities, applying corrections, defining selections, and producing histograms.

.. code-block:: python

    @define
    class MyModule(AnalyzerModule):
        def inputs(self, metadata):
            return [Column("Jet")]

        def outputs(self, metadata):
            return [Column("GoodJet")]

        def run(self, columns, params):
            jets = columns["Jet"]
            good_jets = jets[jets.pt > 30]
            columns["GoodJet"] = good_jets
            return columns, []

``EventSourceModule``
^^^^^^^^^^^^^^^^^^^^^

A specialized module that produces events rather than consuming them.
The implicit ``LoadColumns`` module is the primary example -- it loads a chunk of NanoAOD data from disk and creates the initial ``TrackedColumns``.

You would only write an ``EventSourceModule`` if you needed to load events from a non-standard source.

``PureResultModule``
^^^^^^^^^^^^^^^^^^^^

A module that receives *multiple* event collections (one per systematic variation) and produces results that aggregate across them.
The ``HistogramBuilder`` is the primary example -- it receives event collections for central, up, and down variations and fills a single histogram with a ``variation`` axis.

You generally do not create ``PureResultModule`` subclasses directly.
Instead, you use the ``makeHistogram()`` helper function from within a standard ``AnalyzerModule``, which takes care of creating the ``PureResultModule`` and the associated ``ModuleAddition`` for you.


The Module Lifecycle
--------------------

When a module is called during pipeline execution, the following steps occur:

1. **should_run check**: If the module has a ``should_run`` condition and it evaluates to ``False`` for the current metadata, the module is skipped entirely.

2. **Parameter filtering**: The module's ``getParameterSpec()`` is called to determine which dynamic parameters it cares about. Only relevant parameters are passed to ``run()``.

3. **Cache key computation**: The framework computes a key from the module's identity, its filtered parameters, and the provenance of its input columns.

4. **Cache lookup**: If a result for this key exists in the cache, the cached output is returned without executing ``run()``.

5. **Input/output enforcement**: Context managers restrict column access to only the declared ``inputs()`` and ``outputs()``.

6. **Execution**: ``run(columns, params)`` is called.

7. **Cache storage**: The result is stored in the cache for future lookups.


The ``run()`` Method
-----------------------

The ``run()`` method is where your analysis logic lives. It must:

- Accept ``columns`` (a ``TrackedColumns``) and ``params`` (a dictionary of dynamic parameter values).
- Return a tuple of ``(columns, results)`` where:

  - ``columns`` is the (potentially modified) ``TrackedColumns``.
  - ``results`` is a list of ``ResultBase`` objects and/or ``ModuleAddition`` objects.

.. code-block:: python

    def run(self, columns, params):
        # Read input data
        jets = columns[self.input_col]

        # Do computation
        good_jets = jets[(jets.pt > self.min_pt) & (abs(jets.eta) < self.max_eta)]

        # Write output
        columns[self.output_col] = good_jets

        # Return columns and any results
        return columns, []

The ``results`` list can contain:

- **Result objects** like ``Histogram``, ``SelectionFlow``, ``SavedColumns``, etc. These are collected by the framework and stored in the result tree.
- **ModuleAddition** objects, which request the framework to run additional modules (typically a ``PureResultModule`` like ``HistogramBuilder``).


Declaring Inputs and Outputs
------------------------------

The ``inputs()`` and ``outputs()`` methods declare which columns a module reads from and writes to.
These declarations serve two purposes:

1. **Caching**: The framework uses input declarations to compute cache keys (see :doc:`architecture`).
2. **Safety**: During execution, column access is restricted to declared inputs/outputs. Accessing an undeclared column raises an error.

.. code-block:: python

    def inputs(self, metadata):
        return [self.input_col, Column("Weights")]

    def outputs(self, metadata):
        return [self.output_col]

The ``metadata`` argument allows input/output declarations to vary based on the dataset. For example, a module might declare additional inputs when processing MC vs Data.

Returning ``"EVENTS"`` means the module operates on the full event record with no restrictions:

.. code-block:: python

    def outputs(self, metadata):
        return "EVENTS"   # This module may modify any column


Producing Results
-----------------

Histograms are the most common final product of an analysis run.
They should be produced using the ``makeHistogram()`` helper:

.. code-block:: python

    from analyzer.modules.common.histogram_builder import makeHistogram
    from analyzer.modules.common.axis import RegularAxis

    def run(self, columns, params):
        ht = columns["HT"]

        hist_result = makeHistogram(
            "HT_distribution",
            columns,
            RegularAxis(name="HT", start=0, stop=3000, bins=60, unit="GeV"),
            ht,
        )
        return columns, [hist_result]

``makeHistogram()`` returns a ``ModuleAddition`` that, when processed by the framework, triggers a multi-run to collect all systematic variations and fills a histogram with a ``variation`` axis.

You can also return result objects directly:

.. code-block:: python

    from analyzer.core.results import RawEventCount

    def run(self, columns, params):
        count = ak.num(columns.events, axis=0)
        return columns, [RawEventCount("event_count", count=count)]

See :doc:`results_and_provenance` for the full list of available result types.


Configuration via ``attrs``
----------------------------

Module parameters are defined as ``attrs`` fields on the class.
The ``@define`` decorator from ``attrs`` is used instead of standard Python dataclasses.

.. code-block:: python

    from attrs import define
    from analyzer.core.columns import Column

    @define
    class JetFilter(AnalyzerModule):
        input_col: Column
        output_col: Column
        min_pt: float = 30.0
        max_abs_eta: float = 2.4
        include_jet_id: bool = True

These fields become the YAML configuration parameters.
When the framework loads a configuration, it uses ``cattrs`` to deserialize the YAML dictionaries into these ``attrs`` classes.
The ``module_name`` field in the YAML identifies which class to instantiate via a tagged union system.

As is standard in python, fields with default values are optional in the YAML configuration, and fields without defaults are required.
