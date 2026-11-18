#!/bin/bash
# sy：用 spglib 判定空间群，输出点群/晶系与各原子的 Wyckoff 位点
#   sy [POSCAR] [symprec]
#     POSCAR  输入结构（ASE 能读的格式均可，如 POSCAR / CONTCAR / *.cif），默认 POSCAR
#     symprec spglib 距离容差（Å），默认 1e-3；调大易判成高对称、调小易判成低对称
#   输出：空间群国际记号与编号、Hall 编号、点群、晶系、原胞/惯用胞原子数、
#         每个不等价位点的 Wyckoff 字母与多重度、site symmetry、等价原子序号
#   说明：角度容差用 spglib 默认，详见 `sy -h`
#   解释器：默认用运行 mt 的 python（从 mt 的 shebang 获取），失败时退回 python3

HERE=$(dirname "${BASH_SOURCE[0]}")
SCRIPT="$HERE/symmetry_info.py"

_has_libs() { "$1" -c 'import ase, spglib' > /dev/null 2>&1; }

# 默认用运行 mt 的 python：从 mt 的 shebang 取解释器
_mt_python() {
  local mt_bin line name
  mt_bin=$(command -v mt 2>/dev/null) || mt_bin=""
  if [ -n "$mt_bin" ]; then
    line=$(sed -n '1p' "$mt_bin" 2>/dev/null)
    line=${line#\#\!}
    case "$line" in
      *env\ *) name=${line##*env }; name=${name%% *}; command -v "$name" && return 0 ;;
      *) set -- $line; [ -x "$1" ] && { printf '%s\n' "$1"; return 0; } ;;
    esac
  fi
  command -v python3 || command -v python
}

_resolve_python() {
  local py
  py=$(_mt_python) || { echo "ERROR: 没有找到 python；请确认 mt 在 PATH 中" >&2; return 1; }
  if ! _has_libs "$py"; then
    echo "ERROR: $py 无法 import ase 与 spglib（请确认 mt 装在装好 mcta 依赖的那个环境里）" >&2
    return 1
  fi
  PY_CMD=("$py")
}

_resolve_python || exit 1
exec "${PY_CMD[@]}" "$SCRIPT" "$@"
