#!/bin/bash
# z2：ASE 格式转换
#   z2 IN [OUT]
#     IN   输入结构文件（ASE 能读的格式均可）
#     OUT  可选：扩展名(.cif / cif / .xyz …) 或完整路径；省略默认 .cif
#   示例：z2 POSCAR           → POSCAR.cif
#         z2 POSCAR .xyz      → POSCAR.xyz
#         z2 POSCAR out.cif   → out.cif
#   解释器：默认用运行 mt 的 python（从 mt 的 shebang 获取），失败时退回 python3

HERE=$(dirname "${BASH_SOURCE[0]}")
SCRIPT="$HERE/z2_convert.py"

_has_ase() { "$1" -c 'import ase' > /dev/null 2>&1; }

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
  if ! _has_ase "$py"; then
    echo "ERROR: $py 无法 import ase（请确认 mt 装在装好 mcta 依赖的那个环境里）" >&2
    return 1
  fi
  PY_CMD=("$py")
}

_resolve_python || exit 1
exec "${PY_CMD[@]}" "$SCRIPT" "$@"
