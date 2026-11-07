#!/bin/bash
# pr：输出外应力
test -s OUTCAR && grep 'external pressure =' OUTCAR > /dev/null && grep 'external pressure =' OUTCAR || echo 'No pressure data!'
