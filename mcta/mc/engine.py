"""表驱动的 Ising 蒙特卡洛：数据格式与通用计算层。

分成两个严格分离的层：

* **构型层**（``mcta.mc.geometry``）：只负责把"原子排布"翻译成一张表。
  表里没有任何物理公式，只有邻居关系、耦合通道和分组。
* **计算层**（本模块）：完全通用，只读表，不认识任何几何。
  它不知道什么是 square、什么是 bilayer，只知道"每个 cell 有哪些邻居、
  每个邻居属于哪条耦合通道"。

表的结构
--------

所有构型都是「层 × 块」两级：晶格被分成 ``nlayer`` 层，每层 ``nblock``
个块，每块内是 ``Y_s × X_s`` 的周期格点。一个 *cell* 就是一块，
用 ``cell = layer * nblock + block`` 编号。

对每个 cell，表给出它的邻居列表，每个邻居是::

    (目标 cell, 行偏移 dj, 列偏移 di, 耦合通道)

``dj``/``di`` 取值 -1 / 0 / +1，表示在**目标 cell 自己的坐标系**里
相对当前位置的偏移（周期边界在内核里回绕）。

耦合通道：一条通道对应一个耦合常数（如 square 的 Ja/Jb/Jc）。表里存
通道编号，耦合常数由使用者按名字传入。

``groups`` 给出观测量用的子晶格划分（每个 init 一组划分），
``init_states`` 给出每个初态下每个 cell 的初始自旋（+1 / -1）。
"""

import os
import time

import numpy as np
from numba import njit, prange

from mcta.mc import functions

kB = 8.61733e-2          # 玻尔兹曼常数 (meV/K)

__all__ = ["Lattice", "kB", "run"]


# ===========================================================================
# 表
# ===========================================================================
class Lattice:
    """一个构型的完整描述。

    属性
    ----
    name         构型名（"square" 等），只用于日志
    nlayer       层数
    nblock       每层的块数
    X_s, Y_s     块内格点数（周期）
    channels     耦合通道名，如 ``("Ja", "Jb", "Jc")``
    nbr_cell     邻居表：每个 cell 的目标 cell 编号（CSR 风格）
    nbr_dj       邻居表：行偏移
    nbr_di       邻居表：列偏移
    nbr_ch       邻居表：耦合通道编号
    nbr_ptr      CSR 起点，``len == ncell + 1``
    cell_order   cell 的遍历顺序（影响更新次序，进而影响可复现性）
    init_states  初态名 -> 每 cell 的初始自旋（+1/-1，int8 数组）
    groups       初态名 -> 子晶格分组（每组是 cell 编号的数组）
    num_atoms    原子数（用于比热的归一）
    factor_atoms 磁化率的归一系数（单组时 = num_atoms，两组时另定）
    accept_factor 接受判据里的系数：``p = exp(accept_factor * beta * dE)``。
                  普通 Ising 是 2.0；S=3/2 的 u_3 变体是 4.5（因为它的
                  自旋自由度更多、翻转代价不同）。这是自旋模型的属性，
                  放在表里由计算层照用。
    param_map     CLI 的 ``-p`` 参数怎么映射到各条通道。默认按顺序一一
                  对应、缺的补 0；个别构型有特殊规则（比如 bilayer-ab
                  给少于 5 个参数时，第 5 条通道取第 2 个的值）。
    """

    __slots__ = ("name", "nlayer", "nblock", "X_s", "Y_s", "channels",
                 "nbr_cell", "nbr_dj", "nbr_di", "nbr_ch", "nbr_ptr",
                 "cell_order", "init_states", "groups", "num_atoms",
                 "factor_atoms", "X", "Y", "accept_factor",
                 "param_map")

    def __init__(self, name, nlayer, nblock, X_s, Y_s, channels,
                 nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order,
                 init_states, groups, num_atoms, factor_atoms=None,
                 X=None, Y=None, accept_factor=2.0, param_map=None):
        self.name = name
        self.nlayer = nlayer
        self.nblock = nblock
        self.X_s = X_s
        self.Y_s = Y_s
        self.channels = tuple(channels)
        self.nbr_cell = np.ascontiguousarray(nbr_cell, dtype=np.int64)
        self.nbr_dj = np.ascontiguousarray(nbr_dj, dtype=np.int64)
        self.nbr_di = np.ascontiguousarray(nbr_di, dtype=np.int64)
        self.nbr_ch = np.ascontiguousarray(nbr_ch, dtype=np.int64)
        self.nbr_ptr = np.ascontiguousarray(nbr_ptr, dtype=np.int64)
        self.cell_order = np.ascontiguousarray(cell_order, dtype=np.int64)
        self.init_states = init_states
        self.groups = groups
        self.num_atoms = num_atoms
        self.factor_atoms = num_atoms if factor_atoms is None else factor_atoms
        self.X = X
        self.Y = Y
        self.accept_factor = accept_factor
        # param_map：None 表示"按顺序一一对应、缺的补 0"
        self.param_map = param_map

    @property
    def ncell(self):
        """cell 总数。"""
        return self.nlayer * self.nblock

    @property
    def nchannel(self):
        """耦合通道数。"""
        return len(self.channels)

    @property
    def n_neighbors(self):
        """每个 cell 的邻居数（各 cell 相同）。"""
        return self.nbr_ptr[1] - self.nbr_ptr[0]

    def coupling(self, J):
        """按表里的规则把 CLI 参数变成各条通道的耦合常数。

        默认：``J[0], J[1], ...`` 一一对应，缺的补 0，多余的忽略。
        ``param_map`` 给了特殊规则时按它来。
        """
        values = np.zeros(self.nchannel)
        if self.param_map is None:
            for idx in range(min(self.nchannel, len(J))):
                values[idx] = J[idx]
            return values
        for channel, source in self.param_map.items():
            idx = self.channels.index(channel)
            if isinstance(source, int):
                if source < len(J):
                    values[idx] = J[source]
            else:                       # source 是一个取值列表
                for s in source:
                    if s < len(J):
                        values[idx] = J[s]
                        break
        return values

    def initial_state(self, init):
        """按初态名生成初始自旋数组，形状 ``(ncell, Y_s, X_s)``。"""
        if init not in self.init_states:
            raise KeyError("构型 %s 不支持初态 %r（可选：%s）"
                           % (self.name, init, ", ".join(sorted(self.init_states))))
        signs = self.init_states[init]
        return np.repeat(signs[:, None, None], self.Y_s, axis=1).repeat(
            self.X_s, axis=2).astype(np.int8)

    def summary(self):
        """给日志用的一行摘要。"""
        return ("%s: %d 层 x %d 块, 每块 %dx%d, %d 邻居, 通道 %s"
                % (self.name, self.nlayer, self.nblock, self.X_s, self.Y_s,
                   self.n_neighbors, "/".join(self.channels)))


# ===========================================================================
# 内核：只读表，不认几何
# ===========================================================================
@njit(inline='always')
def _u01(seed, sweep, cell, j, i):
    """counter-based 均匀随机数（splitmix64 变体）。

    同一个 (seed, sweep, cell, j, i) 永远得到同一个数，与线程数、调度
    顺序都无关，所以结果可复现，也不用在 Python 侧生成巨大的随机数数组。
    """
    c = np.uint64(seed) ^ (np.uint64(sweep) * np.uint64(0x9E3779B97F4A7C15))
    c ^= np.uint64(cell + 1) * np.uint64(0xBF58476D1CE4E5B9)
    c ^= np.uint64(j + 1) * np.uint64(0x94D049BB133111EB)
    c ^= np.uint64(i + 1) * np.uint64(0xD6E8FEB86659FD93)
    c ^= c >> np.uint64(33)
    c *= np.uint64(0xFF51AFD7ED558CCD)
    c ^= c >> np.uint64(33)
    c *= np.uint64(0xC4CEB9FE1A85EC53)
    c ^= c >> np.uint64(33)
    return (c >> np.uint64(11)) * (1.0 / 9007199254740992.0)


@njit(cache=True)
def update3(spins, seed, sweep, X_s, Y_s, coup, val, accept_factor,
            nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order):
    """一条链的一次 sweep。

    链内串行：按 ``cell_order`` 依次更新每个 cell 的每个格点。
    每个格点的局域场由表给出：遍历该 cell 的邻居，把邻居自旋按通道
    加权求和，再乘以自己的自旋得到能量改变。

    返回全体系的能量和（与旧实现同量纲）。
    """
    nn_sum = 0.0
    for co in range(len(cell_order)):
        c = cell_order[co]
        for j in range(Y_s):
            for i in range(X_s):
                h = 0.0
                for k in range(nbr_ptr[c], nbr_ptr[c + 1]):
                    tc = nbr_cell[k]
                    dj = nbr_dj[k]
                    di = nbr_di[k]
                    jj = j + dj
                    if jj >= Y_s:
                        jj -= Y_s
                    elif jj < 0:
                        jj += Y_s
                    ii = i + di
                    if ii >= X_s:
                        ii -= X_s
                    elif ii < 0:
                        ii += X_s
                    h += coup[nbr_ch[k]] * spins[tc, jj, ii]
                energy = -h * spins[c, j, i]
                if val == 0:
                    if energy > 0:
                        spins[c, j, i] *= -1
                else:
                    if energy >= 0 or _u01(seed, sweep, c, j, i) < np.exp(accept_factor * val * energy):
                        spins[c, j, i] *= -1
                nn_sum += energy
    return nn_sum


# ===========================================================================
# 矢量自旋内核族（经典 Heisenberg 型，自旋是三分量单位矢量）
# ===========================================================================
#
# 标量内核和矢量内核**共用同一张表**——邻居关系、耦合通道都一样，
# 区别只在：
#   * 自旋是 (x, y, z) 三分量，而不是标量 ±1
#   * 交换能对三个分量**分别**计算
#   * 多一个单点各向异性项（Aa / Ab），只作用在某一个分量上
#   * 提议是"翻转到随机取向"，而不是"翻转符号"


@njit(inline='always')
def _aniso_energy(v0, v1, v2, Aa, Ab):
    """单个自旋的各向异性能。

    Aa < 0 时各向异性在 x 分量；Aa == Ab 时退化成一维（-Aa * v^2）。
    """
    if Aa < 0:
        if Aa == Ab:
            return -Aa * v0 * v0
        return Aa * v1 * v1 + Ab * v2 * v2
    if Aa == Ab:
        return -Aa * v2 * v2
    return Aa * v0 * v0 + Ab * v1 * v1


@njit(cache=True)
def update3_vector(spins, laRn, Aa, Ab, seed, sweep, X_s, Y_s, coup, val,
                   nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order):
    """矢量自旋：一条链的一次 sweep（链内串行）。

    spins : (ncell, Y_s, X_s, 3)，就地更新
    laRn  : (ncell, Y_s, X_s, 3)，每个格点的随机取向提议
    """
    nn_sum = 0.0
    for co in range(len(cell_order)):
        c = cell_order[co]
        for j in range(Y_s):
            for i in range(X_s):
                # --- 三个分量各自的交换场 ---
                h0 = 0.0
                h1 = 0.0
                h2 = 0.0
                for k in range(nbr_ptr[c], nbr_ptr[c + 1]):
                    tc = nbr_cell[k]
                    dj = nbr_dj[k]
                    di = nbr_di[k]
                    jj = j + dj
                    if jj >= Y_s:
                        jj -= Y_s
                    elif jj < 0:
                        jj += Y_s
                    ii = i + di
                    if ii >= X_s:
                        ii -= X_s
                    elif ii < 0:
                        ii += X_s
                    w = coup[nbr_ch[k]]
                    h0 += w * spins[tc, jj, ii, 0]
                    h1 += w * spins[tc, jj, ii, 1]
                    h2 += w * spins[tc, jj, ii, 2]

                e0 = -h0 * spins[c, j, i, 0]
                e1 = -h1 * spins[c, j, i, 1]
                e2 = -h2 * spins[c, j, i, 2]

                ez = _aniso_energy(spins[c, j, i, 0], spins[c, j, i, 1],
                                   spins[c, j, i, 2], Aa, Ab)
                Ez = _aniso_energy(laRn[c, j, i, 0], laRn[c, j, i, 1],
                                   laRn[c, j, i, 2], Aa, Ab)

                energy = e0 + e1 + e2
                # 用随机取向时的交换能（各分量分别算）
                Erandn = (-h0 * laRn[c, j, i, 0] - h1 * laRn[c, j, i, 1]
                           - h2 * laRn[c, j, i, 2] + Ez)

                if val == 0:
                    if energy < 0:
                        DeltaE = ez + energy - Erandn
                    else:
                        spins[c, j, i, 0] *= -1
                        spins[c, j, i, 1] *= -1
                        spins[c, j, i, 2] *= -1
                        DeltaE = ez - energy - Erandn
                    if DeltaE > 0:
                        spins[c, j, i, 0] = laRn[c, j, i, 0]
                        spins[c, j, i, 1] = laRn[c, j, i, 1]
                        spins[c, j, i, 2] = laRn[c, j, i, 2]
                else:
                    if energy < 0:
                        if e2 >= 0 or _u01(seed, sweep, c, j, i) < np.exp(2.0 * val * e2):
                            spins[c, j, i, 2] *= -1
                            DeltaE = ez + e0 + e1 - e2 - Erandn
                        else:
                            DeltaE = ez + energy - Erandn
                    else:
                        spins[c, j, i, 0] *= -1
                        spins[c, j, i, 1] *= -1
                        spins[c, j, i, 2] *= -1
                        DeltaE = ez - energy - Erandn

                    if DeltaE >= 0 or _u01(seed, sweep, c, j, i) < np.exp(val * DeltaE):
                        spins[c, j, i, 0] = laRn[c, j, i, 0]
                        spins[c, j, i, 1] = laRn[c, j, i, 1]
                        spins[c, j, i, 2] = laRn[c, j, i, 2]

                # 总能量按 z 分量的符号统计（与旧实现一致）
                z0 = 1.0 if spins[c, j, i, 2] >= 0 else -1.0
                field = 0.0
                for k in range(nbr_ptr[c], nbr_ptr[c + 1]):
                    tc = nbr_cell[k]
                    dj = nbr_dj[k]
                    di = nbr_di[k]
                    jj = j + dj
                    if jj >= Y_s:
                        jj -= Y_s
                    elif jj < 0:
                        jj += Y_s
                    ii = i + di
                    if ii >= X_s:
                        ii -= X_s
                    elif ii < 0:
                        ii += X_s
                    zn = 1.0 if spins[tc, jj, ii, 2] >= 0 else -1.0
                    field -= coup[nbr_ch[k]] * zn
                nn_sum += field * z0

    return nn_sum


@njit(cache=True, parallel=True)
def sweeps_vector(spins, las, seeds, vals, sweep0, nsteps, X_s, Y_s, coup,
                  Aa, Ab, nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order,
                  offset, Nw, Ew, record, Ecur):
    """矢量自旋：多条独立链并行推进（每条链内部串行）。"""
    nrep = spins.shape[0]
    for r in prange(nrep):
        sp = spins[r]
        val = vals[r]
        for c in range(nsteps):
            E0 = update3_vector(sp, las[r, c], Aa, Ab, seeds[r], sweep0 + c,
                                X_s, Y_s, coup, val, nbr_cell, nbr_dj, nbr_di,
                                nbr_ch, nbr_ptr, cell_order)
            Ecur[r] = E0 / 2.0
            if record:
                idx = offset + c
                Ew[r, idx] = E0 / 2.0
                for c2 in range(sp.shape[0]):
                    blk = sp[c2, :, :, 2]
                    Nw[r, idx, c2] = np.sum(blk) / blk.size


@njit(cache=True, parallel=True)
def sweeps(spins, seeds, vals, sweep0, nsteps, X_s, Y_s, coup, accept_factor,
            nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order,
            offset, Nw, Ew, record, Ecur):
    """多条独立链并行推进 nsteps 个 sweep（每条链内部串行）。

    spins : (nrep, ncell, Y_s, X_s)，就地更新
    seeds : (nrep,)，每条链的基准随机种子
    vals  : (nrep,)，每条链自己的逆温度 1/kT（replica exchange 时各链温度不同）
    Nw    : (nrep, nworks, ncell)，每个采样点各 cell 的磁化
    Ew    : (nrep, nworks)，每个采样点的总能量
    Ecur  : (nrep,)，每条链当前的总能量（交换判据要用）
    """
    nrep = spins.shape[0]
    for r in prange(nrep):
        sp = spins[r]
        val = vals[r]
        for c_step in range(nsteps):
            E0 = update3(sp, seeds[r], sweep0 + c_step, X_s, Y_s, coup, val,
                         accept_factor, nbr_cell, nbr_dj, nbr_di, nbr_ch,
                         nbr_ptr, cell_order)
            Ecur[r] = E0 / 2.0
            if record:
                idx = offset + c_step
                Ew[r, idx] = E0 / 2.0
                for c in range(sp.shape[0]):
                    blk = sp[c]
                    Nw[r, idx, c] = np.sum(blk) / blk.size


@njit(cache=True)
def block_magnetization(spins, group):
    """一组 cell 的平均磁化。"""
    total = 0.0
    count = 0
    for k in range(len(group)):
        blk = spins[group[k]]
        total += np.sum(blk)
        count += blk.size
    return total / count


# ===========================================================================
# 驱动
# ===========================================================================
def _chain_seeds(seed, n, rng):
    """每条链一个基准种子。

    随机数在核内按 (种子, sweep 序号, 格点) 现算，所以既不占内存，
    也不会因为线程调度而变。

    给了 seed 时，链种子由它**派生**（而不是随机生成）：这样同一个
    --seed 一定得到同一批结果，且不同链之间互不相同。不给 seed 时
    才是随机的。
    """
    if seed is None:
        return rng.integers(0, 2 ** 63 - 1, size=n, dtype=np.uint64)
    return (np.uint64(seed) * np.arange(1, n + 1, dtype=np.uint64)
            + np.uint64(0x9E3779B97F4A7C15))


def _logger(file):
    """给本次运行建一个独立的 logger：写文件 + 打到终端。

    不用 logging.basicConfig，是因为它在 root logger 已有 handler 时会直接
    失效——同一进程里跑第二次时日志会写进上一次的 .log 文件。
    """
    import logging
    logger = logging.getLogger("mcta.mc." + os.path.basename(file))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    formatter = logging.Formatter("%(message)s")
    out = logging.FileHandler(file, mode="w", encoding="utf-8")
    out.setFormatter(formatter)
    logger.addHandler(out)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger



def _swap_configs(latts, Ecur, vals, rng, first):
    """在相邻温度之间尝试交换构型（replica exchange / 并行回火）。

    Metropolis 判据：``p = min(1, exp[(b_i - b_j)(E_i - E_j)])``，其中
    b = 1/kT。链号固定对应温度，交换的只是构型，所以每个温度上的采样序列
    仍然是连续的马尔可夫链。奇偶交替选对，避免同一条链同时参与两次交换。
    """
    accepted = 0
    for i in range(first, len(vals) - 1, 2):
        j = i + 1
        log_ratio = (vals[i] - vals[j]) * (Ecur[i] - Ecur[j])
        if log_ratio >= 0.0 or rng.random() < np.exp(log_ratio):
            tmp = latts[i].copy()
            latts[i] = latts[j]
            latts[j] = tmp
            Ecur[i], Ecur[j] = Ecur[j], Ecur[i]
            accepted += 1
    return accepted


def _observables(Nw, Ew, groups, val, factor, arrays_T2, num):
    """从一条链的采样序列算磁化、磁化率、比热。

    ``Nw`` 形状 (nworks, ncell)，``groups`` 是若干 cell 编号数组。
    """
    mags, chis = [], []
    for group in groups:
        arr = Nw[:, group]
        m_ave = functions.Average(arr)
        s_ave = functions.Average2(arr)
        mags.append(m_ave)
        chis.append(val * factor * (s_ave - m_ave ** 2))
    cv = arrays_T2 * (functions.Average2(Ew) - functions.Average(Ew) ** 2) / num
    return mags, chis, cv


def run(lattice, file, init, J, arrays_temperatures, nequilibrium, nworks,
        chains=1, seed=None, swap=0):
    """用给定的表跑一次 Ising 蒙特卡洛。

    参数
    ----
    lattice          :Lattice: 构型表
    file             日志文件名
    init             初态名
    J                耦合常数列表，按 ``lattice.channels`` 的顺序
    arrays_temperatures  温度列表 (K)
    nequilibrium, nworks  平衡 / 采样 sweep 数
    chains         独立链数（多核加速）
    seed             随机数种子，给定则可复现
    swap             replica exchange 的交换间隔（0 = 关闭）
    """
    logger = _logger(file)
    X_s, Y_s = lattice.X_s, lattice.Y_s
    ncell = lattice.ncell
    num = lattice.num_atoms

    # 耦合常数：按表里的映射规则从 CLI 参数得到
    coup = lattice.coupling(J)

    np.seterr(divide='ignore', invalid='ignore')
    arrays_values = np.where(arrays_temperatures < 0.01, 0,
                              1.0 / (arrays_temperatures * kB))
    lav = len(arrays_values)
    arrays_T2 = kB * arrays_values ** 2

    logger.info("{} {:<12} {} {} × {:<8} {} {} + {:<8} {} {}".format(
        "configuration:", lattice.name, "lattice dimensions:",
        lattice.X, lattice.Y, "iterations:", nequilibrium, nworks,
        "Atom number:", num))
    logger.info("{} {:<8} {} {:<8}".format(
        "init:", init, "parameters(meV):",
        " ".join("%g" % c for c in coup)))

    groups = lattice.groups.get(init)
    if groups is None:
        logger.info("Inconsistent parameters...")
        return

    single = len(groups) == 1
    factor = lattice.factor_atoms
    rng = np.random.default_rng(seed)

    if swap > 0 and lav >= 2:
        _run_replica_exchange(logger, lattice, init, coup, arrays_values,
                               arrays_temperatures, arrays_T2, groups, single,
                               factor, num, nequilibrium, nworks, swap, rng,
                               seed)
        return

    logger.info("{} {:<8} {}".format(
        "chains:", chains,
        "seed:" if seed is not None else "seed: random"))
    latts = np.zeros((chains, ncell, Y_s, X_s), dtype=np.int8)
    for r in range(chains):
        latts[r] = lattice.initial_state(init)
    Nw_all = np.zeros((chains, nworks, ncell))
    Ew_all = np.zeros((chains, nworks))
    Ecur = np.zeros(chains)
    seeds = _chain_seeds(seed, chains, rng)
    sweep_id = 0

    _log_header(logger, groups, single, latts[0])

    for i in range(lav):
        t0 = time.time()
        val = arrays_values[i]
        vals = np.full(chains, val)
        # 每个温度重新开始计数：旧实现每个温度都会重新生成随机数，
        # 这里保持一致，让同一个 seed 的结果可复现
        sweep_id = 0
        # 平衡：链内串行、链间并行
        sweeps(latts, seeds, vals, sweep_id, nequilibrium, X_s, Y_s, coup,
               lattice.accept_factor, lattice.nbr_cell, lattice.nbr_dj,
               lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
               lattice.cell_order, 0, Nw_all, Ew_all, False, Ecur)
        sweep_id += nequilibrium
        # 采样
        sweeps(latts, seeds, vals, sweep_id, nworks, X_s, Y_s, coup,
               lattice.accept_factor, lattice.nbr_cell, lattice.nbr_dj,
               lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
               lattice.cell_order, 0, Nw_all, Ew_all, True, Ecur)
        sweep_id += nworks
        t = time.time() - t0
        _log_row(logger, groups, single, arrays_temperatures[i], val,
                 arrays_T2[i], factor, num, Nw_all, Ew_all, t)



# ===========================================================================
# 矢量自旋的驱动
# ===========================================================================
def _random_directions(rng, shape):
    """每个格点一个随机单位矢量（三分量）。"""
    arr = rng.standard_normal(shape, dtype=np.float32)
    norm = np.sqrt(np.sum(arr * arr, axis=-1, keepdims=True))
    return (arr / norm).astype(np.float32)


def run_vector(lattice, file, init, J, A, arrays_temperatures, nequilibrium,
               nworks, chains=1, seed=None, swap=0):
    """用给定的表跑一次矢量自旋（经典 Heisenberg 型）蒙特卡洛。

    参数与 :func:`run` 相同，另外：
    A   各向异性常数（1 或 2 个）：``A[0]`` 是 Aa，``A[1]`` 是 Ab
        （只给 1 个时 Ab = Aa）
    """
    logger = _logger(file)
    X_s, Y_s = lattice.X_s, lattice.Y_s
    ncell = lattice.ncell
    num = lattice.num_atoms
    Aa = A[0] if len(A) > 0 else 0.0
    Ab = A[1] if len(A) > 1 else Aa

    coup = lattice.coupling(J)

    np.seterr(divide='ignore', invalid='ignore')
    arrays_values = np.where(arrays_temperatures < 0.01, 0,
                              1.0 / (arrays_temperatures * kB))
    lav = len(arrays_values)
    arrays_T2 = kB * arrays_values ** 2

    logger.info("{} {:<12} {} {} × {:<8} {} {} + {:<8} {}".format(
        "configuration:", lattice.name, "lattice dimensions:",
        lattice.X, lattice.Y, "iterations:", nequilibrium, nworks,
        "Atom number:", num))
    logger.info("{} {:<8} {} {:<8}".format(
        "init:", init, "parameters(meV):",
        " ".join("%g" % c for c in coup)))
    logger.info("{} {:<8} {} {:<8} {:<8} {:<8}".format(
        "init:", init, "parameters(meV):",
        " ".join("%g" % c for c in coup), "anisotropy:", "%g" % Aa))

    groups = lattice.groups.get(init)
    if groups is None:
        logger.info("Inconsistent parameters...")
        return

    single = len(groups) == 1
    factor = lattice.factor_atoms
    rng = np.random.default_rng(seed)

    def make_state():
        """初态：三分量，z 分量按表里的符号，xy 分量为 0。"""
        signs = lattice.init_states[init]
        st = np.zeros((ncell, Y_s, X_s, 3), dtype=np.float32)
        st[:, :, :, 2] = signs[:, None, None]
        return st

    logger.info("{} {:<8} {}".format(
        "chains:", chains,
        "seed:" if seed is not None else "seed: random"))

    if swap > 0 and lav >= 2:
        _run_replica_exchange_vector(logger, lattice, init, coup, Aa, Ab,
                                     make_state, arrays_values,
                                     arrays_temperatures, arrays_T2, groups,
                                     single, factor, num, nequilibrium, nworks,
                                     swap, rng, seed)
        return

    latts = np.zeros((chains, ncell, Y_s, X_s, 3), dtype=np.float32)
    for r in range(chains):
        latts[r] = make_state()
    Nw_all = np.zeros((chains, nworks, ncell))
    Ew_all = np.zeros((chains, nworks))
    Ecur = np.zeros(chains)
    seeds = _chain_seeds(seed, chains, rng)
    sweep_id = 0

    _log_header(logger, groups, single, latts[0])

    for i in range(lav):
        t0 = time.time()
        val = arrays_values[i]
        vals = np.full(chains, val)
        sweep_id = 0
        # 随机取向提议：每个 sweep 重新随机
        chunk = 32
        for phase, nsteps, record in ((0, nequilibrium, False), (1, nworks, True)):
            done = 0
            while done < nsteps:
                n = min(chunk, nsteps - done)
                las = _random_directions(rng, (chains, n, ncell, Y_s, X_s, 3))
                sweeps_vector(latts, las, seeds, vals, sweep_id, n, X_s, Y_s,
                              coup, Aa, Ab, lattice.nbr_cell, lattice.nbr_dj,
                              lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
                              lattice.cell_order, done if record else 0,
                              Nw_all, Ew_all, record, Ecur)
                sweep_id += n
                done += n
        t = time.time() - t0
        _log_row(logger, groups, single, arrays_temperatures[i], val,
                 arrays_T2[i], factor, num, Nw_all, Ew_all, t)


def _run_replica_exchange_vector(logger, lattice, init, coup, Aa, Ab, make_state,
                                  arrays_values, arrays_temperatures, arrays_T2,
                                  groups, single, factor, num, nequilibrium,
                                  nworks, swap, rng, seed):
    """矢量自旋的 replica exchange。"""
    nT = len(arrays_values)
    X_s, Y_s = lattice.X_s, lattice.Y_s
    ncell = lattice.ncell
    logger.info("{} {:<8} {} {}".format("chains:", nT, "swap every:",
                                         "%d sweeps" % swap))
    latts = np.zeros((nT, ncell, Y_s, X_s, 3), dtype=np.float32)
    for t in range(nT):
        latts[t] = make_state()
    vals = np.array(arrays_values, dtype=float)
    Nw_all = np.zeros((nT, nworks, ncell))
    Ew_all = np.zeros((nT, nworks))
    Ecur = np.zeros(nT)
    seeds = _chain_seeds(seed, nT, rng)
    sweep_id = 0
    attempt = 0
    accepted = 0
    t_start = time.time()

    _log_header(logger, groups, single, latts[0])

    for phase, nsteps, record in ((0, nequilibrium, False), (1, nworks, True)):
        done = 0
        while done < nsteps:
            n = min(swap, nsteps - done)
            las = _random_directions(rng, (nT, n, ncell, Y_s, X_s, 3))
            sweeps_vector(latts, las, seeds, vals, sweep_id, n, X_s, Y_s, coup,
                          Aa, Ab, lattice.nbr_cell, lattice.nbr_dj,
                          lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
                          lattice.cell_order, done if record else 0,
                          Nw_all, Ew_all, record, Ecur)
            sweep_id += n
            done += n
            attempt += 1
            accepted += _swap_configs(latts, Ecur, vals, rng, attempt % 2)

    elapsed = time.time() - t_start
    logger.info("{} {:<8} {}".format("swaps:", attempt, "accepted: %d" % accepted))
    for i in range(nT):
        _log_row(logger, groups, single, arrays_temperatures[i],
                 arrays_values[i], arrays_T2[i], factor, num,
                 Nw_all[i: i + 1], Ew_all[i: i + 1], elapsed)

def _log_header(logger, groups, single, latt0):
    """写表头与初态磁化。

    ``latt0`` 是 (ncell, ...) 形状，磁化取 z 分量（对标量自旋就是它本身）。
    """
    if single:
        logger.info("{:>16} {:>16}".format("Round", "magnetism"))
        m_ave = functions.Average(latt0[..., 2] if latt0.ndim == 4 else latt0)
        logger.info("{:>16} {:>16.6}".format(0, m_ave))
        logger.info("{:>16} {:>16} {:>16} {:>16} {:>16}".format(
            "Temperature", "magnetism", "susceptibility", "specific heat", "time(s)"))
    else:
        logger.info("{:>16} {:>16} {:>16}".format("Round", "magnetism0", "magnetism1"))
        mags = [functions.Average(latt0[group, ..., 2] if latt0.ndim == 4
                                 else latt0[group]) for group in groups]
        logger.info("{:>16} {:>16.6} {:>16.6}".format(0, mags[0], mags[1]))
        logger.info("{:>16} {:>16} {:>16} {:>18} {:>18} {:>16} {:>16}".format(
            "Temperature", "magnetism0(e)", "magnetism1(e)", "susceptibility0(e)",
            "susceptibility1(e)", "specific heat", "time(s)"))


def _log_row(logger, groups, single, temperature, val, T2, factor,
              num, Nw_all, Ew_all, t):
    """写一个温度的结果（对各链取平均）。"""
    Nw = Nw_all.mean(axis=0)
    Ew = Ew_all.mean(axis=0)
    mags, chis, cv = _observables(Nw, Ew, groups, val, factor, T2, num)
    if single:
        logger.info("{:>16.2f} {:>16.6f} {:>16.6f} {:>16.6f} {:>16.6f}".format(
            temperature, float(mags[0]), float(chis[0]), float(cv), t))
    else:
        logger.info("{:>16.2f} {:>16.6f} {:>16.6f} {:>18.6f} {:>18.6f} {:>16.6f} {:>16.6f}".format(
            temperature, float(mags[0]), float(mags[1]), float(chis[0]),
            float(chis[1]), float(cv), t))


def _run_replica_exchange(logger, lattice, init, coup, arrays_values,
                           arrays_temperatures, arrays_T2, groups, single,
                           factor, num, nequilibrium, nworks, swap, rng,
                           seed):
    """replica exchange（并行回火）：每个温度一条链，定期交换相邻温度的构型。"""
    nT = len(arrays_values)
    X_s, Y_s = lattice.X_s, lattice.Y_s
    ncell = lattice.ncell
    logger.info("{} {:<8} {} {}".format("chains:", nT, "swap every:",
                                         "%d sweeps" % swap))
    latts = np.zeros((nT, ncell, Y_s, X_s), dtype=np.int8)
    for t in range(nT):
        latts[t] = lattice.initial_state(init)
    vals = np.array(arrays_values, dtype=float)
    Nw_all = np.zeros((nT, nworks, ncell))
    Ew_all = np.zeros((nT, nworks))
    Ecur = np.zeros(nT)
    seeds = _chain_seeds(seed, nT, rng)
    sweep_id = 0
    attempt = 0
    accepted = 0
    t_start = time.time()

    _log_header(logger, groups, single, latts[0])

    for phase, nsteps, record in ((0, nequilibrium, False), (1, nworks, True)):
        done = 0
        while done < nsteps:
            n = min(swap, nsteps - done)
            sweeps(latts, seeds, vals, sweep_id, n, X_s, Y_s, coup,
                   lattice.accept_factor, lattice.nbr_cell, lattice.nbr_dj,
                   lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
                   lattice.cell_order, done if record else 0, Nw_all, Ew_all,
                   record, Ecur)
            sweep_id += n
            done += n
            attempt += 1
            accepted += _swap_configs(latts, Ecur, vals, rng, attempt % 2)

    elapsed = time.time() - t_start
    logger.info("{} {:<8} {}".format("swaps:", attempt, "accepted: %d" % accepted))
    for i in range(nT):
        _log_row(logger, groups, single, arrays_temperatures[i],
                 arrays_values[i], arrays_T2[i], factor, num,
                 Nw_all[i: i + 1], Ew_all[i: i + 1], elapsed)
