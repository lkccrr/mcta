"""二维 XY 模型（平面转子）蒙特卡洛与 BKT 判据。

自旋是平面内的角度 θ（不是 ±1，也不是三维单位矢量），哈密顿量

    H = -J Σ_{<ij>} cos(θ_i - θ_j)

邻居表来自 :mod:`mcta.mc.geometry.xy_geometry`；每条无向边在表里
记两次，所以总能量取 -1/2 的因子，而单格点变角时直接对各邻居求和。

BKT 判据
--------
螺旋度模数（superfluid stiffness）Υ：给 x 方向加均匀相位梯度后自由能
的二阶响应，用涨落公式在零梯度处计算

    Υ = (1/N)[ <Σ_b J dx_b² cos(θ_i-θ_j)>
               - β ( <(Σ_b J dx_b sin(θ_i-θ_j))²>
                     - <Σ_b J dx_b sin(θ_i-θ_j)>² ) ]

其中 b 遍历几何层给出的**无向边表**，dx_b 是该键沿笛卡尔 x 方向的位移
（dx=0 的键自动不贡献）。这对所有二维格子通用方格只取 +x 键的旧写法
完全等价，但能正确处理三角/蜂窝/笼目/diced 的斜向键。

涡旋密度 n_v：在几何层给出的**最小环**上算相位绕数 q = winding/(2π)，
|q|≥1 记为涡旋；n_v = 含涡旋的环数 / 总环数。低温涡旋-反涡旋成对，
n_v 很小；T_BKT 以上自由涡旋激增。
"""

import os
import time
import numpy as np
from numba import njit, prange

from mcta.mc.engine import (kB, _u01, _chain_seeds, _logger, _info,
                             _log_setup, inverse_temperature)


TWO_PI = 2.0 * np.pi

__all__ = ["run_xy", "total_energy_xy", "helicity_and_vortex", "make_state",
           "snapshot_path", "save_snapshots"]


def snapshot_path(log_file):
    """由日志文件名推出对应构型快照 npz：``xxx.log`` -> ``xxx_states.npz``。"""
    root, _ = os.path.splitext(str(log_file))
    return root + "_states.npz"


def save_snapshots(log_file, lattice, temps, states):
    """把各温度的末态构型写入 npz，供涡旋状态箭头图读取。

    ``states`` 形状 ``(nT, ncell, Y, X)``，每个温度一条末态构型。连同几何
    信息（构型名、原胞尺寸、基矢、基元）一起存，plots 可据此把
    ``(cell, j, i)`` 映射到笛卡尔坐标画箭头、并定位最小环涡旋核心。
    """
    from mcta.mc.geometry.xy_geometry import DEFS
    d = DEFS.get(lattice.name, {})
    a1 = np.asarray(d.get("a1", (1.0, 0.0)), dtype=float)
    a2 = np.asarray(d.get("a2", (0.0, 1.0)), dtype=float)
    basis = np.asarray(d.get("basis", ((0.0, 0.0),)), dtype=float)
    np.savez_compressed(
        snapshot_path(log_file),
        confg=np.array(str(lattice.name)),
        X=np.array(int(lattice.X_s)), Y=np.array(int(lattice.Y_s)),
        a1=a1, a2=a2, basis=basis,
        temps=np.asarray(temps, dtype=float),
        states=np.asarray(states, dtype=np.float32))


# ---------------------------------------------------------------------------
# 能量与初态
# ---------------------------------------------------------------------------
@njit(cache=True)
def total_energy_xy(theta, X_s, Y_s, J, nbr_cell, nbr_dj, nbr_di, nbr_ptr):
    """精确总能量 H = -1/2 Σ_edges J cos(θ_i - θ_j)。

    邻居表把每条无向边记两次，故取 1/2；只在初始化/测试调用，热更新走
    update3_xy 的增量维护。
    """
    E = 0.0
    ncell = theta.shape[0]
    for c in range(ncell):
        for j in range(Y_s):
            for i in range(X_s):
                th = theta[c, j, i]
                acc = 0.0
                for k in range(nbr_ptr[c], nbr_ptr[c + 1]):
                    tc = nbr_cell[k]
                    jj = j + nbr_dj[k]
                    if jj >= Y_s:
                        jj -= Y_s
                    elif jj < 0:
                        jj += Y_s
                    ii = i + nbr_di[k]
                    if ii >= X_s:
                        ii -= X_s
                    elif ii < 0:
                        ii += X_s
                    acc += np.cos(th - theta[tc, jj, ii])
                E -= 0.5 * J * acc
    return E


def make_state(init, X_s, Y_s, rng, ncell=1):
    """按初态名生成角度数组，形状 ``(ncell, Y_s, X_s)``。

    fm 全同相；afm1 棋盘；afm2 竖条；afm3 横条；random 均匀随机相位。
    """
    ii, jj = np.meshgrid(np.arange(X_s), np.arange(Y_s))
    if init == "random":
        one = rng.uniform(-np.pi, np.pi, size=(Y_s, X_s))
    elif init in ("afm2", "afm5"):
        one = np.pi * (ii % 2)
    elif init in ("afm3",):
        one = np.pi * (jj % 2)
    elif init in ("afm1", "afm4"):
        one = np.pi * ((ii + jj) % 2)
    else:
        one = np.zeros((Y_s, X_s))
    return np.broadcast_to(one, (ncell, Y_s, X_s)).copy()


# ---------------------------------------------------------------------------
# Metropolis 内核
# ---------------------------------------------------------------------------
@njit(inline='always')
def _wrap(a):
    return a - TWO_PI * np.floor(a / TWO_PI + 0.5)


@njit(cache=True)
def update3_xy(theta, seed, sweep, X_s, Y_s, J, val,
               nbr_cell, nbr_dj, nbr_di, nbr_ptr, cell_order, E0):
    """一条链一次 sweep：逐格点提议新角度，返回 sweep 末的精确总能量。

    提议 θ_new 在 [0, 2π) 均匀随机（平面内“随机取向”，与矢量内核的提议
    思路一致），是对称提议；接受率 min(1, exp(-βΔE))。ΔE 只涉及该格点的
    成键，维护精确总能量 E。
    """
    E = E0
    for co in range(len(cell_order)):
        c = cell_order[co]
        for j in range(Y_s):
            for i in range(X_s):
                old = theta[c, j, i]
                u = _u01(seed, sweep, c, j, i)
                new = u * TWO_PI
                dE = 0.0
                for k in range(nbr_ptr[c], nbr_ptr[c + 1]):
                    tc = nbr_cell[k]
                    jj = j + nbr_dj[k]
                    if jj >= Y_s:
                        jj -= Y_s
                    elif jj < 0:
                        jj += Y_s
                    ii = i + nbr_di[k]
                    if ii >= X_s:
                        ii -= X_s
                    elif ii < 0:
                        ii += X_s
                    tn = theta[tc, jj, ii]
                    dE -= J * (np.cos(new - tn) - np.cos(old - tn))
                if dE <= 0.0:
                    theta[c, j, i] = new
                    E += dE
                else:
                    u2 = _u01(seed + np.uint64(0x9E3779B97F4A7C15),
                              sweep, c, j, i)
                    if u2 < np.exp(-val * dE):
                        theta[c, j, i] = new
                        E += dE
    return E


@njit(cache=True)
def _sample_xy(theta, X_s, Y_s, J, bonds, loops, loop_ptr):
    """当前构型的三个瞬时量：螺旋度 cos/sin 加权和、含涡旋的环数。

    bonds: (n_edges, 7) = c1,j1,i1,c2,j2,i2,dx（无向边，每条一次）
    loops: (n_points, 3) 最小环的格点序列，loop_ptr 是 CSR 起点
    """
    cx = 0.0
    sx = 0.0
    nv = 0
    for b in range(bonds.shape[0]):
        c1 = int(bonds[b, 0]); j1 = int(bonds[b, 1]); i1 = int(bonds[b, 2])
        c2 = int(bonds[b, 3]); j2 = int(bonds[b, 4]); i2 = int(bonds[b, 5])
        dx = bonds[b, 6]
        d = theta[c1, j1, i1] - theta[c2, j2, i2]
        cx += J * dx * dx * np.cos(d)
        sx += J * dx * np.sin(d)
    for p in range(loop_ptr.shape[0] - 1):
        w = 0.0
        last = loop_ptr[p + 1] - 1
        for k in range(loop_ptr[p], loop_ptr[p + 1]):
            c = int(loops[k, 0]); j = int(loops[k, 1]); i = int(loops[k, 2])
            k2 = loop_ptr[p] if k == last else k + 1
            c2 = int(loops[k2, 0]); j2 = int(loops[k2, 1])
            i2 = int(loops[k2, 2])
            w += _wrap(theta[c2, j2, i2] - theta[c, j, i])
        if np.abs(w) > np.pi:          # |绕数| >= 1
            nv += 1
    return cx, sx, nv


@njit(cache=True, parallel=True)
def sweeps_xy(theta, seeds, vals, sweep0, nsteps, X_s, Y_s, J,
              nbr_cell, nbr_dj, nbr_di, nbr_ptr, cell_order,
              offset, Nw, Mw, Ew, Cw, Sw, Vw, record, Ecur,
              bonds, loops, loop_ptr):
    """多条独立链并行推进；采样时记录能量、磁化、螺旋度项、涡旋数。"""
    nrep = theta.shape[0]
    for r in prange(nrep):
        sp = theta[r]
        val = vals[r]
        for s in range(nsteps):
            Ecur[r] = update3_xy(sp, seeds[r], sweep0 + s, X_s, Y_s, J, val,
                                 nbr_cell, nbr_dj, nbr_di, nbr_ptr,
                                 cell_order, Ecur[r])
            if record:
                idx = offset + s
                Ew[r, idx] = Ecur[r]
                for c in range(sp.shape[0]):
                    Nw[r, idx, c] = np.cos(sp[c]).mean()
                    Mw[r, idx, c] = np.sin(sp[c]).mean()
                cx, sx, nv = _sample_xy(sp, X_s, Y_s, J,
                                        bonds, loops, loop_ptr)
                Cw[r, idx] = cx
                Sw[r, idx] = sx
                Vw[r, idx] = nv


def helicity_and_vortex(Cw, Sw, Vw, val, N, nloops=None, area=1.0):
    """从采样序列算 (Υ, n_v)。

    Υ = [<Cx> - β(<Sx²> - <Sx>²)] / (N × area)，Cx/Sx 已含 J 和 dx 权重；
    area 是每格点面积（以最近邻长度平方为单位），方格 = 1。普适跳变
    Υ=2k_BT/π 要求按面积归一，非方格必须用几何层给出的 area。
    n_v = <含涡旋的环数> / 环数（默认 = N，方格时每格点一个环）。
    """
    c_av = float(np.mean(Cw))
    s_av = float(np.mean(Sw))
    s2 = float(np.mean(Sw ** 2))
    ups = (c_av - val * (s2 - s_av ** 2)) / (N * area)
    nv = float(np.mean(Vw)) / (N if nloops is None else nloops)
    return ups, nv


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
def _log_header_xy(logger, latt0):
    m_ave = float(np.hypot(np.cos(latt0).mean(), np.sin(latt0).mean()))
    logger.info("{:>16} {:>16}".format("Round", "magnetism"))
    logger.info("{:>16} {:>16.6}".format(0, m_ave))
    logger.info("{:>16} {:>16} {:>16} {:>16} {:>16} {:>16} {:>16}".format(
        "Temperature", "magnetism", "susceptibility", "specific heat",
        "helicity", "vortex", "time(s)"))


def _log_row_xy(logger, temperature, mag, chi, cv, ups, nv, t):
    logger.info("{:>16.2f} {:>16.6f} {:>16.6f} {:>16.6f} {:>16.6f} "
                "{:>16.6f} {:>16.6f}".format(
                    temperature, float(mag), float(chi), float(cv),
                    float(ups), float(nv), t))


# ---------------------------------------------------------------------------
# 驱动
# ---------------------------------------------------------------------------
def run_xy(lattice, file, init, J, arrays_temperatures, nequilibrium, nworks,
           chains=1, seed=None, swap=0):
    """跑一次二维 XY 模拟，写日志（含 Υ 与涡旋密度两列）。"""
    logger = _logger(file)
    X_s, Y_s = lattice.X_s, lattice.Y_s
    ncell = lattice.ncell
    num = lattice.num_atoms
    Jc = float(J[0]) if J else 1.0
    nbr = (lattice.nbr_cell, lattice.nbr_dj, lattice.nbr_di,
           lattice.nbr_ptr, lattice.cell_order)
    geo = (lattice.xy_bonds, lattice.xy_loops, lattice.xy_loop_ptr)
    nloops = int(lattice.xy_loop_ptr.shape[0]) - 1
    area = 1.0 if lattice.xy_area is None else float(lattice.xy_area)

    np.seterr(divide='ignore', invalid='ignore')
    arrays_values = inverse_temperature(arrays_temperatures)
    lav = len(arrays_values)
    arrays_T2 = kB * arrays_values ** 2

    _log_setup(logger, lattice, init, nequilibrium, nworks, num,
               chains, seed, swap, lav, [("J(meV):", "%g" % Jc)])

    groups = lattice.groups.get(init)
    if groups is None:
        logger.info("Inconsistent parameters...")
        return
    factor = lattice.factor_atoms

    rng = np.random.default_rng(seed)
    seeds = _chain_seeds(seed, chains, rng)

    if swap > 0 and lav >= 2:
        _run_swap(logger, file, lattice, init, Jc, nbr, geo, nloops, area,
                  arrays_values, arrays_temperatures, arrays_T2, factor, num,
                  ncell, nequilibrium, nworks, swap, rng, seed, make_state,
                  groups)
        return

    theta = np.stack([make_state(init, X_s, Y_s, rng, ncell)
                      for _ in range(chains)])
    Ecur = np.array([total_energy_xy(theta[r], X_s, Y_s, Jc, *nbr[:4])
                     for r in range(chains)])
    Nw = np.zeros((chains, nworks, ncell))
    Mw = np.zeros((chains, nworks, ncell))
    Ew = np.zeros((chains, nworks))
    Cw = np.zeros((chains, nworks))
    Sw = np.zeros((chains, nworks))
    Vw = np.zeros((chains, nworks))

    _log_header_xy(logger, theta[0])
    states = []
    for i in range(lav):
        t0 = time.time()
        val = arrays_values[i]
        vals = np.full(chains, val)
        sweeps_xy(theta, seeds, vals, 0, nequilibrium, X_s, Y_s, Jc, *nbr,
                  0, Nw, Mw, Ew, Cw, Sw, Vw, False, Ecur, *geo)
        sweeps_xy(theta, seeds, vals, 0, nworks, X_s, Y_s, Jc, *nbr,
                  0, Nw, Mw, Ew, Cw, Sw, Vw, True, Ecur, *geo)
        # 记录该温度末态构型（第一条链），供涡旋状态箭头图使用
        states.append(theta[0].copy())
        mag = float(np.hypot(np.mean(Nw), np.mean(Mw)))
        chi = val * factor * float(np.var(Nw, axis=1).mean()
                                   + np.var(Mw, axis=1).mean())
        Ebar = Ew.mean()
        cv = arrays_T2[i] * float(np.var(Ew, axis=1).mean()) / num
        ups, nv = helicity_and_vortex(Cw, Sw, Vw, val, num, nloops, area)
        _log_row_xy(logger, arrays_temperatures[i], mag, chi, cv, ups, nv,
                    time.time() - t0)
    save_snapshots(file, lattice, arrays_temperatures, np.asarray(states))


def _run_swap(logger, file, lattice, init, Jc, nbr, geo, nloops, area,
              arrays_values, arrays_temperatures, arrays_T2, factor, num,
              ncell, nequilibrium, nworks, swap, rng, seed, make_state_fn,
              groups):
    """并行回火：每个温度一条链，定期交换相邻构型。"""
    import time as _time
    from mcta.mc.engine import _swap_configs

    X_s, Y_s = lattice.X_s, lattice.Y_s
    nT = len(arrays_values)
    theta = np.stack([make_state_fn(init, X_s, Y_s, rng, ncell)
                      for _ in range(nT)])
    Ecur = np.array([total_energy_xy(theta[r], X_s, Y_s, Jc, *nbr[:4])
                     for r in range(nT)])
    vals = np.asarray(arrays_values, dtype=float)
    seeds = _chain_seeds(seed, nT, rng)
    Nw = np.zeros((nT, nworks, ncell))
    Mw = np.zeros((nT, nworks, ncell))
    Ew = np.zeros((nT, nworks))
    Cw = np.zeros((nT, nworks))
    Sw = np.zeros((nT, nworks))
    Vw = np.zeros((nT, nworks))
    attempt = accepted = 0
    t_start = _time.time()

    _log_header_xy(logger, theta[0])
    for phase, nsteps, record in ((0, nequilibrium, False),
                                  (1, nworks, True)):
        done = 0
        while done < nsteps:
            n = min(swap, nsteps - done)
            sweeps_xy(theta, seeds, vals, done, n, X_s, Y_s, Jc, *nbr,
                      done if record else 0, Nw, Mw, Ew, Cw, Sw, Vw, record,
                      Ecur, *geo)
            done += n
            if phase == 1 or n == swap:
                attempt += 1
                accepted += _swap_configs(theta, Ecur, vals, rng, attempt % 2)
    logger.info(_info(("swaps:", str(attempt)), ("accepted:", str(accepted))))
    elapsed = _time.time() - t_start
    for i in range(nT):
        mag = float(np.hypot(np.mean(Nw[i]), np.mean(Mw[i])))
        chi = vals[i] * factor * float(np.var(Nw[i]) + np.var(Mw[i]))
        cv = arrays_T2[i] * float(np.var(Ew[i])) / num
        ups, nv = helicity_and_vortex(Cw[i:i + 1], Sw[i:i + 1],
                                      Vw[i:i + 1], vals[i], num, nloops,
                                      area)
        _log_row_xy(logger, arrays_temperatures[i], mag, chi, cv, ups, nv,
                    elapsed)
    # theta[i] 是第 i 条链的末态；按索引对应温度存档（与日志行一致）
    save_snapshots(file, lattice, arrays_temperatures, theta)
