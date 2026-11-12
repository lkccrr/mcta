"""mt：命令统一入口，负责说明用途并把参数原样转给对应的工具。

    mt                    总览： 命令的用途、常用示例与当前目录的下一步建议
    mt band      [参数]   等价于 mt.band      [参数]
    mt dos       [参数]   等价于 mt.dos       [参数]
    mt phband    [参数]   等价于 mt.phband    [参数]
    mt phdos     [参数]   等价于 mt.phdos     [参数]
    mt ph        [参数]   等价于 mt.ph        [参数]
    mt ph3       [参数]   等价于 mt.ph3       [参数]
    mt seeker    [参数]   等价于 mt.seeker    [参数]
    mt sqs       [参数]   等价于 mt.sqs       [参数]
    mt mc        [参数]   等价于 mt.mc        [参数]
    mt sh        [参数]   等价于 mt.sh        [参数]
"""

import glob
import os
import platform
import shutil
import sys

from mcta import __version__, version_string

# 命令表：短名 -> (可执行文件名, 说明, 数据来源, 示例)
TOOLS = (
    {
        "key": "band",
        "name": "mt.band",
        "what": "电子能带 / 态密度",
        "source": "VASP 的 vasprun.xml、EIGENVAL、DOSCAR、PROCAR，或 vaspkit 的 BAND*/PDOS*.dat",
        "examples": (
            ("mt.band -i calc", "当前目录/指定目录的能带"),
            ("mt.band -i calc -d", "能带 + 态密度（并排）"),
            ("mt.band -i calc -r -p Mo-d", "投影能带（PROCAR）"),
        ),
    },
    {
        "key": "dos",
        "name": "mt.dos",
        "what": "态密度（DOS / PDOS，Energy 为横轴）",
        "source": "VASP 的 DOSCAR，或 vaspkit 的 PDOS*.dat / TDOS*.dat",
        "examples": (
            ("mt.dos -i calc", "DOSCAR 或 PDOS*.dat 画 DOS（横轴 Energy）"),
            ("mt.dos -i calc -p d", "只画 d 轨道投影"),
            ("mt.dos -i calc -n", "交换坐标轴，纵轴 Energy（同 mt.band -d 面板）"),
        ),
    },
    {
        "key": "phband",
        "name": "mt.phband",
        "what": "声子能带",
        "source": "phonopy-bandplot 写出的 BAND.dat（-i 可给多个文件对比）",
        "examples": (
            ("mt.phband -i BAND.dat", "声子能带"),
            ("mt.phband -i BAND.dat -d", "声子能带 + 声子态密度（并排）"),
            ("mt.phband -B 23 100 -y -2 110", "断轴显示光学支"),
        ),
    },
    {
        "key": "phdos",
        "name": "mt.phdos",
        "what": "声子态密度（Frequency 为横轴）",
        "source": "phonopy 的 projected_dos.dat / total_dos.dat",
        "examples": (
            ("mt.phdos", "当前目录的 DOS 文件"),
            ("mt.phdos -i calc -z", "填充曲线"),
            ("mt.phdos -i calc -n", "交换坐标轴，纵轴 Frequency（同 mt.phband -d 面板）"),
        ),
    },
    {
        "key": "ph",
        "name": "mt.ph",
        "what": "phonopy 流程引导",
        "source": "POSCAR/CONTCAR + VASP 力计算输出（vasprun.xml）",
        "examples": (
            ("mt.ph -b -d", "写 band.conf 与 mesh.conf"),
            ("mt.ph fs vasprun.xml", "单份力文件计算力常数"),
            ("mt.ph w --dim", "离线查用法：先英文原文，后中文翻译"),
        ),
    },
    {
        "key": "ph3",
        "name": "mt.ph3",
        "what": "phono3py 热导率流程引导",
        "source": "POSCAR-unitcell + VASP 力计算输出（vasprun.xml）",
        "examples": (
            ("mt.ph3 -s 2 2 2 -S 4 4 4", "fc3/fc2 超胞 + 位移"),
            ("mt.ph3 cf3 -n disp-{00001..00755}", "收集力 -> FORCES_FC3"),
            ("mt.ph3 kappa -m 11 11 11", "RTA 热导率 -> kappa-m*.hdf5"),
        ),
    },
    {
        "key": "seeker",
        "name": "mt.seeker",
        "what": "MP 结构检索 / 策展",
        "source": "Materials Project API（mp-api）",
        "examples": (
            ("mt.seeker -c Ti-C -k 3", "按化学体系检索近稳定相并导出结构包"),
            ("mt.seeker -f MoS2 -k 5 -F cif,poscar", "按化学式检索，只留 CIF/POSCAR"),
            ("mt.seeker -w \"ehull<=0.05 and is_2d\"", "规则筛选本地已下载结构（-R 预览）"),
        ),
    },
    {
        "key": "skl",
        "name": "mt.skl",
        "what": "scikit-learn 结构清单分析",
        "source": "exports/*/manifest.csv（离线，不联网）",
        "examples": (
            ("mt.skl", "随机森林预测 ehull 与带隙，输出 <home>/ml/"),
            ("mt.skl --home .", "指定工作根目录（默认当前目录）"),
        ),
    },
    {
        "key": "sqs",
        "name": "mt.sqs",
        "what": "自定义晶胞 → 准随机固溶体（SQS）",
        "source": "sqsgenerator（C++ 引擎，不联网、不需要 MP_API_KEY）",
        "examples": (
            ("mt.sqs -c cell.vasp -a \"Cu:0.5,Au:0.5\"", "CuAu 等比合金，默认 3³ 超胞 + 10 万次迭代"),
            ("mt.sqs -c LaAlO3.cif --host La -a \"La:0.5,Sr:0.5\"", "A 位随机化，Al/O 保持不变"),
            ("mt.sqs -c cell.vasp -a Cu,Au -R", "预览：只搜索、不写盘"),
        ),
    },
    {
        "key": "mc",
        "name": "mt.mc",
        "what": "自旋（Ising/Heisenberg）蒙特卡洛模拟",
        "source": "内置的方格/三角/双层……模型（需要 numba：pip install \"mcta[mc]\"）",
        "examples": (
            ("mt.mc -h", "全部参数"),
            ("mt.mc -x 100 -y 100 -t 35", "方格子 100×100，0–34 K 共 35 个温度"),
            ("mt.mc -c bilayer-ab -t 0 60 2", "双层 AB 堆垛，0–60 K 扫描"),
        ),
    },
    {
        "key": "sh",
        "name": "mt.sh",
        "what": "执行内置*.sh脚本",
        "source": "随包分发的 scripts/ 目录脚本",
        "examples": (
            ("mt.sh", "列出可用脚本及来源"),
            ("mt.sh xy", "执行内置 xy.sh（参数原样转给脚本）"),
        ),
    },
)

_ALIAS = {
    "band": "band", "bandplot": "band",
    "dos": "dos",
    "phband": "phband", "pbandplot": "phband", "pband": "phband",
    "phdos": "phdos",
    "ph": "ph", "phonon": "ph",
    "ph3": "ph3", "phono3py": "ph3",
    "seeker": "seeker", "search": "seeker",
    "skl": "skl",
    "sqs": "sqs",
    "sh": "sh", "script": "sh",
    "mc": "mc", "ising": "mc", "spins2": "mc",
}

_VASP_MARKS = ("EIGENVAL", "DOSCAR", "PROCAR")
_PHONON_MARKS = ("vasprun.xml", "phonopy_params.yaml", "SPOSCAR",
                 "band.yaml", "band.conf", "mesh.conf", "FORCE_SETS",
                 "FORCE_CONSTANTS", "projected_dos.dat", "total_dos.dat")


def _tool(key):
    for tool in TOOLS:
        if tool["key"] == key:
            return tool
    return None


def _line(text, width=17):
    """把说明文字按命令行宽度对齐（CJK 字符按两列计）。"""
    shown = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
    return text + " " * max(width - shown, 1)


_NAME_COL, _ARG_COL = 17, 32
_IND = " " * (2 + _NAME_COL)


# ------------------------------------------------------------------ 概览 ---
def _detect(directory="."):
    """按当前目录里的文件猜下一步该用哪个命令，返回 (发现, 建议列表)。"""
    found = [n for n in _VASP_MARKS if os.path.exists(os.path.join(directory, n))]
    phonon = [n for n in _PHONON_MARKS if os.path.exists(os.path.join(directory, n))]
    dat = sorted(os.path.basename(p) for pattern in ("BAND.dat", "PBAND*.dat", "PDOS*.dat")
                 for p in glob.glob(os.path.join(directory, pattern)))

    hints = []
    if found:
        if "EIGENVAL" in found:
            hints.append("mt.band -i . -d" if "DOSCAR" in found
                         else "mt.band -i .")
            if "DOSCAR" in found:
                hints.append("mt.dos -i .")
        elif "DOSCAR" in found:
            hints.append("mt.dos")
        else:
            hints.append("mt.band -r -p s,p,d")
    if phonon:
        if any(n in phonon for n in ("band.conf", "mesh.conf")):
            hints.append("mt.ph band" if "band.conf" in phonon else "mt.ph dos")
        elif "phonopy_params.yaml" in phonon:
            hints.append("mt.ph band")
        elif "vasprun.xml" in phonon:
            # vasprun.xml 既可能是能带计算的输出，也可能是声子的力计算
            hints.append("mt.band -i .")
            hints.append("mt.ph -x")
        elif "FORCE_SETS" in phonon or "FORCE_CONSTANTS" in phonon:
            hints.append("mt.ph band")
        if "projected_dos.dat" in phonon or "total_dos.dat" in phonon:
            hints.append("mt.phdos")
    if dat and not found:
        hints.append("mt.band -i ." if any("BAND" in n for n in dat)
                     else "mt.dos")
    return found + phonon + dat, hints


def overview(directory="."):
    for tool in TOOLS:
        print("  " + _line(tool["name"], _NAME_COL) + tool["what"])
        print(_IND + "数据来源：" + tool["source"])
        for command, note in tool["examples"]:
            print(_IND + _line(command, _ARG_COL) + note)
        print()

    print("用法      mt <命令> [参数...]        参数原样转给该命令，如 mt ph -h")
    print("          mt which                   命令的安装位置")
    print()

    found, hints = _detect(directory)
    print("当前目录  %s" % os.path.abspath(directory))
    if found:
        print("发现      " + ", ".join(found))
    if hints:
        print("建议      " + hints[0])
        for hint in hints[1:]:
            print("          " + hint)
    elif not found:
        print("无可识别的 VASP / phonopy 结果文件")
    print("\nmt %s %s (python %s)\n" % (__version__, os.path.dirname(os.path.abspath(__file__)),
                                        platform.python_version()))

def which():
    print("mt %s (python %s)" % (__version__, platform.python_version()))
    names = ("mt",) + tuple(tool["name"] for tool in TOOLS)
    for name in names:
        path = shutil.which(name)
        print("  " + _line(name, 15) + (path or "未找到（当前环境未安装 mt）"))
    return 0 if all(shutil.which(name) for name in names) else 1


# ------------------------------------------------------------------ 转发 ---
def _run(key, argv):
    """在进程内调用对应入口，参数与 ``<命令> [参数]`` 完全一致。"""
    from mcta.bandplot import dos, ph, ph3, phdos, wrapper

    entry = {"band": wrapper.main, "dos": dos.main, "phband": wrapper.pmain,
             "phdos": phdos.main, "ph": ph.main, "ph3": ph3.main}
    if key == "seeker":
        from mcta.seeker import cli as seeker_cli
        entry["seeker"] = seeker_cli.main
    elif key == "skl":
        from mcta.skl import cli as skl_cli
        entry["skl"] = skl_cli.main
    elif key == "sqs":
        from mcta.sqs import cli as sqs_cli
        entry["sqs"] = sqs_cli.main
    elif key == "sh":
        from mcta.sh import cli as sh_cli
        entry["sh"] = sh_cli.main
    elif key == "mc":
        from mcta.mc import wrapper as mc_wrapper
        entry["mc"] = mc_wrapper.main
    name = _tool(key)["name"]
    saved = sys.argv
    sys.argv = [name] + list(argv)
    try:
        return entry[key]()
    finally:
        sys.argv = saved


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        overview()
        return 0

    head, rest = args[0], args[1:]
    if head in ("-h", "-H", "--help", "help"):
        print((__doc__ or "").strip())
        print("\nmt <命令> < " + " | ".join(t["key"] for t in TOOLS) + " > -h 查看该命令的参数")
        return 0
    if head in ("-v", "-V", "--version", "version"):
        print(version_string())
        return 0
    if head in ("which", "where"):
        return which()

    key = _ALIAS.get(head)
    if key is None:
        print("ERROR: 未知命令 %r。" % head)
        print("可用：mt / mt band / mt dos / mt phband / mt phdos / mt ph / mt ph3 / mt seeker / mt skl / mt sqs / mt sh / mt mc / mt which / mt -v/-V")
        return 2
    result = _run(key, rest)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
