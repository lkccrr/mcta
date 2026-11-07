"""直接读取 VASP 输出文件，替代 vaspkit 生成的 .dat 中间文件。

支持的文件：
    vasprun.xml 本征值（能带）、k 点、占据数、费米能与结构（由 ASE 解析）
    EIGENVAL    本征值、k 点、占据数（没有 vasprun.xml 时的快速通路）
    PROCAR      投影能带（需 LORBIT=11）
    DOSCAR      总态密度与分波态密度
    OUTCAR      费米能、ISPIN、POTCAR 元素名
    KPOINTS     高对称点路径与标签（line-mode）
    POSCAR      晶格、元素与原子数（或其 CONTCAR，由 ASE 解析）

本模块输出的数组与 :mod:`mcta.bandplot.readdata` 中的 .dat 解析结果一一对应，
因此 :mod:`mcta.bandplot.plots` / :mod:`mcta.bandplot.projected` / :mod:`mcta.bandplot.mass`
可以直接复用，无需知道数据来自 VASP 还是 vaspkit。

交给 ASE 的部分：**POSCAR/CONTCAR**（缩放系数含负值表示体积、Direct/Cartesian、
Selective dynamics、VASP4 把元素名写在标题行）和 **vasprun.xml**（ASE 把整个
XML 读成 Atoms，能带、k 点、占据数、费米能都挂在 calculator 上）。EIGENVAL /
DOSCAR / PROCAR / KPOINTS 仍是本地解析：ASE 没有这些文件的读取器，而且
DOSCAR 是 Fortran 定宽输出（``-9.2E+002.0E+00`` 这类粘连数字按空白切分会出错），
必须按指数字段定宽切分。
"""

import os
import re

import numpy as np
from ase.io import read as read_atoms

__all__ = [
    "VaspData", "read_poscar", "read_kpoints", "read_eigenval", "read_vasprun",
    "read_outcar", "read_doscar", "read_procar", "reciprocal",
    "kpath_distances", "match_labels",
]

_INT = re.compile(r"^[+-]?\d+$")
_POSCAR_NAMES = ("POSCAR", "CONTCAR", "POSCAR-unitcell")
# EIGENVAL 与 PROCAR 的 k 点行末尾都带权重："... weight = 0.1000000"
_WEIGHT_RE = re.compile(r"weight\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
# DOSCAR 为 Fortran 定宽输出，负号会挤掉分隔空格（-9.2E+002.0E+00），
# 这里按“指数固定两位”切分，既能处理粘连也能处理正常空白分隔
_DOS_NUMBER = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+)(?:[EeDd][-+]\d{2})?")


def _num(token):
    """把 VASP 的 Fortran 指数（1.0D+02）转成 Python 浮点数。"""
    return float(token.replace("D", "E").replace("d", "e"))


def _fixed_width_row(line):
    values = _DOS_NUMBER.findall(line)
    return [_num(v) for v in values]


def _is_float(token):
    try:
        _num(token)
        return True
    except (TypeError, ValueError):
        return False


def _row(line):
    """读取行首的连续数值，遇到第一个非数值即停止。"""
    out = []
    for token in line.split():
        if not _is_float(token):
            break
        out.append(_num(token))
    return out


def _first(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- POSCAR ---
def read_poscar(path):
    """读取晶格、元素名与原子数，解析工作交给 ASE。

    ASE 会处理缩放系数（负值表示总体积）、Direct/Cartesian 坐标、
    Selective dynamics 以及 VASP4 把元素名写在标题行的情况；
    标题里也找不到元素名时 ASE 给出 ``X``，此时返回空的 species，
    由 :class:`VaspData` 回退到 OUTCAR 的 POTCAR 元素名。
    """
    try:
        atoms = read_atoms(path, format="vasp")
    except Exception as exc:                     # ASE 的报错对用户不够直白
        raise ValueError("%s 不是合法的 POSCAR：%s" % (path, exc)) from exc

    symbols = atoms.get_chemical_symbols()
    if not symbols or any(symbol == "X" for symbol in symbols):
        return {"lattice": np.array(atoms.cell.array, dtype=float),
                "species": [], "counts": []}

    species, counts = [], []
    for symbol in symbols:                       # 按出现顺序合并连续的同种元素
        if species and species[-1] == symbol:
            counts[-1] += 1
        else:
            species.append(symbol)
            counts.append(1)
    return {"lattice": np.array(atoms.cell.array, dtype=float),
            "species": species, "counts": counts}


# --------------------------------------------------------------- KPOINTS ---
def read_kpoints(path):
    """解析 KPOINTS。

    返回 ``{"line_mode": bool, "cartesian": bool, "points": [(label, k), ...]}``。
    line-mode 时 points 按 ``起点, 终点, 起点, 终点 ...`` 展开，标签可为空串。

    KPOINTS 头部的写法不统一：标准 VASP 是
    ``标题 / 注释 / 点数 / Line-mode / Reciprocal|Cartesian / k 点``，
    也有省略点数的写法，因此这里在开头几行里找模式关键字，并据此确定
    k 点的起始行。
    """
    with open(path, "r", errors="ignore") as handle:
        lines = handle.read().splitlines()
    if len(lines) < 4:
        raise ValueError("%s 不是合法的 KPOINTS" % path)

    line_mode = False
    cartesian = False
    start = 2
    for index in range(2, min(len(lines), 6)):
        low = lines[index].strip().lower()
        if low.startswith("line"):
            line_mode = True
            start = index + 1
        elif low.startswith("cartesian") or low == "k":
            cartesian = True
            start = index + 1
        elif low.startswith("reciprocal") or low.startswith("mesh"):
            start = index + 1

    points = []
    for line in lines[start:]:
        parsed = _parse_kpoint_line(line)
        if parsed is None:
            continue
        points.append(parsed)
    return {"line_mode": line_mode, "cartesian": cartesian, "points": points}


def _parse_kpoint_line(line):
    """解析一行 KPOINTS，返回 (label, np.array([kx, ky, kz]))；不是 k 点则返回 None。

    兼容三种写法（第 4 列的含义在不同来源里不一样）：
      * 标准 VASP：坐标 权重 ! 标签    → ``0.0 0.0 0.0 1 ! G``
      * 省略叹号：坐标 权重 标签       → ``0.0 0.0 0.0 1 G``
      * vaspkit：  标签 坐标           → ``G 0.0 0.0 0.0``

    叹号之后的内容是标签，因此权重列不会被误当成标签。
    """
    body, sep, comment = line.partition("!")
    tokens = body.split()
    label = comment.split()[0] if sep and comment.split() else ""

    if tokens and not _is_float(tokens[0]):
        # vaspkit 风格：标签在最前
        label = label or tokens[0]
        values = tokens[1:4]
    else:
        values = tokens[:3]
        if not label:
            # 坐标之后第一个非数值列才是标签，数值列是 k 点权重
            label = next((t for t in tokens[3:] if not _is_float(t)), "")
    if len(values) != 3 or not all(_is_float(v) for v in values):
        return None
    return label, np.array([_num(v) for v in values])


# -------------------------------------------------------------- EIGENVAL ---
def read_eigenval(path):
    """解析 EIGENVAL，返回本征值、占据数、k 点（分数坐标）与权重。

    兼容 VASP 5（``NIONS NBANDS NKPTS NELECT``）与 VASP 6（``NELECT NKPTS NBANDS``）
    两种表头；自旋由能带行的列数（3 列非自旋 / 5 列自旋）判定。
    """
    with open(path, "r", errors="ignore") as handle:
        lines = handle.read().splitlines()

    header, start = None, None
    for index, line in enumerate(lines[:12]):
        tokens = line.split()
        if index >= 4 and len(tokens) >= 3 and all(_INT.match(t) for t in tokens):
            header = [int(t) for t in tokens]
            start = index + 1
            break
    if header is None:
        raise ValueError("%s 表头无法识别，可能不是 EIGENVAL" % path)

    if len(header) >= 4:
        nbands, nkpts, nelect = header[1], header[2], header[3]
    else:
        nelect, nkpts, nbands = header[:3]

    kpoints, weights, blocks = [], [], []
    index = start
    total = len(lines)
    while index < total and len(kpoints) < nkpts:
        tokens = lines[index].split()
        if len(tokens) >= 4 and all(_is_float(t) for t in tokens[:4]):
            kpoints.append([_num(t) for t in tokens[:3]])
            weights.append(_num(tokens[3]))
            index += 1
            bands = []
            while len(bands) < nbands and index < total:
                line = lines[index]
                index += 1
                if not line.split():
                    continue
                values = _row(line)
                if len(values) >= 2:
                    bands.append(values)
            blocks.append(bands)
        else:
            index += 1

    ncols = max((len(v) for bands in blocks for v in bands), default=3)
    ispin = 2 if ncols >= 4 else 1

    energies = np.zeros((ispin, nbands, nkpts))
    occupations = np.zeros((ispin, nbands, nkpts))
    for ik, bands in enumerate(blocks):
        for ib, values in enumerate(bands):
            energies[0, ib, ik] = values[1]
            if ispin == 2:
                energies[1, ib, ik] = values[2]
                occupations[0, ib, ik] = values[3] if len(values) > 3 else 0.0
                occupations[1, ib, ik] = values[4] if len(values) > 4 else 0.0
            elif len(values) > 2:
                occupations[0, ib, ik] = values[2]
    return {
        "kpoints": np.array(kpoints) if kpoints else np.zeros((0, 3)),
        "weights": np.array(weights),
        "energies": energies,
        "occupations": occupations,
        "ispin": ispin,
        "nbands": nbands,
        "nkpts": len(kpoints),
        "nelect": nelect,
    }


# ------------------------------------------------------ 能带路径的 k 点筛选 ---
def _path_kpoint_mask(weights):
    """挑出能带路径上的 k 点（返回布尔 mask，None 表示全部保留）。

    有些流程（例如 HSE 等混合泛函）把 SCF 用的 k 网格和能带路径放进同一次
    计算：EIGENVAL 里网格点的权重不为 0，路径点的权重为 0。把两类点一起画
    出来会得到断裂、错位的曲线，所以只保留权重为 0 的那一段路径点。

    权重全为 0 或全不为 0（普通能带计算）时返回 None；权重为 0 的点不连续
    时同样返回 None，避免把普通计算里个别重复点误当成路径。
    """
    weights = np.asarray(weights, dtype=float).ravel()
    if weights.size == 0:
        return None
    zero = np.isclose(weights, 0.0)
    if zero.all() or not zero.any():
        return None
    index = np.flatnonzero(zero)
    if index[-1] - index[0] + 1 != index.size:
        return None
    return zero


# ------------------------------------------------------------- vasprun ---
def read_vasprun(path):
    """用 ASE 解析 vasprun.xml，返回能带、k 点、占据数、费米能与结构。

    ASE 把整个 XML 读成 :class:`ase.Atoms`，能带挂在 calculator 上
    （``get_eigenvalues`` / ``get_occupation_numbers`` / ``get_ibz_k_points``），
    这里整理成与 :func:`read_eigenval` 相同的字典，另外附上 ``efermi``
    和由 ASE 解析出的晶格与元素。
    """
    try:
        atoms = read_atoms(path, format="vasp-xml", index=-1)
    except Exception as exc:                    # ASE 的报错对用户不够直白
        raise ValueError("%s 不是合法的 vasprun.xml：%s" % (path, exc)) from exc

    calc = atoms.calc
    if calc is None or calc.get_number_of_bands() is None:
        raise ValueError("%s 里没有本征值（是否为静态计算？）" % path)

    nspin = calc.get_number_of_spins()
    kpoints = np.array(calc.get_ibz_k_points(), dtype=float)
    nkpts = len(kpoints)
    nbands = calc.get_number_of_bands()

    energies = np.zeros((nspin, nbands, nkpts))
    occupations = np.zeros((nspin, nbands, nkpts))
    for spin in range(nspin):
        for ik in range(nkpts):
            energies[spin, :, ik] = calc.get_eigenvalues(spin=spin, kpt=ik)
            occupations[spin, :, ik] = calc.get_occupation_numbers(spin=spin, kpt=ik)

    species, counts = [], []
    for symbol in atoms.get_chemical_symbols():  # 按出现顺序合并连续的同种元素
        if species and species[-1] == symbol:
            counts[-1] += 1
        else:
            species.append(symbol)
            counts.append(1)

    nelect = calc.parameters.get("NELECT")
    return {
        "eigenval": {
            "kpoints": kpoints,
            "weights": np.array(calc.get_k_point_weights(), dtype=float),
            "energies": energies,
            "occupations": occupations,
            "ispin": nspin,
            "nbands": nbands,
            "nkpts": nkpts,
            "nelect": int(float(nelect)) if nelect is not None else None,
        },
        "efermi": (None if calc.get_fermi_level() is None
                   else float(calc.get_fermi_level())),
        "lattice": np.array(atoms.cell.array, dtype=float),
        "species": species,
        "counts": counts,
    }


# ---------------------------------------------------------------- OUTCAR ---
def read_outcar(path):
    """从 OUTCAR 取费米能、ISPIN、NBANDS 以及 POTCAR 元素名（取最后一次出现）。"""
    info = {"efermi": None, "ispin": 1, "nbands": None, "species": []}
    efermi, ispin = [], []
    title = []
    with open(path, "r", errors="ignore") as handle:
        for line in handle:
            if "E-fermi" in line:
                values = _row(line.split(":", 1)[1]) if ":" in line else _row(line)
                if values:
                    efermi.append(values[0])
            elif line.strip().startswith("ISPIN"):
                values = _row(line.split("=", 1)[1]) if "=" in line else []
                if values:
                    ispin.append(int(values[0]))
            elif "NBANDS" in line:
                values = _row(line.split("=", 1)[1]) if "=" in line else []
                if values:
                    info["nbands"] = int(values[0])
            elif "TITEL" in line:
                match = re.search(r"TITEL\s*=\s*\S+\s+\S+\s+([A-Za-z]+)", line)
                if match:
                    title.append(match.group(1))
    if efermi:
        info["efermi"] = efermi[-1]
    if ispin:
        info["ispin"] = ispin[-1]
    if title:
        info["species"] = [re.sub(r"[^A-Za-z]", "", t) for t in title]
    return info


# --------------------------------------------------------------- DOSCAR ---
def _dos_block(lines, index, nedos):
    """从 ``lines[index]`` 起读 nedos 行数值，返回 ``(数组, 下一行下标)``。

    列数按最短的一行裁齐，避免个别畸形行把整块数据变成 object 数组。
    """
    rows = []
    while index < len(lines) and len(rows) < nedos:
        line = lines[index]
        index += 1
        values = _fixed_width_row(line) if line.strip() else []
        if len(values) > 1:
            rows.append(values)
    if not rows:
        return None, index
    width = min(len(row) for row in rows)
    return np.array([row[:width] for row in rows], dtype=float), index


def _dos_header_values(line):
    """``Emax Emin NEDOS Efermi`` 表头：优先按空白切分（NEDOS 是整数，
    定宽正则只认带小数点的数会漏掉它），出现粘连时再退回定宽切分。"""
    values = _row(line)
    if len(values) < 4:
        values = _fixed_width_row(line)
    return values


def _is_dos_header(values, nedos):
    """每个离子的分波数据前也有一行 ``Emax Emin NEDOS Efermi [1.0]`` 表头。

    判据：列数足够、第三列等于 NEDOS 且为整数；数据行的第三列是 DOS 值，
    同时满足“恰为整数且等于 NEDOS”的概率可以忽略。
    """
    return (len(values) >= 4
            and abs(values[2] - nedos) < 0.5
            and abs(values[2] - round(values[2])) < 1e-6)


def read_doscar(path):
    """解析 DOSCAR，返回总态密度、各离子分波态密度与费米能。

    文件结构：第 1 行 NIONS，随后 4 行表头（体积、温度、'CAR'、体系名），
    第 6 行 ``Emax Emin NEDOS Efermi``，然后是 NEDOS 行总 DOS；每个离子的
    分波数据前都重复一次 ``Emax Emin NEDOS Efermi`` 表头，必须跳过。
    """
    with open(path, "r", errors="ignore") as handle:
        lines = handle.read().splitlines()
    if len(lines) < 6:
        raise ValueError("%s 不是合法的 DOSCAR（行数不足）" % path)

    natoms = int(lines[0].split()[0])
    header = _dos_header_values(lines[5])
    if len(header) < 4 or header[2] < 1:
        raise ValueError("%s 的 DOSCAR 表头无法识别" % path)
    emax, emin, nedos, efermi = header[0], header[1], int(header[2]), header[3]

    total, index = _dos_block(lines, 6, nedos)
    if total is None:
        raise ValueError("%s 的 DOSCAR 没有态密度数据" % path)

    ions = []
    for _ in range(natoms):
        if index >= len(lines):
            break
        if _is_dos_header(_dos_header_values(lines[index]), nedos):
            index += 1
        block, index = _dos_block(lines, index, nedos)
        if block is None:
            break
        ions.append(block)
    return {
        "energies": total[:, 0],
        "total": total,
        "ions": ions,
        "efermi": efermi,
        "nedos": nedos,
        "natoms": natoms,
        "emax": emax,
        "emin": emin,
    }


def _shell_layout(ncols, ispin):
    """按 VASP 的列序（s, py, pz, px, dxy ...，自旋交错）切分轨道壳层。"""
    n_orb = max((ncols - 1) // ispin, 0)
    shells, start = [], 0
    for name, width in (("s", 1), ("p", 3), ("d", 5), ("f", 7)):
        if start >= n_orb:
            break
        stop = min(start + width, n_orb)
        shells.append((name, list(range(start, stop))))
        start = stop
    return shells, n_orb


# ---------------------------------------------------------------- PROCAR ---
def read_procar(path):
    """流式解析 PROCAR，返回每个 (k, band) 的离子投影权重。

    返回 ``{"blocks": {(ik, ib): [array(nions, n_orb), ...]},
    "orbitals": [...], "nspin": 1|2}``；具有两个离子块即自旋极化。
    """
    blocks, orbitals = {}, []
    kweights = {}
    current, atoms = None, []
    ik = ib = -1
    with open(path, "r", errors="ignore") as handle:
        for line in handle:
            stripped = line.lstrip()
            lowered = stripped.lower()
            if lowered.startswith("k-point"):
                tokens = stripped.split()
                try:
                    ik = int(tokens[1]) - 1
                except (IndexError, ValueError):
                    ik += 1
                found = _WEIGHT_RE.search(stripped)
                if found:
                    try:
                        kweights[ik] = float(found.group(1))
                    except ValueError:
                        pass
                current = None
            elif lowered.startswith("band"):
                tokens = stripped.split()
                try:
                    ib = int(tokens[1]) - 1
                except (IndexError, ValueError):
                    ib += 1
                current = None
            elif lowered.startswith("ion"):
                names = stripped.split()[1:]
                if names and names[-1].lower() == "tot":
                    names = names[:-1]
                orbitals = names
                atoms = []
                current = atoms
            elif lowered.startswith("tot"):
                if current is not None and atoms:
                    blocks.setdefault((ik, ib), []).append(np.array(atoms))
                current = None
            elif current is not None:
                values = _row(stripped)
                if len(values) >= 2:
                    row = values[1:len(orbitals) + 1]
                    if len(row) < len(orbitals):
                        row = row + [0.0] * (len(orbitals) - len(row))
                    atoms.append(row)
    nspin = max((len(v) for v in blocks.values()), default=1)
    return {"blocks": blocks, "orbitals": orbitals, "nspin": nspin,
            "kweights": kweights}


# ------------------------------------------------------------------ misc ---
def reciprocal(lattice):
    """倒格矢（行向量），满足 a_i·b_j = 2πδ_ij。"""
    return 2.0 * np.pi * np.linalg.inv(np.asarray(lattice, float)).T


def kpath_distances(kpoints, lattice, as_cartesian=False):
    """把 k 点（分数坐标或 2π/Å 笛卡尔坐标）换算成路径累计长度。"""
    kpoints = np.asarray(kpoints, float)
    if len(kpoints) == 0:
        return np.zeros(0)
    frac = kpoints @ np.asarray(lattice, float).T if as_cartesian else kpoints
    cart = frac @ reciprocal(lattice)
    if len(cart) == 1:
        return np.zeros(1)
    steps = np.linalg.norm(np.diff(cart, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(steps)])


def _score(points, kpoints):
    if not len(points) or not len(kpoints):
        return 1e9
    return sum(float(np.min(np.linalg.norm(kpoints - k, axis=1)))
               for _, k in points)


def match_labels(points, kpoints, distances):
    """把高对称点映射到 k 路径上的位置，返回 ``(ticks, labels)``。

    采用顺序游标匹配，因此 Γ-M-Γ 这类重复出现的点不会被匹配到错误区段。
    """
    ticks, labels = [], []
    cursor = 0
    total = len(kpoints)
    for label, k in points:
        if cursor >= total:
            break
        delta = np.linalg.norm(kpoints[cursor:] - k, axis=1)
        position = cursor + int(np.argmin(delta))
        if float(np.min(delta)) < 1e-3:
            cursor = position
        if ticks and abs(distances[position] - ticks[-1]) < 1e-8:
            continue
        ticks.append(float(distances[position]))
        labels.append(label)
    return ticks, labels


# --------------------------------------------------------------- VaspData ---
class VaspData:
    """一个 VASP 计算目录的惰性读取器。"""

    def __init__(self, directory=".", shift=True, drop_weighted=True):
        self.dir = directory
        self.shift = shift
        # 是否丢掉权重不为 0 的 k 点（HSE 等把 SCF 网格混在能带路径里）
        self.drop_weighted = drop_weighted
        self.alias = {
            "poscar": _first([os.path.join(directory, n) for n in _POSCAR_NAMES]),
            "vasprun": _first([os.path.join(directory, "vasprun.xml")]),
            "eigenval": _first([os.path.join(directory, "EIGENVAL")]),
            "procar": _first([os.path.join(directory, "PROCAR")]),
            "doscar": _first([os.path.join(directory, "DOSCAR")]),
            "outcar": _first([os.path.join(directory, "OUTCAR")]),
            "kpoints": _first([os.path.join(directory, "KPOINTS")]),
            "klabels": _first([os.path.join(directory, "KLABELS")]),
        }
        self._cache = {}

    # -- 基础信息 ---------------------------------------------------------
    def has(self, name):
        if name == "eigenval":                   # vasprun.xml 也能提供本征值
            return bool(self.alias.get("eigenval") or self.alias.get("vasprun"))
        return bool(self.alias.get(name))

    def _get(self, key, reader, *args, **kwargs):
        if key not in self._cache:
            path = self.alias.get(key)
            if not path:
                raise FileNotFoundError("%s 目录下缺少 %s" % (self.dir, key.upper()))
            self._cache[key] = reader(path, *args, **kwargs)
        return self._cache[key]

    @property
    def structure(self):
        if "structure" not in self._cache:
            if self.alias["poscar"]:
                struct = read_poscar(self.alias["poscar"])
                if not struct["species"]:
                    struct["species"] = self.outcar["species"] or []
                    struct["counts"] = [1] * len(struct["species"])
            elif self.alias["vasprun"]:
                # 没有 POSCAR 时用 ASE 从 vasprun.xml 里取最后一次的结构
                data = self.vasprun
                struct = {"lattice": data["lattice"],
                          "species": data["species"], "counts": data["counts"]}
            else:
                struct = {"lattice": np.eye(3), "species": [], "counts": []}
            self._cache["structure"] = struct
        return self._cache["structure"]

    @property
    def vasprun(self):
        return self._get("vasprun", read_vasprun)

    @property
    def outcar(self):
        if "outcar" not in self._cache:
            if self.alias["outcar"]:
                self._cache["outcar"] = read_outcar(self.alias["outcar"])
            else:
                self._cache["outcar"] = {"efermi": None, "ispin": 1,
                                         "nbands": None, "species": []}
        return self._cache["outcar"]

    @property
    def eigenval(self):
        """本征值：优先用 vasprun.xml（ASE），没有或用不了时退回 EIGENVAL。"""
        if "eigenval" not in self._cache:
            if self.alias["vasprun"]:
                try:
                    self._cache["eigenval"] = self.vasprun["eigenval"]
                except (ValueError, OSError) as exc:
                    if not self.alias["eigenval"]:
                        raise
                    print("提示：%s；改用 EIGENVAL。" % exc)
            if "eigenval" not in self._cache:
                path = self.alias["eigenval"]
                if not path:
                    raise FileNotFoundError(
                        "%s 目录下没有 EIGENVAL 或 vasprun.xml" % self.dir)
                self._cache["eigenval"] = read_eigenval(path)
            self._cache["eigenval"] = self._filter_weighted(self._cache["eigenval"])
        return self._cache["eigenval"]

    def _filter_weighted(self, data):
        """丢掉权重不为 0 的 k 点，只留能带路径（HSE 等流程）。

        过滤后的 k 点、能量、占据数一起裁剪，并记下 ``kpoint_index``：
        原始下标 -> 过滤后下标，PROCAR 的投影数据按它重新对齐。
        """
        total = len(data.get("kpoints", []))
        mask = None
        if self.drop_weighted:
            mask = _path_kpoint_mask(data.get("weights", []))
        if mask is None or mask.size != total or bool(mask.all()):
            data["kpoint_index"] = np.arange(total)
            data["dropped_weighted"] = 0
            return data

        index = np.flatnonzero(mask)
        for key in ("kpoints", "weights"):
            values = data.get(key)
            if values is not None and len(values) == total:
                data[key] = np.asarray(values)[index]
        for key in ("energies", "occupations"):
            values = data.get(key)
            if values is None:
                continue
            array = np.asarray(values)
            if array.ndim == 3 and array.shape[2] == total:
                data[key] = array[:, :, index]
        data["nkpts"] = len(index)
        data["kpoint_index"] = index
        data["dropped_weighted"] = total - len(index)
        print("提示：%s 里混有 %d 个权重非零的 k 点（SCF 网格），"
              "已只保留 %d 个权重为 0 的能带路径点。"
              % (self.dir, total - len(index), len(index)))
        return data

    @property
    def efermi(self):
        if "efermi" not in self._cache:
            value = self.outcar.get("efermi")
            if value is None and self.has("doscar"):
                value = self.doscar["efermi"]
            if value is None and self.alias["vasprun"]:
                value = self.vasprun["efermi"]
            self._cache["efermi"] = 0.0 if value is None else float(value)
        return self._cache["efermi"]

    @property
    def doscar(self):
        return self._get("doscar", read_doscar)

    @property
    def procar(self):
        return self._get("procar", read_procar)

    # -- 能带 -------------------------------------------------------------
    @property
    def energies(self):
        """(ispin, nbands, nkpts) 的能带，默认已减去费米能。"""
        data = self.eigenval["energies"].copy()
        if self.shift:
            data -= self.efermi
        return data

    def _fractional_targets(self, info):
        """把 KPOINTS 里给出的高对称点统一换算为分数坐标。"""
        lattice = np.asarray(self.structure["lattice"], float)
        if info["cartesian"]:
            # KPOINTS 的 Cartesian 以 2π/Å 为单位：f_i = k·a_i
            return [(label, k @ lattice.T) for label, k in info["points"]]
        return list(info["points"])

    def _kpoints(self):
        """返回 EIGENVAL 的 k 点（统一为分数坐标）。"""
        kpoints = np.asarray(self.eigenval["kpoints"], float)
        if not self.has("kpoints") or not len(kpoints):
            return kpoints
        info = read_kpoints(self.alias["kpoints"])
        target = self._fractional_targets(info)
        if not info["line_mode"] or not target:
            return kpoints
        # EIGENVAL 一般给分数坐标；个别流程给 2π/Å 笛卡尔坐标，用 KPOINTS 反推校验
        lattice = np.asarray(self.structure["lattice"], float)
        alternative = kpoints @ lattice.T
        if _score(target, alternative) < _score(target, kpoints):
            return alternative
        return kpoints

    @property
    def distances(self):
        if "distances" not in self._cache:
            self._cache["distances"] = kpath_distances(
                self._kpoints(), self.structure["lattice"])
        return self._cache["distances"]

    def ticks_labels(self):
        """高对称点刻度与标签；KLABELS 优先于 KPOINTS。"""
        distances = self.distances
        if self.alias["klabels"]:
            ticks, labels = [], []
            with open(self.alias["klabels"], "r", errors="ignore") as handle:
                for line in handle.read().splitlines()[1:]:
                    tokens = line.split()
                    if len(tokens) == 2 and _is_float(tokens[1]):
                        ticks.append(_num(tokens[1]))
                        labels.append(tokens[0])
            if ticks:
                return ticks, labels
        if not self.has("kpoints"):
            return [], []
        info = read_kpoints(self.alias["kpoints"])
        if not info["line_mode"] or not info["points"]:
            return [], []
        return match_labels(self._fractional_targets(info), self._kpoints(), distances)

    def bands(self):
        """对应 readdata.bands 的返回值：``(arr, ban, ispin)``。

        自旋极化时 ban 为 ``(2, nbands, nkpts)``（与 vaspkit 的 BAND.dat 一致），
        否则为 ``(nbands, nkpts)``。
        """
        energies = self.energies
        ispin = self.eigenval["ispin"]
        ban = energies if ispin == 2 else energies[0]
        return self.distances, ban, ("Ispin" if ispin == 2 else "Noneispin")

    def vbm_cbm(self):
        """按占据数给出每一自旋的 (homo, lumo) 带序号（0 基）。"""
        data = self.eigenval
        result = []
        for spin in range(data["ispin"]):
            occ = data["occupations"][spin]
            filled = np.where(occ.max(axis=1) > 0.5)[0]
            empty = np.where(occ.min(axis=1) < 0.5)[0]
            homo = int(filled.max()) if len(filled) else data["nbands"] // 2 - 1
            lumo = int(empty.min()) if len(empty) else homo + 1
            if lumo <= homo:
                lumo = homo + 1
            result.append((homo, lumo))
        return result

    def mass_data(self):
        """有效质量拟合所需的数据：``[(nk, nbands+1), ...]``（每自旋一份）。"""
        energies = self.energies
        matrix = np.column_stack([self.distances] + [energies[0].T])
        if self.eigenval["ispin"] == 1:
            return [matrix], [self.vbm_cbm()[0]]
        second = np.column_stack([self.distances] + [energies[1].T])
        return [matrix, second], self.vbm_cbm()

    # -- 态密度 -----------------------------------------------------------
    def dos(self):
        """对应 readdata.dos：``(darr, dele, s_elements)``。"""
        data = self.doscar
        energies = data["energies"].copy()
        if self.shift:
            energies -= self.efermi
        ispin = 2 if data["total"].shape[1] >= 5 else 1
        total = data["total"]
        species = self.structure["species"]
        counts = self.structure["counts"]

        arrays, elements = [], []
        if ispin == 2:
            columns = [1, 2]
            elements.append(["TDOS", "up", "down"])
        else:
            columns = [1]
            elements.append(["TDOS", "Total"])
        arrays.append(total[:, columns])

        if not species:
            species = ["Ion%d" % (i + 1) for i in range(len(data["ions"]))]
            counts = [1] * len(species)

        index = 0
        for name, count in zip(species, counts):
            blocks = data["ions"][index:index + count]
            index += count
            if not blocks:
                continue
            summed = np.sum(blocks, axis=0)
            ncols = summed.shape[1]
            shells, _ = _shell_layout(ncols, ispin)
            for spin in range(ispin):
                label = name if ispin == 1 else name + ("_UP" if spin == 0 else "_DW")
                columns = []
                names = []
                for shell, orbitals in shells:
                    picked = [1 + orb * ispin + spin for orb in orbitals]
                    columns.append(summed[:, picked].sum(axis=1))
                    names.append(shell)
                columns.append(np.sum(columns, axis=0))
                names.append("tot")
                arrays.append(np.column_stack(columns))
                elements.append([label] + names)
        return [energies] * len(arrays), arrays, elements

    # -- 投影能带 ---------------------------------------------------------
    def projected(self):
        """对应 projected.bands：``(darr, dbands, composition, s_elements)``。"""
        procar = self.procar
        data = self.eigenval
        nkpts, nbands = data["nkpts"], data["nbands"]
        energies = self.energies
        ispin = max(procar["nspin"], 1) if data["ispin"] == 2 else 1
        orbitals = procar["orbitals"]

        shells = []
        for shell in ("s", "p", "d", "f"):
            picked = [i for i, name in enumerate(orbitals)
                      if name[:1].lower() == shell]
            if picked:
                shells.append((shell, picked))
        if not shells:                            # 无轨道信息时退化为单一通道
            shells = [("tot", list(range(max(len(orbitals), 1))))]

        species = self.structure["species"]
        counts = self.structure["counts"]
        owners = []
        for index, count in enumerate(counts):
            owners += [species[index] if index < len(species) else "Ion%d" % (index + 1)] * count
        if not owners:                            # POSCAR 缺元素行时按离子编号
            nions = max((len(block) for blocks in procar["blocks"].values()
                         for block in blocks), default=1)
            owners = ["Ion%d" % (i + 1) for i in range(nions)]

        weights = {}
        # EIGENVAL 去掉权重非零的 k 点后，PROCAR 的 k 点编号要重新对齐
        kept = np.asarray(data.get("kpoint_index", np.arange(nkpts)))
        dropped = int(data.get("dropped_weighted", 0))
        index_map = {int(old): new for new, old in enumerate(kept)} if dropped else {}
        if index_map:
            procar_nkpts = max((ik for (ik, _) in procar["blocks"]), default=-1) + 1
            if procar_nkpts != len(kept) + dropped:
                print("提示：PROCAR 的 k 点数（%d）与 EIGENVAL（%d）不一致，"
                      "投影数据按原编号对齐。" % (procar_nkpts, len(kept) + dropped))
                index_map = {}
        for (ik, ib), blocks in procar["blocks"].items():
            if index_map:
                new_ik = index_map.get(ik)
                if new_ik is None:          # 被过滤掉的 k 点（权重非零）直接跳过
                    continue
            else:
                new_ik = ik
            if ik < 0 or ib < 0 or ib >= nbands:
                continue
            if new_ik < 0 or new_ik >= nkpts:
                continue
            for spin, block in enumerate(blocks[:ispin]):
                for ion, row in enumerate(block):
                    owner = owners[ion] if ion < len(owners) else "Ion%d" % (ion + 1)
                    if not row.size:
                        continue
                    for shell, picked in shells:
                        value = float(np.sum(row[picked])) if picked else 0.0
                        key = (owner, shell, spin)
                        weights.setdefault(key, np.zeros((nbands, nkpts)))[ib, new_ik] += value

        order = []
        for name in species or sorted({k[0] for k in weights}):
            for shell, _ in shells:
                for spin in range(ispin):
                    if (name, shell, spin) in weights:
                        order.append((name, shell, spin))

        darr, dbands, composition, elements = [], [], [], []
        for name, shell, spin in order:
            label = name if ispin == 1 else name + ("_UP" if spin == 0 else "_DW")
            darr.append(self.distances)
            dbands.append(energies[spin])
            composition.append(weights[(name, shell, spin)][None, :, :])
            elements.append([label, shell])
        return darr, dbands, composition, elements

    # -- 导出 vaspkit 风格 .dat -------------------------------------------
    def export_dat(self, outdir="."):
        """把内存中的数组写成 vaspkit 兼容的 .dat 与 KLABELS，便于他处复用。"""
        os.makedirs(outdir, exist_ok=True)
        arr, bands, ispin = self.bands()
        nbands, nkpts = bands.shape[-2:]
        written = []
        bandfile = os.path.join(outdir, "BAND.dat")
        with open(bandfile, "w") as handle:
            if ispin == "Ispin":
                handle.write("# Spin-Up(eV) Spin-down(eV)\n")
            else:
                handle.write("# Band Structure\n")
            # 第二行必须以 NKPTS、NBANDS 两个整数结尾（readdata.bands 的约定）
            handle.write("#  NKPTS NBANDS  %d %d\n" % (nkpts, nbands))
            for ib in range(nbands):
                handle.write("# Band Index: %d\n" % (ib + 1))
                for ik in range(nkpts):
                    if ispin == "Ispin":
                        handle.write("%12.6f%12.6f%12.6f\n"
                                     % (arr[ik], bands[0, ib, ik], bands[1, ib, ik]))
                    else:
                        handle.write("%12.6f%12.6f\n" % (arr[ik], bands[ib, ik]))
        written.append(bandfile)

        ticks, labels = self.ticks_labels()
        if ticks:
            klabel = os.path.join(outdir, "KLABELS")
            with open(klabel, "w") as handle:
                handle.write("K-Path\n")
                for tick, label in zip(ticks, labels):
                    handle.write("%s %10.6f\n" % (label, tick))
            written.append(klabel)

        if self.has("doscar"):
            darr, dele, elements = self.dos()
            energy = darr[0]
            for array, names in zip(dele, elements):
                name = names[0]
                filename = ("TDOS.dat" if name == "TDOS" else "PDOS_%s.dat" % name)
                path = os.path.join(outdir, filename)
                mode = "w"
                with open(path, mode) as handle:
                    handle.write("#Energy " + " ".join(names[1:]) + "\n")
                    for i in range(len(energy)):
                        handle.write("%12.6f" % energy[i])
                        for column in range(array.shape[1]):
                            handle.write("%14.6f" % array[i, column])
                        handle.write("\n")
                if path not in written:
                    written.append(path)
        return written
