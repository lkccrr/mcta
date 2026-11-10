"""sy：用 spglib 判定空间群，并列出 Wyckoff 位点信息。

用法：
    mt.sh sy [结构文件] [symprec]
    sy [结构文件] [symprec]

参数：
    结构文件  输入结构，ASE 能读的格式均可（POSCAR / CONTCAR / *.cif / *.xyz 等），
              默认当前目录的 POSCAR。**第一个参数永远按文件名解释**（只有完全不给
              参数时才用默认 POSCAR），所以 `mt.sh sy 0.001` 是“找名为 0.001 的
              结构文件”并报错，不会被猜成 symprec；想给默认 POSCAR 换精度请写全
              `mt.sh sy POSCAR 0.001`。
    symprec   spglib 的距离容差，正有限浮点数，默认 1e-3（单位 Å）。

symprec 的含义（默认 1e-3 Å）：
    spglib 判定“两个原子是否对称等价”的距离容差。1e-3 Å 是接近晶体学精度的严格值：
    1e-3 Å 以内的数值噪声（DFT 优化残留、坐标截断、四舍五入）会被吸收，仍能认出
    理想的高对称空间群；若结构的真实畸变超过 1e-3 Å，则如实降为低对称空间群。
    调大（如 1e-2）：把小畸变当噪声，容易把带畸变的结构判成高对称空间群、位点数变少；
    调小（如 1e-4、1e-5）：更苛刻，容易判成低对称（P1 等）甚至直接判失败
    （spglib 返回 None，命令会提示容差可能过严并 exit 1）。
    角度容差保持 spglib 默认值：它只影响晶轴方向的判定，默认值与 symprec 配套，
    显式改写反而容易造成“位置严格、角度宽松”的不一致结果。

输出字段：
    结构文件与原子数
    空间群国际记号与编号、Hall 编号与 Hall 记号、点群、晶系
    原胞原子数、惯用胞（standard/conventional cell）原子数
    本次实际使用的 symprec
    每个不等价位点：Wyckoff 字母 + 多重度、site symmetry、元素与等价原子编号（从 1 起）

    Wyckoff 字母/多重度按 spglib 对标准化（惯用）胞的判定给出；原点选法不同时同一位点
    可能标成 a 或 b（如金刚石：惯用胞输入为 8a，2 原子原胞输入为 8b），多重度与
    site symmetry 不受影响。

示例：
    mt.sh sy                       # 读当前目录 POSCAR，symprec = 1e-3
    mt.sh sy CONTCAR               # 读 CONTCAR
    mt.sh sy POSCAR 1e-2           # 放宽容差，畸变结构可能判成更高对称性
    mt.sh sy POSCAR 0.0001         # 收紧容差，畸变结构可能判成更低对称性
    mt.sh sy relaxed.cif 5e-4      # 读 CIF 并指定 symprec
"""

import math
import os
import sys

import spglib
from ase.io import read

SYMPREC = 1e-3

SYNOPSIS = ("用法: mt.sh sy [结构文件] [symprec]"
            "（结构文件默认 POSCAR、symprec 默认 1e-3；mt.sh sy -h 查看详细说明）")

# 空间群编号区间 -> 晶系
_CRYSTAL_SYSTEMS = (
    (2, "三斜", "triclinic"),
    (15, "单斜", "monoclinic"),
    (74, "正交", "orthorhombic"),
    (142, "四方", "tetragonal"),
    (167, "三方", "trigonal"),
    (194, "六方", "hexagonal"),
    (230, "立方", "cubic"),
)


def _usage(stream=sys.stdout):
    print(__doc__.strip(), file=stream)


def _fail(message):
    print("ERROR: " + message, file=sys.stderr)
    print(SYNOPSIS, file=sys.stderr)
    return 1


def _field(obj, name):
    """兼容 spglib 新版 dataclass 与旧版 dict 两种返回形式。"""
    value = getattr(obj, name, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(name)
    return value


def _crystal_system(number):
    for limit, zh, en in _CRYSTAL_SYSTEMS:
        if number <= limit:
            return zh, en
    return "未知", "unknown"


def _ranges(indices):
    """把连续的原子序号压成区间：1, 2, 3, 5 -> 1-3, 5。"""
    parts = []
    start = prev = indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
            continue
        parts.append(str(start) if start == prev else "%d-%d" % (start, prev))
        start = prev = i
    parts.append(str(start) if start == prev else "%d-%d" % (start, prev))
    return ", ".join(parts)


def _orbits(ds):
    """返回 ({轨道编号: [原子下标]}, 出现顺序)。优先 crystallographic_orbits。"""
    orbit_ids = _field(ds, "crystallographic_orbits")
    if orbit_ids is None:
        orbit_ids = _field(ds, "equivalent_atoms")
    groups, order = {}, []
    for i, oid in enumerate(int(v) for v in orbit_ids):
        if oid not in groups:
            groups[oid] = []
            order.append(oid)
        groups[oid].append(i)
    return groups, order


def _positive_float(token):
    """能解析成正的有限浮点数就返回该值，否则返回 None。"""
    try:
        value = float(token)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "-H", "--help", "help"):
        _usage()
        return 0

    if len(args) > 2:
        return _fail("只接受两个参数（结构文件、symprec），多出 %r" % args[2])
    if args and args[0].startswith("-"):
        return _fail("无法识别的选项 %r（本命令只有 [结构文件] [symprec] 两个参数）" % args[0])

    # 第一个参数永远按文件名解释，只有完全不给参数才用默认 POSCAR
    src = args[0] if args else "POSCAR"
    symprec = SYMPREC
    if len(args) == 2:
        symprec = _positive_float(args[1])
        if symprec is None:
            return _fail("symprec 必须是正的有限浮点数（如 1e-3、0.0001、1e-2），收到 %r"
                         % args[1])

    if not os.path.isfile(src):
        return _fail("找不到结构文件 %r（当前目录 %s）" % (src, os.getcwd()))

    try:
        atoms = read(src)
    except Exception as exc:
        return _fail(
            f"ASE 无法识别 {src!r} 的格式：{exc}.\n"
            f"  支持的格式：POSCAR / CONTCAR / .cif / .xyz / .extxyz / "
            f".pdb / .traj / .json 等。"
        )

    if len(atoms) == 0:
        return _fail(f"{src!r} 里没有原子")
    if atoms.cell.volume < 1e-9:
        return _fail(f"{src!r} 没有周期晶格（晶胞体积为 0），spglib 无法判定空间群")

    # 晶格、分数坐标、原子序数交给 spglib（ASE 与 kb 一致的读法）
    cell = (atoms.cell.array, atoms.get_scaled_positions(), atoms.get_atomic_numbers())
    try:
        ds = spglib.get_symmetry_dataset(cell, symprec=symprec)
    except Exception as exc:
        return _fail(f"spglib 判定失败：{exc}")

    if ds is None:
        detail = ""
        try:
            detail = spglib.get_error_message()
        except Exception:
            pass
        return _fail(
            "spglib 判定失败（返回 None）：可能是 symprec=%g 对当前结构过严，"
            "或结构存在明显的数值噪声/畸变。\n"
            "  常见原因：未优化的坐标、晶胞参数与原子位置不自洽、键长差异过大；"
            "可试 `mt.sh sy 结构文件 1e-2` 放宽容差。%s"
            % (symprec, (" spglib: " + detail) if detail else "")
        )

    number = int(_field(ds, "number"))
    hall_number = int(_field(ds, "hall_number"))
    spacegroup = _field(ds, "international")
    hall_symbol = ""
    try:
        hall_symbol = _field(spglib.get_spacegroup_type(hall_number), "hall_symbol") or ""
    except Exception:
        pass
    pointgroup = _field(ds, "pointgroup")
    zh, en = _crystal_system(number)

    # 原胞 / 惯用胞原子数
    mapping = [int(v) for v in _field(ds, "mapping_to_primitive")]
    n_primitive = len(set(mapping))
    std_map = [int(v) for v in _field(ds, "std_mapping_to_primitive")]
    n_conventional = len(std_map)

    print("结构: %s（%d 个原子）" % (src, len(atoms)))
    print("空间群: %s（No. %d）" % (spacegroup, number))
    print("Hall 编号: %d%s" % (hall_number, ("（%s）" % hall_symbol) if hall_symbol else ""))
    print("点群: %s" % pointgroup)
    print("晶系: %s（%s）" % (zh, en))
    print("原胞原子数: %d   惯用胞原子数: %d" % (n_primitive, n_conventional))
    print("symprec: %g Å（角度容差用 spglib 默认）" % symprec)

    # 按不等价位点分组：优先 crystallographic_orbits，退化到 equivalent_atoms
    groups, order = _orbits(ds)
    print("Wyckoff 位点（%d 个不等价位点）:" % len(order))
    if not order:
        print("  （无）")
        return 0

    # 惯用胞的 Wyckoff 字母/多重度：对标准化晶胞再判一次，得到常规胞里的标注
    std_groups, std_labels = {}, {}
    std_ds = None
    std_lattice = _field(ds, "std_lattice")
    std_positions = _field(ds, "std_positions")
    std_types = _field(ds, "std_types")
    if std_lattice is not None and std_positions is not None and std_types is not None:
        try:
            std_ds = spglib.get_symmetry_dataset(
                (std_lattice, std_positions, std_types), symprec=symprec)
        except Exception:
            std_ds = None
    if std_ds is not None:
        std_groups, std_order = _orbits(std_ds)
        std_wyckoffs = _field(std_ds, "wyckoffs")
        std_sites = _field(std_ds, "site_symmetry_symbols")
        for oid in std_order:
            std_labels[oid] = (std_wyckoffs[std_groups[oid][0]],
                               std_sites[std_groups[oid][0]], len(std_groups[oid]))

    # 输入胞的轨道 <-> 惯用胞的轨道：靠对应的原胞原子编号集合配对
    std_prims = {}
    for oid, idx in std_groups.items():
        std_prims[oid] = set(std_map[j] for j in idx)

    wyckoffs = _field(ds, "wyckoffs")
    site_symmetries = _field(ds, "site_symmetry_symbols")
    for oid in order:
        first = groups[oid][0]
        letter, site_sym, multiplicity = (wyckoffs[first], site_symmetries[first],
                                          len(groups[oid]))
        prims = set(mapping[i] for i in groups[oid])
        for std_oid, std_prim in std_prims.items():
            if std_prim == prims:
                letter, site_sym, multiplicity = std_labels[std_oid]
                break
        symbol = atoms[first].symbol
        indices = [i + 1 for i in groups[oid]]
        print("  %-6s %-8s %-8s 原子序号: %s"
              % ("%d%s" % (multiplicity, letter), site_sym, symbol, _ranges(indices)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
