============
Installation
============

From source:

.. code-block:: console

    git clone <your fork or working remote>
    cd py-sec-edgar-m
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    pip install -e .

Sanity-check the CLI:

.. code-block:: console

    py-sec-edgar --help

First-run workflow:

.. code-block:: console

    py-sec-edgar refdata refresh
    py-sec-edgar index refresh --skip-if-exists --save-idx-as-csv
