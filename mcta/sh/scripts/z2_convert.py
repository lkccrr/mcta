"""z2：ASE 结构格式转换器。

用法：
    mt.sh z2 IN [OUT]
    z2 IN [OUT]

参数：
    IN   输入结构文件（ASE 能读的格式：POSCAR / CONTCAR / *.cif / *.xyz / *.pdb
         / *.traj 等）。格式不识别时报错退出。
    OUT  输出目标，可选。分三种情况：
          · 省略  → 在输入文件同目录、同 stem 下输出 .cif（默认格式）
          · 扩展名（.cif / cif / .xyz …）→ 在输入 stem 后拼上这个扩展名
          · 完整路径（含路径和扩展名）→ 按给出的路径写出，扩展名决定格式

示例：
    mt.sh z2 POSCAR                  # POSCAR → POSCAR.cif
    mt.sh z2 CONTCAR .xyz            # CONTCAR → CONTCAR.xyz
    mt.sh z2 CONTCAR xyz             # CONTCAR → CONTCAR.xyz（自动补点）
    mt.sh z2 POSCAR out.cif          # → out.cif
    mt.sh z2 POSCAR /tmp/si.extxyz   # → /tmp/si.extxyz
"""

import os
import sys

from ase.io import read, write

SYNOPSIS = "用法: mt.sh z2 IN [OUT]（mt.sh z2 -h 查看详细说明）"


# 这些 stem 会被 ASE 特殊路由到 VASP handler（即使扩展名是 .cif 也会写成 VASP）
# 解决：对这些文件显式传 format，让 ASE 按扩展名选 writer
VASP_ROUTED_STEMS = {
    "POSCAR", "CONTCAR", "SPOSCAR",
    "POSCAR.ORIG", "CONTCAR.ORIG",
}

# ASE format 名与扩展名不完全一致的别名映射
FORMAT_ALIAS = {
    ".poscar": "vasp",
    ".vasp": "vasp",
    ".pdb": "proteindatabank",
}


def _extract_format(out_path):
    """从输出路径提取 ASE format 字符串。无扩展名返回 None。"""
    ext = os.path.splitext(out_path)[1].lower()
    if not ext:
        return None
    return FORMAT_ALIAS.get(ext, ext.lstrip("."))


def _fail(message):
    print("ERROR: " + message, file=sys.stderr)
    print(SYNOPSIS, file=sys.stderr)
    return 1


def _resolve_out(in_path, out_arg):
    """根据输入和可选的 out_arg 决定最终输出路径。"""
    stem, _ = os.path.splitext(in_path)
    if out_arg is None:
        return stem + ".cif"

    # 纯扩展名（以 . 开头，或不含 .）
    if out_arg.startswith(".") and "/" not in out_arg and "\\" not in out_arg:
        return stem + out_arg
    if "." not in os.path.basename(out_arg) and "/" not in out_arg and "\\" not in out_arg:
        return stem + "." + out_arg

    # 完整路径
    return out_arg


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

    # 输入
    try:
        atoms = read(src)
    except Exception as exc:
        return _fail(
            f"ASE 无法识别 {src!r} 的格式：{exc}.\n"
            f"  支持：POSCAR / CONTCAR / .cif / .xyz / .extxyz / .pdb / .traj "
            f"等；部分格式需要 pip install pymatgen。"
        )

    # 输出：stem 是 VASP 特殊名时显式传 format，避免被错误路由
    out_stem = os.path.splitext(os.path.basename(out))[0].upper()
    fmt = _extract_format(out)
    try:
        if out_stem in VASP_ROUTED_STEMS and fmt is not None:
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
