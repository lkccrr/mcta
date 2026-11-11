import ast, argparse, os, re, platform, glob
import matplotlib.pyplot as plt
from mcta.bandplot import plots, pplots, readdata
from mcta import version_string

plt.rcParams['xtick.direction'] = 'in'
plt.rcParams['ytick.direction'] = 'in'
plt.rcParams['ytick.minor.visible'] = True
plt.rcParams['font.family'] = 'STIXGeneral'
plt.rcParams["mathtext.fontset"] = 'cm'

class cla_fig:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

# ---------------------------------------------------------------- inputs ---
# 一个目录里只要有下面任一文件，就按 VASP 输出处理，否则找 vaspkit 的 *.dat
# （OUTCAR 单独存在时什么也画不了，故不计入判定）
_VASP_MARKERS = ("EIGENVAL", "DOSCAR", "PROCAR")
# vasprun.xml 在 phonopy 的力计算目录里也很常见，只有目录中没有声子结果时
# 才把它当作 VASP 输出（能带由 ASE 从 vasprun.xml 解析）
_PHONON_MARKERS = ("band.yaml", "BAND.dat", "projected_dos.dat",
                   "phonopy_params.yaml", "band.conf", "mesh.conf",
                   "FORCE_SETS", "FORCE_CONSTANTS")

def _is_vasp_dir(directory):
    if any(os.path.exists(os.path.join(directory, name)) for name in _VASP_MARKERS):
        return True
    if not os.path.exists(os.path.join(directory, "vasprun.xml")):
        return False
    return not any(os.path.exists(os.path.join(directory, name))
                   for name in _PHONON_MARKERS)

def _dat_band_files(directory):
    """vaspkit 风格的能带文件：BAND.dat 优先，其次 PBAND*.dat（投影能带）。"""
    native = os.path.join(directory, "BAND.dat")
    if os.path.exists(native):
        return [native]
    return sorted(glob.glob(os.path.join(directory, "PBAND*.dat")))

def _dat_dos_files(directory):
    files = sorted(glob.glob(os.path.join(directory, "PDOS*.dat")))
    if not files:
        files = sorted(glob.glob(os.path.join(directory, "TDOS*.dat")))
    return files

def _expand_dos(values):
    """-d 的取值：目录取其中的 DOS 文件，其余按通配符展开。"""
    files = []
    for value in values:
        if os.path.isdir(value):
            files += _dat_dos_files(value)
        else:
            files += sorted(glob.glob(value))
    return files

def _expand_inputs(paths):
    dirs, files, missing = [], [], []
    for value in paths:
        if os.path.isdir(value):
            dirs.append(value)
            continue
        hits = sorted(glob.glob(value))
        if hits:
            files += hits
        else:
            missing.append(value)
    return dirs, files, missing

def resolve_inputs(paths):
    """把 -i 的取值解析成 ``(mode, dirs, bandfiles, dosfiles)``。

    目录按内容自动判定：有 EIGENVAL/DOSCAR/PROCAR/vasprun.xml 走 VASP，
    否则找 BAND.dat / PBAND*.dat / PDOS*.dat。出错时 mode 为 None。
    """
    dirs, files, missing = _expand_inputs(paths)
    if missing:
        _error("ERROR: 找不到输入：%s" % ", ".join(missing))
        return None, [], [], []
    if dirs and files:
        _error("ERROR: 目录与 .dat 文件不能混在一起比较，请分开指定。")
        return None, [], [], []
    if dirs:
        vasp = [d for d in dirs if _is_vasp_dir(d)]
        if vasp and len(vasp) != len(dirs):
            others = [d for d in dirs if d not in vasp]
            _error("ERROR: 目录类型不一致：%s 是 VASP 输出，%s 里只有 .dat。"
                  % (", ".join(vasp), ", ".join(others)))
            return None, [], [], []
        if vasp:
            return "vasp", vasp, [], []
        band = [f for d in dirs for f in _dat_band_files(d)]
        dos = [f for d in dirs for f in _dat_dos_files(d)]
        if not band and not dos:
            _error("ERROR: %s 里既没有 VASP 输出（EIGENVAL/DOSCAR/PROCAR/vasprun.xml），"
                  "也没有 BAND.dat / PBAND*.dat / PDOS*.dat。" % ", ".join(dirs))
            return None, [], [], []
        return "dat", dirs, band, dos
    workdir = os.path.dirname(os.path.abspath(files[0])) if files else "."
    return "dat", [], files, _dat_dos_files(workdir)

# mt.band

_ERROR = False


def _error(msg):
    """打印错误并标记本次运行失败，供 main 返回非零退出码。"""
    global _ERROR
    _ERROR = True
    print(msg)
def main():
    global _ERROR
    _ERROR = False
    parser = argparse.ArgumentParser(description='Plot the band structure or DOS from VASP output or vaspkit result.',
                                     add_help=False,
                                     epilog='''
Example:
mt.band                                      # 当前目录：自动找 VASP 输出或 BAND.dat 画能带
mt.band -i calc                              # 指定目录，自动识别 VASP 输出 / *.dat
mt.band -i calc -d                           # 能带 + DOS（DOSCAR 或 PDOS*.dat）
mt.band -d                                   # 只画 DOS
mt.band -i calc -r -p Mo-d -y -3 3           # 投影能带（PROCAR / PBAND*.dat）
mt.band -i pbe hse                           # 两个目录对比能带
mt.band -i BAND.dat -d PDOS*.dat             # 处理vaspkit输出的.dat文件
''',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",       action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version",    action="version",     version=version_string())
    parser.add_argument('-S', "--figsz",       type=float, nargs=2,  help='figure size: width, height', metavar=('width','height'))
    parser.add_argument('-D', "--divid",    action='store_true',  help="plot the up and down spin in divided subplot")
    parser.add_argument('-y', "--vrang",   type=float, nargs=2,  help="energy (eV) range, default: [-5.0, 5.0]", metavar=('start','end'))
    parser.add_argument('-G', "--legnd",     type=str,             nargs='+', help="legend labels", default=[])
    parser.add_argument('-A', "--locat",   type=str.lower,       nargs='+', help="arrange the legend location, default: best", default=[], metavar="str")
    parser.add_argument('-C', "--color",      type=str,             nargs='+', help="line color: b, blue; g, green; r, red; c, cyan; m, magenta; y, yellow;"+
                                                                                    "k, black; w, white", default=[], metavar="clrs")
    parser.add_argument('-k', "--style",  type=str,             nargs='+', help="linestyle: solid, dashed, dashdot, dotted or tuple; default: solid",
                                                                                    default=[], metavar="str")
    parser.add_argument('-w', "--width",  type=str,             nargs='+', help="linewidth, default: 0.8", default=[], metavar="0.8")
    parser.add_argument('-m', "--emass",       type=float,           nargs='?', help='calculate the effective masses, default: 0.15', default=None, const=0.15,
                                                                                    metavar="scale")
    parser.add_argument('-r', "--projs",  action='store_true',  help='plot the projected band structure')
    parser.add_argument('-i', "--input",      type=str,             nargs='*', default=None, metavar="PATH", help="directory with VASP output (EIGENVAL/DOSCAR/PROCAR/vasprun.xml) or vaspkit *.dat files; " "auto-detected, default: current directory. Give 2 or 3 directories to compare")
    parser.add_argument('-o', "--outpt",     type=str,             help="plot figure filename, default: BAND.png", default="BAND.png")
    parser.add_argument('-q', "--resol",        type=int,             help="dpi of the figure, default: 500", default=500)
    parser.add_argument('--klabels',          type=str,             help="filename of KLABELS, default: KLABELS", default="KLABELS")
    parser.add_argument('-l', "--label",     type=str.upper,       nargs='+', default=[], help='labels for high-symmetry points, such as X S Y K M')
    parser.add_argument('-d', "--dospl",        type=str,             nargs='*', default=None, help="also plot DOS (from DOSCAR or PDOS*.dat/TDOS.dat); no value means auto-detect")
    parser.add_argument('--vasp',             type=str,             nargs='+', metavar='DIR',
                    help='(legacy) same as -i DIR; kept for backward compatibility')
    parser.add_argument('--no-shift',         action='store_true',  help='keep raw energies (do not shift by E-fermi)')
    parser.add_argument('--keep-weights',      action='store_true',  help='keep the k points with a non-zero weight (e.g. the SCF mesh of an HSE run) instead of only the band path')
    parser.add_argument('--export-dat',       type=str,             nargs='?', const='', default=None, metavar='DIR',
                    help='also write vaspkit-style BAND.dat/KLABELS/PDOS files into DIR (default: the VASP directory)')
    parser.add_argument('-x', "--horiz", type=float, nargs=2,  help="Density of states, electrons/eV range", metavar=('start','end'))
    parser.add_argument('-n', "--exchg",   action='store_true',  help="exchange the x and y axes of DOS")
    parser.add_argument('-p', "--parts",    type=str,             nargs='+', default=[], help='the partial DOS to plot, s p d, or symbol-s,p,d')
    parser.add_argument('-e', "--elems",   type=str,             nargs='+', default=[], help="PDOS labels")
    parser.add_argument('-W', "--ratio",    type=float,           help='width ratio for DOS subplot')
    parser.add_argument('-z', "--alpha",       type=float,           nargs='?', help='fill a shaded region between PDOS and axis, default: 0.2', default=None, const=0.2, metavar="alpha")
    parser.add_argument('--no-mirror',        action='store_true',  help='keep the spin-down DOS positive (default: spin-up > 0, spin-down < 0)')

    args = parser.parse_args()

    if args.vasp:                       # 旧写法 --vasp DIR 等价于 -i DIR
        args.input = (list(args.input) if args.input else []) + list(args.vasp)

    want_bands = args.input is not None
    want_dos = args.dospl is not None
    if not want_bands and not want_dos:
        want_bands = True               # 不带参数：只画能带

    mode, dirs, bandfiles, autodos = resolve_inputs(list(args.input) if args.input else ["."])
    if mode is None:
        return 1 if _ERROR else 0

    dosfiles = None
    if want_dos:
        if mode == "vasp":
            if args.dospl:
                print("提示：VASP 目录直接用 DOSCAR，忽略 -d 后面的文件。")
        elif args.dospl:
            dosfiles = _expand_dos(args.dospl)
            if not dosfiles:
                _error("ERROR: -d 没找到 DOS 文件：%s" % " ".join(args.dospl))
                return 1 if _ERROR else 0
        else:
            dosfiles = autodos or _dat_dos_files(".")
            if not dosfiles:
                _error("ERROR: 没有找到 PDOS*.dat 或 TDOS*.dat；请用 -d 指定文件。")
                return 1 if _ERROR else 0
    if not want_bands:
        bandfiles = []

    labels = [re.sub("'|‘|’", '′', re.sub('"|“|”', '″', re.sub('^GA[A-Z]+$|^G$', 'Γ', i))) for i in args.label]
    elements = [re.sub("'|‘|’", '′', re.sub('"|“|”', '″', i)) for i in args.elems]
    if dosfiles:
        dosfiles.sort()

    color = []
    for i in args.color:
        j = i.split('*')
        if len(j) == 2:
            color += [ast.literal_eval(j[0])] * int(j[1]) if '(' in j[0] and ')' in j[0] else [j[0]] * int(j[1])
        else:
            color += [ast.literal_eval(i)] if '(' in i and ')' in i else [i]

    linestyle = []
    for i in args.style:
        j = i.split('*')
        if len(j) == 2:
            linestyle += [ast.literal_eval(j[0])] * int(j[1]) if '(' in j[0] and ')' in j[0] else [j[0]] * int(j[1])
        else:
            linestyle += [ast.literal_eval(i)] if '(' in i and ')' in i else [i]

    linewidth = []
    for i in args.width:
        j = i.split('*')
        linewidth += [float(j[0])] * int(j[1]) if len(j) == 2 else [float(i)]

    # 数据所在的目录（-i 给了目录就用它，否则用第一个 .dat 的目录，再否则当前目录）
    if dirs:
        workdir = dirs[0]
    elif bandfiles:
        workdir = os.path.dirname(os.path.abspath(bandfiles[0]))
    elif dosfiles:
        workdir = os.path.dirname(os.path.abspath(dosfiles[0]))
    else:
        workdir = os.getcwd()

    pltname = os.path.split(os.path.abspath(workdir))[-1]
    formula = ''
    poscar = os.path.join(workdir, 'POSCAR')
    if not os.path.exists(poscar):
        poscar = os.path.join(workdir, 'CONTCAR')
    if os.path.exists(poscar):
        symbol, factor = readdata.symbols(poscar)
        for i in range(len(symbol)):
            if factor[i] > 1:
                formula = formula + symbol[i]
                for j in str(factor[i]):
                    formula = formula + '$_'+ j + '$'
            else:
                formula = formula + symbol[i]

    legend = args.legnd or ([formula] if formula else [pltname])

    ticks   = []
    klabels = []
    klabels_file = args.klabels
    if not os.path.exists(klabels_file):
        candidate = os.path.join(workdir, args.klabels)
        if os.path.exists(candidate):
            klabels_file = candidate
    if os.path.exists(klabels_file):
        ticks, klabels = readdata.klabels(klabels_file)

    if len(labels) == 0:
        labs=[re.sub('GAMMA|Gamma|G', 'Γ', re.sub('Undefined|Un|[0-9]', '', i)) for i in klabels]

    if len(ticks) > len(labels):
        labels += [''] * (len(ticks) - len(labels))
    elif len(ticks) < len(labels):
        labels = labels[:len(ticks)]

    width_ratios = args.ratio or (0.3 if args.divid else 0.5)
    location = [int(i) if i.isdigit() else i for i in args.locat]

    fig_p = cla_fig(output=args.outpt, size=args.figsz, vertical=args.vrang, horizontal=args.horiz,
                    color=color, linestyle=linestyle, linewidth=linewidth, location=location, dpi=args.resol,
                    width_ratios=width_ratios, exchange=args.exchg, fill=args.alpha,
                    mirror=not args.no_mirror)
    if args.projs and args.dospl is not None:
        print("提示：投影能带暂不支持与 DOS 同图，已忽略 -d。")
# VASP 输出为默认通路；只有目录里没有 VASP 文件时才走 .dat
    if mode == "vasp":
        vasp_plot(dirs, args, labels, elements, fig_p, want_bands=want_bands)
        return 1 if _ERROR else 0
# calculate the effective masses
    if args.emass is not None:
        if not fig_p.vertical:
            fig_p.vertical = [-5.0, 5.0]
        _dat_mass(workdir, args, ticks, labels, legend, fig_p)
# plot Projected Band Structure
    elif args.projs:
        if not fig_p.vertical:
            fig_p.vertical = [-5.0, 5.0]
        bandfile = [f for f in bandfiles if os.path.basename(f).startswith('PBAND')]
        if not bandfile:
            bandfile = sorted(glob.glob(os.path.join(workdir, 'PBAND*.dat')))
        if not bandfile:
            _error("ERROR: 没有 PBAND*.dat；投影能带需要 vaspkit 321 或 --export-dat。")
            return 1 if _ERROR else 0
        if bandfile:
            from mcta.bandplot import projected
            try:
                darr, dbands, composition, s_elements = projected.bands(bandfile)
            except ValueError as e:
                _error("ERROR: %s" % e)
                return 1 if _ERROR else 0
            index_f, labels_elements = projected.select(s_elements, args.parts)
            if len(index_f) > 0:
                ispin = [0 if s_elements[i][0].endswith('_DW') else 1 for i, j in index_f]
                if not elements:
                    elements = labels_elements
                if all(x == ispin[0] for x in ispin):
                    projected.pplot(darr, dbands, composition, ticks, labels, index_f, elements, legend, fig_p)
                else:
                    projected.pplot2(darr, dbands, composition, ticks, labels, index_f, elements, ispin, legend, fig_p)
            else:
                _error("ERROR: -p %s 没有匹配到任何投影；"
                      "可用 -p Mo-d（元素-轨道）、-p d（按轨道）、-p all。"
                      % " ".join(args.parts))
# plot Band Structure
    else:
        bandfile = list(bandfiles)
        len_bandfile = len(bandfile)
        if len_bandfile == 1:
            if not fig_p.vertical:
                fig_p.vertical = [-5.0, 5.0]
            arr, bands, ispin = readdata.bands(bandfile[0])
            if not dosfiles:
                if ispin == "Noneispin":
                    plots.Noneispin(arr, bands, ticks, labels, legend, fig_p)
                elif ispin == "Ispin" and not args.divid:
                    plots.Ispin(arr, bands, ticks, labels, legend, fig_p)
                elif ispin == "Ispin" and args.divid:
                    plots.Dispin(arr, bands, ticks, labels, legend, fig_p)
            else:
                darr, dele, s_elements = readdata.dos(dosfiles)
                index_f, labels_elements = readdata.select(s_elements, args.parts)
                if not elements:
                    elements = labels_elements
                if ispin == "Noneispin":
                    plots.NoneispinWd(arr, bands, ticks, labels, darr, dele, index_f, elements, legend, fig_p)
                elif ispin == "Ispin" and not args.divid:
                    plots.IspinWd(arr, bands, ticks, labels, darr, dele, index_f, elements, legend, fig_p)
                elif ispin == "Ispin" and args.divid:
                    plots.DispinWd(arr, bands, ticks, labels, darr, dele, index_f, elements, legend, fig_p)
            print("已保存：" + fig_p.output)
# plot DOS
        elif len_bandfile == 0:
            if dosfiles:
                if fig_p.output == "BAND.png":
                    fig_p.output = "DOS.png"
                darr, dele, s_elements = readdata.dos(dosfiles)
                index_f, labels_elements = readdata.select(s_elements, args.parts)
                if not elements:
                    elements = labels_elements
                plots.pdosfiles(darr, dele, index_f, elements, legend, fig_p)
                print("已保存：" + fig_p.output)
                print("提示：只画 DOS 可用 mt.dos（默认 Energy 为横轴）。")
            else:
                _error("ERROR: 没有能带数据（EIGENVAL / BAND.dat / PBAND*.dat）；若只想看 DOS 请加 -d。")
# compare two Band Structures
        elif len_bandfile == 2:
            if not fig_p.vertical:
                fig_p.vertical = [-5.0, 5.0]
            arr =   [''] * 2
            bands = [''] * 2
            ispin = [''] * 2
            arr[0], bands[0], ispin[0] = readdata.bands(bandfile[0])
            arr[1], bands[1], ispin[1] = readdata.bands(bandfile[1])
            if len(legend) < 3:
                legend = legend + [''] * (3 - len(legend))

            if all(x == "Noneispin" for x in ispin):
                plots.Noneispin2(arr, bands, ticks, labels, legend, fig_p)
            elif all(x == "Ispin" for x in ispin):
                plots.Dispin2(arr, bands, ticks, labels, legend, fig_p)
            else:
                _error("ERROR: 两个体系的自旋设置不一致（ISPIN=1 与 ISPIN=2）。")
                return 1 if _ERROR else 0
            print("已保存：" + fig_p.output)
# compare three Band Structures
        elif len_bandfile == 3:
            if not fig_p.vertical:
                fig_p.vertical = [-5.0, 5.0]
            arr =   [''] * 3
            bands = [''] * 3
            ispin = [''] * 3
            arr[0], bands[0], ispin[0] = readdata.bands(bandfile[0])
            arr[1], bands[1], ispin[1] = readdata.bands(bandfile[1])
            arr[2], bands[2], ispin[2] = readdata.bands(bandfile[2])
            if len(legend) < 4:
                legend = legend + [''] * (4 - len(legend))

            if all(x == "Noneispin" for x in ispin):
                plots.Noneispin3(arr, bands, ticks, labels, legend, fig_p)
            elif all(x == "Ispin" for x in ispin):
                plots.Dispin3(arr, bands, ticks, labels, legend, fig_p)
            else:
                _error("ERROR: 三个体系的自旋设置不一致（ISPIN=1 与 ISPIN=2）。")
                return 1 if _ERROR else 0
            print("已保存：" + fig_p.output)
        else:
            print("Input file mismatch.")

# VASP direct mode (EIGENVAL / PROCAR / DOSCAR / OUTCAR / KPOINTS / POSCAR)
    return 1 if _ERROR else 0
def _vasp_formula(structure):
    formula = ''
    for name, count in zip(structure["species"], structure["counts"]):
        formula += name
        if count > 1:
            for digit in str(count):
                formula += '$_' + digit + '$'
    return formula

def _vasp_ticks(vd, labels, arr):
    ticks, klabels = vd.ticks_labels()
    if labels:
        names = list(labels)
    else:
        names = [re.sub('GAMMA|Gamma|G', 'Γ', re.sub('Undefined|Un|[0-9]', '', str(i))) for i in klabels]
    if not ticks:
        end = arr[-1] if arr is not None and len(arr) else 1.0
        return [0.0, end], ['', '']
    if len(ticks) > len(names):
        names += [''] * (len(ticks) - len(names))
    elif len(ticks) < len(names):
        names = names[:len(ticks)]
    return ticks, names

def _print_mass(values):
    print("{:<8}{:<8}{:<8}{:<8}{:<8}{:<8}".format("e_x","e_y","h1_x","h1_y","h2_x","h2_y"))
    for i in values:
        if isinstance(i, float):
            print("{:<8.3f}".format(i), end='')
        else:
            print("{:<8s}".format('-'), end='')
    print()

def _dat_mass(workdir, args, ticks, labels, legend, fig_p):
    """vaspkit 通路的有效质量：BAND_GAP 里的文件名是相对路径，先切到数据目录。"""
    from mcta.bandplot import mass
    band_gap = os.path.join(workdir, "BAND_GAP")
    if not os.path.exists(band_gap):
        _error("ERROR: BAND_GAP file does not exist in %s." % workdir)
        return
    scale = 0.15 if args.emass > 0.75 or args.emass < 0.05 else args.emass
    caller = os.getcwd()
    if not os.path.isabs(fig_p.output):
        fig_p.output = os.path.join(caller, fig_p.output)
    try:
        os.chdir(workdir)
        lumo, homo, homo_c, filename = mass.get_vbm_cbm("BAND_GAP")
        extension = [len(lumo), len(homo), len(homo_c), len(filename)]
        if not all(x == 1 for x in extension) and not all(x == 2 for x in extension):
            _error("ERROR: Input file mismatch.")
            return
        data = mass.bs_dat_read(filename)
        if all(x == 1 for x in extension):
            calM = mass.dat_read(data[0], lumo[0], homo[0], homo_c[0], scale)
            pltlabel = mass.npfit(calM)
            mass.plot(data[0], calM, pltlabel, ticks, labels, legend, fig_p)
            _print_mass(pltlabel)
        else:
            calM_u = mass.dat_read(data[0], lumo[0], homo[0], homo_c[0], scale)
            calM_d = mass.dat_read(data[1], lumo[1], homo[1], homo_c[1], scale)
            pltlabel_u = mass.npfit(calM_u)
            pltlabel_d = mass.npfit(calM_d)
            mass.plot2(data, calM_u, pltlabel_u, calM_d, pltlabel_d, ticks, labels, legend, fig_p)
            _print_mass(pltlabel_u)
            _print_mass(pltlabel_d)
    finally:
        os.chdir(caller)

def _vasp_mass(vd, args, ticks, labels, legend, fig_p):
    from mcta.bandplot import mass
    if not fig_p.vertical:
        fig_p.vertical = [-5.0, 5.0]
    scale = 0.15 if args.emass > 0.75 or args.emass < 0.05 else args.emass
    if vd.distances.size < 12:
        _error("ERROR: k 点只有 %d 个，太稀疏，无法做带边抛物线拟合。" % vd.distances.size)
        return
    data, pairs = vd.mass_data()
    for homo, lumo in pairs:
        if homo < 1 or lumo >= data[0].shape[1] - 1:
            _error("ERROR: 带边落在首/末条能带，无法做抛物线拟合；请检查费米能与能带范围。")
            return
    if len(pairs) == 1:
        homo, lumo = pairs[0]
        calM = mass.dat_read(data[0], lumo, homo, homo - 1, scale)
        pltlabel = mass.npfit(calM)
        mass.plot(data[0], calM, pltlabel, ticks, labels, legend, fig_p)
        _print_mass(pltlabel)
    else:
        (homo_u, lumo_u), (homo_d, lumo_d) = pairs
        calM_u = mass.dat_read(data[0], lumo_u, homo_u, homo_u - 1, scale)
        calM_d = mass.dat_read(data[1], lumo_d, homo_d, homo_d - 1, scale)
        pltlabel_u = mass.npfit(calM_u)
        pltlabel_d = mass.npfit(calM_d)
        import numpy as np
        mass.plot2(np.array(data), calM_u, pltlabel_u, calM_d, pltlabel_d, ticks, labels, legend, fig_p)
        _print_mass(pltlabel_u)
        _print_mass(pltlabel_d)
    print("已保存：" + fig_p.output)

def _vasp_projected(vd, args, ticks, labels, legend, fig_p):
    from mcta.bandplot import projected
    if not vd.has("procar"):
        _error("ERROR: 目录中没有 PROCAR；投影能带请在计算中设置 LORBIT = 11。")
        return
    if not fig_p.vertical:
        fig_p.vertical = [-5.0, 5.0]
    darr, dbands, composition, s_elements = vd.projected()
    index_f, labels_elements = projected.select(s_elements, args.parts)
    if not index_f:
        _error("ERROR: 投影筛选无匹配，可用 -p Mo-d、-p d 或 -p all。")
        return
    ispin = [0 if s_elements[i][0].endswith('_DW') else 1 for i, j in index_f]
    elements = args.elems or [re.sub(r'-\$tot\$$', '', i).replace('(dw)', '(down)')
                                     for i in labels_elements]
    if all(x == ispin[0] for x in ispin):
        projected.pplot(darr, dbands, composition, ticks, labels, index_f, elements, legend, fig_p)
    else:
        projected.pplot2(darr, dbands, composition, ticks, labels, index_f, elements, ispin, legend, fig_p)
    print("已保存：" + fig_p.output)

def _clean_dos_labels(labels):
    cleaned = []
    for text in labels:
        text = text.replace('$', '')
        if text.startswith('TDOS-'):
            suffix = text[5:]
            text = 'Total' if suffix.lower() == 'total' else 'Total (%s)' % suffix
        else:
            text = re.sub(r'-tot(?=\s|$)', '', text)
        cleaned.append(text.replace('(dw)', '(down)'))
    return cleaned

def _vasp_dos(vd, args, elements, ticks, labels, legend, fig_p, bands=True):
    from mcta.bandplot import plots, readdata
    if not vd.has("doscar"):
        _error("ERROR: 目录中没有 DOSCAR；请设置 LORBIT = 11 并保留 DOSCAR。")
        return
    darr, dele, s_elements = vd.dos()
    index_f, labels_elements = readdata.select(s_elements, args.parts)
    if not index_f:
        _error("ERROR: 没有匹配的 DOS 列，可用 -p s,p,d 或 -p Mo-d。")
        return
    if not elements:
        elements = _clean_dos_labels(labels_elements)
    if not bands:
        if fig_p.output == "BAND.png":
            fig_p.output = "DOS.png"
        plots.pdosfiles(darr, dele, index_f, elements, legend, fig_p)
        print("已保存：" + fig_p.output)
        print("提示：只画 DOS 可用 mt.dos（默认 Energy 为横轴）。")
        return
    arr, ban, ispin = vd.bands()
    if ispin == "Noneispin":
        plots.NoneispinWd(arr, ban, ticks, labels, darr, dele, index_f, elements, legend, fig_p)
    elif not args.divid:
        plots.IspinWd(arr, ban, ticks, labels, darr, dele, index_f, elements, legend, fig_p)
    else:
        plots.DispinWd(arr, ban, ticks, labels, darr, dele, index_f, elements, legend, fig_p)
    print("已保存：" + fig_p.output)

def vasp_plot(dirs, args, labels, elements, fig_p, want_bands=True):
    from mcta.bandplot import plots, vaspread
    for directory in dirs:
        if not os.path.isdir(directory):
            _error("ERROR: %s is not a directory." % directory)
            return
    datas = [vaspread.VaspData(d, shift=not args.no_shift,
                                drop_weighted=not args.keep_weights) for d in dirs]

    if args.export_dat is not None:
        targets = [args.export_dat or d for d in dirs]
        if len(targets) > 1:
            targets = [os.path.join(t, os.path.basename(os.path.abspath(d)))
                       for t, d in zip(targets, dirs)]
        for vd, target in zip(datas, targets):
            if not vd.has("eigenval") and not vd.has("doscar"):
                _error("ERROR: %s 中既没有 EIGENVAL/vasprun.xml 也没有 DOSCAR。" % vd.dir)
                continue
            written = vd.export_dat(target)
            print("已导出 %d 个文件到 %s" % (len(written), target))

    formulas = [_vasp_formula(vd.structure) or os.path.basename(os.path.abspath(vd.dir))
                for vd in datas]
    if args.legnd:
        legend = list(args.legnd)
    elif len(datas) == 1:
        legend = [formulas[0]]
    else:
        legend = [formulas[0]] + formulas

    if len(datas) == 1:
        vd = datas[0]
        if want_bands and not vd.has("eigenval"):
            if args.dospl is not None:
                print("提示：%s 中没有 EIGENVAL/vasprun.xml，改为只画 DOS。" % vd.dir)
                want_bands = False
            else:
                _error("ERROR: %s 中没有 EIGENVAL/vasprun.xml，无法绘制能带；若只想看 DOS 请加 -d。" % vd.dir)
                return
        has_bands = want_bands and vd.has("eigenval")
        arr = vd.distances if has_bands else None
        if has_bands:
            ticks, names = _vasp_ticks(vd, labels, arr)
        else:
            ticks, names = [0.0, 1.0], ['', '']
        if args.emass is not None:
            if not has_bands:
                _error("ERROR: 有效质量需要 EIGENVAL 或 vasprun.xml。")
                return
            _vasp_mass(vd, args, ticks, names, legend, fig_p)
        elif args.projs:
            _vasp_projected(vd, args, ticks, names, legend, fig_p)
        elif args.dospl is not None:
            _vasp_dos(vd, args, elements, ticks, names, legend, fig_p, bands=has_bands)
        else:
            arr, ban, ispin = vd.bands()
            if not fig_p.vertical:
                fig_p.vertical = [-5.0, 5.0]
            if ispin == "Noneispin":
                plots.Noneispin(arr, ban, ticks, names, legend, fig_p)
            elif not args.divid:
                plots.Ispin(arr, ban, ticks, names, legend, fig_p)
            else:
                plots.Dispin(arr, ban, ticks, names, legend, fig_p)
            print("已保存：" + fig_p.output)
        return

    if len(datas) > 3:
        _error("ERROR: 最多支持 3 个目录对比。")
        return
    arrs, bandss, ispins = [], [], []
    for vd in datas:
        if not vd.has("eigenval"):
            _error("ERROR: %s 中没有 EIGENVAL/vasprun.xml。" % vd.dir)
            return
        arr, ban, ispin = vd.bands()
        arrs.append(arr)
        bandss.append(ban)
        ispins.append(ispin)
    ticks, names = _vasp_ticks(datas[0], labels, arrs[0])
    if not fig_p.vertical:
        fig_p.vertical = [-5.0, 5.0]
    if len(legend) < len(datas) + 1:
        legend = legend + [''] * (len(datas) + 1 - len(legend))
    if all(x == "Noneispin" for x in ispins):
        (plots.Noneispin2 if len(datas) == 2 else plots.Noneispin3)(
            arrs, bandss, ticks, names, legend, fig_p)
    elif all(x == "Ispin" for x in ispins):
        (plots.Dispin2 if len(datas) == 2 else plots.Dispin3)(
            arrs, bandss, ticks, names, legend, fig_p)
    else:
        _error("ERROR: 对比的体系自旋设置不一致（有的 ISPIN=1，有的 ISPIN=2）。")
        return
    print("已保存：" + fig_p.output)

# mt.phband
def pmain():
    global _ERROR
    _ERROR = False
    parser = argparse.ArgumentParser(description='Plot the phonon band structure or DOS from phonopy results.',
                                     add_help=False,
                                     epilog=r'''
Example:
mt.phband -i BAND.dat -o BAND.png -l g m k g -d projected_dos.dat -G $\pi^2_4$ -e Si C O
mt.phband -B 23 100 -l g m k g -y -2 110      # broken axis for the optical branch
''',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",       action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version",    action="version",     version=version_string())
    parser.add_argument('-S', "--figsz",       type=float, nargs=2,  help='figure size: width, height', metavar=('width','height'))
    parser.add_argument('-B', "--brkax",     type=float, nargs=2,  help='broken axis: start, end')
    parser.add_argument('--hratios',    type=float,           help='height ratio for broken axis, default: 0.2', default=0.2)
    parser.add_argument('-y', "--vrang",   type=float, nargs=2,  help="frequency (THz) range", metavar=('start','end'))
    parser.add_argument('-G', "--legnd",     type=str,             nargs='+', help="legend labels", default=[])
    parser.add_argument('-A', "--locat",   type=str.lower,       nargs='+', help="arrange the legend location, default: best", default=[], metavar="str")
    parser.add_argument('-C', "--color",      type=str,             nargs='+', help="line color: b, blue; g, green; r, red; c, cyan; m, magenta; y, yellow;"+
                                                                                    "k, black; w, white", default=[], metavar="clrs")
    parser.add_argument('-k', "--style",  type=str,             nargs='+', help="linestyle: solid, dashed, dashdot, dotted or tuple; default: solid",
                                                                                    default=[], metavar="str")
    parser.add_argument('-w', "--width",  type=str,             nargs='+', help="linewidth, default: 0.8", default=[], metavar="0.8")
    parser.add_argument('-i', "--input",      type=str,             nargs='+', help="plot figure from .dat file, default: BAND.dat", default=["BAND.dat"])
    parser.add_argument('-o', "--outpt",     type=str,             help="plot figure filename, default: BAND.png", default="BAND.png")
    parser.add_argument('-q', "--resol",        type=int,             help="dpi of the figure, default: 500", default=500)
    parser.add_argument('-j', "--bconf",   type=str,             help="filename of band setting file, default: band.conf", default="band.conf")
    parser.add_argument('-l', "--label",     type=str.upper,       nargs='+', default=[], help='labels for high-symmetry points, such as X S Y K M')
    parser.add_argument('-d', "--dospl",        type=str,             nargs='?', default='', help="also plot Phonon DOS from .dat file; for a standalone DOS figure use mt.phdos")
    parser.add_argument('-x', "--horiz", type=float, nargs=2,  help="Phonon density of states range", metavar=('start','end'))
    parser.add_argument('-n', "--exchg",   action='store_true',  help="exchange the x and y axes of Phonon DOS")
    parser.add_argument('-e', "--elems",   type=str,             nargs='+', default=[], help="PDOS labels")
    parser.add_argument('-W', "--ratio",    type=float,           help='width ratio for DOS subplot, default 0.5', default=0.5)
    parser.add_argument('-z', "--alpha",       type=float,           nargs='?', help='fill a shaded region between PDOS and axis, default: 0.2', default=None,
                                                                                    const=0.2, metavar="alpha")

    args = parser.parse_args()

    labels = [re.sub("'|‘|’", '′', re.sub('"|“|”', '″', re.sub('^GA[A-Z]+$|^G$', 'Γ', i))) for i in args.label]
    elements = [re.sub("'|‘|’", '′', re.sub('"|“|”', '″', i)) for i in args.elems]
    if args.dospl != '':
        dosfile = args.dospl or ('projected_dos.dat' if os.path.exists('projected_dos.dat') else '') or ('total_dos.dat' if os.path.exists('total_dos.dat') else '')
        dosfile = dosfile if os.path.exists(dosfile) else None
    else:
        dosfile = None

    color = []
    for i in args.color:
        j = i.split('*')
        if len(j) == 2:
            color += [ast.literal_eval(j[0])] * int(j[1]) if '(' in j[0] and ')' in j[0] else [j[0]] * int(j[1])
        else:
            color += [ast.literal_eval(i)] if '(' in i and ')' in i else [i]

    linestyle = []
    for i in args.style:
        j = i.split('*')
        if len(j) == 2:
            linestyle += [ast.literal_eval(j[0])] * int(j[1]) if '(' in j[0] and ')' in j[0] else [j[0]] * int(j[1])
        else:
            linestyle += [ast.literal_eval(i)] if '(' in i and ')' in i else [i]

    linewidth = []
    for i in args.width:
        j = i.split('*')
        linewidth += [float(j[0])] * int(j[1]) if len(j) == 2 else [float(i)]

    pltname = os.path.split(os.getcwd())[-1]
    s_ele = []
    formula = ''
    if os.path.exists('POSCAR-unitcell'):
        symbol, factor = readdata.symbols('POSCAR-unitcell')
        for i in range(len(symbol)):
            if factor[i] > 1:
                s_ele = s_ele + [symbol[i]] * factor[i]
                formula = formula + symbol[i]
                for j in str(factor[i]):
                    formula = formula + '$_'+ j + '$'
            else:
                s_ele = s_ele + [symbol[i]]
                formula = formula + symbol[i]

    if not elements and s_ele:
        elements = s_ele

    legend = args.legnd or ([formula] if formula else [pltname])

    klabels = []
    if os.path.exists(args.bconf):
        klabels = readdata.bandset(args.bconf)
    if len(labels) == 0:
        labs=[re.sub('^GA[A-Z]+$|^G$', 'Γ', i) for i in klabels]

    broken = args.brkax
    height_ratio = args.hratios if 0 < args.hratios < 1 else 0.2
    width_ratios = args.ratio if 0 < args.ratio < 1 else 0.5
    location = [int(i) if i.isdigit() else i for i in args.locat]

    fig_p = cla_fig(output=args.outpt, size=args.figsz, vertical=args.vrang, horizontal=args.horiz,
                    color=color, linestyle=linestyle, linewidth=linewidth, location=location, dpi=args.resol,
                    height_ratio=height_ratio, width_ratios=width_ratios, exchange=args.exchg, fill=args.alpha)
# plot Phonon Band Structure
    try:
        bandfile = [f for i in args.input for f in glob.glob(i)]
        len_bandfile = len(bandfile)
        if len_bandfile == 1:
            arr, fre, ticks = readdata.pbands(bandfile[0])
            if len(ticks) > len(labels):
                labels += [''] * (len(ticks) - len(labels))
            elif len(ticks) < len(labels):
                labels = labels[:len(ticks)]
            if dosfile:
                darr, dele = readdata.pdos(dosfile)
                if args.brkax is None:
                    pplots.NobrokenWd(arr, fre, ticks, labels, darr, dele, elements, legend, fig_p)
                else:
                    pplots.BrokenWd(arr, fre, ticks, labels, broken, darr, dele, elements, legend, fig_p)
            else:
                if args.brkax is None:
                    pplots.Nobroken(arr, fre, ticks, labels, legend, fig_p)
                else:
                    pplots.Broken(arr, fre, ticks, labels, broken, legend, fig_p)
    # plot Phonon DOS
        elif len_bandfile == 0:
            if dosfile:
                if fig_p.output == "BAND.png":
                        fig_p.output = "PHDOS.png"
                darr, dele = readdata.pdos(dosfile)
                pplots.pdosfile(darr, dele, elements, legend, fig_p)
                print("提示：只画声子态密度可用 mt.phdos（默认 Frequency 为横轴）。")
            else:
                _error("ERROR: 没有找到 *.dat 文件；只画声子态密度请用 mt.phdos。")
    # compare two Phonon Band Structures
        elif len_bandfile == 2:
            arr = [''] * 2
            fre = [''] * 2
            ticks = [''] * 2
            arr[0], fre[0], ticks[0] = readdata.pbands(bandfile[0])
            arr[1], fre[1], ticks[1] = readdata.pbands(bandfile[1])
            if len(ticks[0]) > len(labels):
                labels += [''] * (len(ticks[0]) - len(labels))
            elif len(ticks[0]) < len(labels):
                labels = labels[:len(ticks[0])]
            if len(legend) < 3:
                legend += [''] * (3 - len(legend))

            if args.brkax is None:
                pplots.Nobroken2(arr, fre, ticks[0], labels, legend, fig_p)
            else:
                pplots.Broken2(arr, fre, ticks[0], labels, broken, legend, fig_p)
    # compare three Phonon Band Structures
        elif len_bandfile == 3:
            arr = [''] * 3
            fre = [''] * 3
            ticks = [''] * 3
            arr[0], fre[0], ticks[0] = readdata.pbands(bandfile[0])
            arr[1], fre[1], ticks[1] = readdata.pbands(bandfile[1])
            arr[2], fre[2], ticks[2] = readdata.pbands(bandfile[2])
            if len(ticks[0]) > len(labels):
                labels += [''] * (len(ticks[0]) - len(labels))
            elif len(ticks[0]) < len(labels):
                labels = labels[:len(ticks[0])]
            if len(legend) < 4:
                legend += [''] * (4 - len(legend))

            if args.brkax is None:
                pplots.Nobroken3(arr, fre, ticks[0], labels, legend, fig_p)
            else:
                pplots.Broken3(arr, fre, ticks[0], labels, broken, legend, fig_p)
        else:
            _error("ERROR: 输入能带文件数量不匹配（只支持 1~3 个）。")
    except (ValueError, IndexError, KeyError, TypeError, OSError, UnicodeDecodeError) as exc:
        _error("ERROR: 解析声子输入文件失败：%s" % exc)
    return 1 if _ERROR else 0

