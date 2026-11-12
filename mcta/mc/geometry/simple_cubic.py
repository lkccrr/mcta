"""简单立方晶格（simple-cubic）的表生成器。

按距离分层的邻居表，共 26 邻居/格点：

通道 0 (Ja, 6 邻居, 距离 a):
    ±x 同 cell, ±y 同 cell, ±z 相邻 cell

通道 1 (Jb, 12 邻居, 距离 a√2):
    x-y 面对角线 (同 cell, 4 个)
    x-z 面对角线 (相邻 cell, 4 个)
    y-z 面对角线 (相邻 cell, 4 个)

通道 2 (Jc, 8 邻居, 距离 a√3):
    体对角线 (相邻 cell, 8 个)

cell 编号即 z 层号，每层 X × Y 周期格点。
"""

import numpy as np

from mcta.mc.engine import Lattice

CHANNELS = ("Ja", "Jb", "Jc")
NB = 1   # 每层一个块


def _build(Z):
    """拼邻居表。"""
    ncell = Z * NB
    nbr_cell, nbr_dj, nbr_di, nbr_ch = [], [], [], []
    nbr_ptr = np.zeros(ncell + 1, dtype=np.int64)

    for c in range(ncell):
        nbr_ptr[c] = len(nbr_cell)

        # ---- 通道 0: Ja 最近邻 (6 个) ----
        # ±x, 同 cell
        nbr_cell.append(c); nbr_dj.append(0); nbr_di.append(-1); nbr_ch.append(0)
        nbr_cell.append(c); nbr_dj.append(0); nbr_di.append(1);  nbr_ch.append(0)
        # ±y, 同 cell
        nbr_cell.append(c); nbr_dj.append(-1); nbr_di.append(0); nbr_ch.append(0)
        nbr_cell.append(c); nbr_dj.append(1);  nbr_di.append(0); nbr_ch.append(0)
        # ±z, 相邻 cell
        for dz in (-1, +1):
            tc = (c + dz) % ncell
            nbr_cell.append(tc); nbr_dj.append(0); nbr_di.append(0); nbr_ch.append(0)

        # ---- 通道 1: Jb 次近邻 (12 个) ----
        # x-y 面对角线 (同 cell, 4 个)
        for dj, di in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            nbr_cell.append(c); nbr_dj.append(dj); nbr_di.append(di); nbr_ch.append(1)
        # x-z 面对角线 (相邻 cell, 4 个)
        for dz in (-1, +1):
            for di in (-1, +1):
                tc = (c + dz) % ncell
                nbr_cell.append(tc); nbr_dj.append(0); nbr_di.append(di); nbr_ch.append(1)
        # y-z 面对角线 (相邻 cell, 4 个)
        for dz in (-1, +1):
            for dj in (-1, +1):
                tc = (c + dz) % ncell
                nbr_cell.append(tc); nbr_dj.append(dj); nbr_di.append(0); nbr_ch.append(1)

        # ---- 通道 2: Jc 第三近邻 (8 个) ----
        for dz in (-1, +1):
            for dj in (-1, +1):
                for di in (-1, +1):
                    tc = (c + dz) % ncell
                    nbr_cell.append(tc); nbr_dj.append(dj); nbr_di.append(di); nbr_ch.append(2)

    nbr_ptr[ncell] = len(nbr_cell)
    return (np.array(nbr_cell), np.array(nbr_dj), np.array(nbr_di),
            np.array(nbr_ch), nbr_ptr)


def _init_states(Z):
    out = {}
    ncell = Z * NB
    out["fm"] = np.ones(ncell, dtype=np.int8)
    out["afm1"] = np.array([1 if c % 2 == 0 else -1 for c in range(ncell)],
                            dtype=np.int8)
    out["afm2"] = -np.ones(ncell, dtype=np.int8)
    return out


def _groups(Z):
    ncell = Z * NB
    out = {}
    allc = np.arange(ncell)
    out["fm"] = [allc]
    out["afm1"] = [
        np.array([c for c in range(ncell) if c % 2 == 0]),
        np.array([c for c in range(ncell) if c % 2 == 1]),
    ]
    out["afm2"] = [allc]
    return out


def build(X, Y, Z=None):
    if Z is None:
        Z = 64
    Z = max(1, Z)
    nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr = _build(Z)
    NL = Z
    NB = 1
    X_s, Y_s = X, Y
    ncell = NL * NB
    cell_order = np.arange(ncell, dtype=np.int64)

    return Lattice(
        name="simple-cubic",
        nlayer=NL, nblock=NB, X_s=X_s, Y_s=Y_s,
        channels=CHANNELS,
        nbr_cell=nbr_cell, nbr_dj=nbr_dj, nbr_di=nbr_di, nbr_ch=nbr_ch,
        nbr_ptr=nbr_ptr, cell_order=cell_order,
        init_states=_init_states(Z), groups=_groups(Z),
        num_atoms=X * Y * Z,
        factor_atoms=X * Y * Z,
        X=X, Y=Y,
    )
