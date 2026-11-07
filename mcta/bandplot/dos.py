"""mt.dos：单独绘制态密度（DOS / PDOS），默认 Energy 为横轴。

与 ``mt.band -d`` 的分工：
- ``mt.dos``        独立成图，横轴 Energy、纵轴 DOS（``-n`` 可换回纵轴 Energy）
- ``mt.band -d`` 把 DOS 画在能带图右侧，与能带共用纵轴 Energy

数据来源与 mt.band 相同：VASP 的 DOSCAR（LORBIT = 11），
或 vaspkit 的 PDOS*.dat / TDOS*.dat。

用法：
    mt.dos                       当前目录的 DOSCAR 或 PDOS*.dat
    mt.dos -i calc -p d          只画 d 轨道投影
    mt.dos -i calc -o DOS.png    指定输出文件
    mt.dos -n                    交换坐标轴（Energy 为纵轴，与 mt.band -d 的面板一致）
"""
import argparse
import ast
import glob
import os
import re

import matplotlib.pyplot as plt

from mcta import version_string
from mcta.bandplot import plots, readdata
from mcta.bandplot.wrapper import (cla_fig, _clean_dos_labels,
                                   _dat_dos_files, _is_vasp_dir)

plt.rcParams['xtick.direction'] = 'in'
plt.rcParams['ytick.direction'] = 'in'
plt.rcParams['ytick.minor.visible'] = True
plt.rcParams["mathtext.fontset"] = 'cm'

DEFAULT_ENERGY = [-5.0, 5.0]


def _resolve(paths):
    """把 -i 的取值解析成 ``(mode, target)``：``("vasp", dir)`` 或 ``("dat", [files])``。

    目录：有 DOSCAR 走 VASP，否则找 PDOS*.dat / TDOS*.dat；文件：按 .dat 处理。
    出错时返回 ``(None, None)`` 并打印提示。
    """
    dirs, files, missing = [], [], []
    for value in paths:
        if os.path.isdir(value):
            dirs.append(value)
            continue
        hits = [h for h in sorted(glob.glob(value)) if os.path.isfile(h)]
        if hits:
            files += hits
        else:
            missing.append(value)
    if missing:
        print("ERROR: 找不到输入：%s" % ", ".join(missing))
        return None, None
    if dirs and files:
        print("ERROR: 目录与 .dat 文件不能混在一起，请只给一种。")
        return None, None
    if dirs:
        if len(dirs) > 1:
            print("ERROR: mt.dos 一次只画一个体系；对比请分别画图。")
            return None, None
        directory = dirs[0]
        if os.path.exists(os.path.join(directory, "DOSCAR")):
            return "vasp", directory
        dats = _dat_dos_files(directory)
        if dats:
            return "dat", dats
        if _is_vasp_dir(directory):
            print("ERROR: %s 里没有 DOSCAR；计算时请设置 LORBIT = 11。" % directory)
        else:
            print("ERROR: %s 里没有 DOSCAR、PDOS*.dat 或 TDOS*.dat。" % directory)
        return None, None
    if not files:
        print("ERROR: 没有输入文件。")
        return None, None
    return "dat", sorted(files)


def _formula(workdir):
    """从 POSCAR/CONTCAR 拼化学式（如 Cu$_2$O），拿不到就返回空串。"""
    for name in ("POSCAR", "CONTCAR"):
        poscar = os.path.join(workdir, name)
        if not os.path.exists(poscar):
            continue
        symbol, factor = readdata.symbols(poscar)
        formula = ""
        for sym, num in zip(symbol, factor):
            formula += sym
            if num > 1:
                formula += "$_" + str(num) + "$"
        return formula
    return ""


def _expand(values, literal=False):
    """展开 ``x*3`` 形式的取值；literal=True 时把 ``(r,g,b)`` 之类转成元组。"""
    out = []
    for value in values:
        count = value.split('*')
        if len(count) == 2:
            item = count[0]
            if literal and '(' in item and ')' in item:
                out += [ast.literal_eval(item)] * int(count[1])
            else:
                out += [item] * int(count[1])
        else:
            out += [ast.literal_eval(value)] if literal and '(' in value and ')' in value else [value]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Plot the density of states (DOS/PDOS) from VASP output or vaspkit results; '
                    'the energy is on the horizontal axis by default.',
        add_help=False,
        epilog='''
Example:
mt.dos                                           # 当前目录的 DOSCAR 或 PDOS*.dat，横轴为 Energy
mt.dos -i calc                                   # 指定目录，自动识别 DOSCAR / PDOS*.dat
mt.dos -i calc -p d -x 0 30                      # 只画 d 轨道，DOS 范围 0-30
mt.dos -i calc -o PDOS.png -z                    # 填充曲线
mt.dos -i calc -n                                # 交换坐标轴，纵轴 Energy（同 mt.band -d 面板）
mt.dos -i PDOS*.dat                              # 直接给 vaspkit 的 .dat 文件
''',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",       action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version",    action="version",     version=version_string())
    parser.add_argument('-i', "--input",      type=str, nargs='*', default=None, metavar="PATH",
                        help="directory with DOSCAR or PDOS*.dat/TDOS*.dat, or .dat files; default: current directory")
    parser.add_argument('-o', "--output",     type=str, help="plot figure filename, default: DOS.png", default="DOS.png")
    parser.add_argument('-q', "--dpi",        type=int, help="dpi of the figure, default: 500", default=500)
    parser.add_argument('-S', "--size",       type=float, nargs=2, help='figure size: width, height', metavar=('width', 'height'))
    parser.add_argument('-y', "--energy",     type=float, nargs=2, help="energy (eV) range, default: [-5.0, 5.0]", metavar=('start', 'end'))
    parser.add_argument('-x', "--horizontal", type=float, nargs=2, help="Density of states, electrons/eV range", metavar=('start', 'end'))
    parser.add_argument('-p', "--partial",    type=str, nargs='+', default=[], help='the partial DOS to plot, s p d, or symbol-s,p,d')
    parser.add_argument('-e', "--elements",   type=str, nargs='+', default=[], help="PDOS labels")
    parser.add_argument('-n', "--exchange",   action='store_true', help="exchange the axes: energy vertical (mt.band -d style)")
    parser.add_argument('-G', "--legend",     type=str, nargs='+', default=[], help="legend labels")
    parser.add_argument('-A', "--location",   type=str.lower, nargs='+', default=[], help="arrange the legend location, default: best", metavar="str")
    parser.add_argument('-C', "--color",      type=str, nargs='+', default=[], help="line color: b, blue; g, green; r, red; c, cyan; m, magenta; y, yellow; k, black; or a tuple like (0.1,0.2,0.3); a*3 repeats it 3 times", metavar="str")
    parser.add_argument('-k', "--linestyle",  type=str, nargs='+', default=[], help="linestyle: solid, dashed, dashdot, dotted or tuple; default: solid", metavar="str")
    parser.add_argument('-w', "--linewidth",  type=str, nargs='+', default=[], help="linewidth, default: 0.8", metavar="0.8")
    parser.add_argument('-z', "--fill",       type=float, nargs='?', help='fill a shaded region between PDOS and axis, default: 0.2', default=None, const=0.2, metavar="alpha")
    parser.add_argument('--no-mirror',        action='store_true', help='keep the spin-down DOS positive (default: spin-up > 0, spin-down < 0)')
    parser.add_argument('--no-shift',         action='store_true', help='keep raw energies (do not shift by E-fermi)')
    parser.add_argument('-f', "--font",       type=str, help="font to use", default='STIXGeneral')
    args = parser.parse_args(argv)

    mode, target = _resolve(list(args.input) if args.input else ["."])
    if mode is None:
        return

    if mode == "vasp":
        from mcta.bandplot import vaspread
        vd = vaspread.VaspData(target, shift=not args.no_shift)
        darr, dele, s_elements = vd.dos()
        workdir = target
    else:
        darr, dele, s_elements = readdata.dos(target)
        workdir = os.path.dirname(os.path.abspath(target[0]))

    index_f, labels_elements = readdata.select(s_elements, args.partial)
    if not index_f:
        print("ERROR: 没有匹配的 DOS 列，可用 -p s,p,d 或 -p Mo-d。")
        return

    elements = args.elements or _clean_dos_labels(labels_elements)
    legend = args.legend or [_formula(workdir) or os.path.basename(os.path.abspath(workdir)) or "."]

    location = [int(i) if i.isdigit() else i for i in args.location]
    font = args.font
    plt.rcParams['font.family'] = '%s' % font

    fig_p = cla_fig(output=args.output, size=args.size,
                    # vertical 始终表示能量范围；exchange=True 时能量在横轴
                    vertical=args.energy or list(DEFAULT_ENERGY),
                    horizontal=args.horizontal,
                    color=_expand(args.color), linestyle=_expand(args.linestyle),
                    linewidth=[float(i) for i in _expand(args.linewidth)],
                    location=location, dpi=args.dpi, fill=args.fill,
                    mirror=not args.no_mirror,
                    # mt.dos 默认能量为横轴：pdosfiles 里 exchange=True 就是这个朝向
                    exchange=not args.exchange)

    plots.pdosfiles(darr, dele, index_f, elements, legend, fig_p)
    print("已保存：" + fig_p.output)


if __name__ == "__main__":
    main()
