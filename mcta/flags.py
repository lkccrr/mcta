"""mt 的子命令表、总览、参数转发与绘图配置。

命令行入口与帮助文本在 mcta/__main__.py；这里只提供它需要的表格与函数。
"""

import glob
import os
import platform
import shutil
from pathlib import Path

from mcta import __version__

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
        "key": "seek",
        "name": "mt.seek",
        "what": "MP 结构检索 / 策展",
        "source": "Materials Project API（mp-api）",
        "examples": (
            ("mt.seek -c Ti-C -k 3", "按化学体系检索近稳定相并导出结构包"),
            ("mt.seek -f MoS2 -k 5 -F cif,poscar", "按化学式检索，只留 CIF/POSCAR"),
            ("mt.seek -w \"ehull<=0.05 and is_2d\"", "规则筛选本地已下载结构（-R 预览）"),
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
        "what": "自旋（Ising/Heisenberg）蒙特卡洛模拟，内置晶格或从晶体结构自动构建",
        "source": "内置方形/三角/双层……模型，或任意晶体结构的原子邻居图（需要 numba：pip install mcta[mc]）",
        "examples": (
            ("mt.mc -h", "全部参数"),
            ("mt.mc -x 100 -y 100 -t 35", "方格子 100×100，0–34 K 共 35 个温度"),
            ("mt.mc -s POSCAR -A Fe -D 2.7 3.2 -x 2 -y 2 -z 2", "从 POSCAR 构建超胞 + Fe 原子邻居图，两通道"),
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
    {
        "key": "server",
        "name": "mt.server",
        "what": "本地文件与终端服务：浏览目录、编辑文本、查看图片、SSH 级终端",
        "source": "以当前用户身份运行，可访问该用户有权限的所有文件；每次启动生成随机 token 写入 URL，默认只监听 127.0.0.1",
        "examples": (
            ("mt.server", "后台启动，地址与 token 在启动后打印"),
            ("mt.server -p 8080", "指定端口"),
            ("mt.server -f", "前台运行，Ctrl+C 停止"),
            ("mt.server -S", "停止后台服务"),
        ),
    },
)

# 总览分组：每组两行解释 + 三条示例；TOOLS 仍是完整的命令表（_tool / which 使用）。
GROUPS = (
    {
        "title": "能带 / 态密度绘图",
        "names": "mt.band  mt.dos  mt.phband  mt.phdos",
        "lines": (
            "电子与声子的能带和态密度绘图：band / phband 画能带，dos / phdos 画态密度，可并排、投影或交换坐标轴。",
            "数据来源：vasprun.xml / EIGENVAL / DOSCAR / PROCAR、vaspkit BAND*/PDOS*.dat，以及 phonopy BAND.dat / total_dos.dat。",
        ),
        "examples": (
            ("mt.band -i calc -d", "电子能带 + 态密度并排"),
            ("mt.dos -i calc -p d", "d 轨道投影态密度（Energy 横轴）"),
            ("mt.phband -i BAND.dat -d", "声子能带 + 声子态密度"),
        ),
    },
    {
        "title": "声子流程",
        "names": "mt.ph  mt.ph3",
        "lines": (
            "phonopy / phono3py 流程引导：写计算配置、收集力、求力常数，再衔接声子能带/态密度或热导率。",
            "数据来源：POSCAR / CONTCAR + VASP 力计算输出 vasprun.xml；ph3 另需 POSCAR-unitcell 与位移、力文件。",
        ),
        "examples": (
            ("mt.ph -b -d", "生成 band.conf 与 mesh.conf"),
            ("mt.ph fs vasprun.xml", "由一份力计算求力常数"),
            ("mt.ph3 kappa -m 11 11 11", "RTA 热导率 -> kappa-m*.hdf5"),
        ),
    },
    {
        "title": "结构检索与数据工具",
        "names": "mt.seek  mt.skl  mt.sqs",
        "lines": (
            "从 Materials Project 检索并策展结构，用 scikit-learn 分析结构清单，或生成准随机固溶体 SQS。",
            "数据来源：MP API（需 MP_API_KEY）、exports/*/manifest.csv（离线）、本地晶胞文件；三者共用 MT_SEEK_HOME 工作目录。",
        ),
        "examples": (
            ("mt.seek -c Ti-C -k 3", "按化学体系检索近稳定相"),
            ("mt.skl", "随机森林预测 ehull 与带隙"),
            ('mt.sqs -c cell.vasp -a Cu,Au', "CuAu 等比合金 SQS"),
        ),
    },
    {
        "title": "蒙特卡洛模拟",
        "names": "mt.mc",
        "lines": (
            "自旋（Ising / Heisenberg）蒙特卡洛：内置晶格模型，或从晶体结构的原子邻居图自动构建。",
            "数据来源：内置方形/三角/双层模型或任意晶体结构（POSCAR/CIF）；大体系需 numba（pip install mcta[mc]）。",
        ),
        "examples": (
            ("mt.mc -h", "全部参数"),
            ("mt.mc -x 100 -y 100 -t 35", "方格子 100×100，0–34 K 共 35 个温度"),
            ("mt.mc -s POSCAR -A Fe", "从 POSCAR 构建 Fe 原子邻居图"),
        ),
    },
    {
        "title": "内置脚本",
        "names": "mt.sh",
        "lines": (
            "列出并执行随包分发的 bash 脚本，参数原样转给脚本；本地 ./NAME.sh 优先于内置同名脚本。",
            "脚本来源：mcta/sh/scripts/ 目录；可用 MTSH_SCRIPTS 指定自定义脚本目录。",
        ),
        "examples": (
            ("mt.sh", "列出可用脚本及来源"),
            ("mt.sh xy", "执行内置 xy.sh（参数原样转发）"),
            ("mt.sh po", "执行内置 po.sh（赝势相关）"),
        ),
    },
    {
        "title": "本地文件与终端服务",
        "names": "mt.server",
        "lines": (
            "浏览器里浏览目录、编辑文本、查看图片/PDF/3D 结构，并提供与 SSH 一致的交互式终端。",
            "以当前用户身份运行；每次启动生成随机 token 写入 URL，默认只监听 127.0.0.1，勿将链接分享给他人。",
        ),
        "examples": (
            ("mt.server", "后台启动，地址与 token 在启动后打印"),
            ("mt.server -p 8080", "指定端口"),
            ("mt.server -S", "停止后台服务"),
        ),
    },
)

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
    for group in GROUPS:
        print("  " + group["title"] + "    " + group["names"])
        for line in group["lines"]:
            print("    " + line)
        for command, note in group["examples"]:
            print("      " + _line(command, _ARG_COL) + note)
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
    print("\nMcTa %s %s (python %s)\n" % (__version__, os.path.dirname(os.path.abspath(__file__)),
                                        platform.python_version()))

def which():
    print("McTa %s (python %s)" % (__version__, platform.python_version()))
    names = ("mt",) + tuple(tool["name"] for tool in TOOLS)
    for name in names:
        path = shutil.which(name)
        print("  " + _line(name, 15) + (path or "未找到（当前环境未安装 mt）"))
    return 0 if all(shutil.which(name) for name in names) else 1


# ---------------------------------------------------------------- 绘图配置 ---
# 优先级：环境变量 > ~/.config/mcta/config > 内置默认值。
_CONFIG_FILE = Path.home() / ".config" / "mcta" / "config"


def _read_conf_file(name: str) -> str:
    """从 ~/.config/mcta/config 读一项（KEY=VALUE 行，# 开头为注释）。"""
    try:
        if not _CONFIG_FILE.is_file():
            return ""
        for line in _CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line[0] in "#;" or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip("'\"")
    except OSError:
        pass
    return ""


def _get(name: str, default: str) -> str:
    """环境变量优先，其次配置文件，最后默认值。"""
    return os.environ.get(name) or _read_conf_file(name) or default


def font_family() -> str:
    return _get("MT_FONT_FAMILY", "STIXGeneral")


def mathtext_fontset() -> str:
    return _get("MT_MATHTEXT_FONTSET", "cm")


def resol() -> int:
    return int(_get("MT_RESOL", "500"))


def xtick_direction() -> str:
    return _get("MT_XTICK_DIRECTION", "in")


def ytick_direction() -> str:
    return _get("MT_YTICK_DIRECTION", "in")
