"""自定义晶胞 → 扩胞 → 准随机结构（SQS）。

引擎是 sqsgenerator（C++ 核心 + Python 接口），它不属于 pymatgen 也不算本包
的硬依赖：Windows 目前没有 Python 3.13 的轮子，建议在 WSL/服务器上
`pip install sqsgenerator`（或 `pip install "mcta[sqs]"`）。

pymatgen 里的 run_mcsqs / SQSTransformation 只是调度器，真正干活的是 ATAT 的
mcsqs 可执行文件或 icet 包，两者都得另外装，因此这里直接对接 sqsgenerator。

本模块只做四件事：
  1. 读自定义晶胞（POSCAR / CIF / JSON 等 pymatgen 能读的格式）；
  2. 决定哪些位点参与随机化（子晶格）以及各元素占几个；
  3. 组装 sqsgenerator 配置、跑优化、把结果转回 pymatgen 结构；
  4. 落盘并打包（复用 tools.write_structure_files / make_bundle）。
"""
import json
import re
import shutil
from pathlib import Path

from mcta.seeker import config, state
from mcta.seeker.tools import (_safe_name, make_bundle, pad,
                                      write_structure_files)

# 迭代次数低于这个值基本搜不到像样的 SQS，直接拦掉比让用户等半天更好
MIN_ITERATIONS = 1000
DEFAULT_ITERATIONS = 100000
MAX_ITERATIONS = 50_000_000


# ---------------------------------------------------------------- 引擎探测
def engine_info() -> dict:
    """返回 sqsgenerator 是否可用及版本号。"""
    try:
        import sqsgenerator
    except ImportError:
        return {"available": False, "error": "未安装 sqsgenerator"}
    except Exception as e:  # noqa: BLE001  某些平台会因缺少运行库导入失败
        return {"available": False, "error": f"导入 sqsgenerator 失败：{e}"}
    ver = getattr(sqsgenerator, "__version__", "")
    if isinstance(ver, tuple):
        ver = ".".join(str(x) for x in ver)
    return {"available": True, "version": str(ver)}


def engine_missing_hint() -> str:
    """装不上时给一条可操作的路，而不是一句 ImportError。"""
    return (
        "未安装 sqsgenerator（mt.sqs 扩胞需要它）。\n"
        "  Linux / WSL：pip install sqsgenerator（或 pip install \"mcta[sqs]\"）\n"
        "  Windows：官方暂无 Python 3.13 的轮子，请在 WSL 的 Ubuntu 里装好后运行，\n"
        "           例如 ssh 进 WSL 后执行 mt.sqs -c cell.vasp -a \"Cu:0.5,Au:0.5\"。\n"
        "  自检：python -c \"import sqsgenerator\""
    )


# ---------------------------------------------------------------- 输入解析
def load_cell(path: str) -> dict:
    """读自定义晶胞文件，返回 pymatgen 的 Structure。"""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"error": f"找不到晶胞文件：{p}"}
    try:
        from pymatgen.core import Structure
        st = Structure.from_file(str(p))
    except Exception as e:  # noqa: BLE001
        return {"error": f"读取 {p.name} 失败：{type(e).__name__}: {e}\n"
                         f"  支持 POSCAR/CONTCAR、CIF、JSON 等 pymatgen 能识别的格式"}
    if not len(st):
        return {"error": f"{p.name} 里没有原子"}
    return {"structure": st, "path": str(p), "name": p.stem}


def parse_supercell(spec) -> dict:
    """'3,3,3' / '3' / '2x2x1' → [3, 3, 3]。"""
    if spec is None:
        return {"dims": [3, 3, 3]}
    if isinstance(spec, (list, tuple)):
        parts = list(spec)
    else:
        parts = [x for x in re.split(r"[,\sxX*]+", str(spec).strip()) if x]
    try:
        dims = [int(x) for x in parts]
    except ValueError:
        return {"error": f"扩胞倍数写法不对：{spec}；应形如 3,3,3"}
    if len(dims) == 1:
        dims *= 3
    if len(dims) != 3:
        return {"error": f"扩胞倍数要 3 个数：{spec}；应形如 3,3,3"}
    if any(d < 1 for d in dims):
        return {"error": f"扩胞倍数必须 ≥1：{spec}"}
    if dims[0] * dims[1] * dims[2] > 20000:
        return {"error": f"扩胞后位点过多（{dims[0]*dims[1]*dims[2]} 倍），"
                         f"SQS 搜索会很慢，请减小倍数"}
    return {"dims": dims}


def _site_counts(st) -> dict:
    out = {}
    for site in st:
        sym = site.specie.symbol if hasattr(site, "specie") else str(site.specie)
        out[sym] = out.get(sym, 0) + 1
    return out


def pick_host(st, host: str = None) -> dict:
    """决定随机化哪个元素的位点。

    晶胞里只有一种元素时自动选它；有多种元素时必须显式给 --sqs-host，
    否则很难猜对（把 O 位随机化这种事一旦发生，算出来的东西没意义）。
    """
    counts = _site_counts(st)
    if host:
        want = str(host).strip()
        for sym in counts:
            if sym.lower() == want.lower():
                return {"host": sym, "n_host_cell": counts[sym], "all_species": counts}
        return {"error": f"晶胞里没有元素 {want}；可选：{', '.join(sorted(counts))}"}
    if len(counts) == 1:
        sym = next(iter(counts))
        return {"host": sym, "n_host_cell": counts[sym], "all_species": counts}
    listing = "  ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
    return {"error": f"晶胞里有多种元素（{listing}），请用 --sqs-host 指定要随机化的位点。\n"
                     f"  例如：--sqs-host {sorted(counts)[0]} "
                     f"-a \"{sorted(counts)[0]}:0.5,X:0.5\""}


def parse_alloy(spec: str) -> dict:
    """解析合金成分写法：'Cu:0.5,Au:0.5' / 'Cu,Au' / 'Cu:27,Au:27'。

    值 ≤1 视为分数，>1 视为原子个数；不写值即等分。
    """
    if not spec:
        return {"error": "缺少 --sqs-alloy：请给出该位点上的合金成分，"
                         "如 -a \"Cu:0.5,Au:0.5\""}
    entries = []
    for chunk in re.split(r"[,;]+", str(spec).strip()):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.fullmatch(r"([A-Za-z]{1,3})\s*[:=]?\s*([0-9]*\.?[0-9]*)", chunk)
        if not m:
            return {"error": f"成分写法不对：{chunk}；应形如 Cu:0.5 或 Cu:27"}
        sym = m.group(1)
        sym = sym[0].upper() + sym[1:].lower()
        val = m.group(2)
        entries.append((sym, None if val == "" else float(val)))
    if not entries:
        return {"error": f"成分写法不对：{spec}"}
    try:
        from pymatgen.core import Element
        for sym, _ in entries:
            Element(sym)          # 拼错的元素符号在这里就拦下
    except Exception:  # noqa: BLE001
        return {"error": f"成分里有无法识别的元素：{spec}"}
    syms = [s for s, _ in entries]
    if len(set(syms)) != len(syms):
        return {"error": f"成分里元素重复：{spec}"}
    if len(syms) < 2:
        return {"error": f"SQS 至少需要两种元素（当前只有 {syms[0]}）"}
    return {"entries": entries, "species": syms}


def _largest_remainder(fractions, total: int) -> list:
    """按分数分配整数个数，用最大余数法保证和恰好等于 total。"""
    raw = [f * total for f in fractions]
    base = [int(x) for x in raw]
    rest = total - sum(base)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in range(rest):
        base[order[i % len(order)]] += 1
    return base


def composition_counts(entries: list, n_sites: int) -> dict:
    """把 parse_alloy 的结果折算成该子晶格上的原子个数。"""
    vals = [v for _, v in entries]
    if all(v is None for v in vals):
        fracs = [1 / len(entries)] * len(entries)
    elif all(v is not None for v in vals):
        if all(float(v).is_integer() and v >= 1 for v in vals) and sum(vals) != 1:
            # 明显是按个数写的：直接按比例缩放到 n_sites
            s = sum(vals)
            fracs = [v / s for v in vals]
        else:
            s = sum(vals)
            fracs = [v / s for v in vals]     # 分数（不必精确归一）
    else:
        return {"error": "成分里有的写了数值、有的没写；请统一，如 Cu:0.5,Au:0.5"}
    if any(f <= 0 for f in fracs):
        return {"error": "成分比例必须为正"}
    counts = _largest_remainder(fracs, n_sites)
    out = {sym: c for (sym, _), c in zip(entries, counts)}
    zero = [s for s, c in out.items() if c == 0]
    if zero:
        return {"error": f"{'/'.join(zero)} 在这个超胞里分到 0 个原子："
                         f"位点数 {n_sites} 太少，请加大 --sqs-supercell 或调整比例"}
    return {"counts": out, "fractions": dict(zip((s for s, _ in entries), fracs))}


def plan(cell: dict, host: str, alloy: str, supercell, iterations: int,
         number: int, seed=None) -> dict:
    """把命令行输入整理成 sqsgenerator 的配置，并给出人类可读的摘要。"""
    st = cell["structure"]
    hp = pick_host(st, host)
    if "error" in hp:
        return hp
    al = parse_alloy(alloy)
    if "error" in al:
        return al
    dims = parse_supercell(supercell)
    if "error" in dims:
        return dims

    dims = dims["dims"]
    n_cell = len(st)
    mult = dims[0] * dims[1] * dims[2]
    n_super = n_cell * mult
    n_host = hp["n_host_cell"] * mult
    comp = composition_counts(al["entries"], n_host)
    if "error" in comp:
        return comp

    all_host = n_host == n_super
    cfg = {
        "structure": {
            "lattice": [[float(x) for x in row] for row in st.lattice.matrix],
            "coords": [[float(c) for c in site.frac_coords] for site in st],
            "species": [site.specie.symbol for site in st],
            "supercell": dims,
        },
        "iterations": int(iterations),
        "max_results_per_objective": max(1, int(number)),
    }
    if all_host:
        # 整个晶胞都是随机化对象：interact 模式，给出全局个数
        cfg["composition"] = dict(comp["counts"])
        cfg["sublattice_mode"] = "interact"
    else:
        # 只有部分位点参与：split 模式，按元素标签指定子晶格
        cfg["sublattice_mode"] = "split"
        cfg["composition"] = [{**{"sites": hp["host"]}, **comp["counts"]}]
    if seed is not None:
        # 带种子的运行要求单线程，否则每次结果都不一样
        cfg["seed"] = [int(seed)]
        cfg["thread_config"] = [1]

    return {
        "config": cfg,
        "host": hp["host"],
        "n_host_cell": hp["n_host_cell"],
        "all_species": hp["all_species"],
        "dims": dims,
        "n_cell": n_cell,
        "n_super": n_super,
        "n_host": n_host,
        "counts": comp["counts"],
        "fractions": comp["fractions"],
        "all_host": all_host,
        "formula_in": st.composition.reduced_formula,
        "iterations": int(iterations),
    }


# ---------------------------------------------------------------- 优化
def _parse_error_text(err) -> str:
    """sqsgenerator 的 ParseError 只带 msg/key，拼成一句人话。"""
    msg = getattr(err, "msg", "") or str(err)
    key = getattr(err, "key", "")
    return f"{key}: {msg}" if key else msg


def run_optimization(cfg: dict) -> dict:
    """调用 sqsgenerator，返回按目标函数排序的 pymatgen 结构列表。"""
    try:
        import sqsgenerator as sg
        from sqsgenerator.core import ParseError
    except ImportError:
        return {"error": engine_missing_hint()}
    try:
        parsed = sg.parse_config(cfg)
    except Exception as e:  # noqa: BLE001
        return {"error": f"SQS 配置无效：{type(e).__name__}: {e}"}
    if isinstance(parsed, ParseError):
        return {"error": "SQS 配置被 sqsgenerator 拒绝：" + _parse_error_text(parsed)}
    try:
        pack = sg.optimize(parsed)
    except Exception as e:  # noqa: BLE001
        return {"error": f"SQS 优化失败：{type(e).__name__}: {e}"}

    rows = []
    try:
        for _objective, results in pack:
            for item in results:
                st = item.structure()
                rows.append((float(item.objective), st))
    except Exception as e:  # noqa: BLE001
        return {"error": f"读取 SQS 结果失败：{type(e).__name__}: {e}"}
    if not rows:
        return {"error": "sqsgenerator 没有返回任何结果：请加大 --sqs-iterations 后重试"}
    rows.sort(key=lambda t: t[0])

    out, seen = [], set()
    for obj, st in rows:
        try:
            ps = sg.to_pymatgen(st)
        except Exception:  # noqa: BLE001  老版本没有适配器时手工转
            from pymatgen.core import Element, Structure
            ps = Structure(st.lattice, [Element.from_Z(int(z)) for z in st.species],
                           st.frac_coords)
        # 去重键必须带上元素：同一批候选常常是"同坐标、不同占位"的不同解，
        # 只用坐标去重会把它们当成同一个结构丢掉
        key = tuple((site.specie.symbol,
                     *(round(float(c), 4) for c in site.frac_coords))
                    for site in ps)
        if key in seen:
            continue
        seen.add(key)
        out.append({"structure": ps, "objective": obj})
    return {"candidates": out}


# ---------------------------------------------------------------- 导出
def _tag(i: int) -> str:
    return f"sqs-{i:02d}"


def export(name: str, candidates: list, info: dict, formats=None,
           with_job_template: bool = False) -> dict:
    """把 SQS 候选逐个落盘，打成包裹，并写入 SQS 元信息。"""
    entries, failed = [], []
    for i, cand in enumerate(candidates, 1):
        tag = _tag(i)
        # 每个候选固定用 cache/files/<tag> 落盘；先把旧内容清掉，
        # 否则上一次用 -F poscar 跑出来的 POSCAR 会被这次的 -F cif 一起打包进去
        out_dir = config.STRUCT_CACHE / "files" / tag
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        # 按元素排一下：SQS 的位点顺序是随机的，直接写 POSCAR 会出现
        # 几十个单原子元素块（VASP 能读但很难看）
        st = cand["structure"].get_sorted_structure()
        w = write_structure_files(tag, st.as_dict(), formats=formats,
                                  out_dir=str(out_dir),
                                  with_job_template=with_job_template)
        if "error" in w:
            failed.append({"tag": tag, "error": w["error"]})
            continue
        meta = w["meta"]
        meta["sqs_objective"] = round(cand["objective"], 6)
        entries.append({"mp_id": tag, "export_dir": w["export_dir"], "meta": meta,
                        "e_above_hull_eV": "", "band_gap_eV": ""})
    if not entries:
        return {"error": "SQS 结构全部写文件失败", "failed": failed}

    extra = {"sqs.json": json.dumps(_summary_json(name, info, candidates),
                                    ensure_ascii=False, indent=1),
             "sqs_summary.csv": _summary_csv(info, candidates)}
    b = make_bundle(name, entries, source="自定义晶胞 + sqsgenerator（SQS）",
                    extra_files=extra)
    if "error" in b:
        return {"error": b["error"], "failed": failed}
    return {"bundle": b, "n_ok": len(entries), "failed": failed,
            "sqs_json": str(Path(b["bundle_dir"]) / "sqs.json")}


def _summary_json(name: str, info: dict, candidates: list) -> dict:
    return {
        "name": name,
        "engine": "sqsgenerator",
        "engine_version": engine_info().get("version", ""),
        "cell": {"file": info.get("path", ""), "formula": info["formula_in"],
                 "n_sites": info["n_cell"]},
        "sublattice": {"host": info["host"], "n_sites_cell": info["n_host_cell"],
                       "mode": "interact" if info["all_host"] else "split"},
        "supercell": info["dims"],
        "n_sites_total": info["n_super"],
        "composition_target": info["counts"],
        "fractions": info["fractions"],
        "iterations": info["iterations"],
        "seed": info.get("seed"),
        "candidates": [
            {"index": _tag(i), "objective": round(c["objective"], 6),
             "formula": c["structure"].composition.reduced_formula,
             "n_sites": len(c["structure"])}
            for i, c in enumerate(candidates, 1)
        ],
        "note": "objective 是关联函数偏差的加权平方和，越小越接近理想随机固溶体；"
                "弛豫后建议用 SRO 复核无序度。",
    }


def _summary_csv(info: dict, candidates: list) -> str:
    lines = ["index,objective,formula,n_sites,file"]
    for i, c in enumerate(candidates, 1):
        tag = _tag(i)
        lines.append(f"{tag},{c['objective']:.6f},"
                     f"{c['structure'].composition.reduced_formula},"
                     f"{len(c['structure'])},structures/{tag}/POSCAR")
    return "\n".join(lines) + "\n"


def format_report(res: dict, info: dict) -> str:
    """给用户看的 SQS 导出报告。"""
    if "error" in res:
        return f"失败：{res['error']}"
    b = res.get("bundle") or {}
    comp = " ".join(f"{k}{v}" for k, v in info["counts"].items())
    lines = ["== MicroCrystalSeeker SQS 报告 ==",
             f"晶胞：      {info['formula_in']}（{info['n_cell']} 原子，"
             f"{Path(info.get('path', '')).name}）",
             f"随机化位点：{info['host']} 位（原胞 {info['n_host_cell']} 个）"
             f"  模式={'interact' if info['all_host'] else 'split'}",
             f"扩胞：      {info['dims'][0]}×{info['dims'][1]}×{info['dims'][2]}"
             f" → {info['n_super']} 原子（其中随机化 {info['n_host']} 个）",
             f"目标成分：  {comp}",
             f"迭代次数：  {info['iterations']}"
             + (f"  种子={info['seed']}" if info.get("seed") is not None else ""),
             "",
             pad("编号", 10) + pad("objective", 12) + pad("化学式", 16) + "原子数"]
    for i, cand in enumerate(res["candidates"], 1):
        st = cand["structure"]
        lines.append(pad(_tag(i), 10) + pad(f"{cand['objective']:.5f}", 12)
                     + pad(st.composition.reduced_formula, 16) + str(len(st)))
    if res.get("failed"):
        for f in res["failed"]:
            lines.append(f"{f['tag']}: 写文件失败 {f['error']}")
    want = info.get("n_requested", 1)
    if want > len(res["candidates"]):
        lines.append(f"\n提示：只拿到 {len(res['candidates'])} 个互不相同的候选"
                     f"（请求 {want} 个）；加大 --sqs-iterations 或换扩胞倍数可再多些。")
    if res.get("dry_run"):
        lines += ["", "（-y 预览：只搜索、未写盘、未打包）"]
        return "\n".join(lines)
    lines += ["", f"包裹目录：{b['bundle_dir']}",
              f"压缩包：  {b['tar_gz']}",
              f"清单：    {b['manifest']}",
              f"SQS 信息：{res['sqs_json']}",
              "", "上传服务器：", f"  scp \"{b['tar_gz']}\" user@server:~/calc/",
              "", "提示：SQS 不唯一，objective 越小越接近理想随机固溶体；",
              "      弛豫时建议固定体积（ISIF=2），弛豫后再算一次 SRO 确认无序度未退化。"]
    return "\n".join(lines)


# ---------------------------------------------------------------- 入口
def run(cell_path: str, host: str = None, alloy: str = None, supercell=None,
        iterations: int = DEFAULT_ITERATIONS, number: int = 1, seed=None,
        name: str = None, formats=None, with_job_template: bool = False,
        dry_run: bool = False, progress=None) -> dict:
    """CLI 调用入口：读晶胞 → 规划 → 优化 → 落盘打包。"""
    info = engine_info()
    if not info["available"]:
        return {"error": engine_missing_hint()}

    if iterations < MIN_ITERATIONS:
        return {"error": f"--sqs-iterations 太小（{iterations}），"
                         f"至少 {MIN_ITERATIONS}；建议 100000 起步"}
    if iterations > MAX_ITERATIONS:
        return {"error": f"--sqs-iterations 过大（{iterations}）"}

    cell = load_cell(cell_path)
    if "error" in cell:
        return cell

    p = plan(cell, host, alloy, supercell, iterations, number, seed)
    if "error" in p:
        return p
    p["path"] = cell["path"]

    if progress:
        progress("plan", p)
    got = run_optimization(p["config"])
    if "error" in got:
        return got
    cands = got["candidates"][:max(1, int(number))]
    p["n_requested"] = max(1, int(number))
    if dry_run:
        return {"candidates": cands, "info": p, "dry_run": True}

    bname = _safe_name(name or f"sqs-{p['formula_in']}-{p['n_super']}")
    res = export(bname, cands, p, formats=formats,
                 with_job_template=with_job_template)
    if "error" in res:
        return res
    res.update({"candidates": cands, "info": p})
    state.log_event("sqs", {"cell": cell["path"], "host": p["host"],
                            "supercell": p["dims"], "alloy": alloy},
                    {"n": len(cands), "best": cands[0]["objective"]})
    return res
