"""允许 ``python -m mcta`` 直接调用统一入口。"""

import sys

from mcta.cli import main

if __name__ == "__main__":
    sys.exit(main())
