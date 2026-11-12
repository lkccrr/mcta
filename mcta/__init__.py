"""mt —— Meta Crystal Toolkit & Analysis"""

import os
import platform

__version__ = "0.0.8"


def version_string() -> str:
    """统一的 -V 输出格式。"""
    return "Meta Crystal Toolkit & Analysis " + __version__ + " from " + os.path.dirname(__file__) + ' (python' + platform.python_version() + ')'
