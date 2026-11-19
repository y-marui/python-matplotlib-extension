"""macOS-only, extraction-only bridge for PowerPoint's selected OLE Figure."""

from __future__ import annotations

from macos_powerpoint_bridge.bridge import extract_selected_figure
from macos_powerpoint_bridge.errors import BridgeError

__all__ = ["extract_selected_figure", "BridgeError"]
