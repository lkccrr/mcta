#!/bin/bash
# en：显示每个电子步的能量
test -s OUTCAR && grep 'energy  without entropy=' OUTCAR || echo 'No energy data!'
