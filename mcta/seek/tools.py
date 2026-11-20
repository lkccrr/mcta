"""工具层：检索 → 取结构 → 写结构文件 → 汇总成导出包目录。

设计约束（与定位一致）：
  * 这里**不执行任何计算**，只在服务器上就地产出计算输入文件（不打包、不上传）；
  * 每个工具返回 dict，错误放 {"error": ...}，绝不向智能体抛异常；
  * 所有写文件操作幂等：同名文件覆盖，metadata 落 SQLite 便于回放。
"""
import atexit
import csv
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

from mcta.seek import config, state


# ---------------------------------------------------------------- MP 连接
_MPR = {"key": None, "client": None}


def _rester():
    """取复用的 MPRester（一个进程一个连接）。

    实测（MP 官方 API，20 个结构）：每个结构新建连接 19.4s，复用后 10.4s
    —— 每结构省约 0.45s，20 个结构就要白等 9 秒。
    """
    from mp_api.client import MPRester
    key = config.MP_API_KEY
    if _MPR["client"] is None or _MPR["key"] != key:
        close_rester()
        _MPR["client"] = MPRester(key)
        _MPR["key"] = key
    return _MPR["client"]


def close_rester() -> None:
    """关闭复用的连接（进程退出时自动调用）。"""
    client = _MPR["client"]
    _MPR["client"] = None
    _MPR["key"] = None
    if client is not None:
        try:
            client.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


atexit.register(close_rester)


def _format_mp_import_error(exc: ImportError) -> str:
    """把 mp_api.client 导入失败翻译成可定位的报错，而不是笼统说没装。"""
    msg = str(exc) or exc.name or type(exc).__name__
    hint = ""
    if any(k in msg for k in ("CXXABI", "GLIBC", "libstdc++")):
        lib_dir = Path(sys.prefix) / "lib"
        hint = (f"\n  提示：这是 C++ 运行库版本不匹配（常见于 scipy/numpy 的二进制扩展）。"
                f"\n  可尝试：export LD_LIBRARY_PATH={lib_dir}:$LD_LIBRARY_PATH 后重试")
    return f"mp-api 依赖导入失败：{type(exc).__name__}: {msg}{hint}"


def _check_mp_api() -> dict | None:
    """探测 mp_api.client 能否导入；返回错误 dict 或 None。"""
    try:
        import mp_api.client  # noqa: F401
    except ImportError as exc:
        if exc.name == "mp_api" or importlib.util.find_spec("mp_api") is None:
            return {"error": "未安装 mp-api：pip install mp-api"}
        return {"error": _format_mp_import_error(exc)}
    return None


# 网络抖动/限流时可重试的特征
_TRANSIENT = ("429", "500", "502", "503", "504", "timed out", "timeout",
              "connection reset", "connection aborted", "temporarily unavailable")


def _is_transient(exc: Exception) -> bool:
    s = f"{type(exc).__name__}: {exc}".lower()
    return any(t in s for t in _TRANSIENT)


def _with_retry(fn, *args, attempts: int = 3, **kwargs):
    """对瞬时错误做指数退避重试；非瞬时错误立即抛出。

    fn 每次重试都会被重新调用，所以传进来的应是"自己取连接"的闭包
    （如 lambda: _rester().xxx(...)），否则重连后仍在用已关闭的旧客户端。
    """
    delay = 1.0
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1 or not _is_transient(e):
                raise
            time.sleep(delay)
            delay *= 2
            close_rester()          # 连接可能已损坏，下次调用会重连
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------- 内部工具
# Windows 保留设备名：即使带扩展名也不能作为文件名/目录名
_RESERVED = {"con", "prn", "aux", "nul",
             *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


def _safe_name(text: str) -> str:
    """把任意输入压成单层、安全的目录名。

    首尾的点一律剥掉，因此 "." 与 ".." 不可能作为结果返回（两者会把
    导出目录指向工作根本身），剩下的字符不含路径分隔符。
    """
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip(".-")
    stem, dot, tail = name.partition(".")
    if stem.lower() in _RESERVED:      # 跨平台：Windows 上 CON/NUL 等不可用
        name = f"{stem}-x{dot}{tail}"
    return name or "batch"


def _checked_export_dir(name: str) -> Path:
    """返回 EXPORT_ROOT/<name>，并确认它确实是 EXPORT_ROOT 的直接子目录。

    这是 rmtree 之前的最后一道闸：任何能跳出工作根目录的名字都被拒绝，
    避免把工作根本身、隐藏状态目录 .mt.seek/ 或别的导出包当成待清理目标。
    """
    root = config.export_dir_for(name)
    if root.resolve().parent != config.EXPORT_ROOT.resolve():
        raise ValueError(f"非法的包裹名：{name!r}（会写到导出目录之外）")
    return root


def _to_structure(structure_dict: dict):
    from pymatgen.core import Structure
    return Structure.from_dict(structure_dict)


_DIMS = ("3D", "2D", "1D", "0D")


def _dimensionality(st) -> str:
    """结构的成键维度：'3D' / '2D' / '1D' / '0D'，无法判断时返回 '?'。

    先用 Larsen 的图方法做快路径：它只处理一个晶胞的成键图，判定为 3D 时
    可直接返回（大晶胞上比 Cheon 快 5～7 倍，实测 72 原子 160ms vs 1066ms）。
    非 3D 时再用 Cheon 的成键网络复核 —— 层状结构（含 c≈a 的菱面体堆垛）
    只有 Cheon 判得准，不会漏判 3R-MoS2 这类结构。

    小晶胞（<=24 原子）跳过 Larsen：Cheon 在几十个原子上本来就只要几毫秒，
    而 CrystalNN 首次调用要花 1 秒多做导入，反而拖慢最常见的 3 原子体系。

    注意：两种方法对离子晶体（NaCl、MgO）都会给出非标准标签
    （Cheon 返回 "intercalated ion"，Larsen 返回 0），一律退回晶格判据归一化，
    否则 manifest 里会出现 3D/2D 之外的野值。
    """
    if len(st) > 24:
        try:
            from pymatgen.analysis.dimensionality import get_dimensionality_larsen
            from pymatgen.analysis.graphs import StructureGraph
            from pymatgen.analysis.local_env import CrystalNN
            with warnings.catch_warnings():      # CrystalNN 缺氧化态会刷警告
                warnings.simplefilter("ignore")
                graph = StructureGraph.from_local_env_strategy(st, CrystalNN())
            if int(get_dimensionality_larsen(graph)) == 3:
                return "3D"
        except Exception:  # noqa: BLE001
            pass
    try:
        from pymatgen.analysis.dimensionality import get_dimensionality_cheon
        dim = str(get_dimensionality_cheon(st)).strip()
        if dim in _DIMS:
            return dim
    except Exception:  # noqa: BLE001
        pass
    try:
        a, b, c = sorted(st.lattice.abc)
        if c > 2.2 * b:      # 两个短轴 + 一个长轴 -> 层状
            return "2D"
        if b > 2.2 * a:      # 一个短轴 + 两个长轴 -> 链状
            return "1D"
        return "3D"
    except Exception:  # noqa: BLE001
        return "?"


def describe_structure(structure_dict: dict) -> dict:
    """给出结构的基本元信息，供 manifest 与报告使用。"""
    try:
        st = _to_structure(structure_dict)
        info = {
            "formula": st.composition.reduced_formula,
            "n_sites": len(st),
            "elements": sorted({str(el) for el in st.composition.elements}),
            "volume_A3": round(st.volume, 3),
            "lattice": [round(x, 4) for x in st.lattice.abc],
        }
        try:
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
            info["spacegroup"] = SpacegroupAnalyzer(st, symprec=0.1).get_space_group_symbol()
        except Exception:  # noqa: BLE001
            info["spacegroup"] = "?"
        mag = sorted(set(info["elements"]) & config.MAGNETIC_ELEMENTS)
        info["magnetic_elements"] = mag
        info["note_magnetic"] = ("含磁性元素，服务器端建议 FM/AFM/NM 多初态" if mag else "")
        # 判断维度：优先用成键网络分析（能识别 3R 堆垛这类 c≈a 的层状结构），
        # 失败时退回"某一晶格矢量显著偏长"的粗略判据
        info["dimensionality"] = _dimensionality(st)
        info["likely_2d"] = info["dimensionality"] == "2D"
        return info
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- 检索
def search_mp(chemsys: str = None, formula: str = None, max_ehull: float = 0.05,
              limit: int = 10, refresh: bool = False) -> dict:
    """在 Materials Project 检索近稳定相。

    chemsys: 化学体系，如 "Ti-C"、"Li-Fe-P-O"
    formula: 精确化学式，如 "MoS2"（与 chemsys 二选一）
    refresh: 忽略本地检索缓存，强制重新查询
    """
    try:
        if not config.MP_API_KEY:
            return {"error": "未设置环境变量 MP_API_KEY（materialsproject.org 免费注册）"}
        err = _check_mp_api()
        if err:
            return err
        query = {}
        if formula:
            query["formula"] = formula
        elif chemsys:
            query["chemsys"] = chemsys
        else:
            return {"error": "必须提供 chemsys 或 formula"}

        # mp-api 各版本字段名有差异：优先取含对称性信息的字段集，失败则退化
        field_sets = [
            ["material_id", "formula_pretty", "energy_above_hull",
             "band_gap", "nsites", "is_stable", "symmetry"],
            ["material_id", "formula_pretty", "energy_above_hull",
             "band_gap", "nsites"],
        ]
        # 同一查询 12 小时内直接复用本地结果：检索一次要 2～7 秒，
        # 而策展/补下载往往要对同一体系反复跑，没必要每次重查。
        cpath = _search_cache_path(chemsys, formula, max_ehull)
        if not refresh:
            hit = _load_search_cache(cpath)
            if hit:
                cands = hit["candidates"][:limit]
                return {"query": chemsys or formula, "n_found": len(cands),
                        "n_matched": hit.get("n_matched", len(hit["candidates"])),
                        "candidates": cands, "cached": True}

        docs, last_err = None, None

        def _search(**kw):
            return _rester().materials.summary.search(**kw)

        for fields in field_sets:
            try:
                docs = _with_retry(_search, **query,
                                   energy_above_hull=(None, max_ehull),
                                   fields=fields)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        if docs is None:
            return {"error": _query_error(last_err, chemsys or formula)}

        def _sg(d):
            sym = getattr(d, "symmetry", None)
            return getattr(sym, "symbol", "?") if sym else "?"

        n_matched = len(docs)
        ordered = sorted(docs, key=lambda d: (not getattr(d, "is_stable", False),
                                              d.energy_above_hull))
        # 缓存完整候选（上限 300），否则先用 --topks 5 缓存、再用 --topks 20 就取不全
        all_cands = [{
            "mp_id": str(d.material_id),
            "formula": d.formula_pretty,
            "e_above_hull_eV": round(float(d.energy_above_hull), 4),
            "band_gap_eV": round(float(d.band_gap), 3),
            "n_sites": d.nsites,
            "stable": bool(getattr(d, "is_stable", False)),
            "spacegroup": _sg(d),
        } for d in ordered[:300]]
        cands = all_cands[:limit]
        state.log_event("search_mp", {"chemsys": chemsys, "formula": formula,
                                       "max_ehull": max_ehull}, {"n": len(cands)})
        _save_search_cache(cpath, n_matched, all_cands)
        return {"query": chemsys or formula, "n_found": len(cands),
                "n_matched": n_matched, "candidates": cands}
    except Exception as e:  # noqa: BLE001
        return {"error": _query_error(e, chemsys or formula)}


_SEARCH_TTL = 12 * 3600        # 检索结果缓存有效期（MP 数据库按月更新，12h 足够）


def _search_cache_path(chemsys, formula, max_ehull) -> Path:
    key = f"{chemsys or ''}_{formula or ''}_{max_ehull}"
    return config.STRUCT_CACHE / "search" / f"{_safe_name(key)}.json"


def _load_search_cache(path: Path):
    try:
        if not path.is_file():
            return None
        age = time.time() - path.stat().st_mtime
        if age > _SEARCH_TTL:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_search_cache(path: Path, n_matched: int, cands: list) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"n_matched": n_matched, "candidates": cands},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _query_error(err, query: str) -> str:
    """把 mp-api 的原始异常翻译成用户能据此动手的提示。"""
    if err is None:
        return f"检索「{query}」失败：未知错误"
    msg = str(err)
    low = msg.lower()
    if "does not support the request" in msg or "no valid" in low:
        return (f"检索「{query}」没有结果：Materials Project 不认识这个查询。"
                f"\n  化学式用标准写法（MoS2、LiFePO4），化学体系用连字符（Li-Fe-P-O）；"
                f"确认元素符号拼写正确。")
    if "401" in msg or "no api key" in low or "invalid api key" in low:
        return ("MP_API_KEY 无效或已过期。到 materialsproject.org 重新获取后，"
                "写入 ~/.config/mcta/config（MP_API_KEY=你的key）或导出环境变量。")
    if "429" in msg or "rate limit" in low:
        return "请求过于频繁（429）：等几十秒再跑，或把 --topks 调小、少跑几个体系。"
    return f"{type(err).__name__}: {msg}"


def get_structure(mp_id: str) -> dict:
    """按 mp_id 取结构，落本地缓存；返回 structure_dict 与元信息。"""
    mp_id = _safe_name(mp_id)
    cache = config.STRUCT_CACHE / f"{mp_id}.json"
    try:
        if cache.exists():
            d = json.loads(cache.read_text(encoding="utf-8"))
            return {"mp_id": mp_id, "structure_dict": d["structure"],
                    "meta": d.get("meta", {}), "cached": True}
        if not config.MP_API_KEY:
            return {"error": "未设置 MP_API_KEY"}
        try:
            st = _with_retry(lambda mid: _rester().get_structure_by_material_id(mid),
                             mp_id)
        except ImportError as exc:
            err = _check_mp_api()
            return err or {"error": _format_mp_import_error(exc)}
        except Exception as e:  # noqa: BLE001
            if "404" in str(e):
                return {"error": f"Materials Project 上没有 {mp_id}（检查 ID 拼写）"}
            return {"error": f"下载 {mp_id} 失败：{type(e).__name__}: {e}"}
        if st is None:
            return {"error": f"Materials Project 上没有 {mp_id}："
                             f"检查 ID 拼写，或在 next-gen.materialsproject.org 确认该结构是否公开"}
        config.ensure_dirs()
        info = describe_structure(st.as_dict())
        cache.write_text(json.dumps({"structure": st.as_dict(), "meta": info},
                                    ensure_ascii=False), encoding="utf-8")
        state.log_event("get_structure", {"mp_id": mp_id}, {"cached": False})
        return {"mp_id": mp_id, "structure_dict": st.as_dict(),
                "meta": info, "cached": False}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- 写结构文件
JOB_TEMPLATES = {
    "INCAR": """# mt.seek 模板 — 按体系自行调整
SYSTEM = __SYSTEM__
ENCUT  = 520
PREC   = Accurate
EDIFF  = 1E-5
EDIFFG = -0.02
ISMEAR = 0
SIGMA  = 0.05
IBRION = 2
NSW    = 100
ISIF   = 3
LREAL  = Auto
LWAVE  = .FALSE.
LCHARG = .FALSE.
# 磁性体系：取消下面两行注释并按实际设置
# ISPIN  = 2
# MAGMOM = __MAGMOM__
""",
    "KPOINTS": """K-Points (auto)
0
Gamma
__KX__ __KY__ __KZ__
0 0 0
""",
    "submit.slurm": """#!/bin/bash
#SBATCH -J __NAME__
#SBATCH -p __PARTITION__
#SBATCH -N 1
#SBATCH -n 32
#SBATCH -o slurm-%j.out
#SBATCH -e slurm-%j.err
#SBATCH -t 24:00:00

module load vasp/6.4.2          # 按集群实际模块名修改
cd $SLURM_SUBMIT_DIR
mpirun -np 32 vasp_std > vasp.out
""",
}

# ---------------------------------------------------------------- 文本对齐
def _disp_width(text: str) -> int:
    """终端显示宽度：中日韩全角字符占 2 列。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in str(text))


def pad(text, width: int) -> str:
    """按显示宽度左对齐补空格（str.ljust 对中文会错位）。"""
    text = str(text)
    return text + " " * max(0, width - _disp_width(text))


def _make_potcar(out: Path) -> str:
    """在 POSCAR 同目录调用 mt.sh po 拼接 POTCAR。

    先检查赝势目录是否给定且存在（与 po.sh 的查找优先级一致），再在 out
    目录里执行 `mt.sh po`；po.sh 会按 POSCAR 顺序拼好 POTCAR 并写在同目录。
    返回空串表示成功，否则返回给用户看的跳过/失败说明（不阻断导出）。
    """
    if config.get_pseudopotential_path() is None:
        return ("未配置赝势目录或目录不存在，跳过 POTCAR"
                "（设置 PBE_PATH / LDA_PATH / GGA_PATH 后自动生成）")
    if not (out / "POSCAR").is_file():
        return "本次未生成 POSCAR，跳过 POTCAR"
    try:
        from mcta.sh.cli import main as sh_main
        cwd = Path.cwd()
        os.chdir(out)
        try:
            rc = sh_main(["po"])
        finally:
            os.chdir(cwd)
    except Exception as e:  # noqa: BLE001
        return f"调用 mt.sh po 失败：{type(e).__name__}: {e}"
    if rc != 0:
        return f"mt.sh po 退出码 {rc}，POTCAR 可能不完整"
    return ""


def write_structure_files(mp_id: str, structure_dict: dict = None,
                          formats=None, out_dir: str = None,
                          with_job_template: bool = False) -> dict:
    """把一个结构写成 CIF / POSCAR / JSON 等文件，返回文件清单。

    formats 默认 ["cif", "poscar", "json"]；写出的文件名统一用小写，
    便于服务器端脚本按通配符批量读取。
    """
    try:
        if structure_dict is None:
            got = get_structure(mp_id)
            if "error" in got:
                return got
            structure_dict = got["structure_dict"]
        mp_id = _safe_name(mp_id)
        formats = [f.lower() for f in (formats or config.DEFAULT_FORMATS)]
        unknown = [f for f in formats if f not in config.STRUCT_FORMATS]
        if unknown:
            return {"error": f"无效的结构格式：{', '.join(unknown)}"}
        st = _to_structure(structure_dict)
        info = describe_structure(structure_dict)
        if "error" in info:
            return info

        out = Path(out_dir) if out_dir else (config.STRUCT_CACHE / "files" / mp_id)
        out.mkdir(parents=True, exist_ok=True)

        # 缓存目录会跨命令复用；删除本次未请求的旧产物，避免它们被打进新包。
        output_names = {"cif": "structure.cif", "poscar": "POSCAR",
                        "json": "structure.json", "xyz": "structure.xyz"}
        requested = set(formats)
        if "vasp" in requested:
            requested.add("poscar")
        for fmt, fname in output_names.items():
            stale = out / fname
            if fmt not in requested and stale.exists():
                stale.unlink()
        # 作业文件（INCAR/KPOINTS/submit.slurm/POTCAR）直接写在编号目录根。
        # POTCAR 无论是否重生成都先清掉旧的：赝势不可用时不能把上次的留在包里。
        job_names = list(JOB_TEMPLATES) + ["POTCAR"]
        if with_job_template:
            stale = out / "POTCAR"
            if stale.exists():
                stale.unlink()
        else:
            for name in job_names:
                stale = out / name
                if stale.exists():
                    stale.unlink()
            shutil.rmtree(out / "job_template", ignore_errors=True)

        written = {}
        if "cif" in formats:
            from pymatgen.io.cif import CifWriter
            p = out / "structure.cif"
            CifWriter(st).write_file(str(p))
            written["cif"] = str(p)
        if "poscar" in formats or "vasp" in formats:
            p = out / "POSCAR"
            p.write_text(st.to(fmt="poscar"), encoding="utf-8")
            written["poscar"] = str(p)
        if "json" in formats:
            p = out / "structure.json"
            p.write_text(json.dumps(st.as_dict(), ensure_ascii=False, indent=1),
                         encoding="utf-8")
            written["json"] = str(p)
        if "xyz" in formats:
            p = out / "structure.xyz"
            lines = [str(len(st)), info["formula"]]
            for site in st:
                c = site.coords
                lines.append(f"{site.specie.symbol} {c[0]:.6f} {c[1]:.6f} {c[2]:.6f}")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            written["xyz"] = str(p)

        potcar_status = ""
        if with_job_template:
            # 作业文件直接落进编号目录（不再单独建 job_template/ 子目录），
            # 便于在服务器上 cd 到编号目录即可提交。
            d = {"SYSTEM": f"{mp_id} {info['formula']}",
                 "NAME": f"{mp_id}", "PARTITION": "normal",
                 "MAGMOM": " ".join(["5.0"] * info["n_sites"]),
                 "KX": 8, "KY": 8, "KZ": 8}
            for fname, text in JOB_TEMPLATES.items():
                for k, v in d.items():
                    text = text.replace(f"__{k}__", str(v))
                (out / fname).write_text(text, encoding="utf-8")
                written[fname] = str(out / fname)
            # POTCAR：赝势目录可用时调 mt.sh po，在 POSCAR 同目录拼接生成。
            potcar_status = _make_potcar(out)
            potcar = out / "POTCAR"
            if potcar.is_file() and potcar.stat().st_size > 0:
                written["POTCAR"] = str(potcar)
                if not potcar_status:
                    potcar_status = "ok"

        state.register_structure(mp_id, info.get("formula", "?"), str(out),
                                 "exported", {"files": list(written), **info})
        result = {"mp_id": mp_id, "export_dir": str(out), "files": written,
                  "meta": info}
        if with_job_template:
            result["potcar"] = potcar_status or "未生成"
        return result
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- 打包
MANIFEST_FIELDS = ["mp_id", "formula", "n_sites", "spacegroup", "dimensionality",
                   "volume_A3", "a_A", "b_A", "c_A", "likely_2d", "magnetic_elements",
                   "e_above_hull_eV", "band_gap_eV", "export_dir"]


def make_bundle(name: str, entries: list, source: str = "Materials Project",
                extra_files: dict = None) -> dict:
    """把若干结构目录汇总成一个导出包目录。

    直接在服务器上运行，不再打包、不再 scp：产物只有 WORKROOT/<name>/，
    结构直接放在包根的 <编号>/ 下，另含 README.md / manifest.csv / mt.seek.db。

    entries: [{"mp_id":..., "export_dir":..., "meta": {...}, "e_above_hull_eV":..., ...}]
    source: 清单 README 里写的结构来源（SQS 模式下换成自定义晶胞的说明）
    extra_files: {文件名: 文本}，写在包根目录（如 sqs.json / sqs_summary.csv）
    """
    try:
        if not entries:
            return {"error": "没有可打包的结构"}
        config.ensure_dirs()
        name = _safe_name(name)
        try:
            root = _checked_export_dir(name)
        except ValueError as e:
            return {"error": str(e)}
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)

        rows = []
        for e in entries:
            mp_id = _safe_name(e["mp_id"])
            src = Path(e["export_dir"])
            dst = root / mp_id
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            meta = e.get("meta", {}) or {}
            lat = meta.get("lattice", ["", "", ""])
            rows.append({
                "mp_id": mp_id,
                "formula": meta.get("formula", "?"),
                "n_sites": meta.get("n_sites", ""),
                "spacegroup": meta.get("spacegroup", ""),
                "dimensionality": meta.get("dimensionality", ""),
                "volume_A3": meta.get("volume_A3", ""),
                "a_A": lat[0] if len(lat) > 0 else "",
                "b_A": lat[1] if len(lat) > 1 else "",
                "c_A": lat[2] if len(lat) > 2 else "",
                "likely_2d": meta.get("likely_2d", ""),
                "magnetic_elements": "".join(meta.get("magnetic_elements", [])),
                "e_above_hull_eV": e.get("e_above_hull_eV", ""),
                "band_gap_eV": e.get("band_gap_eV", ""),
                "export_dir": mp_id,
            })

        with (root / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
            # lineterminator="\n"：Windows 上默认写 \r\n，服务器端 awk/csv
            # 会把 \r 读进最后一个字段（export_dir），导致路径拼错
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)

        (root / "README.md").write_text(_bundle_readme(name, rows, source),
                                        encoding="utf-8")
        for fname, text in (extra_files or {}).items():
            (root / fname).write_text(text, encoding="utf-8")
        # 先记本次汇总事件，再复制库：包内 db 也含 make_bundle 这条，自洽可追溯。
        # 真库仍在 .mt.seek/，包内只是随包快照。
        state.log_event("make_bundle", {"name": name, "n": len(rows)},
                        {"dir": str(root)})
        _copy_db_into(root)
        return {"bundle_dir": str(root), "n_structures": len(rows),
                "manifest": str(root / "manifest.csv"),
                "db": str(root / "mt.seek.db")}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def _copy_db_into(root: Path) -> None:
    """把 SQLite 状态库复制一份到导出包根（文件名为 mt.seek.db）。

    仅当真库存在时才复制；复制前先 WAL checkpoint 保证数据已落盘。
    """
    import sqlite3
    src = config.DB_PATH
    if not src.exists():
        return
    try:
        con = sqlite3.connect(str(src))
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            con.close()
    except sqlite3.Error:
        pass
    shutil.copy2(src, root / "mt.seek.db")


def _bundle_readme(name: str, rows: list, source: str = "Materials Project") -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_sqs = source != "Materials Project"
    lines = [
        f"# {name}",
        "",
        f"生成时间：{ts}　由 mt.seek 导出（直接在服务器上运行），结构来源 {source}。",
        "",
        f"结构数量：**{len(rows)}**",
    ]
    if is_sqs:
        lines += ["", "> SQS 是准随机超胞：用有限大小超胞复现无限随机固溶体的关联函数。",
                  "> 每个结构的 objective 见 `sqs_summary.csv`（越小越接近理想随机），",
                  "> 完整参数（晶胞、子晶格、扩胞倍数、迭代数）见 `sqs.json`。"]
    lines += [
        "",
        "## 目录结构",
        "",
        "```",
        f"{name}/",
        "├── README.md          # 本说明",
        "├── manifest.csv       # 结构清单与元信息",
        "├── mt.seek.db         # 本次检索/导出的事件与结构状态（SQLite）",
        "├── <编号>/            # 每个结构一个目录（编号即 mp_id 或 SQS 编号）",
        "│   ├── *.cif / POSCAR / *.json    # 该 id 的结构文件",
        "│   └── INCAR / KPOINTS / 提交脚本 / POTCAR   # 仅 --job-template 时生成；POTCAR 需赝势目录",
        "└── ...",
        "```",
        "",
        "本包已在服务器上就地生成，无需上传、无需解压。按 `manifest.csv` 的",
        "`export_dir`（相对本包目录）进入对应编号目录，即为该结构的全部文件；",
        "其中 POSCAR 可直接作为计算输入，作业模板按实际体系修改后使用。",
        "",
        "## 结构清单",
        "",
        "| 编号 | 化学式 | 原子数 | 空间群 | 磁性元素 | ehull (eV) | 带隙 (eV) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['mp_id']} | {r['formula']} | {r['n_sites']} | {r['spacegroup']} | "
            f"{r['magnetic_elements'] or '-'} | {r['e_above_hull_eV']} | {r['band_gap_eV']} |")
    tail = ("", "> SQS 结构的无序度会随弛豫退化：建议固定体积（ISIF=2）后弛豫，"
                "再用 SRO 复核。", "")
    if not is_sqs:
        tail = ("", "> 结构版权与引用遵循 Materials Project 使用条款；发表时请引用对应 mp-id。", "")
    lines += list(tail)
    return "\n".join(lines)


def list_exports() -> dict:
    """列出已有的导出包，便于人工确认。"""
    items = []
    for p in sorted(config.EXPORT_ROOT.iterdir()):
        if p.is_dir() and (p / "manifest.csv").exists():
            items.append({"name": p.name, "dir": str(p)})
    return {"exports": items, "n": len(items)}
