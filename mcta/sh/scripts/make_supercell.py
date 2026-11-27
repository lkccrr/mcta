"""kb：按 a×b×c 扩胞并写出结构文件。

用法：
    mt.sh kb [POSCAR] [a [b [c]]] [OUT]
    kb [POSCAR] [a [b [c]]] [OUT]

参数（从左往右解析）：
    POSCAR  输入结构文件（ASE 能读的格式均可：POSCAR、CONTCAR、*.cif、*.xyz
            等）。省略时取当前目录的 POSCAR；若第一个参数是自然数，则按倍数
            解析，输入仍取默认的 POSCAR。**无法识别的格式会报错退出。**
    a b c   扩胞倍数，只认自然数（1、2、3…），最多 3 个，缺的自动补 1：
            只给 2 → 2×1×1；给 2 3 → 2×3×1；一个都不给 → 1×1×1。
    OUT     输出文件名，仅当 3 个倍数之后还有参数时生效。默认 SPOSCAR。
            扩展名决定输出格式：
              *.vasp / *.poscar / POSCAR / CONTCAR / SPOSCAR
                → VASP 5 格式，direct 坐标。若输入也是 VASP 且元素已
                  分组连续出现则保持原顺序，否则按原子序数从小到大分组。
              *.cif → CIF
              *.xyz / *.extxyz → XYZ / Extended XYZ
              *.pdb → PDB
              *.traj → ASE trajectory
              其他 ASE 支持的扩展名 → ASE 自动选择 writer
            若扩展名 ASE 不支持，会报错退出。

示例：
    mt.sh kb                         # POSCAR -> SPOSCAR（1×1×1）
    mt.sh kb 2                       # POSCAR -> SPOSCAR（2×1×1）
    mt.sh kb 2 2                     # POSCAR -> SPOSCAR（2×2×1）
    mt.sh kb 2 2 1                   # POSCAR -> SPOSCAR（2×2×1）
    mt.sh kb POSCAR 2 2 1 out.cif    # 输出 CIF 格式
    mt.sh kb CONTCAR 3               # CONTCAR -> SPOSCAR（3×1×1）
    mt.sh kb CONTCAR 3 new.xyz       # 输出 XYZ 格式
"""

import os
import re
import sys
from collections import Counter

from ase.build import make_supercell
from ase.data import atomic_numbers
from ase.io import read, write
from ase.io.vasp import write_vasp

_DIGITS = re.compile(r"^\d+$")
_INTEGER = re.compile(r"^[+-]?\d+$")

# stem 含这些词时 ASE 会忽略扩展名按 VASP 解析（glob=['*POSCAR*','*CONTCAR*','*CENTCAR*']）
VASP_ROUTED_STEMS = {"POSCAR", "CONTCAR", "SPOSCAR", "POSCAR.ORIG", "CONTCAR.ORIG"}

# VASP 输出扩展名别名
VASP_EXTS = {".vasp", ".poscar"}
VASP_NAMES = {"POSCAR", "CONTCAR", "SPOSCAR"}

FORMAT_ALIAS = {
    ".poscar": "vasp",
    ".vasp": "vasp",
    ".pdb": "proteindatabank",
}

SYNOPSIS = "用法: mt.sh kb [POSCAR] [a [b [c]]] [OUT]（mt.sh kb -h 查看详细说明）"


def _usage(stream=sys.stdout):
    print(__doc__.strip(), file=stream)


def _fail(message):
    print("ERROR: " + message, file=sys.stderr)
    print(SYNOPSIS, file=sys.stderr)
    return 1


def _natural(token):
    if _DIGITS.match(token):
        value = int(token)
        if value >= 1:
            return value
    return None


def _read_format(in_path):
    """决定 ASE read 的 format。stem 在 VASP_ROUTED_STEMS 且扩展名不是 VASP 别名时
    按扩展名显式指定，覆盖 ASE 的 glob 路由；否则交给 ASE 自动识别。"""
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


def _atoms_by_number(atoms):
    """按原子序数从小到大把 atoms 里的元素分组排序，返回重排后的 atoms 和
    ASE write_vasp 所需的 symbol_count 列表。ASE 自带 sort=True 是字母序，
    对 CoCrFeNi 等体系会错排，所以手动排。"""
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


def _is_vasp_target(path):
    name = os.path.basename(path).upper()
    ext = os.path.splitext(path)[1].lower()
    if ext in VASP_EXTS:
        return True
    if ext == "" and name in VASP_NAMES:
        return True
    return False


def _is_vasp_input(path):
    """判断输入路径是否是"VASP 格式"——stem 在 VASP_ROUTED_STEMS 里，且
    扩展名是 VASP 别名或无扩展名。用于决定输出 VASP 时是否尝试保持输入顺序。"""
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    if stem.upper() not in VASP_ROUTED_STEMS:
        return False
    if not ext:
        return True  # 无扩展名的 POSCAR / CONTCAR / SPOSCAR
    ext = ext.lower()
    return FORMAT_ALIAS.get(ext) == "vasp"


def _has_continuous_groups(symbols):
    """检查 symbols 列表里每个元素是否只出现一段连续的位置。
    如 ['Fe','Fe','Co','Co'] 返回 True；['Fe','Co','Fe'] 返回 False（Fe 被拆成两段）。"""
    seen = set()
    prev = None
    for s in symbols:
        if s != prev:
            if s in seen:
                return False  # 切换到一个之前已出现过的元素 → 被拆组
            seen.add(s)
            prev = s
    return True


def _symbol_count_in_order(symbols):
    """按首次出现顺序组装 symbol_count 列表 [(sym, count), ...]。"""
    counts = {}
    for s in symbols:
        counts[s] = counts.get(s, 0) + 1
    return list(counts.items())


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "-H", "--help", "help"):
        _usage()
        return 0

    src, rest = "POSCAR", args
    if args and _natural(args[0]) is None:
        if _INTEGER.match(args[0]):
            return _fail("扩胞倍数必须是自然数（1、2、3…），收到 %r" % args[0])
        src, rest = args[0], args[1:]

    scale = []
    while rest and len(scale) < 3:
        value = _natural(rest[0])
        if value is None:
            break
        scale.append(value)
        rest = rest[1:]

    out = "SPOSCAR"
    if len(scale) == 3 and rest:
        out, rest = rest[0], rest[1:]

    if rest:
        return _fail("无法解析的参数 %r（倍数只认自然数、最多 3 个，"
                     "输出名只能放在 3 个倍数之后）" % rest[0])

    if not os.path.isfile(src):
        return _fail("找不到结构文件 %r（当前目录 %s）" % (src, os.getcwd()))

    scale += [1] * (3 - len(scale))
    a, b, c = scale

    # --- 输入：两遍尝试链，先按扩展名显式 format 覆盖，失败再让 ASE auto ---
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
            f"  支持的格式：POSCAR / CONTCAR / .cif / .xyz / .extxyz / "
            f".pdb / .traj / .json 等；需要额外解析器的格式"
            f"可能需要 pip install pymatgen。"
        )

    supercell = make_supercell(atoms, [[a, 0, 0], [0, b, 0], [0, 0, c]])

    # --- 输出 ---
    if _is_vasp_target(out):
        # VASP 输出排序策略：输入也是 VASP 且元素分组连续时保持原序；
        # 否则按原子序数从小到大分组。
        symbols = supercell.get_chemical_symbols()
        keep_order = _is_vasp_input(src) and _has_continuous_groups(symbols)
        try:
            if keep_order:
                sc = _symbol_count_in_order(symbols)
                write_vasp(out, supercell, symbol_count=sc, direct=True, vasp5=True)
            else:
                sc_out, sc = _atoms_by_number(supercell)
                write_vasp(out, sc_out, symbol_count=sc, direct=True, vasp5=True)
        except Exception as exc:
            return _fail(f"写出 VASP 格式 {out!r} 失败：{exc}")
    else:
        try:
            write(out, supercell)
        except Exception as exc:
            return _fail(
                f"ASE 无法写出 {out!r}（扩展名 {os.path.splitext(out)[1]!r} 不支持或依赖缺失）：{exc}"
            )

    print("%s: %s -> %d atoms (%d×%d×%d)" % (out, src, len(supercell), a, b, c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
