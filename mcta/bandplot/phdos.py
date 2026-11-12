"""mt.phdos：单独绘制声子态密度（Phonon DOS），默认 Frequency 为横轴。

与 ``mt.phband -d`` 的分工：
- ``mt.phdos``      独立成图，横轴 Frequency、纵轴 Phonon DOS（``-n`` 换回纵轴 Frequency）
- ``mt.phband -d``  把声子态密度画在声子能带右侧，与能带共用纵轴 Frequency

数据来源与 mt.phband 相同：phonopy 的 projected_dos.dat 或 total_dos.dat。

用法：
    mt.phdos                     当前目录的 projected_dos.dat / total_dos.dat
    mt.phdos -i calc             指定目录，自动找上面两种文件
    mt.phdos -i dos.dat -o PHDOS.png
    mt.phdos -n                  交换坐标轴（Frequency 为纵轴，与 mt.phband -d 的面板一致）
"""
import argparse
import ast
import glob
import os

import matplotlib.pyplot as plt

from mcta import version_string
from mcta.bandplot import pplots, readdata
from mcta.bandplot.wrapper import cla_fig

plt.rcParams['xtick.direction'] = 'in'
plt.rcParams['ytick.direction'] = 'in'
plt.rcParams['ytick.minor.visible'] = True
plt.rcParams['font.family'] = 'STIXGeneral'
plt.rcParams["mathtext.fontset"] = 'cm'

# phonopy 写出的两种 DOS 文件，projected_dos.dat 优先（列更全）
DOS_FILES = ("projected_dos.dat", "total_dos.dat")


def _pick(directory):
    """在目录里按 DOS_FILES 的顺序找第一个存在的文件，找不到返回 None。"""
    for name in DOS_FILES:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    return None


def _resolve(paths):
    """把 ``-i`` 的取值解析成 ``(dosfile, workdir)``；失败返回 ``(None, None)``。

    目录：找 projected_dos.dat / total_dos.dat；文件：直接用作 DOS 文件。
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
        _error("ERROR: 找不到输入：%s" % ", ".join(missing))
        return None, None
    if dirs and files:
        _error("ERROR: 目录与 .dat 文件不能混在一起，请只给一种。")
        return None, None
    if dirs:
        if len(dirs) > 1:
            _error("ERROR: mt.phdos 一次只画一个体系；对比请分别画图。")
            return None, None
        directory = dirs[0]
        dosfile = _pick(directory)
        if dosfile is None:
            _error("ERROR: %s 里没有 projected_dos.dat 或 total_dos.dat；"
                  "先用 mt.ph dos 生成。" % directory)
            return None, None
        return dosfile, directory
    if not files:
        _error("ERROR: 没有输入文件。")
        return None, None
    if len(files) > 1:
        print("提示：mt.phdos 一次只画一个文件，已使用 %s。" % files[0])
    return files[0], os.path.dirname(os.path.abspath(files[0]))


def _unitcell(workdir):
    """从 POSCAR-unitcell 拿 (原子符号列表, 化学式)；没有就返回 ([], "")。"""
    poscar = os.path.join(workdir, "POSCAR-unitcell")
    if not os.path.exists(poscar):
        return [], ""
    try:
        symbol, factor = readdata.symbols(poscar)
    except Exception:
        return [], ""
    atoms, formula = [], ""
    for sym, num in zip(symbol, factor):
        num = int(num)
        atoms += [sym] * max(num, 1)
        formula += sym
        if num > 1:
            formula += "$_" + str(num) + "$"
    return atoms, formula


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



_ERROR = False


def _error(msg):
    """打印错误并标记本次运行失败，供 main 返回非零退出码。"""
    global _ERROR
    _ERROR = True
    print(msg)
def main(argv=None):
    global _ERROR
    _ERROR = False
    parser = argparse.ArgumentParser(
        description='Plot the phonon density of states (Phonon DOS) from phonopy results; '
                    'the frequency is on the horizontal axis by default.',
        add_help=False,
        epilog='''
Example:
mt.phdos                                         # 当前目录的 projected_dos.dat / total_dos.dat
mt.phdos -i calc                                 # 指定目录，自动找 phonopy 的 DOS 文件
mt.phdos -i calc -o PHDOS.png -z -f 0.55         # 填充曲线、缩小字号
mt.phdos -i calc -x 0 0.6 -y 0 12                # DOS 与频率范围
mt.phdos -i projected_dos.dat -n                 # 交换坐标轴，纵轴 Frequency（同 mt.phband -d 面板）
''',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",       action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version",    action="version",     version=version_string())
    parser.add_argument('-i', "--input",      type=str, nargs='*', default=None, metavar="PATH",
                        help="directory with projected_dos.dat/total_dos.dat, or .dat files; default: current directory")
    parser.add_argument('-o', "--outpt",     type=str, help="plot figure filename, default: PHDOS.png", default="PHDOS.png")
    parser.add_argument('-q', "--resol",        type=int, help="dpi of the figure, default: 500", default=500)
    parser.add_argument('-S', "--figsz",       type=float, nargs=2, help='figure size: width, height', metavar=('width', 'height'))
    parser.add_argument('-y', "--freqs",  type=float, nargs=2, help="frequency (THz) range", metavar=('start', 'end'))
    parser.add_argument('-x', "--horiz", type=float, nargs=2, help="phonon DOS range", metavar=('start', 'end'))
    parser.add_argument('-n', "--exchg",   action='store_true', help="exchange the axes: frequency vertical (mt.phband -d style)")
    parser.add_argument('-e', "--elems",   type=str, nargs='+', default=[], help="PDOS labels")
    parser.add_argument('-G', "--legnd",     type=str, nargs='+', default=[], help="legend labels")
    parser.add_argument('-A', "--locat",   type=str.lower, nargs='+', default=[], help="arrange the legend location, default: best", metavar="str")
    parser.add_argument('-C', "--color",      type=str, nargs='+', default=[], help="line color: b, blue; g, green; r, red; c, cyan; m, magenta; y, yellow; k, black; or a tuple like (0.1,0.2,0.3); a*3 repeats it 3 times", metavar="str")
    parser.add_argument('-k', "--style",  type=str, nargs='+', default=[], help="linestyle: solid, dashed, dashdot, dotted or tuple; default: solid", metavar="str")
    parser.add_argument('-w', "--width",  type=str, nargs='+', default=[], help="linewidth, default: 0.8", metavar="0.8")
    parser.add_argument('-z', "--alpha",       type=float, nargs='?', help='fill a shaded region between PDOS and axis, default: 0.2', default=None, const=0.2, metavar="alpha")
    args = parser.parse_args(argv)

    dosfile, workdir = _resolve(list(args.input) if args.input else ["."])
    if dosfile is None:
        return 1 if _ERROR else 0

    darr, dele = readdata.pdos(dosfile)
    atoms, formula = _unitcell(workdir)
    elements = [str(i) for i in args.elems] or atoms
    legend = list(args.legnd) or [formula or os.path.basename(os.path.abspath(workdir)) or "."]

    location = [int(i) if i.isdigit() else i for i in args.locat]
    fig_p = cla_fig(output=args.outpt, size=args.figsz,
                    # vertical 始终表示频率范围；exchange=True 时频率在横轴
                    vertical=args.freqs,
                    horizontal=args.horiz,
                    color=_expand(args.color), linestyle=_expand(args.style),
                    linewidth=[float(i) for i in _expand(args.width)],
                    location=location, dpi=args.resol, fill=args.alpha,
                    # mt.phdos 默认频率为横轴：pdosfile 里 exchange=True 就是这个朝向
                    exchange=not args.exchg)

    pplots.pdosfile(darr, dele, elements, legend, fig_p)
    print("已保存：" + fig_p.output)
    return 1 if _ERROR else 0


if __name__ == "__main__":
    main()
