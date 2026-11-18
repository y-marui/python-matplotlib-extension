__version__ = "0.1.0"

from matplotlib_extension.container import LegacyFigureError
from matplotlib_extension.package import PackageError, UnsupportedFigureWarning
from matplotlib_extension.pyplot import (
    extract_editable_png,
    install_matplotlib_savefig,
    loadfig,
    recover_data,
    save_pptx,
    savefig,
)

install_matplotlib_savefig()

__all__ = [
    "LegacyFigureError",
    "PackageError",
    "UnsupportedFigureWarning",
    "extract_editable_png",
    "install_matplotlib_savefig",
    "loadfig",
    "recover_data",
    "save_pptx",
    "savefig",
]
