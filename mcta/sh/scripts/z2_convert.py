"""z2：ASE 结构格式转换器。

用法：
    mt.sh z2 IN [OUT]
    z2 IN [OUT]

参数：
    IN   输入结构文件（ASE 能读的格式：POSCAR / CONTCAR / *.cif / *.xyz / *.pdb
         / *.traj 等）。格式不识别时报错退出。
    OUT  输出目标，可选。分四种情况：
          · 省略  → 在输入文件同目录、同 stem 下输出 .cif（默认格式）
          · POSCAR / SPOSCAR / CONTCAR → 输出同名文件，VASP 格式
          · 扩展名（.cif / cif / .xyz …）→ 在输入 stem 后拼上这个扩展名
          · 完整路径（含目录）→ 按给出的路径写出，扩展名决定格式
            （文件名是 POSCAR / SPOSCAR / CONTCAR 时按 VASP 格式写）

    VASP 输出统一使用 direct=True、vasp5=True；若输入也是 VASP 且元素已
    分组连续出现则保持原顺序，否则按原子序数从小到大分组。

示例：
    mt.sh z2 POSCAR                  # POSCAR → POSCAR.cif
    mt.sh z2 CONTCAR .xyz            # CONTCAR → CONTCAR.xyz
    mt.sh z2 CONTCAR xyz             # CONTCAR → CONTCAR.xyz（自动补点）
    mt.sh z2 POSCAR out.cif          # → out.cif
    mt.sh z2 POSCAR /tmp/si.extxyz   # → /tmp/si.extxyz
    mt.sh z2 si.cif POSCAR           # → POSCAR（VASP 格式）
    mt.sh z2 si.cif SPOSCAR          # → SPOSCAR（VASP 格式）
"""

import os
import sys
from collections import Counter

from ase.data import atomic_numbers
from ase.io import read, write

SYNOPSIS = "用法: mt.sh z2 IN [OUT]（mt.sh z2 -h 查看详细说明）"


# 这些 stem 会被 ASE 特殊路由到 VASP handler（即使扩展名是 .cif 也会写成 VASP）
# 解决：对这些文件显式传 format，让 ASE 按扩展名选 writer
VASP_ROUTED_STEMS = {
    "POSCAR", "CONTCAR", "SPOSCAR",
    "POSCAR.ORIG", "CONTCAR.ORIG",
}

# 输出参数直接写这些名字时：既是 VASP 格式，也是输出文件名（不当成扩展名）
VASP_OUTPUT_NAMES = {"POSCAR", "SPOSCAR", "CONTCAR"}

# VASP 写出设置：分数坐标、VASP5（带元素符号行）。
# 元素分组排序在 _vasp_atoms_by_number 里独立处理（不使用 ASE 自带的 sort，那是字母序）。
VASP_WRITE_KWARGS = {"direct": True, "vasp5": True}

# ASE format 名与扩展名不完全一致的别名映射
FORMAT_ALIAS = {
    ".poscar": "vasp",
    ".vasp": "vasp",
    ".pdb": "proteindatabank",
}


def _extract_format(out_path):
    """从输出路径提取 ASE format 字符串。VASP 专用名返回 vasp，无扩展名返回 None。"""
    base = os.path.basename(out_path)
    if base.upper() in VASP_OUTPUT_NAMES:
        return "vasp"
    ext = os.path.splitext(base)[1].lower()
    if not ext:
        return None
    return FORMAT_ALIAS.get(ext, ext.lstrip("."))


def _fail(message):
    print("ERROR: " + message, file=sys.stderr)
    print(SYNOPSIS, file=sys.stderr)
    return 1


def _read_format(in_path):
    """决定输入文件的 ASE format。

    ASE 注册 VASP 的 glob 是 ['*POSCAR*', '*CONTCAR*', '*CENTCAR*']，stem 只要含
    这些词就会被路由到 VASP handler——无论扩展名。这里当 stem 在 VASP_ROUTED_STEMS
    且扩展名是 VASP 别名（.vasp/.poscar）或无扩展名时返回 None 让 ASE 自动识别；
    否则返回扩展名对应的 format，让扩展名优先说话。
    """
    base = os.path.basename(in_path)
    stem, ext = os.path.splitext(base)
    if stem.upper() not in VASP_ROUTED_STEMS:
        return None
    if not ext:
        return None
    ext = ext.lower()
    if FORMAT_ALIAS.get(ext) == "vasp":
        return None
    if ext in FORMAT_ALIAS:
        return FORMAT_ALIAS[ext]
    return ext.lstrip(".")


def _resolve_out(in_path, out_arg):
    """根据输入和可选的 out_arg 决定最终输出路径。"""
    stem, _ = os.path.splitext(in_path)
    if out_arg is None:
        return stem + ".cif"

    base = os.path.basename(out_arg)
    has_dir = "/" in out_arg or "\\" in out_arg

    # POSCAR / SPOSCAR / CONTCAR：本身就是输出文件名（VASP 格式），不是扩展名
    if base.upper() in VASP_OUTPUT_NAMES:
        return out_arg

    # 纯扩展名（以 . 开头，或不含 .）
    if out_arg.startswith(".") and not has_dir:
        return stem + out_arg
    if "." not in base and not has_dir:
        return stem + "." + out_arg

    # 完整路径
    return out_arg


def _vasp_atoms_by_number(atoms):
    """按原子序数从小到大把 atoms 里的元素分组排序，返回重排后的 atoms 和
    ASE write_vasp 所需的 symbol_count 列表（[(sym, n), …]）。

    ASE 自带的 sort=True 按字母序，对含过渡金属的体系（如 CoCrFeNi）排序不对
    （字母序 Co<Cr<Fe<Ni，但原子序数 Cr=24<Fe=26<Co=27<Ni=28），所以手动排。
    同一元素内部保持原顺序不变。
    """
    symbols = atoms.get_chemical_symbols()
    by_sym = {}
    for i, s in enumerate(symbols):
        by_sym.setdefault(s, []).append(i)

    def key(s):
        return (atomic_numbers.get(s, 999), s)
    ordered_syms = sorted(by_sym.keys(), key=key)
    new_indices = [i for s in ordered_syms for i in by_sym[s]]
    new_atoms = atoms[new_indices]
    counts = Counter(symbols)
    symbol_count = [(s, counts[s]) for s in ordered_syms]
    return new_atoms, symbol_count


def _is_vasp_input(path):
    """判断输入路径是否是 VASP 格式（stem 命中 VASP_ROUTED_STEMS 且扩展名是 VASP 别名或无扩展名）。"""
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    if stem.upper() not in VASP_ROUTED_STEMS:
        return False
    if not ext:
        return True
    ext = ext.lower()
    return FORMAT_ALIAS.get(ext) == "vasp"


def _has_continuous_groups(symbols):
    seen = set()
    prev = None
    for s in symbols:
        if s != prev:
            if s in seen:
                return False
            seen.add(s)
            prev = s
    return True


def _symbol_count_in_order(symbols):
    counts = {}
    for s in symbols:
        counts[s] = counts.get(s, 0) + 1
    return list(counts.items())


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "-H", "--help", "help"):
        print(__doc__.strip())
        return 0

    if not args:
        return _fail("缺少输入文件参数")

    if len(args) > 2:
        return _fail("参数过多（最多 2 个：输入 [输出]）")

    src = args[0]
    out_arg = args[1] if len(args) >= 2 else None

    if not os.path.isfile(src):
        return _fail(f"找不到输入文件 {src!r}（当前目录 {os.getcwd()}）")

    out = _resolve_out(src, out_arg)

    # 输入：两遍尝试链，先按扩展名显式 format 覆盖，失败再让 ASE auto。
    atoms = None
    last_err = None
    read_fmt = _read_format(src)
    attempts = []
    if read_fmt is not None:
        attempts.append(lambda: read(src, format=read_fmt))
    attempts.append(lambda: read(src))  # auto
    for loader in attempts:
        try:
            atoms = loader()
            break
        except Exception as exc:
            last_err = exc
    if atoms is None:
        return _fail(
            f"ASE 无法识别 {src!r} 的格式：{last_err}.\n"
            f"  支持：POSCAR / CONTCAR / .cif / .xyz / .extxyz / .pdb / .traj "
            f"等；部分格式需要 pip install pymatgen。"
        )

    # 输出
    out_stem = os.path.splitext(os.path.basename(out))[0].upper()
    fmt = _extract_format(out)
    try:
        if fmt == "vasp":
            # VASP 输出排序：输入也是 VASP 且元素分组连续时保持原序；否则原子序数排序
            symbols = atoms.get_chemical_symbols()
            keep_order = _is_vasp_input(src) and _has_continuous_groups(symbols)
            if keep_order:
                sc = _symbol_count_in_order(symbols)
                write(out, atoms, format="vasp", symbol_count=sc, **VASP_WRITE_KWARGS)
            else:
                atoms_out, sc = _vasp_atoms_by_number(atoms)
                write(out, atoms_out, format="vasp", symbol_count=sc, **VASP_WRITE_KWARGS)
        elif out_stem in VASP_ROUTED_STEMS and fmt is not None:
            write(out, atoms, format=fmt)
        else:
            write(out, atoms)
    except Exception as exc:
        return _fail(
            f"ASE 无法写出 {out!r}（扩展名 {os.path.splitext(out)[1]!r} 不支持或依赖缺失）：{exc}"
        )

    print(f"{src}  →  {out}  ({len(atoms)} atoms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
