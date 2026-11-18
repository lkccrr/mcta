#!/bin/bash
# re：检测 OUTCAR 是否达到收敛标准
test -s OUTCAR && {
  grep 'reached required accuracy' OUTCAR > /dev/null && { echo -n "reached required accuracy: "; pwd; } || { printf "%27s" ': '; pwd && exit 1; }
} || echo 'No OUTCAR file!'
