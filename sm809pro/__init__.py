"""
sm809pro -- a clean, validated driver library for the SOLAKAKA SM809 Pro mouse.

Public API:
    from sm809pro import SM809Pro, actions, macros, protocol
    from sm809pro.status import StatusListener

The full HID protocol was reverse-engineered from the vendor WebHID driver, the
official GamingMS.exe (via IDA), and validated on live hardware.
"""

from . import protocol
from . import actions
from . import macros
from . import defaults
from .device import SM809Pro, pick_control_interface, detect_modes, choose_mode

__version__ = "0.1.0"

__all__ = [
    "SM809Pro",
    "pick_control_interface",
    "detect_modes",
    "choose_mode",
    "protocol",
    "actions",
    "macros",
    "defaults",
    "__version__",
]
