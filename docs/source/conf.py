# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

project = "OneStopCoffea"
copyright = "2025, Charlie Kapsiak"
author = "Charlie Kapsiak"

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath("../.."))
sys.path.insert(0, os.path.abspath("_ext"))

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "autoapi.extension",
    "sphinx.ext.mathjax",
    "sphinx_autodoc_typehints",
    "yaml_links",
    "sphinx.ext.graphviz",
]

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "private-members": False,
    "show-inheritance": True,
}


templates_path = ["_templates"]
exclude_patterns = []

#html_theme = "pydata_sphinx_theme"
html_theme = "furo"
html_static_path = ["_static"]


autoapi_dirs = [str(Path(__file__).parent.parent.parent / 'analyzer')]
