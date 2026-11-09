#!/bin/bash
# kb：用 ASE 扩胞成 a×b×c，输出 SPOSCAR（可指定输出名）
#   kb [POSCAR] [a [b [c]]] [OUT]
#     POSCAR  输入结构（ASE 能读的格式均可，如 POSCAR / CONTCAR / *.cif），默认 POSCAR
#     a b c   扩胞倍数，只认自然数（默认 1，最多 3 个，缺的补 1）
#     OUT     输出文件名，放在 3 个倍数之后，默认 SPOSCAR
#   输出为 VASP 5 格式、direct 坐标、按元素排序
#   解释器：优先 $PYTHON，其次自动找能 import ase 的 python（含未激活的 conda 环境）

HERE=$(dirname "${BASH_SOURCE[0]}")
SCRIPT="$HERE/make_supercell.py"

_has_ase() { "$1" -c 'import ase' > /dev/null 2>&1; }

# 选出第一个能 import ase 的解释器，放到 PY_CMD（可能是 "conda run -n my python"）
_resolve_python() {
  local py
  if [ -n "${PYTHON:-}" ]; then
    if _has_ase "$PYTHON"; then PY_CMD=("$PYTHON"); return 0; fi
    echo "ERROR: PYTHON=$PYTHON 无法 import ase（请先 pip install ase，或改用装了 ase 的解释器）" >&2
    return 1
  fi

  # 当前 PATH 的解释器优先，其次是 conda 环境（mt.sh 常常装在某个 conda 环境里）
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

  # 最后兜底：conda 本身不在 PATH 时也能试一次
  local conda
  for conda in "$HOME/.local/miniconda3/bin/conda" "$HOME/miniconda3/bin/conda" \
                "$HOME/anaconda3/bin/conda"; do
    if [ -x "$conda" ] && "$conda" run -n my python -c 'import ase' > /dev/null 2>&1; then
      PY_CMD=("$conda" run -n my python); return 0
    fi
  done

  echo "ERROR: 没有找到能 import ase 的 python（已尝试：${candidates[*]:-无}）；请 pip install ase，或用 PYTHON=/path/to/python 指定" >&2
  return 1
}

_resolve_python || exit 1
exec "${PY_CMD[@]}" "$SCRIPT" "$@"
