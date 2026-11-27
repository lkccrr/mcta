#!/bin/bash
# kb：用 ASE 扩胞成 a×b×c，输出 SPOSCAR（可指定输出名）
#   kb [POSCAR] [a [b [c]]] [OUT]
#     POSCAR  输入结构（ASE 能读的格式均可，如 POSCAR / CONTCAR / *.cif），默认 POSCAR
#     a b c   扩胞倍数，只认自然数（默认 1，最多 3 个，缺的补 1）
#     OUT     输出文件名，放在 3 个倍数之后，默认 SPOSCAR
#   输出为 VASP 5 格式、direct 坐标、按元素排序
#   解释器：默认用运行 mt 的 python（从 mt 的 shebang 获取），失败时退回 python3

HERE=$(dirname "${BASH_SOURCE[0]}")
SCRIPT="$HERE/make_supercell.py"

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
  # 优先：cli.py 递归调用时会把当前解释器放进 MTA_PYTHON
  if [ -n "${MTA_PYTHON:-}" ] && command -v "$MTA_PYTHON" >/dev/null 2>&1; then
    if "$MTA_PYTHON" -c 'import ase' >/dev/null 2>&1; then
      PY_CMD=("$MTA_PYTHON")
      return 0
    fi
  fi
  py=$(_mt_python) || { echo "ERROR: 没有找到 python；请确认 mt 在 PATH 中" >&2; return 1; }
  if ! _has_ase "$py"; then
    echo "ERROR: $py 无法 import ase（请确认 mt 装在装好 mcta 依赖的那个环境里）" >&2
    return 1
  fi
  PY_CMD=("$py")
}

_resolve_python || exit 1
exec "${PY_CMD[@]}" "$SCRIPT" "$@"
