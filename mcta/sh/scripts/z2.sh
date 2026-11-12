#!/bin/bash
# z2：ASE 格式转换
#   z2 IN [OUT]
#     IN   输入结构文件（ASE 能读的格式均可）
#     OUT  可选：扩展名(.cif / cif / .xyz …) 或完整路径；省略默认 .cif
#   示例：z2 POSCAR           → POSCAR.cif
#         z2 POSCAR .xyz      → POSCAR.xyz
#         z2 POSCAR out.cif   → out.cif

HERE=$(dirname "${BASH_SOURCE[0]}")
SCRIPT="$HERE/z2_convert.py"

_has_ase() { "$1" -c 'import ase' > /dev/null 2>&1; }

_resolve_python() {
  local py
  if [ -n "${PYTHON:-}" ]; then
    if _has_ase "$PYTHON"; then PY_CMD=("$PYTHON"); return 0; fi
    echo "ERROR: PYTHON=$PYTHON 无法 import ase" >&2
    return 1
  fi

  local -a candidates=()
  command -v python3 > /dev/null && candidates+=("$(command -v python3)")
  [ -n "${CONDA_PREFIX:-}" ] && candidates+=("$CONDA_PREFIX/bin/python")
  for py in "$HOME/.local/miniconda3/envs/my/bin/python" \
            "$HOME/miniconda3/envs/my/bin/python" \
            "$HOME/anaconda3/envs/my/bin/python"; do
    [ -x "$py" ] && candidates+=("$py")
  done
  local base
  for base in "$HOME/.local/miniconda3/envs" "$HOME/miniconda3/envs" \
              "$HOME/anaconda3/envs" "$HOME/.conda/envs" "$HOME/mambaforge/envs" \
              /opt/conda/envs /usr/local/miniconda3/envs /usr/local/anaconda3/envs; do
    for py in "$base"/*/bin/python; do
      [ -x "$py" ] && candidates+=("$py")
    done
  done

  for py in "${candidates[@]}"; do
    if _has_ase "$py"; then PY_CMD=("$py"); return 0; fi
  done

  local conda
  for conda in "$HOME/.local/miniconda3/bin/conda" "$HOME/miniconda3/bin/conda" \
                "$HOME/anaconda3/bin/conda"; do
    if [ -x "$conda" ] && "$conda" run -n my python -c 'import ase' > /dev/null 2>&1; then
      PY_CMD=("$conda" run -n my python); return 0
    fi
  done

  echo "ERROR: 没有找到能 import ase 的 python；请 pip install ase，或用 PYTHON=/path/to/python 指定" >&2
  return 1
}

_resolve_python || exit 1
exec "${PY_CMD[@]}" "$SCRIPT" "$@"
