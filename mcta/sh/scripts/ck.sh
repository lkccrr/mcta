#!/bin/bash
# ck：检查四个输入文件是否齐全，POTCAR 缺失时先调 po.sh pos 生成
PO=po.sh; [ -f "$PO" ] || PO="$(dirname "${BASH_SOURCE[0]}")/po.sh"
if [[ -s POTCAR ]]; then :; else bash "$PO" pos; fi
if [[ -s POSCAR && -s INCAR && -s KPOINTS && -s POTCAR ]]; then :; else exit 1; fi
