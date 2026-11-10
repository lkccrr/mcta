#!/bin/bash
# sy：用 spglib 判定空间群，输出点群/晶系与各原子的 Wyckoff 位点
#   sy [POSCAR] [symprec]
#     POSCAR  输入结构（ASE 能读的格式均可，如 POSCAR / CONTCAR / *.cif），默认 POSCAR
#     symprec spglib 距离容差（Å），默认 1e-3；调大易判成高对称、调小易判成低对称
#   输出：空间群国际记号与编号、Hall 编号、点群、晶系、原胞/惯用胞原子数、
#         每个不等价位点的 Wyckoff 字母与多重度、site symmetry、等价原子序号
#   说明：角度容差用 spglib 默认，详见 `sy -h`
#   解释器：优先 $PYTHON，其次自动找能 import ase 与 spglib 的 python（含未激活的 conda 环境）

HERE=$(dirname "${BASH_SOURCE[0]}")
SCRIPT="$HERE/symmetry_info.py"

_has_libs() { "$1" -c 'import ase, spglib' > /dev/null 2>&1; }

# 选出第一个能 import ase 与 spglib 的解释器，放到 PY_CMD（可能是 "conda run -n my python"）
_resolve_python() {
  local py
  if [ -n "${PYTHON:-}" ]; then
    if _has_libs "$PYTHON"; then PY_CMD=("$PYTHON"); return 0; fi
    echo "ERROR: PYTHON=$PYTHON 无法 import ase 与 spglib（请先 pip install ase spglib，或改用装好这两个库的解释器）" >&2
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
    if _has_libs "$py"; then PY_CMD=("$py"); return 0; fi
  done

  # 最后兜底：conda 本身不在 PATH 时也能试一次
  local conda
  for conda in "$HOME/.local/miniconda3/bin/conda" "$HOME/miniconda3/bin/conda" \
                "$HOME/anaconda3/bin/conda"; do
    if [ -x "$conda" ] && "$conda" run -n my python -c 'import ase, spglib' > /dev/null 2>&1; then
      PY_CMD=("$conda" run -n my python); return 0
    fi
  done

  echo "ERROR: 没有找到能 import ase 与 spglib 的 python（已尝试：${candidates[*]:-无}）；请 pip install ase spglib，或用 PYTHON=/path/to/python 指定" >&2
  return 1
}

_resolve_python || exit 1
exec "${PY_CMD[@]}" "$SCRIPT" "$@"
