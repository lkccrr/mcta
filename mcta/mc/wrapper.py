import argparse, os, platform
import numpy as np
from mcta import version_string

try:
    import numba                       # numba 是可选依赖（pip install "mcta[mc]"）
except ImportError:
    numba = None

from mcta.mc import __version__

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

Example:
mt.mc -x 100 -y 100 -e 2000 -w 5000 -n 8 -t 35 -r
''',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",     action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version",  action="version",     version=version_string())
    parser.add_argument('-n', "--np",           type=int,   default=4   )
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

    NP = args.np
    numba.set_num_threads(NP)

    X = check(args.length)
    Y = check(args.width)
    Z = check(args.height)
    config = args.config
    init = args.init

    arrays_temperatures = temperatures(args.temperatur)

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
            if config == "square":
                file = '{}_single_{}_{}.log'.format(config, X, Y)
                from mcta.mc.single import square
                square.run(file, init, X, Y, J, A, arrays_temperatures, nequilibrium, nworks)
            elif config == "triangular":
                file = '{}_single_{}_{}.log'.format(config, X, Y)
                from mcta.mc.single import triangular
                triangular.run(file, init, X, Y, J, A, arrays_temperatures, nequilibrium, nworks)
            elif config == "bilayer-aa":
                file = '{}_single_{}_{}.log'.format(config, X, Y)
                from mcta.mc.single import bilayer_aa
                bilayer_aa.run(file, init, X, Y, J, A, arrays_temperatures, nequilibrium, nworks)
            elif config == "bilayer-ab":
                file = '{}_single_{}_{}.log'.format(config, X, Y)
                from mcta.mc.single import bilayer_ab
                bilayer_ab.run(file, init, X, Y, J, A, arrays_temperatures, nequilibrium, nworks)
            elif config == "bilayer-ab-u-3":
                file = '{}_single_{}_{}.log'.format(config, X, Y)
                from mcta.mc.single import bilayer_ab_u_3
                bilayer_ab_u_3.run(file, init, X, Y, J, A, arrays_temperatures, nequilibrium, nworks)
            else:
                print("Inconsistent parameters...")
        else:
            if config == "square":
                file = '{}_Ising_{}_{}.log'.format(config, X, Y)
                from mcta.mc.ising import square
                square.run(file, init, X, Y, J, arrays_temperatures, nequilibrium, nworks)
            elif config == "triangular":
                file = '{}_Ising_{}_{}.log'.format(config, X, Y)
                from mcta.mc.ising import triangular
                triangular.run(file, init, X, Y, J, arrays_temperatures, nequilibrium, nworks)
            elif config == "bilayer-aa":
                file = '{}_Ising_{}_{}.log'.format(config, X, Y)
                from mcta.mc.ising import bilayer_aa
                bilayer_aa.run(file, init, X, Y, J, arrays_temperatures, nequilibrium, nworks)
            elif config == "bilayer-ab":
                file = '{}_Ising_{}_{}.log'.format(config, X, Y)
                from mcta.mc.ising import bilayer_ab
                bilayer_ab.run(file, init, X, Y, J, arrays_temperatures, nequilibrium, nworks)
            elif config == "bilayer-ab-u-3":
                file = '{}_Ising_{}_{}.log'.format(config, X, Y)
                from mcta.mc.ising import bilayer_ab_u_3
                bilayer_ab_u_3.run(file, init, X, Y, J, arrays_temperatures, nequilibrium, nworks)
            else:
                print("Inconsistent parameters...")

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
    i = len(arr_temperatures)
    if i == 1:
        return np.arange(arr_temperatures[0]+1)
    elif i == 2:
        return np.arange(arr_temperatures[0], arr_temperatures[1]+1)
    else:
        k = i // 3
        l = i % 3
        j = 0
        while j < k:
            if j == 0:
                arrays_temperatures = np.arange(arr_temperatures[0], arr_temperatures[1], arr_temperatures[2])
            else:
                arrays_temperatures=np.concatenate((arrays_temperatures,
                    np.arange(arr_temperatures[j * 3], arr_temperatures[j * 3 + 1], arr_temperatures[j * 3 + 2])))
            if arrays_temperatures[-1] != arr_temperatures[j * 3 + 1]:
                arrays_temperatures = np.append(arrays_temperatures, arr_temperatures[j * 3 + 1])
            j += 1
        if l == 2:
            arrays_temperatures=np.concatenate((arrays_temperatures,
                np.arange(arr_temperatures[j * 3], arr_temperatures[j * 3 + 1]+1)))
        return arrays_temperatures
