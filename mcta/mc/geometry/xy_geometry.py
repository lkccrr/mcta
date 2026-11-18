"""二维 XY 模型的五种规则晶格表生成器。

全部构型都是"平移不变的二维 Bravais 格子 + 子晶格基元"：每个子晶格
当作一个 cell，占据 X×Y 个原胞；邻居表按 cell 给出相对原胞偏移
``(target_cell, dj, di)``，内核用同一套索引逻辑即可支持多子晶格。

定义里只写**基矢 a1/a2、基元笛卡尔坐标 basis 和最小环长度 girth**；
邻居偏移由 :func:`_make_nbr` 自动枚举基元间距最近的平移得到，避免手工
推导偏移出错。最近邻距离 a_nn 由枚举结果确定，并用于面积归一。

除标准 Lattice 字段外，这里还生成三张 XY 判据专用的几何表：

``xy_bonds``   无向边表 ``(n_edges, 7)``，每行 ``(c1,j1,i1,c2,j2,i2,dx)``，
               ``dx`` 是该键沿笛卡尔 x 方向的位移（以最近邻长度为单位）。
``xy_loops``   最小环表 ``(n_points, 3)`` + ``xy_loop_ptr``（CSR），按绕行
               顺序存格点 ``(cell, j, i)``；跨边界取最小镜像。最小环由小
               原胞上的 DFS 搜索得到，再平移复制到全格。
``xy_area``    每个格点占据的面积（以最近邻长度平方为单位）。螺旋度模数
               的普适跳变 Υ=2k_BT/π 要求按**面积**而非格点数归一：
               Υ = (1/A)[<Σ J dx² cos Δθ> - β Var(Σ J dx sin Δθ)]，
               A = xy_area × 格点数。

能量与采样在 ``mcta.mc.xy_engine``；本模块只描述几何，不含物理公式。
"""

import math

import numpy as np

from mcta.mc.engine import Lattice

CHANNELS = ("J",)
SQ3 = math.sqrt(3.0) / 2.0

# 每种格子的定义：
#   a1, a2      原胞基矢（笛卡尔）
#   basis       子晶格基元的笛卡尔坐标
#   girth       最小环长度（涡旋绕数在这个环上算）
DEFS = {
    "xy-square": {
        "a1": (1.0, 0.0), "a2": (0.0, 1.0),
        "basis": [(0.0, 0.0)], "girth": 4,
    },
    "xy-triangular": {
        "a1": (1.0, 0.0), "a2": (0.5, SQ3),
        "basis": [(0.0, 0.0)], "girth": 3,
    },
    "xy-honeycomb": {
        "a1": (1.5, SQ3), "a2": (1.5, -SQ3),
        "basis": [(0.0, 0.0), (1.0, 0.0)], "girth": 6,
    },
    "xy-kagome": {
        "a1": (2.0, 0.0), "a2": (1.0, 2.0 * SQ3),
        "basis": [(0.0, 0.0), (1.0, 0.0), (0.5, SQ3)], "girth": 3,
    },
    # dice（T3）：rim 度 3、hub 度 6，最近邻等长
    "xy-diced": {
        "a1": (1.5, SQ3), "a2": (0.0, 2.0 * SQ3),
        "basis": [(0.0, 0.0), (1.0, 0.0), (1.5, SQ3)], "girth": 6,
    },
}


def _all_neighbors(a1, a2, basis, R=3):
    """枚举基元间所有 (子晶格, dj, di, 笛卡尔位移) 候选，返回最近邻表。

    最近邻距离取所有非零基元间距的最小值；返回每 cell 的邻居列表
    ``[[(target_cell, dj, di), ...], ...]`` 以及该距离 a_nn。
    """
    candidates = []
    for c, (bx, by) in enumerate(basis):
        cell = []
        for t, (px, py) in enumerate(basis):
            for dj in range(-R, R + 1):
                for di in range(-R, R + 1):
                    if c == t and dj == 0 and di == 0:
                        continue
                    dx = di * a1[0] + dj * a2[0] + px - bx
                    dy = di * a1[1] + dj * a2[1] + py - by
                    d2 = dx * dx + dy * dy
                    if d2 > 1e-12:
                        cell.append((t, dj, di, math.sqrt(d2)))
        candidates.append(cell)
    dmin = min(n[3] for cell in candidates for n in cell)
    tol = 1e-6
    nbr = [[(t, dj, di) for t, dj, di, d in cell if abs(d - dmin) < tol]
           for cell in candidates]
    return nbr, dmin


def _node_id(c, j, i, Y, X):
    return (c * Y + j) * X + i


def _build_bonds(X, Y, nbr_csr, a1, a2, basis):
    """生成无向边表 (n_edges, 7)：c1,j1,i1,c2,j2,i2,dx。"""
    seen = {}
    for c in range(len(nbr_csr)):
        for j in range(Y):
            for i in range(X):
                for tc, dj, di in nbr_csr[c]:
                    jj = (j + int(dj)) % Y
                    ii = (i + int(di)) % X
                    na, nb = _node_id(c, j, i, Y, X), _node_id(tc, jj, ii, Y, X)
                    if na >= nb or (na, nb) in seen:
                        continue
                    dx = (di * a1[0] + dj * a2[0]
                          + basis[tc][0] - basis[c][0])
                    seen[(na, nb)] = (c, j, i, tc, jj, ii, float(dx))
    return np.asarray(sorted(seen.values()), dtype=np.float64).reshape(-1, 7)


def _loop_templates(nbr_csr, girth, size):
    """在小周期格上找 girth 长度的简单环，归一化成相对偏移模板。"""
    ncell = len(nbr_csr)
    templates = set()
    for ac in range(ncell):
        for aj in range(size):
            for ai in range(size):
                stack = [[(ac, aj, ai)]]
                while stack:
                    path = stack.pop()
                    c, j, i = path[-1]
                    if len(path) == girth:
                        for tc, dj, di in nbr_csr[c]:
                            if (tc, (j + int(dj)) % size,
                                    (i + int(di)) % size) == (ac, aj, ai):
                                tpl = tuple(
                                    (cc - ac,
                                     (jj - aj + size // 2) % size - size // 2,
                                     (ii - ai + size // 2) % size - size // 2)
                                    for cc, jj, ii in path)
                                templates.add(tpl)
                                break
                        continue
                    for tc, dj, di in nbr_csr[c]:
                        node = (tc, (j + int(dj)) % size, (i + int(di)) % size)
                        if node == (ac, aj, ai) or node in path:
                            continue
                        stack.append(path + [node])
    return templates


def _build_loops(X, Y, nbr_csr, girth):
    """把小格上搜到的环模板平移复制到全格，返回 (loops, loop_ptr)。"""
    size = max(4, 2 * girth)
    templates = _loop_templates(nbr_csr, girth, size)
    rows = []
    seen = set()
    for c in range(len(nbr_csr)):
        for j in range(Y):
            for i in range(X):
                for tpl in templates:
                    chain = []
                    for tc, dj, di in tpl:
                        chain.append((tc, (j + dj) % Y, (i + di) % X))
                    ids = [_node_id(cc, jj, ii, Y, X)
                           for cc, jj, ii in chain]
                    key = frozenset(ids)
                    if len(key) != girth or key in seen:
                        continue
                    seen.add(key)
                    rows.extend(chain)
    loops = np.asarray(rows, dtype=np.int64).reshape(-1, 3)
    ptr = np.arange(0, len(rows) + 1, girth, dtype=np.int64)
    return loops, ptr


def build(name, X, Y, Z=None):
    """生成 X×Y 原胞的二维 XY 构型表。

    ``X, Y`` 是原胞数；总格点数 = ``ncell * X * Y``。
    """
    if name not in DEFS:
        raise KeyError("未知 XY 构型 %r" % name)
    d = DEFS[name]
    X, Y = int(X), int(Y)
    if X < 2 or Y < 2:
        raise ValueError("XY 构型的 X/Y 至少为 2，收到 %d×%d" % (X, Y))
    a1, a2, basis = d["a1"], d["a2"], d["basis"]
    ncell = len(basis)

    # 自动枚举最近邻
    nbr, a_nn = _all_neighbors(a1, a2, basis)
    nbr_csr = [np.asarray(spec, dtype=np.int64) for spec in nbr]
    nbr_cell = np.concatenate([col[:, 0] for col in nbr_csr])
    nbr_dj = np.concatenate([col[:, 1] for col in nbr_csr])
    nbr_di = np.concatenate([col[:, 2] for col in nbr_csr])
    nbr_ch = np.zeros(len(nbr_cell), dtype=np.int64)
    nbr_ptr = np.concatenate([[0], np.cumsum([len(c) for c in nbr_csr])])

    bonds = _build_bonds(X, Y, nbr_csr, a1, a2, basis)
    loops, loop_ptr = _build_loops(X, Y, nbr_csr, d["girth"])
    # 面积归一：原胞面积 = |a1 × a2|；每格点面积 = 原胞面积 / ncell，
    # 再除以最近邻距离平方，转成以 a_nn 为单位的无量纲面积。
    cell_area = abs(a1[0] * a2[1] - a1[1] * a2[0])
    area_per_site = cell_area / ncell / (a_nn * a_nn)

    num = ncell * X * Y
    allc = np.arange(ncell)
    names = ("fm", "afm1", "afm2", "afm3", "afm4", "afm5", "random")
    init_states = {n: np.ones(ncell, dtype=np.int8) for n in names}
    groups = {n: [allc] for n in names}
    return Lattice(
        name=name, nlayer=1, nblock=ncell, X_s=X, Y_s=Y,
        channels=CHANNELS,
        nbr_cell=nbr_cell, nbr_dj=nbr_dj, nbr_di=nbr_di, nbr_ch=nbr_ch,
        nbr_ptr=nbr_ptr, cell_order=np.arange(ncell, dtype=np.int64),
        init_states=init_states, groups=groups,
        num_atoms=num, factor_atoms=X * Y,
        X=X, Y=Y,
        xy_bonds=bonds, xy_loops=loops, xy_loop_ptr=loop_ptr,
        xy_area=area_per_site,
    )


def build_square(X, Y, Z=None):
    return build("xy-square", X, Y, Z)


def build_triangular(X, Y, Z=None):
    return build("xy-triangular", X, Y, Z)


def build_honeycomb(X, Y, Z=None):
    return build("xy-honeycomb", X, Y, Z)


def build_kagome(X, Y, Z=None):
    return build("xy-kagome", X, Y, Z)


def build_diced(X, Y, Z=None):
    return build("xy-diced", X, Y, Z)


__all__ = ["DEFS", "build", "build_square", "build_triangular",
           "build_honeycomb", "build_kagome", "build_diced"]
