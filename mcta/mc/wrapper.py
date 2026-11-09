import argparse, os, platform
import numpy as np
from mcta import version_string

try:
    import numba                       # numba 是可选依赖（pip install "mcta[mc]"）
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

default values:
x, y, z = 64, 64, 64
iterations for equilibrium, works = 1000, 1000
exchange coupling (meV) = 1.0
single-ion anisotropy (meV) = 0.1
temperatures = 35

multi-core (works for every configuration):
-R  number of independent chains; the statistics are averaged over the chains.
    Default: the same as the thread count.
-n  maximum number of threads (0 = automatic). Default: a little over half
    of the physical cores (e.g. 4 on a 6-core machine).
--seed  fix the random numbers: the result no longer depends on the thread count
--swap  replica exchange (parallel tempering): one chain per temperature, the
    configurations of neighbouring temperatures are exchanged every N sweeps so
    that the low-temperature runs do not get stuck. Use it when the machine has
    few cores, or to speed up a long low-temperature scan.

note: the geometry of every configuration is stored as a data table; the
      simulation engine only reads that table, so a new atomic arrangement
      needs a new table generator only.

Example:
mt.mc -x 100 -y 100 -e 2000 -w 5000 -n 8 -t 35 -r
mt.mc -x 128 -y 128 -t 0 40 2 -R 6 --seed 42 -r
mt.mc -x 64 -y 64 -t 0 60 2 --swap 10 --seed 42 -r   # replica exchange
''',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",     action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version",  action="version",     version=version_string())
    parser.add_argument('-n', "--np",           type=int,   default=0   , help="numba 线程数，默认取物理核数")
    parser.add_argument('-R', "--replicas",     type=int,   default=0   , help="并行推进的独立链数（多核加速），0 表示与线程数相同")
    parser.add_argument("--seed",               type=int,   default=None, help="随机数种子，给定后结果可复现")
    parser.add_argument("--swap",               type=int,   default=0   , help="replica exchange：每多少个 sweep 交换一次相邻温度的构型（0=关闭，链数=温度点数）")
    parser.add_argument('-x', "--length",       type=int,   default=64  )
    parser.add_argument('-y', "--width",        type=int,   default=64  )
    parser.add_argument('-z', "--height",       type=int,   default=64  )
    parser.add_argument('-e', "--equilibrium",  type=int,   default=1000)
    parser.add_argument('-w', "--works",        type=int,   default=1000)
    parser.add_argument('-a', "--single",       type=float, default=None,  nargs='*')
    parser.add_argument('-p', "--parameters",   type=float, default=[1.0], nargs='+')
    parser.add_argument('-j', "--parameterX",   type=float, default=[],    nargs='+')
    parser.add_argument('-k', "--parameterY",   type=float, default=[],    nargs='+')
    parser.add_argument('-t', "--temperatur",   type=float, default=[35],  nargs='+')
    parser.add_argument('-l', "--labl",         type=str,   default='',    help='图例')
    parser.add_argument('-r', "--export",       action='store_true',       help="结束后绘图")
    parser.add_argument('-o', "--plot",         type=str,                  help="日志文件绘图")
    parser.add_argument('-f', "--format",       default="png",             type=str.lower, choices=['png', 'pdf', 'svg', 'jpg', 'tif'])
    parser.add_argument('-i', "--init",         default="fm",              type=str.lower, choices=['fm', 'afm1', 'afm2','afm3', 'afm4', 'afm5', 'random'])
    parser.add_argument('-c', "--config",       default="square",          type=str.lower, choices=['square', 'triangular', 'bilayer-aa', 'bilayer-ab', 'bilayer-ab-u-3'])
    args = parser.parse_args()

    if numba is None:
        print('ERROR: mt.mc 需要 numba（可选依赖），请先安装：'
              'pip install "mcta[mc]"')
        return 1

    seed = args.seed
    swap = args.swap

    arrays_temperatures = temperatures(args.temperatur)

    # 按本机核数决定并行策略：
    #   独立多链 -> 链数 = 线程数（统计量取平均，误差更小）
    #   并行回火 -> 链数 = 温度点数
    # 线程数默认取"略多于物理核数的一半"（见 mcta/mc/parallel.py 的说明）：
    # 把核心跑满实测反而更慢，超线程的边际收益也很小。
    # 用户显式给了 -R / -n 就按用户说的来。
    mode = "tempering" if swap > 0 else "chains"
    NP, replicas = parallel.thread_plan(mode, args.replicas, args.np,
                                        n_temps=len(arrays_temperatures))
    numba.set_num_threads(NP)

    X = check(args.length)
    Y = check(args.width)
    Z = check(args.height)
    config = args.config
    init = args.init
    # 多链并行与 replica exchange 都是通用能力（内核只读表），
    # 所有构型都支持；这里只在初态可能不被某些构型支持时提示。

    nequilibrium = args.equilibrium
    nworks       = args.works
    J  = args.parameters
    JX = args.parameterX
    JY = args.parameterY
    format = args.format
    legend = args.labl

    if args.plot and os.path.exists(args.plot):
        from mcta.mc import plots
        plots.main(args.plot, format, legend)
    else:
        if args.single is not None:
            A = [0.1] if args.single == [] else args.single
            # 矢量自旋：同样表驱动，只是换成矢量内核族
            from mcta.mc import geometry
            from mcta.mc import engine
            file = '{}_single_{}_{}.log'.format(config, X, Y)
            lattice = geometry.build(config, X, Y)
            engine.run_vector(lattice, file, init, J, A, arrays_temperatures,
                              nequilibrium, nworks, replicas, seed, swap)
        else:
            # Ising（标量自旋）：表驱动。几何只在表里，计算代码通用。
            from mcta.mc import geometry
            from mcta.mc import engine
            file = '{}_Ising_{}_{}.log'.format(config, X, Y)
            lattice = geometry.build(config, X, Y)
            engine.run(lattice, file, init, J, arrays_temperatures,
                       nequilibrium, nworks, replicas, seed, swap)

        if args.export and os.path.exists(file):
            from mcta.mc import plots
            plots.main(file, format, legend)

def check(num):
    if num < 10:
        num = 10
    if num % 2 != 0:
        num += 1
    if num % 4 != 0:
        num += 2
#    if num % 8 != 0:
#        num += 4
    return num

def temperatures(arr_temperatures):
    """把 -t 的参数解析成温度数组。

    规则
    ----
    * 1 个值  T          -> 0, 1, ..., T-1（整数温度）
    * 2 个值  T0 T1      -> T0, T0+1, ..., T1（闭区间）
    * 3 个值  T0 T1 d    -> T0, T0+d, ..., T1（闭区间，步长 d）
    * 3k 个值            -> k 段三元组，每段都是闭区间
    * 3k+2 个值          -> k 段三元组 + 末尾一段 (T0, T1) 闭区间

    三元组的两种解读
    ----------------
    ``-t 20 26 2`` 里第三个数 2 是**步长**（2 K 一档），这是文档里
    推荐的用法。但 ``-t 20 25 30`` 里步长 30 大于跨度 5，按步长解读
    只会得到 [20, 25]——第三个温度被静默丢掉，这几乎肯定不是用户的
    本意（他想说的是"算 20、25、30 这三个温度"）。

    所以：**当步长 >= 跨度时，整组按"离散温度点列表"处理**，三个数
    就是三个温度。这样两种意图都能正确表达：

        -t 20 26 2      ->  20, 22, 24, 26          （步长 2）
        -t 20 25 30     ->  20, 25, 30               （三个离散点）
        -t 0 40 2       ->  0, 2, 4, ..., 40         （步长 2）
    """
    i = len(arr_temperatures)
    if i == 1:
        return np.arange(arr_temperatures[0] + 1)
    if i == 2:
        return np.arange(arr_temperatures[0], arr_temperatures[1] + 1)

    def _segment(t0, t1, step):
        """闭区间 [t0, t1]，步长 step。

        step >= 跨度时，整组按"离散温度点"处理（见 docstring）。
        """
        if step >= t1 - t0:
            return np.array([t0, t1, step], dtype=float)
        if step <= 0:
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
        # 末尾一段 (T0, T1)：闭区间
        base = k * 3
        segments.append(np.arange(arr_temperatures[base],
                                  arr_temperatures[base + 1] + 1))
    elif l == 1:
        # 末尾还剩一个值：它就是一个单独的温度点。
        # （旧实现这里什么都不做，末尾的温度被静默丢掉——比如
        #  -t 20 22 24 26 28 30 32 34 36 38 只会得到 9 个温度。）
        segments.append(np.array([arr_temperatures[k * 3]], dtype=float))
    if not segments:
        return np.array([])
    out = np.concatenate(segments)
    # 去重并保持顺序（步长恰好等于跨度时可能出现重复端点）
    return np.unique(out) if out.size > 1 else out
