"""Error type raised by this bridge.

A single, flat error type matches
``matplotlib_extension.package.PackageError``'s style and
``macos_powerpoint_bridge.errors.BridgeError``'s: every rejection (bad
selection, unsaved presentation, unexpected OOXML structure) is a
deliberate "fail closed with a message", never a guess.
"""

from __future__ import annotations


class BridgeError(Exception):
    """Raised for any selection, presentation-state, or package-structure
    rejection in this extraction-only bridge."""
