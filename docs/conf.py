from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

import py_sec_edgar


project = "py-sec-edgar"
author = "Ryan S. McCoy and contributors"
copyright = "2026, Ryan S. McCoy and contributors"
version = py_sec_edgar.__version__
release = py_sec_edgar.__version__

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
source_suffix = ".rst"
master_doc = "index"
language = "en"
pygments_style = "sphinx"
todo_include_todos = False

html_theme = "alabaster"
html_static_path = ["_static"]
htmlhelp_basename = "py-sec-edgar-docs"
