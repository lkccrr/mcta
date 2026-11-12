"""双层 AB 堆垛 S=3/2 变体（bilayer-ab-u-3）的表生成器。

几何：2 层，每层 8 个块，块内 X_s x Y_s 的周期格点。
耦合：3 条通道 J0 / J1 / Ja，每个格点 3+3+6 = 12 个邻居。

这个构型与 bilayer-ab 的块索引规则相同，但耦合更少：
J1 把 J1_ 的两个邻居也包进来，所以只有 3 条通道。
"""

import numpy as np

from mcta.mc.engine import Lattice

CHANNELS = ("J0", "J1", "Ja")

NL, NB = 2, 8          # 层数、每层块数


def _neighbors_of(f, g):
    """返回 (f, g) 这个 cell 的 12 个邻居。

    对应 ising/bilayer_ab_u_3_update.py 的 update3。
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

    # --- 层相关的偏移 ---
    if g == 0:
        di_0 = di_an                    # x_0 = x_an
        fo2 = f2b                       # fo2 = f2
        dj_0 = dj_b                     # y__0 = y__b
        di_0b = di_b                    # x__0 = x__b
        foa = f3                        # foa = f3
        dj_1 = dj_a                     # y_1 = y__a
        di_1 = di_b                     # x_1 = x__b
        fob = f1                        # fob = f1
        dj_b2 = dj_b                    # y_b = y__b
        di_b2 = di_a                    # x_b = x__a
        foc = fo2 - 1 if fo2 % 2 == 1 else fo2 + 1
        di_c = -1                       # x_c = inn
    else:
        di_0 = di_ap                    # x_0 = x_ap
        fo2 = f0                        # fo2 = f0
        dj_0 = dj_a                     # y__0 = y__a
        di_0b = di_a                    # x__0 = x__a
        foa = f1                        # foa = f1
        dj_1 = dj_b                     # y_1 = y__b
        di_1 = di_a                     # x_1 = x__a
        fob = f3                        # fob = f3
        dj_b2 = dj_a                    # y_b = y__a
        di_b2 = di_b                    # x_b = x__b
        foc = fo2 + 1 if fo2 % 2 == 0 else fo2 - 1
        di_c = 1                        # x_c = ipp

    out = []

    # --- 通道 J0：3 个邻居 ---
    # latt[go,f  ,j   ,i   ] + latt[go,fp ,j   ,x_0 ] + latt[go,fo2,y__0,x__0]
    out.append((go, f,   0,  0,    0))
    out.append((go, fp,  0,  di_0,  0))
    out.append((go, fo2, dj_0, di_0b, 0))

    # --- 通道 J1：3 个邻居 ---
    # latt[go,foa,y_1,x_1] + latt[go,fob,y_b,x_b] + latt[go,foc,y__0,x_c]
    out.append((go, foa, dj_1,  di_1, 1))
    out.append((go, fob, dj_b2, di_b2, 1))
    out.append((go, foc, dj_0,  di_c, 1))

    # --- 通道 Ja：6 个邻居 ---
    # latt[g,f0,y__a,x__a] + latt[g,f3,y__a,x__b] + latt[g,f1,y__b,x__a] +
    # latt[g,f2,y__b,x__b] + latt[g,fp,j,x_ap]   + latt[g,fp,j,x_an]
    out.append((g, f0,  dj_a, di_a, 2))
    out.append((g, f3,  dj_a, di_b, 2))
    out.append((g, f1,  dj_b, di_a, 2))
    out.append((g, f2b, dj_b, di_b, 2))
    out.append((g, fp,  0,   di_ap, 2))
    out.append((g, fp,  0,   di_an, 2))

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
    """初态：照 ising/bilayer_ab_u_3.py（与 bilayer-ab 的 fm/afm1-3 相同）。"""
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
    """观测量用的子晶格划分（照 ising/bilayer_ab_u_3.py）。"""
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
    """生成双层 AB (S=3/2) 晶格的表。"""
    X_s, Y_s = X // 2, Y // 2
    nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr = _build()
    # 更新顺序：与旧实现一致（块在外、层在内）
    # cell 编号 = g * NB + f；更新顺序与旧实现一致：块在外、层在内
    cell_order = np.array([g * NB + f for f in range(NB) for g in range(NL)],
                           dtype=np.int64)
    return Lattice(
        name="bilayer-ab-u-3",
        nlayer=NL, nblock=NB, X_s=X_s, Y_s=Y_s,
        channels=CHANNELS,
        nbr_cell=nbr_cell, nbr_dj=nbr_dj, nbr_di=nbr_di, nbr_ch=nbr_ch,
        nbr_ptr=nbr_ptr, cell_order=cell_order,
        init_states=_init_states(), groups=_groups(),
        # 原子数：2 层 x 8 块 x (X/2) x (Y/2) = 4XY
        num_atoms=4 * X * Y,
        factor_atoms=X * Y,
        X=X, Y=Y,
        # S=3/2 的接受判据系数（普通 Ising 是 2.0）
        accept_factor=4.5,
    )
