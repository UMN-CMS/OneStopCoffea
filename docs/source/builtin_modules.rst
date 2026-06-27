Built-in Modules
=================

The framework provides a library of built-in modules for common analysis tasks.
These are organized by category below.

You can search for modules from the command line:

.. code-block:: bash

    ./osca search-modules "Jet"


Data Quality
------------

- **GoldenLumi**: Filters events based on the golden JSON luminosity list. Applies only to Data.
- **NoiseFilter**: Applies standard CMS noise filters (MET filters).
- **VetoMap**: Marks jets in vetoed detector regions.
- **VetoMapFilter**: Removes jets flagged by the veto map.


Jet Modules
-----------

- **JetFilter**: Filters jets by pT, :math:`\eta`, jet ID, and pileup jet ID. The primary jet selection module.
- **JetScaleCorrections**: Applies Jet Energy Scale (JEC) corrections. Declares shape systematics.
- **JetResolutionCorrections**: Applies Jet Energy Resolution (JER) smearing. Declares shape systematics.
- **JetEtaPhiVeto**: Vetoes jets in specific :math:`\eta`-\ :math:`\phi` regions (used for hot ECAL regions).
- **JetCombos**: Computes invariant masses for combinations of jets.
- **BQuarkMaker**: Identifies b-tagged jets at a given working point (L, M, T).
- **HT**: Computes HT (scalar sum of jet pT).
- **Count**: Counts objects in a collection.
- **VecPt**: Selection based on vector sum pT.


Lepton Modules
--------------

- **ElectronMaker**: Selects electrons by working point, pT, and :math:`\eta`.
- **MuonMaker**: Selects muons by ID, isolation, pT, and :math:`\eta`.


Trigger Selection
-----------------

- **HLTSelection**: Selects events passing specified HLT triggers.
- **SelectAllTriggers**: Creates a cutflow of all triggers for efficiency studies.


Selection and Filtering
-----------------------

- **NObjFilter**: Creates a selection mask based on the number of objects in a collection.
- **SelectOnColumns**: Applies all pending selection masks and records cutflow information.


Event-Level Corrections (MC)
-----------------------------

- **PileupSF**: Applies pileup scale factors.
- **L1PrefiringSF**: Applies L1 prefiring corrections.
- **PosNegGenWeight**: Handles generator weight sign.
- **PileupJetIdSF**: Applies pileup jet ID scale factors.
- **BJetShapeSF**: Applies b-jet shape scale factors. Declares weight systematics.


Categories
----------

- **SimpleCategory**: Bins events into categories based on a continuous variable.


Histogramming
-------------

- **SimpleHistogram**: Produces a histogram from one or more input columns.
- **HistogramBuilder**: Internal module that aggregates multi-variation event collections into a single histogram.


Data Export
-----------

- **SaveColumns**: Saves specified columns to the result tree.
- **Skim**: Writes selected events to ROOT files.


Gen-Level
---------

- **GenMatching**: Performs generator-level particle matching.
