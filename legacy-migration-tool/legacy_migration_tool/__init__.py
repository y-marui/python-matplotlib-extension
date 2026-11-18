"""Deprecated, isolated migration tool for legacy dill-based figures.

This package is deliberately separate from ``matplotlib_extension``. It is
the only place in this project where ``dill`` is imported, and only inside
``legacy_migration_tool.convert``. It exists solely to convert trusted,
historical ``.plt.pdf`` files into the safe, data-only ``.mpl.png`` format;
it is not a supported legacy editing path, and it must not grow into one.

See README.md for the full security model before using this tool.
"""

__version__ = "0.1.0"
