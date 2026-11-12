"""双层 AA 堆垛（bilayer-aa）的表生成器。

几何：2 层，每层 8 个块，块内 X_s x Y_s 的周期格点。
耦合：2 条通道 J1 / Ja，每个格点 6+6 = 12 个邻居（外加 J0 的 1 个）。
"""

import numpy as np

from mcta.mc.engine import Lattice

CHANNELS = ("J0", "J1", "Ja")

NL, NB = 2, 8          # 层数、每层块数


def _neighbors_of(f, g):
    """返回 (f, g) 这个 cell 的 13 个邻居。

    对应 ising/bilayer_aa_update.py 的 update3。
    """
    go = 1 - g
    f4 = f % 4
    f2 = f % 2

    # --- 邻居块号 ---
    if f4 < 2:
        f0 = f - 2
        if f0 < 0:
            f0 += 8
        di_a = 0                        # x__a = i
        di_b = 0 if f2 == 1 else -1      # x__b = i 或 inn
    else:
        f0 = f - 1
        if f0 % 2 == 0:
            f0 -= 2
        di_a = 0 if f2 == 0 else 1      # x__a = i 或 ipp
        di_b = 0                        # x__b = i

    f1 = f0 + 4 if f0 < 4 else f0 - 4
    f2b = f1 - 1 if f1 % 2 == 1 else f1 + 1
    f3 = f0 - 1 if f0 % 2 == 1 else f0 + 1

    # --- 同行/同列的偏移 ---
    if f2 == 0:
        fp = f + 1
        di_ap = 0                       # x_ap = i
        di_an = -1                      # x_an = inn
    else:
        fp = f - 1
        di_ap = 1                       # x_ap = ipp
        di_an = 0                       # x_an = i

    # --- 跨行的偏移 ---
    if f < 2:
        dj_a = -1                       # y__a = jnn
        dj_b = 0                        # y__b = j
    elif f > 5:
        dj_a = 0                        # y__a = j
        dj_b = 1                        # y__b = jpp
    else:
        dj_a = 0                        # y__a = j
        dj_b = 0                        # y__b = j

    out = []

    # --- 通道 J0：1 个邻居 ---
    # -J0 * latt[go,f,j,i]
    out.append((go, f, 0, 0, 0))

    # --- 通道 J1：6 个邻居 ---
    # latt[go,f0,y__a,x__a] + latt[go,f3,y__a,x__b] +
    # latt[go,f1,y__b,x__a] + latt[go,f2,y__b,x__b] +
    # latt[go,fp,j,x_ap]   + latt[go,fp,j,x_an]
    out.append((go, f0, dj_a, di_a, 1))
    out.append((go, f3, dj_a, di_b, 1))
    out.append((go, f1, dj_b, di_a, 1))
    out.append((go, f2b, dj_b, di_b, 1))
    out.append((go, fp, 0, di_ap, 1))
    out.append((go, fp, 0, di_an, 1))

    # --- 通道 Ja：6 个邻居（同 J1 的结构，但在本层 g）---
    out.append((g, f0, dj_a, di_a, 2))
    out.append((g, f3, dj_a, di_b, 2))
    out.append((g, f1, dj_b, di_a, 2))
    out.append((g, f2b, dj_b, di_b, 2))
    out.append((g, fp, 0, di_ap, 2))
    out.append((g, fp, 0, di_an, 2))

    return out


def _build():
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
    """初态：照 ising/bilayer_aa.py。

      fm   全部 +1
      afm1 第 1 层反号
      afm2 两层的第 2、3、6、7 块反号
      afm3 第 0 层 2、3、6、7 块与第 1 层 0、1、4、5 块反号
    """
    out = {}
    for name in ("fm", "afm1", "afm2", "afm3"):
        signs = np.ones(NL * NB, dtype=np.int8)
        if name == "afm1":
            for b in range(NB):
                signs[1 * NB + b] = -1
        elif name == "afm2":
            for g in (0, 1):
                for b in (2, 3, 6, 7):
                    signs[g * NB + b] = -1
        elif name == "afm3":
            for b in (2, 3, 6, 7):
                signs[0 * NB + b] = -1
            for b in (0, 1, 4, 5):
                signs[1 * NB + b] = -1
        out[name] = signs
    return out


def _groups():
    """观测量用的子晶格划分（照 ising/bilayer_aa.py）。

    fm   一组：全部
    afm1 两组：第 0 层 / 第 1 层
    afm2 两组：两层的块 0、1、4、5 / 两层的块 2、3、6、7
    afm3 两组：第 0 层 0、1、4、5 + 第 1 层 2、3、6、7 / 反之
    """
    out = {}
    allc = np.arange(NL * NB)
    out["fm"] = [allc]
    out["afm1"] = [
        np.array([0 * NB + b for b in range(NB)]),
        np.array([1 * NB + b for b in range(NB)]),
    ]
    out["afm2"] = [
        np.array([g * NB + b for g in (0, 1) for b in (0, 1, 4, 5)]),
        np.array([g * NB + b for g in (0, 1) for b in (2, 3, 6, 7)]),
    ]
    out["afm3"] = [
        np.array([0 * NB + b for b in (0, 1, 4, 5)]
                 + [1 * NB + b for b in (2, 3, 6, 7)]),
        np.array([0 * NB + b for b in (2, 3, 6, 7)]
                 + [1 * NB + b for b in (0, 1, 4, 5)]),
    ]
    return out


def build(X, Y, Z=None):
    """生成双层 AA 晶格的表。"""
    X_s, Y_s = X // 2, Y // 2
    nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr = _build()
    # 更新顺序：与旧实现一致（块在外、层在内）
    # cell 编号 = g * NB + f；更新顺序与旧实现一致：块在外、层在内
    cell_order = np.array([g * NB + f for f in range(NB) for g in range(NL)],
                           dtype=np.int64)
    return Lattice(
        name="bilayer-aa",
        nlayer=NL, nblock=NB, X_s=X_s, Y_s=Y_s,
        channels=CHANNELS,
        nbr_cell=nbr_cell, nbr_dj=nbr_dj, nbr_di=nbr_di, nbr_ch=nbr_ch,
        nbr_ptr=nbr_ptr, cell_order=cell_order,
        init_states=_init_states(), groups=_groups(),
        # 原子数：2 层 x 8 块 x (X/2) x (Y/2) = 4XY
        num_atoms=4 * X * Y,
        factor_atoms=X * Y,
        X=X, Y=Y,
    )
