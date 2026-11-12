"""方格晶格（square）的表生成器。

这是表驱动架构的参考实现：其它构型照这个模式写。

几何：2 层，每层 8 个块，块内 X_s x Y_s 的周期格点。
耦合：3 条通道 Ja / Jb / Jc，每个格点 4+4+4 = 12 个邻居。

表里存的是「谁和谁相邻」：对每个 cell 给出它的邻居列表，每个邻居是
(目标 cell, 行偏移, 列偏移, 通道)。偏移是目标 cell 自己坐标系里的
-1 / 0 / +1 周期偏移。

注意两个容易搞混的地方：

* **cell 编号** ``cell = layer * nblock + block``（层优先），表里的
  邻居目标也用这个编号。表按 cell 编号从小到大排列，``nbr_ptr`` 依赖
  这个顺序。
* **更新顺序** 由 ``cell_order`` 单独给出（与旧实现一致：块在外层、
  层在内层）。它只影响"谁先更新"，因此只影响可复现性，不影响物理。
"""

import numpy as np

from mcta.mc.engine import Lattice

# 通道顺序即耦合常数 J 的顺序
CHANNELS = ("Ja", "Jb", "Jc")

NL, NB = 2, 8          # 层数、每层块数


def _neighbors_of(f, g):
    """返回 (f, g) 这个 cell 的 12 个邻居。

    每个邻居是 (目标层, 目标块, dj, di, 通道)。
    """
    go = 1 - g
    f2 = f % 2
    out = []

    # --- 邻居块号与坐标偏移 ---
    if g == 0:
        di_o, di_p = 0, -1              # x__o = i,  x__p = inn
    else:
        di_o, di_p = 1, 0               # x__o = ipp, x__p = i

    if f2 == 0:
        fo = f + 1                      # fo = fp
        ga, gb = g, go
        di_a = 0                        # x__a = i
        di_b = -1 if g == 0 else 0       # x__b = inn 或 i
    else:
        fo = f - 1                      # fo = fn
        ga, gb = go, g
        di_b = 0                        # x__b = i
        di_a = 0 if g == 0 else 1       # x__a = i 或 ipp

    fq = (f + 4) % 8
    dj_q = 1 if f + 4 > 7 else 0        # y__q
    fr = (f - 4) % 8
    dj_r = -1 if f < 4 else 0           # y__r
    fu = (f + 2) % 8
    dj_u = 1 if f + 2 > 7 else 0        # y__u
    fd = (f - 2) % 8
    dj_d = -1 if f < 2 else 0           # y__d

    f0 = fo + 2 if fo < 6 else fo - 6
    f1 = fo - 2 if fo > 1 else fo + 6

    # --- 通道 Ja：4 个邻居 ---
    out.append((ga, fo, 0,  di_a, 0))   # latt[ga,fo,j,x__a]
    out.append((gb, fo, 0,  di_b, 0))   # latt[gb,fo,j,x__b]
    out.append((g,  fu, dj_u, 0, 0))    # latt[g,fu,y__u,i]
    out.append((g,  fd, dj_d, 0, 0))    # latt[g,fd,y__d,i]

    # --- 通道 Jb：4 个邻居 ---
    out.append((ga, f0, dj_u, di_a, 1))  # latt[ga,f0,y__u,x__a]
    out.append((ga, f1, dj_d, di_a, 1))  # latt[ga,f1,y__d,x__a]
    out.append((gb, f0, dj_u, di_b, 1))  # latt[gb,f0,y__u,x__b]
    out.append((gb, f1, dj_d, di_b, 1))  # latt[gb,f1,y__d,x__b]

    # --- 通道 Jc：4 个邻居 ---
    out.append((go, f, 0, di_o, 2))      # latt[go,f,j,x__o]
    out.append((go, f, 0, di_p, 2))      # latt[go,f,j,x__p]
    out.append((g,  fq, dj_q, 0, 2))     # latt[g,fq,y__q,i]
    out.append((g,  fr, dj_r, 0, 2))     # latt[g,fr,y__r,i]

    return out


def _build():
    """把邻居表按 cell 编号顺序拼起来。

    表按 ``cell = g * NB + f`` 排列，``nbr_ptr`` 依赖这个顺序。
    """
    ncell = NL * NB
    nbr_cell, nbr_dj, nbr_di, nbr_ch = [], [], [], []
    nbr_ptr = np.zeros(ncell + 1, dtype=np.int64)
    for c in range(ncell):
        g, f = divmod(c, NB)
        nbr_ptr[c] = len(nbr_cell)
        for (tg, tf, dj, di, ch) in _neighbors_of(f, g):
            nbr_cell.append(tg * NB + tf)
            nbr_dj.append(dj)
            nbr_di.append(di)
            nbr_ch.append(ch)
    nbr_ptr[ncell] = len(nbr_cell)
    return (np.array(nbr_cell), np.array(nbr_dj), np.array(nbr_di),
            np.array(nbr_ch), nbr_ptr)


def _init_states():
    """初态：每个 cell 的初始自旋（+1 / -1）。

    照 ising/square.py 的 _initial_state：
      fm   全部 +1
      afm1 第 1、2、5、6 块反号
      afm2 第 2、3、6、7 块反号
      afm3 第 0 层 3-6 块、第 1 层 0-2、7 块反号
    """
    out = {}
    for name in ("fm", "afm1", "afm2", "afm3"):
        signs = np.ones(NL * NB, dtype=np.int8)
        if name == "afm1":
            for g in (0, 1):
                for b in (1, 2, 5, 6):
                    signs[g * NB + b] = -1
        elif name == "afm2":
            for g in (0, 1):
                for b in (2, 3, 6, 7):
                    signs[g * NB + b] = -1
        elif name == "afm3":
            for b in (3, 4, 5, 6):
                signs[0 * NB + b] = -1
            for b in (0, 1, 2, 7):
                signs[1 * NB + b] = -1
        out[name] = signs
    return out


def _groups():
    """观测量用的子晶格划分（照 ising/square.py 的 _INIT_GROUPS）。

    fm   只有一组：全部 16 个 cell
    其余两组，划分方式与原实现一致。
    """
    out = {}
    allc = np.arange(NL * NB)
    out["fm"] = [allc]
    out["afm1"] = [
        np.array([g * NB + b for g in (0, 1) for b in (0, 3, 4, 7)]),
        np.array([g * NB + b for g in (0, 1) for b in (1, 2, 5, 6)]),
    ]
    out["afm2"] = [
        np.array([g * NB + b for g in (0, 1) for b in (0, 1, 4, 5)]),
        np.array([g * NB + b for g in (0, 1) for b in (2, 3, 6, 7)]),
    ]
    out["afm3"] = [
        np.array([b for b in (0, 1, 2, 7)] + [NB + b for b in (3, 4, 5, 6)]),
        np.array([b for b in (3, 4, 5, 6)] + [NB + b for b in (0, 1, 2, 7)]),
    ]
    return out


def build(X, Y, Z=None):
    """生成方格晶格的表。

    参数
    ----
    X, Y : 用户层面的晶格尺寸（方格构型是 4x4 个块的周期，
           所以块内格点数 = X // 4, Y // 4）
    """
    X_s, Y_s = X // 4, Y // 4
    nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr = _build()
    # 更新顺序：与旧实现一致（块在外层、层在内层）
    # cell 编号 = g * NB + f；更新顺序与旧实现一致：块在外、层在内
    cell_order = np.array([g * NB + f for f in range(NB) for g in range(NL)],
                           dtype=np.int64)
    return Lattice(
        name="square",
        nlayer=NL, nblock=NB, X_s=X_s, Y_s=Y_s,
        channels=CHANNELS,
        nbr_cell=nbr_cell, nbr_dj=nbr_dj, nbr_di=nbr_di, nbr_ch=nbr_ch,
        nbr_ptr=nbr_ptr, cell_order=cell_order,
        init_states=_init_states(), groups=_groups(),
        # 原子数：方格构型 8 块 x 2 层 = 16 个原胞，每个原胞 16 个格点
        num_atoms=X * Y,
        # 两组时磁化率的归一系数（原实现用 N，即 X*Y）
        factor_atoms=X * Y,
        X=X, Y=Y,
    )
