import os

import gafaelfawr
import lsst_sphinx_bootstrap_theme

# Common links and substitutions =============================================

rst_epilog = """

.. _mypy: http://www.mypy-lang.org
.. _pre-commit: https://pre-commit.com
.. _pytest: https://docs.pytest.org/en/latest/
.. _tox: https://tox.readthedocs.io/en/latest/
"""

# Extensions =================================================================

extensions = [
    "sphinx.ext.autodoc",
    # "sphinx.ext.autodoc.typehints",
    "sphinx.ext.napoleon",
    "sphinx.ext.doctest",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx-prompt",
    "sphinx_automodapi.automodapi",
    "sphinx_automodapi.smart_resolver",
    "documenteer.sphinxext",
]

# General configuration ======================================================

source_suffix = ".rst"

# The master toctree document.
master_doc = "index"

# General information about the project.
project = "Gafaelfawr"
copyright = (
    "2020 "
    "Association of Universities for Research in Astronomy, Inc. (AURA)"
)
author = "LSST Data Management"

version = gafaelfawr.__version__
release = version

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns = ["_build", "README.rst"]

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"

# The reST default role cross-links Python (used for this markup: `text`)
default_role = "py:obj"

# Intersphinx ================================================================

intersphinx_mapping = {
    "aiohttp": ("https://aiohttp.readthedocs.io/en/stable/", None),
    "aiohttp_session": (
        "https://aiohttp-session.readthedocs.io/en/stable/",
        None,
    ),
    "aioredis": ("https://aioredis.readthedocs.io/en/latest/", None),
    "cachetools": ("https://cachetools.readthedocs.io/en/stable/", None),
    "cryptography": ("https://cryptography.io/en/latest/", None),
    "dynaconf": ("https://dynaconf.readthedocs.io/en/latest/", None),
    "jwt": ("https://pyjwt.readthedocs.io/en/latest/", None),
    "python": ("https://docs.python.org/3/", None),
    "structlog": ("http://www.structlog.org/en/stable/", None),
    "wtforms": ("https://wtforms.readthedocs.io/en/stable/", None),
}

intersphinx_timeout = 10.0  # seconds
intersphinx_cache_limit = 5  # days

# Linkcheck builder ==========================================================

linkcheck_retries = 2

# linkcheck_ignore = [r'^https://jira.lsstcorp.org/browse/']

linkcheck_timeout = 15

# HTML builder ===============================================================

templates_path = [
    "_templates",
    lsst_sphinx_bootstrap_theme.get_html_templates_path(),
]

html_theme = "lsst_sphinx_bootstrap_theme"
html_theme_path = [lsst_sphinx_bootstrap_theme.get_html_theme_path()]

html_context = {
    # Enable "Edit in GitHub" link
    "display_github": True,
    # https://{{ github_host|default("github.com") }}/{{ github_user }}/
    #     {{ github_repo }}/blob/
    #     {{ github_version }}{{ conf_py_path }}{{ pagename }}{{ suffix }}
    "github_user": "lsst",
    "github_repo": "gafaelfawr",
    "conf_py_path": "docs/",
    # GITHUB_REF is available in GitHub Actions, but master is a safe default
    "github_version": os.getenv("GITHUB_REF", default="master") + "/",
}

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
html_theme_options = {"logotext": project}

# The name for this set of Sphinx documents.  If None, it defaults to
# "<project> v<release> documentation".
html_title = f"{project} v{version}"

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = project

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = []

# If true, links to the reST sources are added to the pages.
html_show_sourcelink = False

# Do not copy reST source for each page into the build
html_copy_source = False

# If false, no module index is generated.
html_domain_indices = True

# If false, no index is generated.
html_use_index = True

# API Reference ==============================================================

napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_keyword = True  # TODO
napoleon_use_param = True
napoleon_use_rtype = True

autosummary_generate = True

automodapi_inheritance_diagram = False
automodapi_toctreedirnm = "api"
automodsumm_inherited_members = True

# Docstrings for classes and methods are inherited from parents.
autodoc_inherit_docstrings = True

# Class documentation should only contain the class docstring and
# ignore the __init__ docstring, account to LSST coding standards.
autoclass_content = "class"

# Default flags for automodapi directives. Special members are dunder
# methods.
autodoc_default_options = {
    "show-inheritance": False,
    "special-members": True,
}

# Render inheritance diagrams in SVG
graphviz_output_format = "svg"

graphviz_dot_args = [
    "-Nfontsize=10",
    "-Nfontname=Helvetica Neue, Helvetica, Arial, sans-serif",
    "-Efontsize=10",
    "-Efontname=Helvetica Neue, Helvetica, Arial, sans-serif",
    "-Gfontsize=10",
    "-Gfontname=Helvetica Neue, Helvetica, Arial, sans-serif",
]

# TODO extension =============================================================

todo_include_todos = False
