"""从晶体结构自动构建 mt.mc 构型层。

核心思路
--------
每个磁性原子 = 一个 cell，X_s = Y_s = 1。
numba 计算内核不用改（自旋仍是 ±1），磁矩标度 S = mom/2 只在
Python 侧写日志时加权（--mom），J 是 ±1 自旋的有效耦合。

用法（通过 -s 直接触发，-c 自动忽略）
------------------------------------
mt.mc -s POSCAR -A Fe -D 3.0 3.6 4.2 -x 2 -y 2 -z 2 -t 30 -p 5.0 2.0 1.0
mt.mc -s POSCAR -A Fe -D 3.0 --mom "Fe 4.0" --ini afm -t 30 -p 5.0

由 -s / -A / -D / --mom / --ini 触发。
"""

import numpy as np

try:
    from ase.io import read as ase_read
    from ase.neighborlist import neighbor_list as ase_nl
except ImportError:
    ase_read = None
    ase_nl = None

from mcta.mc.engine import Lattice


def _pick_magnetic(atoms, elements=None, indices=None):
    """确定哪些原子是磁性原子。

    优先级：indices > elements > 自动识别（d 区 + f 区元素）
    """
    if indices is not None:
        return list(indices)
    if elements is not None:
        return [i for i, a in enumerate(atoms) if a.symbol in elements]

    # 默认：d 区 + f 区元素
    d_block = {"Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
               "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
               "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg"}
    f_block = {"La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
               "Ho", "Er", "Tm", "Yb", "Lu", "Ac", "Th", "Pa", "U", "Np",
               "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr"}
    return [i for i, a in enumerate(atoms)
            if a.symbol in d_block or a.symbol in f_block]


def _build_neighbors(atoms, mag_orig_indices, cutoffs):
    """用 ASE 找周期性邻居，按距离分通道。

    返回
    ----
    nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr
    每个磁性原子是一个 cell (X_s=1, Y_s=1)，dj/di 全 0。
    """
    n_mag = len(mag_orig_indices)
    idx_map = {}
    for new_idx, orig in enumerate(mag_orig_indices):
        idx_map[orig] = new_idx

    # ASE 找邻居：cutoff 要覆盖最大通道
    max_cut = cutoffs[-1] + 0.1
    nl = ase_nl("ijdDS", atoms, cutoff=max_cut, self_interaction=False)
    i_arr, j_arr, d_arr = nl[0], nl[1], nl[2]

    # 收集：(cell_i, cell_j, channel)
    edges = {ci: [] for ci in range(n_mag)}
    counts = [0] * len(cutoffs)

    for ii, jj, dd in zip(i_arr, j_arr, d_arr):
        d = float(np.asarray(dd).item())
        if d <= 0 or d > max_cut:
            continue
        # 两个原子都必须是磁性的
        if int(ii) not in idx_map or int(jj) not in idx_map:
            continue
        ci = idx_map[int(ii)]
        cj = idx_map[int(jj)]
        # 确定通道
        ch = -1
        lo = 0.0
        for k, hi in enumerate(cutoffs):
            if lo < d <= hi:
                ch = k
                break
            lo = hi
        if ch < 0:
            continue
        edges[ci].append((cj, ch))
        counts[ch] += 1

    # 构建 CSR 表
    nbr_cell, nbr_dj, nbr_di, nbr_ch = [], [], [], []
    nbr_ptr = np.zeros(n_mag + 1, dtype=np.int64)

    for ci in range(n_mag):
        nbr_ptr[ci] = len(nbr_cell)
        for cj, ch in sorted(edges[ci], key=lambda x: (x[1], x[0])):
            nbr_cell.append(cj)
            nbr_dj.append(0)   # Y_s=1，偏移无意义
            nbr_di.append(0)   # X_s=1，偏移无意义
            nbr_ch.append(ch)
    nbr_ptr[n_mag] = len(nbr_cell)

    return (np.array(nbr_cell), np.array(nbr_dj), np.array(nbr_di),
            np.array(nbr_ch), nbr_ptr, counts)


def _channels(n):
    return tuple("J%s" % chr(ord("a") + k) for k in range(n))


def _parse_mom(text, mag_syms):
    """解析 --mom，返回每磁性原子的标称磁矩数组。

    格式（空格或逗号均可分隔）：
      "2" / "2.0"            所有磁性原子 2.0（S = ±1）
      "All 1.0" / "ALL 1.0"  同上
      "Fe 4.0, Cr 3.0"       按元素设置；未列出的元素取默认 2.0
    """
    n = len(mag_syms)
    s = str(text).strip()
    try:
        moments = np.full(n, float(s), dtype=float)
    except ValueError:
        pass
    else:
        if not np.all(np.isfinite(moments)) or np.any(moments <= 0):
            raise ValueError("--mom 磁矩必须是大于 0 的有限数值")
        return moments
    toks = s.replace(",", " ").split()
    if len(toks) % 2:
        raise ValueError(
            "--mom 格式错误: %r（应为 '2'、'All 1.0' 或 'Fe 4.0 Cr 3.0'，空格或逗号分隔）"
            % text)
    table = {}
    for k in range(0, len(toks), 2):
        name, val = toks[k].lower(), toks[k + 1]
        try:
            table[name] = float(val)
        except ValueError:
            raise ValueError("--mom 格式错误: %r（%s 不是数字）" % (text, val))
    moments = np.array([table.get(sym.lower(), table.get("all", 2.0))
                        for sym in mag_syms], dtype=float)
    if not np.all(np.isfinite(moments)) or np.any(moments <= 0):
        raise ValueError("--mom 磁矩必须是大于 0 的有限数值")
    return moments


def _afm_z_signs(atoms, mag_orig):
    """沿 z 方向逐层交替的 ±1 初态（按分数坐标 z 分层，层间交替）。"""
    zpos = atoms.get_scaled_positions(wrap=True)[mag_orig, 2]
    signs = np.zeros(len(mag_orig), dtype=np.int8)
    layer_sign = 1
    prev = None
    for idx in np.argsort(zpos, kind="stable"):
        z = zpos[idx]
        if prev is not None and abs(z - prev) > 1e-3:
            layer_sign = -layer_sign
        signs[idx] = layer_sign
        prev = z
    return signs


def _parse_spin_list(text, ncell):
    """把 --ini 的 ±1 列表（按原胞磁性原子顺序）解析为 int8 数组。

    空格或逗号均可分隔（如 "1,-1,-1,1" 或 "1 -1 -1 1"）。
    长度等于磁性原子数时直接使用；是磁性原子数的整因数时按超胞重复平铺。
    """
    try:
        vals = [float(x) for x in text.replace(",", " ").split() if x.strip()]
    except ValueError:
        raise ValueError("--ini 列表格式错误: %r（应为如 1,-1,-1,1 或 1 -1 -1 1）"
                         % text)
    if not vals:
        raise ValueError("--ini 列表为空")
    if any(v not in (-1.0, 1.0) for v in vals):
        raise ValueError("--ini 列表只能包含 +1 或 -1")
    arr = np.asarray(vals, dtype=np.int8)
    if arr.size == ncell:
        return arr
    if ncell % arr.size == 0:
        return np.tile(arr, ncell // arr.size)
    raise ValueError("--ini 列表长度 %d 与磁性原子数 %d 不匹配（也不成整倍数）"
                     % (arr.size, ncell))


def _sign_groups(signs):
    """按 ±1 把 cell 分成两组；全同号时为单组。"""
    up = np.where(signs == 1)[0]
    dn = np.where(signs == -1)[0]
    if up.size and dn.size:
        return [up, dn]
    return [np.arange(signs.size)]


def _is_2d(atoms):
    """c 方向非周期，或最大无原子间隙至少为 10 Å 时按二维处理。"""
    if not atoms.get_pbc()[2]:
        return True
    cell = atoms.cell.array
    normal = np.cross(cell[0], cell[1])
    area = np.linalg.norm(normal)
    if area < 1e-12:
        return False
    height = abs(float(np.dot(cell[2], normal / area)))
    if height < 1e-12:
        return False
    # 用包含跨周期边界的最大原子间距计算真空层，避免原子位于
    # fractional z≈0/1 两端时把同一单层误判成很厚的三维结构。
    z = np.mod(atoms.get_scaled_positions(wrap=False)[:, 2], 1.0)
    z.sort()
    gaps = np.diff(np.concatenate((z, [z[0] + 1.0])))
    return float(gaps.max() * height) >= 10.0


def build(structure_path, mag_elements=None, mag_indices=None, cutoffs=None,
          supercell=(1, 1, 1), mom="2", ini=None, fallback_key="fm"):
    """从晶体结构构建 Lattice。

    参数
    ----
    structure_path : str
        结构文件路径（POSCAR / CIF / .vasp 等，ASE 能读就行）
    mag_elements : set of str
        磁性元素符号，如 {"Fe", "Co"}；None 自动识别
    mag_indices : list of int
        磁性原子在原胞中的索引；优先于 mag_elements
    cutoffs : list of float
        各通道距离上限（A），如 [3.0, 3.6, 4.2]；默认 [3.0]
    supercell : tuple of 3 int
        超胞扩展倍数 (nx, ny, nz)，由 CLI 的 -x/-y/-z 给出；
        二维结构忽略 nz，始终不在 z 方向扩胞
    mom : str
        --mom：原子自旋磁矩标称值，默认 "2"（S = ±1）；
        可按元素设置，如 "Fe 4.0, Cr 3.0" 或 "All 1.0"
    ini : str or None
        --ini 的 ±1 列表（如 "1,-1,-1,1"，按原胞磁性原子顺序）；
        关键字 fm / afm / random 由 wrapper 解析为对应的既有键，不传到这里
    fallback_key : str
        未给 --ini 时使用的初态键名（fm / afm / random）

    返回
    ----
    mcta.mc.engine.Lattice
    """
    if ase_read is None:
        raise ImportError("from_structure 需要 ASE (pip install ase)")
    if cutoffs is None:
        cutoffs = [3.0]
    if (not cutoffs or not np.all(np.isfinite(cutoffs))
            or any(c <= 0 for c in cutoffs)
            or any(b <= a for a, b in zip(cutoffs, cutoffs[1:]))):
        raise ValueError("-D/--cutof 必须是大于 0 且严格递增的有限距离")

    atoms = ase_read(structure_path)
    # 必须在扩胞前判断：二维结构沿 z 扩胞会填掉真空层，影响后续判断。
    is_2d = _is_2d(atoms)
    if is_2d:
        supercell = (supercell[0], supercell[1], 1)
    # 扩展超胞
    if any(s != 1 for s in supercell):
        atoms = atoms.repeat(supercell)

    mag_orig = _pick_magnetic(atoms, elements=mag_elements, indices=mag_indices)
    if not mag_orig:
        raise ValueError("未在结构中找到磁性原子")

    n_mag = len(mag_orig)
    nbr_cell, nbr_dj, nbr_di, nbr_ch, nbr_ptr, counts = \
        _build_neighbors(atoms, mag_orig, cutoffs)

    channels = _channels(len(cutoffs))
    cell_order = np.arange(n_mag, dtype=np.int64)
    allc = np.arange(n_mag)

    # 磁矩标称值 -> 自旋标度 S = mom / 2（默认 2 -> S = ±1）
    mag_syms = [atoms[i].symbol for i in mag_orig]
    spin_scale = _parse_mom(mom, mag_syms) / 2.0

    # 如果有任何一个原子 S != 1，构造 per-edge S_i * S_j
    nbr_SS = None
    if not np.allclose(spin_scale, 1.0):
        nbr_SS = np.ones(len(nbr_cell), dtype=np.float64)
        for c in range(n_mag):
            s_own = spin_scale[c]
            for k in range(nbr_ptr[c], nbr_ptr[c + 1]):
                nbr_SS[k] = s_own * spin_scale[nbr_cell[k]]

    # 初态：fm / afm（沿 z 逐层交替）/ random
    init_states = {
        "fm": np.ones(n_mag, dtype=np.int8),
        "afm": _afm_z_signs(atoms, mag_orig),
        "random": np.random.RandomState(42).choice([-1, 1], size=n_mag).astype(np.int8),
    }
    groups = {
        "fm": [allc],
        "random": [allc],
        "afm": _sign_groups(init_states["afm"]),
    }

    # --ini 给了 ±1 列表：注册为 "list" 键
    if ini is not None:
        signs = _parse_spin_list(ini, n_mag)
        init_states["list"] = signs
        groups["list"] = _sign_groups(signs)

    key = fallback_key or "fm"
    if key not in init_states:
        raise ValueError("未知初态 %r（结构模式支持 fm / afm / random 或 ±1 列表）"
                         % key)

    return Lattice(
        name="structure",
        nlayer=n_mag, nblock=1, X_s=1, Y_s=1,
        channels=channels,
        nbr_cell=nbr_cell, nbr_dj=nbr_dj, nbr_di=nbr_di, nbr_ch=nbr_ch,
        nbr_ptr=nbr_ptr, cell_order=cell_order,
        init_states=init_states, groups=groups,
        num_atoms=n_mag, factor_atoms=1,
        X=supercell[0], Y=supercell[1],
        Z=None if is_2d else supercell[2],
        nbr_SS=nbr_SS,
        spin_scale=spin_scale,
    )
