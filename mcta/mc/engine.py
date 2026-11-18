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
import numba
from numba import njit, prange

kB = 8.61733e-2          # 玻尔兹曼常数 (meV/K)


def inverse_temperature(temperatures):
    """温度 (K) -> β = 1/(kB T)；只有 T<=0 用 0 作零温淬火哨兵。

    旧实现把 T<0.01 K 也映射成 0，导致正的极低温变成零温淬火；XY 内核
    中 val=0 又恰好表示无穷温接受全部提议，物理含义完全相反。这里只把
    T<=0 当作显式的零温淬火。
    """
    temps = np.asarray(temperatures, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(temps <= 0, 0.0, 1.0 / (temps * kB))


__all__ = ["Lattice", "kB", "run", "inverse_temperature"]


def Average(arr):
    """数组元素的算术平均（沿用旧 functions.py 的接口）。"""
    return np.sum(arr) / arr.size


def Average2(arr):
    """数组元素平方的算术平均。"""
    return np.sum(arr ** 2) / arr.size


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
    X, Y, Z      用户层面的扩胞尺寸；Z=None 表示二维
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
    factor_atoms 磁化率的归一系数 = 每个 cell 的磁格点数；
                 因为 Nw 记的是每 cell 的平均磁化，方差按 cell 统计。
    spin_scale   每 cell 的自旋标度 S = mom/2（结构模式 --mom 设定；
                 None = 全 1）。只影响输出的磁化/磁化率标度，自旋变量
                 仍是 ±1，能量由 nbr_SS 折算，与它无关。
    nbr_SS       每 cell 的 per-edge S(own) * S(neighbor)，
                 ``len == len(nbr_cell)``；None = 全 1（σ=±1 就是单位自旋）。
                 run 层据此把通道耦合预乘成 per-edge 的 ``nbr_coup``，内核
                 直接查它，所以 Ew/Ecur 都是物理能量（meV），交换判据和
                 比热不需要再乘任何系数。磁矩一律走这里折算；接受判据里
                 ±1 自旋的指数系数固定为 2（翻转使单点能量改变 -2E）。
    param_map    CLI 的 ``-p`` 参数怎么映射到各条通道。默认按顺序一一
                 对应、缺的补 0；个别构型有特殊规则（比如 bilayer-ab
                 给少于 5 个参数时，第 5 条通道取第 2 个的值）。
    """

    __slots__ = ("name", "nlayer", "nblock", "X_s", "Y_s", "channels",
                 "nbr_cell", "nbr_dj", "nbr_di", "nbr_ch", "nbr_ptr",
                 "cell_order", "init_states", "groups", "num_atoms",
                 "factor_atoms", "X", "Y", "Z", "nbr_SS",
                 "param_map", "spin_scale",
                 "xy_bonds", "xy_loops", "xy_loop_ptr", "xy_area")

    def __init__(self, name, nlayer, nblock, X_s, Y_s, channels,
                 nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order,
                 init_states, groups, num_atoms, factor_atoms=None,
                 X=None, Y=None, Z=None, nbr_SS=None,
                 param_map=None, spin_scale=None,
                 xy_bonds=None, xy_loops=None, xy_loop_ptr=None,
                 xy_area=None):
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
        self.Z = Z
        self.nbr_SS = nbr_SS
        # param_map：None 表示"按顺序一一对应、缺的补 0"
        self.param_map = param_map
        # spin_scale：每 cell 的自旋标度 S = mom/2（结构模式 --mom）；None = 全 1
        self.spin_scale = spin_scale
        # XY 判据元数据（仅 xy-* 构型设置）：无向边表与最小环表
        self.xy_bonds = xy_bonds
        self.xy_loops = xy_loops
        self.xy_loop_ptr = xy_loop_ptr
        self.xy_area = xy_area

        # 内核直接按这些表索引，长度对不上会越界或静默算错，先在这里卡住
        if self.nbr_SS is not None and len(self.nbr_SS) != len(self.nbr_cell):
            raise ValueError('nbr_SS 长度 %d != 邻居表长度 %d'
                             % (len(self.nbr_SS), len(self.nbr_cell)))
        if (self.spin_scale is not None
                and len(self.spin_scale) != self.nlayer * self.nblock):
            raise ValueError('spin_scale 长度 %d != cell 数 %d'
                             % (len(self.spin_scale), self.nlayer * self.nblock))

    @property
    def dimensions(self):
        """日志文件名和文件头使用的二维或三维扩胞尺寸。"""
        if self.Z is None:
            return self.X, self.Y
        return self.X, self.Y, self.Z

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

    def coupling3(self, J, JX=None, JY=None):
        """矢量自旋：x/y/z 三方向各自的通道耦合，返回 ``(nchannel, 3)``。

        -p 给 z 方向；-J/-K 分别覆盖 x/y 方向（没给的方向取 -p）。
        """
        cz = self.coupling(J)
        cx = self.coupling(JX) if JX else cz
        cy = self.coupling(JY) if JY else cz
        return np.stack([cx, cy, cz], axis=-1)

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
def total_energy(spins, X_s, Y_s, coup, nbr_cell, nbr_dj, nbr_di, nbr_ch,
                 nbr_ptr, nbr_coup=None):
    """标量构型的精确物理能量 H = -1/2 Σ_edges J_ij s_i s_j。

    邻居表把每条无向边记两次（i 的表里有 j，j 的表里有 i），所以取 1/2。
    这个函数只在初始化和测试里用：热更新走 update3 的增量维护，不必每个
    sweep 重算一遍整张表。
    """
    E = 0.0
    for c in range(spins.shape[0]):
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
                    kc = nbr_coup[k] if nbr_coup is not None \
                        else coup[nbr_ch[k]]
                    h += kc * spins[tc, jj, ii]
                E -= 0.5 * h * spins[c, j, i]
    return E


@njit(cache=True)
def update3(spins, seed, sweep, X_s, Y_s, coup, val,
            nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order,
            E0, nbr_coup=None):
    """一条链的一次 sweep，返回 sweep 结束时构型的**精确总能量**。

    链内串行：按 ``cell_order`` 依次更新每个 cell 的每个格点。
    每个格点的局域场由表给出：遍历该 cell 的邻居，把邻居自旋按通道
    加权求和，再乘以自己的自旋得到能量改变。

    ``E0`` 是本 sweep 开始前构型的精确总能量。每次接受翻转时，总能量
    改变 ΔE = -2*energy（energy 是翻转前该格点的 -h*s），据此增量维护。
    旧实现把 sweep 途中每个格点翻转前的局域能量直接累加，混进了多个不同
    构型，既不是初态能量也不是末态能量，会让 Ew/C_v/交换判据全部失真。

    ``nbr_coup`` 可选。给了就是 per-edge 的实际耦合（结构模式不同磁矩
    时预乘了 S(own)*S(nbr)）；None 表示按通道查表 ``coup[nbr_ch[k]]``。
    """
    E = E0
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
                    k_coup = nbr_coup[k] if nbr_coup is not None \
                        else coup[nbr_ch[k]]
                    h += k_coup * spins[tc, jj, ii]
                energy = -h * spins[c, j, i]
                if val == 0:
                    if energy > 0:
                        spins[c, j, i] *= -1
                        E -= 2.0 * energy
                else:
                    # ±1 自旋翻转使单点能量改变 -2E，指数系数固定为 2
                    if energy >= 0 or _u01(seed, sweep, c, j, i) < np.exp(2.0 * val * energy):
                        spins[c, j, i] *= -1
                        E -= 2.0 * energy
    return E


# ===========================================================================
# 矢量自旋内核族（经典 Heisenberg 型，自旋是三分量单位矢量）
# ===========================================================================
#
# 标量内核和矢量内核**共用同一张表**——邻居关系、耦合通道都一样，
# 区别只在：
#   * 自旋是 (x, y, z) 三分量，而不是标量 ±1
#   * 交换能对三个分量**分别**计算
#   * 多一个单点各向异性项，参考轴固定为 z：E = Aa·s_x² + Ab·s_y²
#     Aa = E_x - E_z，Ab = E_y - E_z；Ac = Aa - Ab 只用于易轴/易面判断
#   * 提议是"翻转到随机取向"，而不是"翻转符号"


@njit(inline='always')
def _aniso_energy(v0, v1, v2, Aa, Ab):
    """单个自旋的各向异性能，参考轴固定为 z。

    Aa = E_x - E_z，Ab = E_y - E_z。取 E_z = 0 后
        E_ani = Aa * v_x² + Ab * v_y²
    v2 保留只为兼容调用签名；Ac = Aa - Ab 不进能量函数。
    """
    return Aa * v0 * v0 + Ab * v1 * v1


def aniso_easy(Aa, Ab, tol=1e-12):
    """按 Aa/Ab 判断易轴或易平面，返回 (kind, axis, Ac)。

    Ac = E_x - E_y = Aa - Ab：Ac > 0 时 y 低于 x，Ac < 0 时 x 低于 y。
    E_z 固定为 0，三个主轴能量即 {E_x: Aa, E_y: Ab, E_z: 0}。
    kind 取 'axis' / 'plane' / 'iso'，axis 如 'z' / 'xy'。
    """
    Ac = Aa - Ab
    if abs(Ac) <= tol:
        if abs(Aa) <= tol:
            return "iso", "xyz", Ac
        if Aa < 0:
            return "plane", "xy", Ac
        return "axis", "z", Ac
    if Ac > 0:
        if Ab < -tol:
            return "axis", "y", Ac
        if abs(Ab) <= tol:
            return "plane", "yz", Ac
        return "axis", "z", Ac
    if Aa < -tol:
        return "axis", "x", Ac
    if abs(Aa) <= tol:
        return "plane", "xz", Ac
    return "axis", "z", Ac


def init_axis_index(Aa, Ab):
    """按易轴/易面选初态与磁化统计的分量索引（0=x, 1=y, 2=z）。

    易平面取平面内的第一个方向；各向同性保持旧行为（z）。
    """
    kind, axis, _ = aniso_easy(Aa, Ab)
    if kind == "iso":
        return 2
    return {"x": 0, "y": 1, "z": 2}[axis[0]]


@njit(cache=True)
def total_energy_vector(spins, X_s, Y_s, coup, Aa, Ab, nbr_cell, nbr_dj,
                        nbr_di, nbr_ch, nbr_ptr, nbr_coup=None):
    """矢量构型的精确能量 H = -1/2 Σ_edges (J·s_i s_j) + Σ_i aniso(s_i)。

    交换项里每条无向边只算一次（邻居表记两次，故取 1/2），各向异性每个
    格点算一次。这正是 Metropolis 判据实际采样的那个能量，用于初始化和
    测试；热更新走 update3_vector 的增量维护。
    """
    E = 0.0
    for c in range(spins.shape[0]):
        for j in range(Y_s):
            for i in range(X_s):
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
                    if nbr_coup is not None:
                        kc0 = nbr_coup[k, 0]
                        kc1 = nbr_coup[k, 1]
                        kc2 = nbr_coup[k, 2]
                    else:
                        kc0 = coup[nbr_ch[k], 0]
                        kc1 = coup[nbr_ch[k], 1]
                        kc2 = coup[nbr_ch[k], 2]
                    h0 += kc0 * spins[tc, jj, ii, 0]
                    h1 += kc1 * spins[tc, jj, ii, 1]
                    h2 += kc2 * spins[tc, jj, ii, 2]
                E -= 0.5 * (h0 * spins[c, j, i, 0]
                            + h1 * spins[c, j, i, 1]
                            + h2 * spins[c, j, i, 2])
                E += _aniso_energy(spins[c, j, i, 0], spins[c, j, i, 1],
                                   spins[c, j, i, 2], Aa, Ab)
    return E


@njit(cache=True)
def update3_vector(spins, laRn, Aa, Ab, seed, sweep, X_s, Y_s, coup, val,
                   nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order,
                   E0, nbr_coup=None):
    """矢量自旋：一条链的一次 sweep，返回末态的精确总能量。

    spins : (ncell, Y_s, X_s, 3)，就地更新
    laRn  : (ncell, Y_s, X_s, 3)，每个格点的随机取向提议
    E0    : 本 sweep 开始前构型的精确总能量（见 total_energy_vector）

    能量增量按"本格点自旋变化 × 邻居场"精确计算：改变一个格点会同时改变
    它自己和所有邻居的成键能，合起来是 -h·(s_new - s_old)（h 来自未变动
    的邻居），各向异性只改本格点。旧实现用 z 分量符号另算一套 Ising 能量，
    与 Metropolis 实际采样的哈密顿量不是同一个量，这里一并纠正。

    ``nbr_coup`` 可选，形状 ``(nedges, 3)``。给了就是 per-edge 的
    三维耦合（结构模式不同磁矩时预乘了 S(own)*S(nbr)）；None 表示
    按通道查表 ``coup[nbr_ch[k], dir]``。
    """
    E = E0
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
                    kc0 = nbr_coup[k, 0] if nbr_coup is not None \
                        else coup[nbr_ch[k], 0]
                    kc1 = nbr_coup[k, 1] if nbr_coup is not None \
                        else coup[nbr_ch[k], 1]
                    kc2 = nbr_coup[k, 2] if nbr_coup is not None \
                        else coup[nbr_ch[k], 2]
                    h0 += kc0 * spins[tc, jj, ii, 0]
                    h1 += kc1 * spins[tc, jj, ii, 1]
                    h2 += kc2 * spins[tc, jj, ii, 2]

                s0 = spins[c, j, i, 0]
                s1 = spins[c, j, i, 1]
                s2 = spins[c, j, i, 2]
                e0 = -h0 * s0
                e1 = -h1 * s1
                e2 = -h2 * s2

                ez = _aniso_energy(s0, s1, s2, Aa, Ab)
                Ez = _aniso_energy(laRn[c, j, i, 0], laRn[c, j, i, 1],
                                   laRn[c, j, i, 2], Aa, Ab)

                # 标准独立抽样 Metropolis：提议在球面上均匀，故 q 对称；
                # 接受率必须比较「当前态」与「提议态」的能量。旧实现先做
                # z 翻转或整体反转再提议，其中整体反转不是细致平衡步骤，
                # 会让各向异性体系的稳态分布偏离 Boltzmann。
                energy = e0 + e1 + e2
                Erandn = (-h0 * laRn[c, j, i, 0] - h1 * laRn[c, j, i, 1]
                           - h2 * laRn[c, j, i, 2] + Ez)
                DeltaE = ez + energy - Erandn

                if val == 0:                       # T=0：只接受严格降能
                    accept = DeltaE > 0.0
                else:
                    accept = (DeltaE >= 0.0 or
                              _u01(seed, sweep, c, j, i) < np.exp(val * DeltaE))
                if accept:
                    spins[c, j, i, 0] = laRn[c, j, i, 0]
                    spins[c, j, i, 1] = laRn[c, j, i, 1]
                    spins[c, j, i, 2] = laRn[c, j, i, 2]

                # 精确能量增量：本格点变化会影响自己和所有邻居的成键，
                # 合并后交换项是 -h·Δs（h 用的邻居在本格点更新期间不变），
                # 各向异性只改本格点一次。
                n0 = spins[c, j, i, 0]
                n1 = spins[c, j, i, 1]
                n2 = spins[c, j, i, 2]
                E -= h0 * (n0 - s0) + h1 * (n1 - s1) + h2 * (n2 - s2)
                E += _aniso_energy(n0, n1, n2, Aa, Ab) - ez

    return E


@njit(cache=True, parallel=True)
def sweeps_vector(spins, las, seeds, vals, sweep0, nsteps, X_s, Y_s, coup,
                  Aa, Ab, nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order,
                  offset, Nw, Ew, record, Ecur, nbr_coup=None, mag_axis=2):
    """矢量自旋：多条独立链并行推进（每条链内部串行）。

    ``nbr_coup`` 可选，形状 ``(nedges, 3)``，透传给 update3_vector。
    ``mag_axis`` 是记录磁化投影的分量（0/1/2）；初态已对齐易轴时，
    它应跟着易轴走，否则输出磁化会恒为 0。
    """
    nrep = spins.shape[0]
    for r in prange(nrep):
        sp = spins[r]
        val = vals[r]
        for c in range(nsteps):
            Ecur[r] = update3_vector(sp, las[r, c], Aa, Ab, seeds[r], sweep0 + c,
                                     X_s, Y_s, coup, val, nbr_cell, nbr_dj,
                                     nbr_di, nbr_ch, nbr_ptr, cell_order,
                                     Ecur[r], nbr_coup)
            if record:
                idx = offset + c
                Ew[r, idx] = Ecur[r]
                for c2 in range(sp.shape[0]):
                    blk = sp[c2, :, :, mag_axis]
                    Nw[r, idx, c2] = np.sum(blk) / blk.size


@njit(cache=True, parallel=True)
def sweeps(spins, seeds, vals, sweep0, nsteps, X_s, Y_s, coup,
            nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, cell_order,
            offset, Nw, Ew, record, Ecur, nbr_coup=None):
    """多条独立链并行推进 nsteps 个 sweep（每条链内部串行）。

    spins : (nrep, ncell, Y_s, X_s)，就地更新
    seeds : (nrep,)，每条链的基准随机种子
    vals  : (nrep,)，每条链自己的逆温度 1/kT（replica exchange 时各链温度不同）
    Nw    : (nrep, nworks, ncell)，每个采样点各 cell 的磁化
    Ew    : (nrep, nworks)，每个采样点的总能量
    Ecur  : (nrep,)，每条链当前的总能量（交换判据要用）

    ``nbr_coup`` 可选，透传给 update3。
    """
    nrep = spins.shape[0]
    for r in prange(nrep):
        sp = spins[r]
        val = vals[r]
        for c_step in range(nsteps):
            # Ecur[r] 传入当前精确能量，update3 返回本次 sweep 后的精确能量
            Ecur[r] = update3(sp, seeds[r], sweep0 + c_step, X_s, Y_s, coup, val,
                              nbr_cell, nbr_dj, nbr_di, nbr_ch,
                              nbr_ptr, cell_order, Ecur[r], nbr_coup)
            if record:
                idx = offset + c_step
                Ew[r, idx] = Ecur[r]
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
    --seeds 一定得到同一批结果，且不同链之间互不相同。不给 seed 时
    才是随机的。

    派生用 SplitMix64 式的整数哈希，把 seed 和链号一起混合。旧实现用
    ``seed * (1..n) + const``，当 seed=0 时所有链拿到同一个种子，随机流
    完全相同——这里必须避免。
    """
    if seed is None:
        return rng.integers(0, 2 ** 63 - 1, size=n, dtype=np.uint64)
    z = (np.uint64(seed) + np.arange(1, n + 1, dtype=np.uint64)
         * np.uint64(0x9E3779B97F4A7C15))
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


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
        handler.close()
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
    # Nw/Ew 形状 (chains, nworks, ...)。必须在每条链内部先对方差取时间平均，
    # 再把各链的样本合并；若先把链平均再取方差，估计量会按 1/chains 缩小，
    # 使 susceptibility/specific heat 随 -C 增大而系统性偏小。
    if Nw.ndim == 2:
        Nw = Nw[None, ...]
    if Ew.ndim == 1:
        Ew = Ew[None, ...]
    for group in groups:
        arr = Nw[:, :, group]
        m_ave = Average(arr)
        var = float(np.var(arr, axis=1).mean())
        mags.append(m_ave)
        chis.append(val * factor * var)
    cv = arrays_T2 * float(np.var(Ew, axis=1).mean()) / num
    return mags, chis, cv


# 头部信息行：label 后只空一格紧跟 value，字段之间用两个空格分隔。
# 不再按固定列宽对齐；所有结构参数行共用 _info() 保持风格一致。
def _info(*pairs):
    """把若干 (label, value) 拼成一行：label 后只空一格，字段间两空格。"""
    return "  ".join(
        (label + " " + value).rstrip() if value else label
        for label, value in pairs)


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

    # 结构模式不同磁矩时，把通道耦合预乘成 per-edge 的实际耦合
    nbr_coup = None
    if lattice.nbr_SS is not None:
        nbr_coup = np.ascontiguousarray(
            coup[lattice.nbr_ch] * lattice.nbr_SS)

    np.seterr(divide='ignore', invalid='ignore')
    arrays_values = inverse_temperature(arrays_temperatures)
    lav = len(arrays_values)
    arrays_T2 = kB * arrays_values ** 2

    _log_setup(logger, lattice, init, nequilibrium, nworks, num,
               chains, seed, swap, lav,
               [("parameters(meV):", " ".join("%g" % c for c in coup))])

    groups = lattice.groups.get(init)
    if groups is None:
        logger.info("Inconsistent parameters...")
        return

    single = len(groups) == 1
    factor = lattice.factor_atoms
    ss = lattice.spin_scale
    rng = np.random.default_rng(seed)

    if swap > 0 and lav >= 2:
        _run_replica_exchange(logger, lattice, init, coup, arrays_values,
                               arrays_temperatures, arrays_T2, groups, single,
                               factor, num, nequilibrium, nworks, swap, rng,
                               seed, nbr_coup=nbr_coup)
        return

    latts = np.zeros((chains, ncell, Y_s, X_s), dtype=np.int8)
    for r in range(chains):
        latts[r] = lattice.initial_state(init)
    Nw_all = np.zeros((chains, nworks, ncell))
    Ew_all = np.zeros((chains, nworks))
    # 从初态算一次精确能量；之后 sweeps 用增量维护，不必每 sweep 重算
    Ecur = np.array([total_energy(latts[r], X_s, Y_s, coup,
                                  lattice.nbr_cell, lattice.nbr_dj,
                                  lattice.nbr_di, lattice.nbr_ch,
                                  lattice.nbr_ptr, nbr_coup)
                     for r in range(chains)])
    seeds = _chain_seeds(seed, chains, rng)
    sweep_id = 0

    _log_header(logger, groups, single, _scaled_header_state(latts[0], ss))

    for i in range(lav):
        t0 = time.time()
        val = arrays_values[i]
        vals = np.full(chains, val)
        # 每个温度重新开始计数：旧实现每个温度都会重新生成随机数，
        # 这里保持一致，让同一个 seed 的结果可复现
        sweep_id = 0
        # 平衡：链内串行、链间并行
        sweeps(latts, seeds, vals, sweep_id, nequilibrium, X_s, Y_s, coup,
               lattice.nbr_cell, lattice.nbr_dj,
               lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
               lattice.cell_order, 0, Nw_all, Ew_all, False, Ecur,
               nbr_coup)
        sweep_id += nequilibrium
        # 采样
        sweeps(latts, seeds, vals, sweep_id, nworks, X_s, Y_s, coup,
               lattice.nbr_cell, lattice.nbr_dj,
               lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
               lattice.cell_order, 0, Nw_all, Ew_all, True, Ecur,
               nbr_coup)
        sweep_id += nworks
        t = time.time() - t0
        _log_row(logger, groups, single, arrays_temperatures[i], val,
                 arrays_T2[i], factor, num,
                 Nw_all if ss is None else Nw_all * ss, Ew_all, t)



# ===========================================================================
# 矢量自旋的驱动
# ===========================================================================
def _random_directions(rng, shape):
    """每个格点一个随机单位矢量（三分量）。"""
    arr = rng.standard_normal(shape, dtype=np.float32)
    norm = np.sqrt(np.sum(arr * arr, axis=-1, keepdims=True))
    return (arr / norm).astype(np.float32)


def run_vector(lattice, file, init, J, A, arrays_temperatures, nequilibrium,
               nworks, chains=1, seed=None, swap=0, JX=None, JY=None):
    """用给定的表跑一次矢量自旋（经典 Heisenberg 型）蒙特卡洛。

    参数与 :func:`run` 相同，另外：
    A   各向异性常数（1 或 2 个）：``A[0]`` 是 Aa，``A[1]`` 是 Ab
        （只给 1 个时 Ab = Aa）
    JX/JY  x/y 方向的交换耦合（列表，按通道）；没给的方向取 J（-p）
    """
    logger = _logger(file)
    X_s, Y_s = lattice.X_s, lattice.Y_s
    ncell = lattice.ncell
    num = lattice.num_atoms
    Aa = A[0] if len(A) > 0 else 0.0
    Ab = A[1] if len(A) > 1 else Aa

    coup = lattice.coupling3(J, JX, JY)

    # 结构模式不同磁矩时，把通道耦合预乘成 per-edge 的三维耦合
    nbr_coup = None
    if lattice.nbr_SS is not None:
        nbr_coup = np.ascontiguousarray(
            coup[lattice.nbr_ch] * lattice.nbr_SS[:, None])

    np.seterr(divide='ignore', invalid='ignore')
    arrays_values = inverse_temperature(arrays_temperatures)
    lav = len(arrays_values)
    arrays_T2 = kB * arrays_values ** 2

    ss = lattice.spin_scale
    kind, axis, Ac = aniso_easy(Aa, Ab)
    mag_axis = init_axis_index(Aa, Ab)
    label = {"axis": "easy axis", "plane": "easy plane", "iso": "isotropic"}[kind]
    _log_setup(logger, lattice, init, nequilibrium, nworks, num,
               chains, seed, swap, lav, [
        ("Jx/Jy/Jz(meV):",
         "  ".join("%g/%g/%g" % (coup[k, 0], coup[k, 1], coup[k, 2])
                   for k in range(len(coup)))),
        ("anisotropy(meV):", "%g/%g (Ac=%g, %s %s)" %
         (Aa, Ab, Ac, label, axis)),
    ])

    groups = lattice.groups.get(init)
    if groups is None:
        logger.info("Inconsistent parameters...")
        return

    single = len(groups) == 1
    factor = lattice.factor_atoms
    rng = np.random.default_rng(seed)

    def make_state():
        """初态：三分量，按易轴/易面把每 cell 的 ±1 放到对应分量。"""
        signs = lattice.init_states[init]
        st = np.zeros((ncell, Y_s, X_s, 3), dtype=np.float32)
        st[:, :, :, mag_axis] = signs[:, None, None]
        return st

    if swap > 0 and lav >= 2:
        _run_replica_exchange_vector(logger, lattice, init, coup, Aa, Ab,
                                     make_state, mag_axis, arrays_values,
                                     arrays_temperatures, arrays_T2, groups,
                                     single, factor, num, nequilibrium, nworks,
                                     swap, rng, seed, nbr_coup=nbr_coup)
        return

    latts = np.zeros((chains, ncell, Y_s, X_s, 3), dtype=np.float32)
    for r in range(chains):
        latts[r] = make_state()
    Nw_all = np.zeros((chains, nworks, ncell))
    Ew_all = np.zeros((chains, nworks))
    Ecur = np.array([total_energy_vector(latts[r], X_s, Y_s, coup, Aa, Ab,
                                         lattice.nbr_cell, lattice.nbr_dj,
                                         lattice.nbr_di, lattice.nbr_ch,
                                         lattice.nbr_ptr, nbr_coup)
                     for r in range(chains)])
    seeds = _chain_seeds(seed, chains, rng)
    sweep_id = 0

    _log_header(logger, groups, single, _scaled_header_state(latts[0], ss),
                mag_axis)

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
                              Nw_all, Ew_all, record, Ecur, nbr_coup, mag_axis)
                sweep_id += n
                done += n
        t = time.time() - t0
        _log_row(logger, groups, single, arrays_temperatures[i], val,
                 arrays_T2[i], factor, num,
                 Nw_all if ss is None else Nw_all * ss, Ew_all, t)


def _run_replica_exchange_vector(logger, lattice, init, coup, Aa, Ab, make_state,
                                  mag_axis, arrays_values, arrays_temperatures,
                                  arrays_T2, groups, single, factor, num,
                                  nequilibrium, nworks, swap, rng, seed,
                                  nbr_coup=None):
    """矢量自旋的 replica exchange。"""
    nT = len(arrays_values)
    X_s, Y_s = lattice.X_s, lattice.Y_s
    ncell = lattice.ncell
    ss = lattice.spin_scale
    latts = np.zeros((nT, ncell, Y_s, X_s, 3), dtype=np.float32)
    for t in range(nT):
        latts[t] = make_state()
    vals = np.array(arrays_values, dtype=float)
    Nw_all = np.zeros((nT, nworks, ncell))
    Ew_all = np.zeros((nT, nworks))
    Ecur = np.array([total_energy_vector(latts[t], X_s, Y_s, coup, Aa, Ab,
                                         lattice.nbr_cell, lattice.nbr_dj,
                                         lattice.nbr_di, lattice.nbr_ch,
                                         lattice.nbr_ptr, nbr_coup)
                     for t in range(nT)])
    seeds = _chain_seeds(seed, nT, rng)
    sweep_id = 0
    attempt = 0
    accepted = 0
    t_start = time.time()

    _log_header(logger, groups, single, _scaled_header_state(latts[0], ss),
                mag_axis)

    for phase, nsteps, record in ((0, nequilibrium, False), (1, nworks, True)):
        done = 0
        while done < nsteps:
            n = min(swap, nsteps - done)
            las = _random_directions(rng, (nT, n, ncell, Y_s, X_s, 3))
            sweeps_vector(latts, las, seeds, vals, sweep_id, n, X_s, Y_s, coup,
                          Aa, Ab, lattice.nbr_cell, lattice.nbr_dj,
                          lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
                          lattice.cell_order, done if record else 0,
                          Nw_all, Ew_all, record, Ecur, nbr_coup, mag_axis)
            sweep_id += n
            done += n
            attempt += 1
            accepted += _swap_configs(latts, Ecur, vals, rng, attempt % 2)

    elapsed = time.time() - t_start
    logger.info(_info(("swaps:", str(attempt)),
                      ("accepted:", str(accepted))))
    for i in range(nT):
        _log_row(logger, groups, single, arrays_temperatures[i],
                 arrays_values[i], arrays_T2[i], factor, num,
                 Nw_all[i: i + 1] if ss is None else Nw_all[i: i + 1] * ss,
                 Ew_all[i: i + 1], elapsed)


def _moment_pairs(lattice):
    """返回磁矩标称值 (μB) 与对应 S 的字段对，供头部参数行使用。

    spin_scale 是每 cell 的 S = mom/2，所以磁矩标称值就是 2*S；
    不同原子磁矩不同时按数值去重后一并列出。无磁矩信息时返回空列表。
    """
    ss = lattice.spin_scale
    if ss is None:
        return []
    spin = np.unique(np.asarray(ss, dtype=float))
    mom = ", ".join("%g" % (2.0 * v) for v in spin)
    s = ", ".join("%g" % v for v in spin)
    return [("moment(μB):", mom), ("S:", s)]


def _log_setup(logger, lattice, init, nequilibrium, nworks, num,
               chains, seed, swap, nT, param_pairs):
    """打印运行前的完整头部信息（两行）。

    第一行: 构型名 维度 | init | iterations | chains | [swap every | threads]
            | seed | count
    第二行: moment(μB) | S | param_pairs（交换耦合 / 各向异性）
    """
    dims = " × ".join(str(d) for d in lattice.dimensions)
    seed_text = ("%d" % seed) if seed is not None else "random"
    is_swap = swap > 0 and nT >= 2
    row1 = [
        (lattice.name + " " + dims, ""),
        ("init:", init),
        ("iterations:", "%d + %d" % (nequilibrium, nworks)),
        ("chains:", str(nT if is_swap else chains)),
    ]
    if is_swap:
        row1.append(("swap every:", "%d sweeps" % swap))
    else:
        row1.append(("threads:", str(numba.get_num_threads())))
    row1.append(("seed:", seed_text))
    row1.append(("count:", str(num)))
    logger.info(_info(*row1))
    logger.info(_info(*(_moment_pairs(lattice) + param_pairs)))


def _scaled_header_state(state, ss):
    """把每 cell 的自旋标度（--mom -> S = mom/2）应用到日志用的初始状态。

    Ising（ndim=3）整体缩放；矢量（ndim=4）三个分量整体缩放，
    因为初态现在可能沿 x/y/易平面，不再只落在 z 上。
    返回 float 数组，形状不变。
    """
    if ss is None:
        return state
    out = state * 1.0
    if out.ndim == 4:
        out *= ss[:, None, None, None]
    else:
        out *= ss[:, None, None]
    return out


def _log_header(logger, groups, single, latt0, mag_axis=2):
    """写表头与初态磁化。

    ``latt0`` 是 (ncell, ...) 形状；矢量自旋取 ``mag_axis`` 分量投影
    （标量自旋就是它本身）。``mag_axis`` 默认 2 保持旧行为。
    """
    if single:
        logger.info("{:>16} {:>16}".format("Round", "magnetism"))
        m_ave = Average(latt0[..., mag_axis] if latt0.ndim == 4 else latt0)
        logger.info("{:>16} {:>16.6}".format(0, m_ave))
        logger.info("{:>16} {:>16} {:>16} {:>16} {:>16}".format(
            "Temperature", "magnetism", "susceptibility", "specific heat", "time(s)"))
    else:
        logger.info("{:>16} {:>16} {:>16}".format("Round", "magnetism0", "magnetism1"))
        mags = [Average(latt0[group, ..., mag_axis] if latt0.ndim == 4
                        else latt0[group]) for group in groups]
        logger.info("{:>16} {:>16.6} {:>16.6}".format(0, mags[0], mags[1]))
        logger.info("{:>16} {:>16} {:>16} {:>18} {:>18} {:>16} {:>16}".format(
            "Temperature", "magnetism0(e)", "magnetism1(e)", "susceptibility0(e)",
            "susceptibility1(e)", "specific heat", "time(s)"))


def _log_row(logger, groups, single, temperature, val, T2, factor,
              num, Nw_all, Ew_all, t):
    """写一个温度的结果（对各链取平均）。"""
    # 直接传全部链：磁化率/比热是二阶矩，必须先在各链内求方差再平均。
    # 若先把链平均成一条序列，方差会按 1/chains 缩小。
    mags, chis, cv = _observables(Nw_all, Ew_all, groups, val, factor, T2, num)
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
                           seed, nbr_coup=None):
    """replica exchange（并行回火）：每个温度一条链，定期交换相邻温度的构型。"""
    nT = len(arrays_values)
    X_s, Y_s = lattice.X_s, lattice.Y_s
    ncell = lattice.ncell
    ss = lattice.spin_scale
    latts = np.zeros((nT, ncell, Y_s, X_s), dtype=np.int8)
    for t in range(nT):
        latts[t] = lattice.initial_state(init)
    vals = np.array(arrays_values, dtype=float)
    Nw_all = np.zeros((nT, nworks, ncell))
    Ew_all = np.zeros((nT, nworks))
    Ecur = np.array([total_energy(latts[t], X_s, Y_s, coup,
                                  lattice.nbr_cell, lattice.nbr_dj,
                                  lattice.nbr_di, lattice.nbr_ch,
                                  lattice.nbr_ptr, nbr_coup)
                     for t in range(nT)])
    seeds = _chain_seeds(seed, nT, rng)
    sweep_id = 0
    attempt = 0
    accepted = 0
    t_start = time.time()

    _log_header(logger, groups, single, _scaled_header_state(latts[0], ss))

    for phase, nsteps, record in ((0, nequilibrium, False), (1, nworks, True)):
        done = 0
        while done < nsteps:
            n = min(swap, nsteps - done)
            sweeps(latts, seeds, vals, sweep_id, n, X_s, Y_s, coup,
                   lattice.nbr_cell, lattice.nbr_dj,
                   lattice.nbr_di, lattice.nbr_ch, lattice.nbr_ptr,
                   lattice.cell_order, done if record else 0, Nw_all, Ew_all,
                   record, Ecur, nbr_coup)
            sweep_id += n
            done += n
            attempt += 1
            accepted += _swap_configs(latts, Ecur, vals, rng, attempt % 2)

    elapsed = time.time() - t_start
    logger.info(_info(("swaps:", str(attempt)),
                      ("accepted:", str(accepted))))
    for i in range(nT):
        _log_row(logger, groups, single, arrays_temperatures[i],
                 arrays_values[i], arrays_T2[i], factor, num,
                 Nw_all[i: i + 1] if ss is None else Nw_all[i: i + 1] * ss,
                 Ew_all[i: i + 1], elapsed)
