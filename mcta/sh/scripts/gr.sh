#!/bin/bash
# gr：输出最终能量和磁矩
test -s OUTCAR && grep 'energy  without entropy=' OUTCAR > /dev/null && grep 'energy  without entropy=' OUTCAR | tail -1 | awk '{printf "%-20s ", $NF}' && {
  test -s OSZICAR && { grep 'mag' OSZICAR > /dev/null && grep 'mag' OSZICAR | tail -1 | sed 's/^.*mag=[ ]*//' || echo ""; } || echo ""
} || echo 'No energy data!'
