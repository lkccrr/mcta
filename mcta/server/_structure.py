"""结构文件与电荷密度解析。

mt.server 从 mcta/server/__init__.py 拆出：常见晶体/分子结构格式的识别、
VASP 电荷密度（CHGCAR/LOCPOT）读取、LAMMPS data 风格判断、原子与轨迹帧解析。
本模块被 _handlers.py（HTTP 文件服务）调用，不依赖其他 server 子模块。
"""

import re
from pathlib import Path

JSON_EXTS = {".json"}

# Materials Studio 的 .xsd 与常规 .xml 都是 XML 文本，文本浏览一律只读。
# .xsd 默认仍按 3D 结构打开：解析时显式指定 ase.io.xsd，不能交给 VASP 读取器。
XML_EXTS = {".xml", ".xsd"}

# 纯 XML 文档不识别为结构，也不参与远端渲染；.xsd 保留结构类型。
XML_DOC_EXTS = {".xml"}


STRUCT_EXTS = {
    # 晶体学 / VASP / 通用坐标 / 分子
    ".cif", ".vasp", ".poscar", ".contcar", ".xyz", ".extxyz", ".xsf",
    ".pdb", ".mol", ".mol2", ".sdf", ".res", ".gen", ".traj",
    # Materials Studio（.xsd 是 XML 文本，但默认仍按 3D 结构打开）
    ".xsd", ".xtd",
    # CASTEP
    ".cell", ".castep", ".geom",
    # SIESTA
    ".xv",
    # DMol3
    ".car", ".arc",
    # Gaussian
    ".gjf", ".com",
    # VASP 轨迹
    ".xdatcar", ".outcar",
    # GROMACS / LAMMPS / CP2K / wannier90
    ".gro", ".dump", ".dcd", ".wout",
    # 其他通用格式
    ".cjson", ".struct", ".rmc6f", ".qbox", ".mustem", ".magres",
}


STRUCT_NAMES = {"POSCAR", "CONTCAR", "SPOSCAR", "XDATCAR", "OUTCAR", "GEOMETRY.IN"}


DENSITY_NAMES = {"CHGCAR", "CHG", "LOCPOT"}


DENSITY_PREFIXES = ("CHGCAR", "CHG", "LOCPOT")  # CHGCAR-big、LOCPOT-slab 等


STRUCT_PREFIXES = ("POSCAR-",)  # POSCAR-unitcell、POSCAR-12345 等


LAMMPS_DATA_EXTS = {".data", ".lmp", ".lammps"}  # 按文件内容判断，不直接当结构


MAX_STRUCT_BYTES = 256 * 1024 * 1024


MAX_DENSITY_BYTES = 512 * 1024 * 1024


MAX_DENSITY_POINTS = 4000000


MAX_STRUCT_FRAMES = 1000  # 轨迹播放帧数上限


MAX_TRAJ_ATOMS = 5000000  # 轨迹所有帧的原子总数上限


def _is_structure(path):
    # *.json（含 CHGCAR_mcta.json / LOCPOT_mcta.json 这类视图存档与日志）
    # 一律按文本处理；不能因 CHGCAR_/LOCPOT_ 前缀误判成 VASP 密度结构。
    suffix = path.suffix.lower()
    if suffix in JSON_EXTS or suffix in XML_DOC_EXTS:
        return False
    if suffix in STRUCT_EXTS:
        return True
    if suffix in LAMMPS_DATA_EXTS:
        return _lammps_data_style(path) is not None
    name = path.name.upper()
    if name in STRUCT_NAMES or name in DENSITY_NAMES or name.startswith(STRUCT_PREFIXES):
        return True
    # 密度前缀匹配
    for prefix in DENSITY_PREFIXES:
        if name == prefix or name.startswith(prefix + "-") or name.startswith(prefix + "_"):
            return True
    return False


def _is_vasp_density(path):
    if path.suffix.lower() in JSON_EXTS or path.suffix.lower() in XML_DOC_EXTS:
        return False
    name = path.name.upper()
    if name in DENSITY_NAMES:
        return True
    for prefix in DENSITY_PREFIXES:
        if name.startswith(prefix + "-") or name.startswith(prefix + "_"):
            return True
    return False


def _read_vasp_density(path):
    """读取 VASP 标量网格；电荷密度换算为 e/Å³，势函数保持原值。

    返回 (atoms, groups)，其中 groups 为 [(label, ndarray), ...]。
    CHGCAR/CHG 自旋极化时第一组为总电荷密度、第二组为自旋密度（磁化密度）。
    LOCPOT 可能含多组势函数。
    """
    import numpy as np
    from pathlib import Path
    from ase.io.vasp import read_vasp_configuration

    path = Path(path)
    name = path.name.upper()
    is_charge = name == "CHGCAR" or name.startswith("CHGCAR-") or name.startswith("CHGCAR_") or \
                name == "CHG" or name.startswith("CHG-") or name.startswith("CHG_")
    is_locpot = name == "LOCPOT" or name.startswith("LOCPOT-") or name.startswith("LOCPOT_")
    is_charge = is_charge and not is_locpot  # CHGCAR-big > LOCPOT-slab 互不影响
    with open(path, "r") as fh:
        atoms = read_vasp_configuration(fh)
        groups = []
        seen_shape = None
        group_index = 0
        while True:
            # 跳过空行直到遇到网格尺寸行
            line = fh.readline()
            while line and not line.strip():
                line = fh.readline()
            if not line:
                break
            fields = line.split()
            if len(fields) != 3:
                raise ValueError("无效的密度网格尺寸")
            try:
                shape = tuple(int(value) for value in fields)
            except ValueError as exc:
                raise ValueError("无效的密度网格尺寸") from exc
            if any(value <= 0 for value in shape):
                raise ValueError("密度网格尺寸必须为正整数")
            if seen_shape is None:
                seen_shape = shape
            elif shape != seen_shape:
                # 不同 shape 停止读取
                break
            count = shape[0] * shape[1] * shape[2]
            if count > MAX_DENSITY_POINTS:
                raise ValueError("密度网格过大（上限 %d 点）" % MAX_DENSITY_POINTS)
            values = []
            while len(values) < count:
                line = fh.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    values.extend(float(value) for value in line.split())
                except ValueError as exc:
                    raise ValueError("密度网格包含无效数值") from exc
            if len(values) < count:
                break
            data = np.asarray(values[:count], dtype=float).reshape(shape, order="F")
            if is_charge:
                volume = abs(float(atoms.cell.volume))
                if not volume:
                    raise ValueError("晶胞体积为零，无法换算电荷密度")
                data = data / volume
            if is_charge:
                label = "总电荷密度" if group_index == 0 else "自旋密度"
            else:
                label = "势函数 %d" % (group_index + 1) if group_index > 0 else "势函数"
            groups.append((label, data))
            group_index += 1
            if group_index >= 4:
                break
    if not groups:
        raise ValueError("文件不包含有效密度网格")
    return atoms, groups


def _density_options(data, label):
    """根据有效数据生成等值面默认值及滑杆量程。

    label 可为 '总电荷密度'（非负、默认 0.02）、'自旋密度'（允许负值、默认中位数）、
    '势函数'（允许负值、默认中位数）。
    """
    import numpy as np

    finite = data[np.isfinite(data)]
    if not finite.size:
        raise ValueError("密度网格没有有限数值")
    minimum = float(finite.min())
    maximum = float(finite.max())
    if minimum == maximum:
        delta = max(abs(minimum) * 0.1, 0.001)
        minimum, maximum = minimum - delta, maximum + delta
    is_total_charge = label == "总电荷密度"
    if is_total_charge:
        lower = max(0.0, minimum)
        upper = float(np.quantile(finite, 0.99))
        value = 0.02
    else:
        lower = float(np.quantile(finite, 0.01))
        upper = float(np.quantile(finite, 0.99))
        value = float(np.median(finite))
    if upper <= lower:
        lower, upper = minimum, maximum
    value = min(max(value, lower), upper)
    step = (upper - lower) / 1000
    value = lower + round((value - lower) / step) * step
    return {"min": lower, "max": upper, "step": step, "value": value}


def _lammps_data_style(path):
    """识别 LAMMPS data 文件并返回其 Atoms 段风格；不是 data 文件返回 None。"""
    try:
        with open(path, "r", errors="replace") as fh:
            head = fh.read(65536)
    except OSError:
        return None
    if "LAMMPS data file" not in head:
        return None
    lines = head.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("Atoms"):
            continue
        if "#" in stripped:
            style = stripped.split("#", 1)[1].strip().split()[0].lower()
            if style:
                return style
        # 没有风格注释时按坐标行列数推断
        for row in lines[index + 1:]:
            fields = row.split()
            if not fields:
                continue
            count = len(fields)
            if count >= 8:
                return "bond"
            if count == 7:
                return "full"
            if count == 6:
                return "charge"
            return "atomic"
        return "atomic"
    return None


def _read_ms_xsd_fallback(path):
    """宽松解析常见 Materials Studio XSD：ASE 的严格 xsd 读取器失败时使用。

    只读取晶胞向量和原子坐标，返回 ase.Atoms；无法识别时返回 None，
    由调用方抛出 ASE 的原始错误，避免把 XSD 误当 VASP 输出。
    """
    import xml.etree.ElementTree as ET
    from ase import Atoms

    try:
        root = ET.parse(str(path)).getroot()
    except Exception:  # noqa: BLE001 - 非法 XML 交由 ASE 报错
        return None
    if root.tag.lower().rsplit('}', 1)[-1] != 'xsd':
        return None

    def local(tag):
        return tag.lower().rsplit('}', 1)[-1]

    symbols, coords, fractional = [], [], []
    cell_vectors = []
    for node in root.iter():
        tag = local(node.tag)
        if tag == 'spacegroup':
            def vector(key):
                value = node.get(key) or node.get(key.lower())
                if not value:
                    return None
                try:
                    return [float(x) for x in value.replace(' ', '').split(',')[:3]]
                except ValueError:
                    return None
            triple = [vector(key) for key in ('AVector', 'BVector', 'CVector')]
            if all(value is not None for value in triple):
                cell_vectors = triple
        elif tag in ('cella', 'cellb', 'cellc'):
            try:
                cell_vectors.append([float(node.get(key, 0)) for key in ('x', 'y', 'z')])
            except (TypeError, ValueError):
                pass
        elif tag in ('atom3d', 'atom'):
            symbol = (node.get('Components') or node.get('Name')
                      or node.get('Symbol') or node.get('Type'))
            if not symbol:
                continue
            symbol = str(symbol).strip().split()[0]
            xyz = node.get('XYZ')
            if xyz:
                try:
                    coords.append([float(x) for x in xyz.split(',')[:3]])
                    fractional.append(True)
                    symbols.append(symbol)
                except ValueError:
                    pass
            elif node.get('Fract_x') is not None:
                try:
                    coords.append([float(node.get(key, 0))
                                   for key in ('Fract_x', 'Fract_y', 'Fract_z')])
                    fractional.append(True)
                    symbols.append(symbol)
                except ValueError:
                    pass
            else:
                vector_node = next((child for child in node
                                    if local(child.tag) == 'vector3d'), None)
                if vector_node is None:
                    continue
                try:
                    coords.append([float(vector_node.get(key, 0))
                                   for key in ('x', 'y', 'z')])
                    fractional.append(False)
                    symbols.append(symbol)
                except ValueError:
                    pass
    if not symbols or len(symbols) != len(coords):
        return None
    cell = cell_vectors if len(cell_vectors) == 3 else None
    try:
        atoms = Atoms(symbols=symbols, positions=coords, cell=cell, pbc=bool(cell))
    except Exception:  # noqa: BLE001 - 数据不可用时交给 ASE 报错
        return None
    if cell and all(fractional):
        atoms.set_scaled_positions(coords)
    return atoms


def _read_atoms(path):
    """读取结构文件；LAMMPS data 文件按 Atoms 段风格显式解析。"""
    from ase.io import read as ase_read

    if Path(str(path)).suffix.lower() == ".xsd":
        # XSD 是 Materials Studio 的 XML 文本；显式选中 ase.io.xsd，
        # 避免 ASE 按扩展名误当 VASP 输出读（CONTCAR.xsd 的缩放因子报错）。
        try:
            return ase_read(str(path), index=0, format="xsd")
        except Exception as ase_exc:  # noqa: BLE001 - 兼容其他 XSD 写法
            atoms = _read_ms_xsd_fallback(path)
            if atoms is None:
                raise ase_exc
            return atoms
    style = _lammps_data_style(path)
    if style is None:
        return ase_read(str(path), index=0)
    last = None
    for candidate in (style, "atomic", "full", "charge", "molecular", "bond"):
        try:
            return ase_read(str(path), index=0, format="lammps-data", atom_style=candidate)
        except Exception as exc:  # 风格不符时换下一种再试
            last = exc
    raise last


def _vasp_coord_info(path):
    """识别 VASP POSCAR 类文件的坐标表示，供写回时保持原格式。

    ASE 读入时统一为笛卡尔(Å)，写出 POSCAR 时固定用 Direct(分数)/scale=1。
    本函数从原文件文本读出缩放因子、坐标模式、VASP4/5 风格与 Selective dynamics
    标记，写回后据此把 ASE 的输出还原成原来的坐标表示。

    非 POSCAR 类文件（XYZ/CIF/LAMMPS 等）返回 None，由 ASE 原生处理。
    """
    try:
        raw = Path(str(path)).read_bytes()[:200000]
    except (OSError, ValueError):
        return None
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) < 8:
        return None

    def _ints(line):
        try:
            out = [int(x) for x in line.split()]
            return out if out and all(v > 0 for v in out) else None
        except ValueError:
            return None

    try:
        scale = float(lines[1].split()[0])
    except (ValueError, IndexError):
        return None
    if scale <= 0:
        return None
    try:
        lattice = [[float(x) for x in lines[k].split()[:3]] for k in (2, 3, 4)]
    except (ValueError, IndexError):
        return None

    # VASP5 在 counts 前多一行元素符号；counts 为全数字行。
    counts = _ints(lines[6]) if len(lines) > 6 else None
    vasp5 = counts is not None
    if not vasp5:
        counts = _ints(lines[5]) if len(lines) > 5 else None
    if not counts:
        return None
    mode_idx = 7 if vasp5 else 6
    selective = False
    if mode_idx < len(lines) and lines[mode_idx].strip().lower().startswith("selective"):
        selective = True
        mode_idx += 1
    if mode_idx >= len(lines):
        return None
    mode = lines[mode_idx].strip().lower()
    direct = mode.startswith("d")
    if not (direct or mode.startswith("c") or mode.startswith("k")):
        return None
    elements = []
    if vasp5 and len(lines) > 5:
        candidates = lines[5].split()
        if len(candidates) == len(counts):
            elements = candidates
    return {
        "scale": scale, "lattice": lattice, "counts": counts, "elements": elements,
        "direct": direct, "vasp5": vasp5, "selective": selective,
        "mode_idx": mode_idx, "mode_line": lines[mode_idx],
        "n_atoms": sum(counts),
    }


def _restore_vasp_coord_format(text, info, symbols=None):
    """把 ASE 写出的 POSCAR 文本按 info 还原成原坐标格式。

    ASE 写 VASP 时固定 scale=1，并可按 direct 参数输出 Direct 或 Cartesian。
    这里识别实际输出模式，必要时双向换算坐标，恢复原 scale、晶格、坐标模式与
    VASP4/5 风格；同时按最终原子顺序重写元素符号/计数行，保证新增原子后的
    元素块与坐标行一一对应。
    """
    lines = text.splitlines()

    def _ints(line):
        try:
            out = [int(x) for x in line.split()]
            return out if out and all(v > 0 for v in out) else None
        except ValueError:
            return None

    out_counts = _ints(lines[6]) if len(lines) > 6 else None
    out_vasp5 = out_counts is not None
    if not out_counts:
        out_counts = _ints(lines[5]) if len(lines) > 5 else None
    if not out_counts:
        return text
    out_mode_idx = 7 if out_vasp5 else 6
    if out_mode_idx < len(lines) and lines[out_mode_idx].strip().lower().startswith("selective"):
        out_mode_idx += 1
    if out_mode_idx >= len(lines):
        return text
    mode_words = lines[out_mode_idx].strip().split()
    if not mode_words:
        return text
    out_mode = mode_words[0].lower()
    out_direct = out_mode.startswith("d")
    if not (out_direct or out_mode.startswith("c") or out_mode.startswith("k")):
        return text
    try:
        out_lattice = [[float(x) for x in lines[k].split()[:3]] for k in (2, 3, 4)]
    except (ValueError, IndexError):
        return text
    n_atoms = len(symbols) if symbols else sum(out_counts)
    orig_scale = info["scale"]
    want_direct = bool(info["direct"])

    def _num(v):
        return repr(float(v))

    def _cart_to_frac(cart, cell):
        """VASP 晶格按行存放：cart = frac @ cell，故 frac = cart @ inv(cell)。"""
        a, b, c = cell[0]
        d, e, f = cell[1]
        g, h, i = cell[2]
        det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
        if abs(det) < 1e-12:
            return None
        inv = [
            [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det],
        ]
        return [sum(cart[j] * inv[j][k] for j in range(3)) for k in range(3)]

    # 分数坐标只与晶格有关，恢复 scale 时无需换算；笛卡尔文件数值 = 实际 Å / scale。
    # 保留 selective dynamics 的 T/F 后缀。
    for idx in range(out_mode_idx + 1, out_mode_idx + 1 + n_atoms):
        if idx >= len(lines):
            break
        parts = lines[idx].split()
        if len(parts) < 3:
            continue
        try:
            vals = [float(x) for x in parts[:3]]
        except ValueError:
            continue
        converted = None
        if want_direct and not out_direct:
            # ASE 笛卡尔 Å → 原文件分数坐标。
            converted = _cart_to_frac(vals, out_lattice)
        elif not want_direct and out_direct:
            # ASE 分数 → 实际笛卡尔 Å → 原文件笛卡尔数值。
            converted = [sum(vals[k] * out_lattice[k][j] for k in range(3)) / orig_scale
                         for j in range(3)]
        elif not want_direct:
            # 同为 Cartesian：ASE 输出的是实际 Å，按原 scale 换算回文件数值。
            converted = [v / orig_scale for v in vals]
        if not converted:
            continue
        tail = ("  " + "  ".join(parts[3:])) if len(parts) > 3 else ""
        lines[idx] = "  ".join(_num(v) for v in converted) + tail

    # 缩放因子与晶格：POSCAR 中 实际晶格(Å) = scale × 文件晶格数值。
    # ASE 输出 scale=1、文件晶格即实际晶格；按原 scale 除回去即可。
    if abs(orig_scale - 1.0) > 1e-12:
        lines[1] = _num(orig_scale)
        for k in (2, 3, 4):
            lines[k] = "  ".join(_num(out_lattice[k - 2][j] / orig_scale) for j in range(3))

    # 元素符号/计数必须与坐标行顺序一致。VASP 要求同类元素聚合成单个块，
    # 因此按最终原子符号去重（保留首次出现顺序）并重排坐标行，使元素行、
    # 计数行与坐标块一一对应；否则改元素后会输出 Al B Al B… 的分离块。
    # 仅当原标签基础元素与当前符号相同时沿用原标签（保留 Fe_pv 等 POTCAR 后缀）。
    if symbols:
        labels = [str(s) for s in (info.get("elements") or [])]
        by_base = {}
        for lab in labels:
            m = re.match(r"^\s*([A-Z][a-z]?)", lab)
            by_base.setdefault(m.group(1) if m else lab.strip(), lab)
        syms = [str(sym) for sym in symbols]
        unique = []
        for sym in syms:
            if sym not in unique:
                unique.append(sym)
        # ASE 以 sort=False 写出，坐标行与 symbols 顺序一一对应；按聚合后的
        # 元素顺序重排坐标行（Selective dynamics 的 T/F 后缀随整行移动）。
        coord_start = out_mode_idx + 1
        coord_rows = lines[coord_start:coord_start + n_atoms]
        buckets = {sym: [] for sym in unique}
        for sym, row in zip(syms, coord_rows):
            buckets[sym].append(row)
        ordered = []
        for sym in unique:
            ordered.extend(buckets[sym])
        for j, row in enumerate(ordered):
            lines[coord_start + j] = row
        pairs = [(by_base.get(sym, sym), len(buckets[sym])) for sym in unique]
        species_line = "  ".join(sym for sym, _ in pairs)
        count_line = "  ".join(str(n) for _, n in pairs)
        if out_vasp5:
            lines[5] = species_line
            lines[6] = count_line
        elif info["vasp5"]:
            # 极少见：ASE 输出 VASP4，但原文件是 VASP5，补回符号行。
            lines.insert(5, species_line)
            out_mode_idx += 1

    lines[out_mode_idx] = str(info.get("mode_line") or
                              ("Direct" if want_direct else "Cartesian"))
    # VASP4 原文件没有元素符号行，删掉 ASE 自动补出的那一行。
    if not info["vasp5"] and out_vasp5:
        del lines[5]
    return "\n".join(lines) + "\n"


def _insert_atom(atoms, index, atom):
    """在 ASE Atoms 的指定位置插入一个 Atom，保留所有数组与晶格/PBC。

    ASE 的 ``Atoms`` 只有 ``append``/``extend``，没有 ``insert``；直接调用
    ``atoms.insert(...)`` 会抛 AttributeError，调用方若静默忽略异常，新增
    原子就不会写回结构文件。这里先追加到末尾，再按目标顺序重排所有数组。
    """
    atoms.append(atom)
    last = len(atoms) - 1
    idx = max(0, min(int(index), last))
    if idx == last:
        return
    order = list(range(last))
    order.insert(idx, last)
    for name, arr in list(atoms.arrays.items()):
        atoms.arrays[name] = arr[order].copy()


def _read_frames(path, limit):
    """读取轨迹的前 limit 帧；单帧结构返回只含 1 帧的列表。"""
    from ase.io import read as ase_read

    style = _lammps_data_style(path)
    if Path(str(path)).suffix.lower() == ".xsd":
        kwargs = {"format": "xsd"}
    else:
        kwargs = {"format": "lammps-data", "atom_style": style} if style else {}
    try:
        seq = ase_read(str(path), index=slice(0, limit), **kwargs)
    except Exception:
        seq = ase_read(str(path), index=":", **kwargs)[:limit]
    if not isinstance(seq, list):
        seq = [seq]
    return seq
