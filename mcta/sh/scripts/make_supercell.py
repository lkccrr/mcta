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
                → VASP 5 格式，direct 坐标，按元素排序
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
    mt.sh kb CONTCAR 3 - new.xyz     # 输出 XYZ 格式
"""

import os
import re
import sys

from ase.build import make_supercell
from ase.io import read, write
from ase.io.vasp import write_vasp

_DIGITS = re.compile(r"^\d+$")            # 纯数字
_INTEGER = re.compile(r"^[+-]?\d+$")      # 带符号整数（用于区分倍数写错和文件名）

VASP_EXTS = {".vasp", ".poscar"}
VASP_NAMES = {"POSCAR", "CONTCAR", "SPOSCAR"}

SYNOPSIS = "用法: mt.sh kb [POSCAR] [a [b [c]]] [OUT]（mt.sh kb -h 查看详细说明）"


def _usage(stream=sys.stdout):
    print(__doc__.strip(), file=stream)


def _fail(message):
    print("ERROR: " + message, file=sys.stderr)
    print(SYNOPSIS, file=sys.stderr)
    return 1


def _natural(token):
    """纯数字且 >= 1 时返回 int，否则返回 None。"""
    if _DIGITS.match(token):
        value = int(token)
        if value >= 1:
            return value
    return None


def _is_vasp_target(path):
    """判断输出目标是否应该用 VASP writer（保留 sort/direct/vasp5 语义）。"""
    name = os.path.basename(path).upper()
    ext = os.path.splitext(path)[1].lower()
    if ext in VASP_EXTS:
        return True
    if ext == "" and name in VASP_NAMES:
        return True
    return False


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "-H", "--help", "help"):
        _usage()
        return 0

    # 第一个参数是自然数 → 倍数，输入用默认 POSCAR；否则是输入文件名
    src, rest = "POSCAR", args
    if args and _natural(args[0]) is None:
        if _INTEGER.match(args[0]):
            return _fail("扩胞倍数必须是自然数（1、2、3…），收到 %r" % args[0])
        src, rest = args[0], args[1:]

    # 倍数最多 3 个，遇非自然数即停
    scale = []
    while rest and len(scale) < 3:
        value = _natural(rest[0])
        if value is None:
            break
        scale.append(value)
        rest = rest[1:]

    # 3 个倍数之后的第一个参数是输出文件名
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

    # --- 输入：ASE 真实格式探测，读失败干净退出 ---
    try:
        atoms = read(src)
    except Exception as exc:
        return _fail(
            f"ASE 无法识别 {src!r} 的格式：{exc}.\n"
            f"  支持的格式：POSCAR / CONTCAR / .cif / .xyz / .extxyz / "
            f".pdb / .traj / .json 等；需要额外解析器的格式（如 OTF 格式）"
            f"可能需要 pip install pymatgen。"
        )

    supercell = make_supercell(atoms, [[a, 0, 0], [0, b, 0], [0, 0, c]])

    # --- 输出：按扩展名选择 writer ---
    if _is_vasp_target(out):
        try:
            write_vasp(out, supercell, direct=True, vasp5=True, sort=True)
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
