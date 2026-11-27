import argparse, os, platform
import numpy as np
from mcta import version_string

try:
    import numba                       # numba 是可选依赖（pip install mcta[mc]）
except ImportError:
    numba = None

from mcta.mc import parallel


def main():
    parser = argparse.ArgumentParser(description='mt.mc: Monte Carlo simulation of the phase transition in 2D/3D magnetic materials',
                                     add_help=False,
                                     epilog='''
configurations:       init:                                 parameters:
square                fm, afm1, afm2, afm3                  Ja, Jb, Jc
triangular            fm, afm1, afm2, afm3                  Ja, Jb, Jc
bilayer-aa            fm, afm1, afm2, afm3                  J0, J1, Ja
bilayer-ab            fm, afm1, afm2, afm3, afm4, afm5      J0, J1, Ja, Jb, J1_
bilayer-ab-u-3        fm, afm1, afm2, afm3                  J0, J1, Ja
simple-cubic          fm, afm1, afm2                        Ja, Jb, Jc
xy-square             fm, afm1, afm2, afm3, random          J (XY 方格，含 BKT 判据)
xy-triangular         fm, afm1, afm2, afm3, random          J (XY 三角)
xy-honeycomb          fm, afm1, afm2, afm3, random          J (XY 蜂窝)
xy-kagome             fm, afm1, afm2, afm3, random          J (XY 笼目)
xy-diced              fm, afm1, afm2, afm3, random          J (XY diced)

default values:
x, y, z = 32, 32, 32
iterations for equilibrium, works = 1000, 1000
exchange coupling (meV) = 1.0
single-ion anisotropy (meV) = 0.1
temperatures = 35

Example:
mt.mc -x 100 -y 100 -e 2000 -w 5000 -N 8 -t 35
mt.mc -x 128 -y 128 -t 0 40 2 -C 6 -S 42
mt.mc -x 64 -y 64 -t 20 40 2 -W 20 -S 42
mt.mc -x 64 -y 64 -t 20 40 2 -R                            # run only, no plots
mt.mc -s POSCAR -A Fe -D 2.7 3.2 -x 2 -y 2 -z 2            # 从 POSCAR 构建超胞 + 邻居
mt.mc -s POSCAR -A Fe -D 3.0 3.6 --mom "Fe 4.0" --ini afm  # 磁矩 + 沿 z 反铁磁初态
mt.mc -s POSCAR -A Fe -D 2.7 --ini 1,-1,-1,1               # 按原胞顺序设 ±1 初态
mt.mc -c xy-square -x 64 -y 64 -p 1 -t 5 20 0.5 -S 42        # XY 方格：扫 Υ 与涡旋定 BKT
mt.mc -c xy-triangular -x 64 -y 64 -p 1 -t 5 30 0.5 -S 42    # 三角 / 蜂窝 / 笼目 / diced 同理
mt.mc -o xy-square_XY_32_32.log -T 10                        # 重绘日志并画 10 K 涡旋状态箭头图

''',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",    action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version", action="version",     version=version_string())
    parser.add_argument('-x', '-X', "--sizex",  type=int, metavar="X", default=32, help="x 方向晶格尺寸/超胞扩展倍数（默认 32）")
    parser.add_argument('-y', '-Y', "--sizey",  type=int, metavar="Y", default=32, help="y 方向晶格尺寸/超胞扩展倍数（默认 32）")
    parser.add_argument('-z', '-Z', "--sizez",  type=int, metavar="Z", default=32, help="z 方向晶格尺寸/超胞扩展倍数（默认 32；二维结构忽略）")
    parser.add_argument('-e', "--equil",        type=int,   default=1000)
    parser.add_argument('-w', "--works",        type=int,   default=1000)
    parser.add_argument('-a', "--aniso",        type=float, default=None,   nargs='*')
    parser.add_argument('-p', "--param",        type=float, default=[1.0],  nargs='+', help="交换耦合参数，按通道顺序；矢量自旋 + -J/-K 时表示 z 方向")
    parser.add_argument('-J', "--parax",        type=float, default=[],     nargs='+', help="矢量自旋 x 方向交换参数；不设时取 -p")
    parser.add_argument('-K', "--paray",        type=float, default=[],     nargs='+', help="矢量自旋 y 方向交换参数；不设时取 -p")
    parser.add_argument('-t', "--temps",        type=float, default=[35],   nargs='+')
    parser.add_argument('-i', "--inits",        default="fm",               type=str.lower, choices=['fm', 'afm1', 'afm2','afm3', 'afm4', 'afm5', 'random'])
    parser.add_argument('-c', "--confg",        default="square",           type=str.lower, choices=['square', 'triangular', 'bilayer-aa', 'bilayer-ab', 'bilayer-ab-u-3', 'simple-cubic', 'xy-square', 'xy-triangular', 'xy-honeycomb', 'xy-kagome', 'xy-diced'])
    parser.add_argument('-s', "--struc",        type=str,   default=None,   help="结构文件（POSCAR/CIF 等，ASE 可读即可）；给了就自动构建邻居表，-c 被忽略")
    parser.add_argument('-A', "--magat",        type=str, nargs='+', default=None, help="磁性元素，空格或逗号分隔（如 Fe Co 或 Fe,Co）；默认自动识别 d/f 区元素")
    parser.add_argument('-D', "--cutof",        type=float, nargs='+', default=[3.0], help="结构模式：各通道距离上限 (A)，如 3.0 3.6 4.2")
    # 结构模式下原子磁矩和自旋初态（空格或逗号分隔均可）
    parser.add_argument('--mom',                type=str, nargs='+', default=["2"], help="结构模式：原子自旋磁矩标称值，默认 2（S=±1）；可按元素设置，如 --mom Fe 4.0 Cr 3.0 或 All 1.0")
    parser.add_argument('--ini',                type=str, nargs='+', default=["fm"], help="结构模式：自旋初态 fm（默认）/ afm（沿 z 逐层反铁磁）/ random（随机），或按原胞磁性原子顺序给 ±1 列表（如 --ini 1,-1,-1,1 或 1 -1 -1 1）")
    parser.add_argument('-N', "--thrds",        type=int,   default=0   ,   help="numba 线程数；0=自动（物理核数的约 3/5，不超过物理核总数）")
    parser.add_argument('-C', "--chain",        type=int,   default=0   ,   help="并行推进的独立链数（多核加速），0 表示与线程数相同；回火模式下链数=温度点数")
    parser.add_argument('-S', "--seeds",        type=int,   default=None,   help="随机数种子，给定后结果可复现")
    parser.add_argument('-W', "--swaps",        type=int,   default=0   ,   help="每多少个 sweep 交换一次相邻温度的构型（0=关闭，链数=温度点数）")
    parser.add_argument('-R', "--dryrn",        action='store_true',        help="不自动绘图（只跑模拟并写日志）；默认结束后绘图")
    parser.add_argument('-l', "--label",        type=str,   default='',     help='图例')
    parser.add_argument('-o', "--plots",        type=str,                   help="日志文件绘图")
    parser.add_argument('-T', "--vtemp",        type=float, default=None,   help="XY 涡旋状态箭头图的温度 (K)；不指定则取最高温度")
    parser.add_argument('-I', "--imgfm",        default="png", type=str.lower, help="输出图片格式（任意 matplotlib 支持的格式，如 png/pdf/svg/jpg/tif）；无法保存时会提示并回退为 png")
    args = parser.parse_args()

    if args.equil < 0:
        parser.error("-e/--equil 必须大于或等于 0")
    if args.works <= 0:
        parser.error("-w/--works 必须大于 0")
    if args.thrds < 0:
        parser.error("-N/--thrds 必须大于或等于 0")
    if args.chain < 0:
        parser.error("-C/--chain 必须大于或等于 0")
    if args.swaps < 0:
        parser.error("-W/--swaps 必须大于或等于 0")
    if args.seeds is not None and args.seeds < 0:
        parser.error("-S/--seeds 必须大于或等于 0")
    if args.aniso is not None and len(args.aniso) > 2:
        parser.error("-a/--aniso 最多接受两个参数")
    for option, values in (("-a/--aniso", args.aniso),
                           ("-p/--param", args.param),
                           ("-J/--parax", args.parax),
                           ("-K/--paray", args.paray),
                           ("-D/--cutof", args.cutof)):
        if values is not None and not np.all(np.isfinite(values)):
            parser.error(f"{option} 的参数必须是有限数值")

    is_xy = args.confg.startswith('xy-')
    if is_xy:
        if args.struc is not None:
            parser.error("XY 模型只能用 -c xy-* 内置格子，不支持 -s 结构文件")
        if args.aniso is not None or args.parax or args.paray:
            parser.error("XY 模型忽略 -a/-J/-K：自旋限制在平面内、交换各向同性")
        if args.inits not in ('fm', 'afm1', 'afm2', 'afm3', 'random'):
            parser.error("XY 模型初态只支持 fm/afm1/afm2/afm3/random")

    if numba is None:
        print('ERROR: mt.mc 需要 numba（可选依赖），请先安装：'
              'pip install mcta[mc]')
        return 1

    seed = args.seeds
    swap = args.swaps

    try:
        arrays_temperatures = temperatures(args.temps)
    except ValueError as exc:
        parser.error(str(exc))

    mode = "tempering" if swap > 0 else "chains"
    NP, chains = parallel.thread_plan(mode, args.chain, args.thrds,
                                        n_temps=len(arrays_temperatures))
    if swap > 0:
        chains = len(arrays_temperatures)
    numba.set_num_threads(NP)

    # 内置构型和结构模式的 -x/-y/-z 默认值均为 32
    X = check(args.sizex)
    Y = check(args.sizey)
    Z = check(args.sizez)
    config = args.confg
    init = args.inits

    nequilibrium = args.equil
    nworks       = args.works
    J  = args.param
    JX = args.parax
    JY = args.paray
    format = args.imgfm
    legend = args.label
    is_heisenberg = args.aniso is not None or JX or JY

    if args.plots:
        if not os.path.isfile(args.plots):
            print(f"ERROR: 日志文件不存在或不是普通文件: {args.plots}")
            return 1
        from mcta.mc import plots
        plots.main(args.plots, format, legend, args.vtemp)
    else:
        # === 构建 lattice ===
        if args.struc is not None:
            from mcta.mc.geometry import from_structure as fs
            if not os.path.exists(args.struc):
                print(f"ERROR: 结构文件不存在: {args.struc}")
                return 1
            # 结构模式的初态：--ini 解析关键字或 ±1 列表；默认 fm
            ini_str = ",".join(args.ini).strip()
            toks = ini_str.replace(",", " ").split()
            if len(toks) == 1 and toks[0].lower() in ("fm", "afm", "random"):
                init_key = toks[0].lower()
                ini_str = None
            else:
                init_key = "list"
            mag_elements = ({e.strip() for e in ",".join(args.magat).split(",")
                             if e.strip()} if args.magat else None)
            cutoffs = args.cutof
            # 结构模式：-x/-y/-z 用作超胞扩展倍数；二维结构忽略 z
            supercell = (max(1, args.sizex), max(1, args.sizey),
                         max(1, args.sizez))
            try:
                lattice = fs.build(args.struc,
                                    mag_elements=mag_elements,
                                    cutoffs=cutoffs,
                                    supercell=supercell,
                                    mom=" ".join(args.mom),
                                    ini=ini_str if init_key == "list" else None,
                                    fallback_key=init_key)
            except (ValueError, ImportError) as e:
                print(f"ERROR: {e}")
                return 1
            init = init_key
            stem = os.path.splitext(os.path.basename(args.struc))[0]
            # 日志里显示输入文件名；X/Y 是用户超胞倍数，不是内核的 X_s/Y_s。
            lattice.name = os.path.basename(args.struc)
            lattice.X, lattice.Y = supercell[0], supercell[1]
        else:
            from mcta.mc import geometry
            lattice = geometry.build(config, X, Y, Z)
            stem = config

        if init == "random" and not is_xy:
            random_rng = np.random.default_rng(seed)
            signs = random_rng.choice(np.array([-1, 1], dtype=np.int8),
                                      size=lattice.ncell)
            lattice.init_states["random"] = signs.astype(np.int8)
            lattice.groups["random"] = [np.arange(lattice.ncell)]

        model = 'XY' if is_xy else ('Heisenberg' if is_heisenberg else 'Ising')
        dims = "_".join(str(d) for d in lattice.dimensions)
        file = '{}_{}_{}.log'.format(stem, model, dims)

        # === 运行模拟 ===
        # -c xy-* 走 XY 平面转子内核；否则给了 -a/-J/-K 用 Heisenberg，其余 Ising
        if is_xy:
            from mcta.mc import xy_engine as xy
            xy.run_xy(lattice, file, init, J, arrays_temperatures,
                      nequilibrium, nworks, chains, seed, swap)
        elif is_heisenberg:
            A = args.aniso if args.aniso else [0.1]
            from mcta.mc import engine
            engine.run_vector(lattice, file, init, J, A, arrays_temperatures,
                              nequilibrium, nworks, chains, seed, swap,
                              JX=JX, JY=JY)
        else:
            from mcta.mc import engine
            engine.run(lattice, file, init, J, arrays_temperatures,
                       nequilibrium, nworks, chains, seed, swap)

        if not args.dryrn and os.path.exists(file):
            from mcta.mc import plots
            plots.main(file, format, legend, args.vtemp)


def check(num):
    if num < 10:
        num = 10
    if num % 2 != 0:
        num += 1
    if num % 4 != 0:
        num += 2
    return num


def temperatures(arr_temperatures):
    """把 -t 的参数解析成温度数组。"""
    if not arr_temperatures:
        return np.array([], dtype=float)
    if not np.all(np.isfinite(arr_temperatures)):
        raise ValueError("-t/--temps 的温度和步长必须是有限数值")
    if any(t < 0 for t in arr_temperatures):
        raise ValueError("-t/--temps 的温度和步长不能为负数")

    i = len(arr_temperatures)
    if i == 1:
        return np.arange(arr_temperatures[0] + 1)
    if i == 2:
        if arr_temperatures[1] < arr_temperatures[0]:
            raise ValueError("-t/--temps 双参数区间要求终温不低于初温")
        return np.arange(arr_temperatures[0], arr_temperatures[1] + 1)

    def _segment(t0, t1, step):
        if t1 < t0:
            raise ValueError("-t/--temps 每个温度区间要求终温不低于初温")
        if step <= 0:
            raise ValueError("-t/--temps 温度区间的步长必须大于 0")
        if step >= t1 - t0:
            # 步长太大，np.arange 只会给出起点；直接返回两个端点。
            # 注意第三个元素绝不能是 step：step 是步长，不是温度。
            return np.array([t0, t1], dtype=float)
        pts = np.arange(t0, t1 + 1e-9, step)
        if pts.size == 0 or pts[-1] < t1 - 1e-9:
            pts = np.append(pts, t1)
        return pts

    k, l = divmod(i, 3)
    segments = []
    for j in range(k):
        base = j * 3
        segments.append(_segment(arr_temperatures[base],
                                 arr_temperatures[base + 1],
                                 arr_temperatures[base + 2]))
    if l == 2:
        base = k * 3
        if arr_temperatures[base + 1] < arr_temperatures[base]:
            raise ValueError("-t/--temps 双参数区间要求终温不低于初温")
        segments.append(np.arange(arr_temperatures[base],
                                  arr_temperatures[base + 1] + 1))
    elif l == 1:
        segments.append(np.array([arr_temperatures[k * 3]], dtype=float))
    out = np.concatenate(segments)
    return np.unique(out) if out.size > 1 else out
