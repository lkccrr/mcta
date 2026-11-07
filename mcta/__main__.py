"""允许 ``python -m mcta`` 直接调用统一入口。"""

import sys

from mcta.cli import main

sys.exit(main())
