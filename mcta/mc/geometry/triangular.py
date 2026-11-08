"""三角晶格（triangular）的表生成器。

几何：2 层，每层 4 个块，块内 X_s x Y_s 的周期格点。
耦合：3 条通道 Ja / Jb / Jc，每个格点 6+6+6 = 18 个邻居。

每条邻居都对照原 spins2 实现 mcta/mc/ising/triangular_update.py 的
update3 列出（该子包已被本架构取代并删除；参考实现保留在
tests/test_geometry_tables.py 里）。
原实现用 k1/k2/k3 和 x_inn/x_ipp/y_jnn/y_jpp 描述邻居块与坐标偏移，
这里把它们展开成 (目标层, 目标块, dj, di)。
"""

import numpy as np

from mcta.mc.engine import Lattice

CHANNELS = ("Ja", "Jb", "Jc")

NL, NB = 2, 4          # 层数、每层块数


def _neighbors_of(f, g):
    """返回 (f, g) 这个 cell 的 18 个邻居。

    对应 ising/triangular_update.py 的 update3：
        for l in range(2): for k in prange(4): ...
    其中 l 是层、k 是块。旧实现的遍历顺序是"层在外、块在内"，
    这里的 cell 编号是"层优先"（cell = g * NB + f），更新顺序由
    cell_order 单独给出。
    """
    lo = 1 - g
    k1 = 3 - f
    k2 = (5 - f) if f > 1 else (1 - f)
    k3 = (2 - f) if f % 2 == 0 else (4 - f)

    # --- 每个块的坐标偏移（相对当前 i/j 的 -1/0/+1）---
    if f == 0:
        di_inn, di_ipp = 0, 1       # x_inn = i, x_ipp = ipp
        dj_jnn, dj_jpp = 0, 1       # y_jnn = j, y_jpp = jpp
        di_c = 1                    # i_c = ipp
        dj_c = 1                    # j_c = jpp
    elif f == 1:
        di_inn, di_ipp = 0, 1
        dj_jnn, dj_jpp = -1, 0      # y_jnn = jnn, y_jpp = j
        di_c = 1
        dj_c = -1
    elif f == 2:
        di_inn, di_ipp = -1, 0      # x_inn = inn, x_ipp = i
        dj_jnn, dj_jpp = -1, 0
        di_c = -1
        dj_c = -1
    else:
        di_inn, di_ipp = -1, 0
        dj_jnn, dj_jpp = 0, 1       # y_jnn = j, y_jpp = jpp
        di_c = -1
        dj_c = 1

    # --- 层相关的列/行偏移 ---
    if g == 0:
        di_1 = di_inn               # i_1 = x_inn
        dj_2 = dj_jpp               # j_2 = y_jpp
        di_b0 = -1                  # ib0 = inn
        di_b1 = di_ipp              # ib1 = x_ipp
    else:
        di_1 = di_ipp               # i_1 = x_ipp
        dj_2 = dj_jnn               # j_2 = y_jnn
        di_b0 = 1                   # ib0 = ipp
        di_b1 = di_inn              # ib1 = x_inn

    out = []

    # --- 通道 Ja：6 个邻居 ---
    # latt[lo,k ,j    ,i    ]
    out.append((lo, f,  0,  0, 0))
    # latt[lo,k1,j    ,i_1  ]
    out.append((lo, k1, 0,  di_1, 0))
    # latt[lo,k2,j_2  ,i    ]
    out.append((lo, k2, dj_2, 0, 0))
    # latt[lo,k3,j_2  ,i_1  ]
    out.append((lo, k3, dj_2, di_1, 0))
    # latt[l ,k1,j    ,x_ipp]
    out.append((g,  k1, 0,  di_ipp, 0))
    # latt[l ,k1,j    ,x_inn]
    out.append((g,  k1, 0,  di_inn, 0))

    # --- 通道 Jb：6 个邻居 ---
    # latt[lo,k ,j    ,ib0  ]
    out.append((lo, f,  0,  di_b0, 1))
    # latt[lo,k1,j    ,ib1  ]
    out.append((lo, k1, 0,  di_b1, 1))
    # latt[lo,k2,j_2  ,ib0  ]
    out.append((lo, k2, dj_2, di_b0, 1))
    # latt[lo,k3,j_2  ,ib1  ]
    out.append((lo, k3, dj_2, di_b1, 1))
    # latt[l ,k2,y_jpp,i    ]
    out.append((g,  k2, dj_jpp, 0, 1))
    # latt[l ,k2,y_jnn,i    ]
    out.append((g,  k2, dj_jnn, 0, 1))

    # --- 通道 Jc：6 个邻居 ---
    # latt[l ,k3,j    ,i    ]
    out.append((g,  k3, 0,  0, 2))
    # latt[l ,k3,j    ,i_c  ]
    out.append((g,  k3, 0,  di_c, 2))
    # latt[l ,k3,j_c  ,i    ]
    out.append((g,  k3, dj_c, 0, 2))
    # latt[l ,k3,j_c  ,i_c  ]
    out.append((g,  k3, dj_c, di_c, 2))
    # latt[l ,k ,j    ,ipp  ]
    out.append((g,  f,  0,  1, 2))
    # latt[l ,k ,j    ,inn  ]
    out.append((g,  f,  0, -1, 2))

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
    """初态：照 ising/triangular.py。

      fm   全部 +1
      afm1 第 1 层反号
      afm2 两层的第 2、3 块反号
      afm3 两层的第 1、2 块反号
    """
    out = {}
    for name in ("fm", "afm1", "afm2", "afm3"):
        signs = np.ones(NL * NB, dtype=np.int8)
        if name == "afm1":
            for b in range(NB):
                signs[1 * NB + b] = -1
        elif name == "afm2":
            for g in (0, 1):
                for b in (2, 3):
                    signs[g * NB + b] = -1
        elif name == "afm3":
            for g in (0, 1):
                for b in (1, 2):
                    signs[g * NB + b] = -1
        out[name] = signs
    return out


def _groups():
    """观测量用的子晶格划分（照 ising/triangular.py）。

    fm   一组：全部
    afm1 两组：第 0 层 / 第 1 层
    afm2 两组：两层的块 0、1 / 两层的块 2、3
    afm3 两组：两层的块 0、3 / 两层的块 1、2
    """
    out = {}
    allc = np.arange(NL * NB)
    out["fm"] = [allc]
    out["afm1"] = [
        np.array([0 * NB + b for b in range(NB)]),
        np.array([1 * NB + b for b in range(NB)]),
    ]
    out["afm2"] = [
        np.array([g * NB + b for g in (0, 1) for b in (0, 1)]),
        np.array([g * NB + b for g in (0, 1) for b in (2, 3)]),
    ]
    out["afm3"] = [
        np.array([g * NB + b for g in (0, 1) for b in (0, 3)]),
        np.array([g * NB + b for g in (0, 1) for b in (1, 2)]),
    ]
    return out


def build(X, Y):
    """生成三角晶格的表。"""
    X_s, Y_s = X // 2, Y // 2
    nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr = _build()
    # 更新顺序：与旧实现一致（层在外、块在内）
    cell_order = np.array([g * NB + f for g in range(NL) for f in range(NB)],
                           dtype=np.int64)
    return Lattice(
        name="triangular",
        nlayer=NL, nblock=NB, X_s=X_s, Y_s=Y_s,
        channels=CHANNELS,
        nbr_cell=nbr_cell, nbr_dj=nbr_dj, nbr_di=nbr_di, nbr_ch=nbr_ch,
        nbr_ptr=nbr_ptr, cell_order=cell_order,
        init_states=_init_states(), groups=_groups(),
        # 原子数：2 层 x 4 块 x (X/2) x (Y/2) = 2XY
        num_atoms=2 * X * Y,
        factor_atoms=X * Y,
        X=X, Y=Y,
    )
