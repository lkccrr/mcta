"""本地数据集策展：去重 → 筛选 → sklearn 多样性/异常 → LLM 计划 → 补下载。

与 tools/agent 的分工：tools 负责「从 MP 拿到结构并落盘」，curate 只处理
**已经在本地的 exports/**；唯一会联网的动作是显式要求的补下载（top_up）。

四类操作：
  * dedup      结构级去重（StructureMatcher，同式不同相才算不同结构）
  * where      规则筛选（安全表达式，如 "ehull<=0.05 and is_2d"）
  * diverse    sklearn 特征空间里的最远点采样，挑出彼此最不相似的 k 个
  * outliers   IsolationForest 标出特征空间中的离群结构
  * curate     自然语言 → JSON 筛选计划（需要 LLM），再按计划执行
"""
import ast
import csv
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from . import config, state

COLUMNS = ["mp_id", "formula", "n_sites", "spacegroup", "dimensionality",
           "vol", "a", "b", "c", "is_2d", "mag", "ehull", "gap", "batch"]

_ELEM_TOKEN = re.compile(r"[A-Z][a-z]?")


@lru_cache(maxsize=8192)
def _elements_of(formula: str) -> frozenset:
    """化学式 -> 元素符号集合（大小写敏感的完整 token）。

    直接对字符串做 `in` 判断会把 N 匹配到 Na、C 匹配到 Cl/Ca，
    所以先按 pymatgen 解析；解析失败再退回按化学式规范切词。
    """
    try:
        from pymatgen.core import Composition
        return frozenset(el.symbol for el in Composition(formula).elements)
    except Exception:  # noqa: BLE001
        return frozenset(_ELEM_TOKEN.findall(formula or ""))


# ---------------------------------------------------------------- 读数据
def _num(v):
    try:
        s = str(v).strip()
        return float(s) if s not in ("", "None", "nan") else None
    except (TypeError, ValueError):
        return None


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def load_dataset() -> list:
    """汇总 exports/*/manifest.csv，按 mp_id 去重并标准化字段。"""
    rows = {}
    if not config.EXPORT_ROOT.exists():
        return []
    manifests = sorted(config.EXPORT_ROOT.glob("*/manifest.csv"))
    # 策展包与 SQS 包本身不算数据源：
    #   curated-* 否则批次归属会被自己的产物覆盖；
    #   sqs-* 是用户自定义晶胞扩出来的超胞，混进来会让同一结构被重复计数
    source = [m for m in manifests
              if not m.parent.name.startswith(("curated-", "sqs-"))
              and not (m.parent / "sqs.json").exists()]
    for manifest in source:
        batch = manifest.parent.name
        try:
            with manifest.open(encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    if not r.get("mp_id") or not r.get("formula"):
                        continue
                    dim = (r.get("dimensionality") or "?").strip()
                    rows[r["mp_id"]] = {
                        "mp_id": r["mp_id"],
                        "formula": r["formula"],
                        "n_sites": int(_num(r.get("n_sites")) or 0),
                        "spacegroup": r.get("spacegroup", "?"),
                        # Cheon 对非周期结构会返回 "intercalated ion" 等长串，统一归为 "?"
                        "dimensionality": dim if dim in ("3D", "2D", "1D", "0D") else "?",
                        "vol": _num(r.get("volume_A3")),
                        "a": _num(r.get("a_A")), "b": _num(r.get("b_A")),
                        "c": _num(r.get("c_A")),
                        "is_2d": _truthy(r.get("likely_2d")),
                        "mag": (r.get("magnetic_elements") or "").strip(),
                        "ehull": _num(r.get("e_above_hull_eV")),
                        "gap": _num(r.get("band_gap_eV")),
                        "batch": batch,
                        "_dir": str(manifest.parent / "structures" / r["mp_id"]),
                    }
        except Exception:  # noqa: BLE001
            continue
    return list(rows.values())


def _rank(r: dict):
    """去重时保留谁：先看是否稳定（ehull 小），再看原子数（小）。"""
    return (r["ehull"] if r["ehull"] is not None else 9.0, r["n_sites"])


# ---------------------------------------------------------------- 去重
def _structure_of(row: dict):
    p = Path(row["_dir"]) / "structure.json"
    if not p.exists():
        return None
    try:
        from pymatgen.core import Structure
        return Structure.from_file(str(p))
    except Exception:  # noqa: BLE001
        return None


def _lattice_close(a: dict, b: dict, tol: float = 0.02) -> bool:
    pairs = [(a.get("a"), b.get("a")), (a.get("b"), b.get("b")), (a.get("c"), b.get("c"))]
    for x, y in pairs:
        if x is None or y is None:
            return False
        if abs(x - y) > tol * max(abs(x), abs(y), 1e-6):
            return False
    return a.get("spacegroup") == b.get("spacegroup")


def dedup(rows: list, tol: float = 0.2) -> dict:
    """结构级去重：同一化学式的不同相保留，真正重复的只留最优者。

    优先用 StructureMatcher 比对 structure.json；缺文件时退化为
    「空间群 + 晶格常数 2% 容差」判据。
    """
    try:
        from pymatgen.analysis.structure_matcher import StructureMatcher
        sm = StructureMatcher(ltol=tol, stol=tol, angle_tol=5)
    except Exception:  # noqa: BLE001
        sm = None

    buckets = {}
    for r in sorted(rows, key=_rank):
        buckets.setdefault(r["formula"], []).append(r)

    kept, groups, similar = [], [], []
    for _, items in buckets.items():
        reps = []          # [(row, structure)]
        for r in items:
            st = _structure_of(r)
            dup_of, near_of = None, None
            for rep, rep_st in reps:
                same = False
                if st is not None and rep_st is not None:
                    try:
                        same = sm is not None and sm.fit(st, rep_st)
                    except Exception:  # noqa: BLE001
                        same = False
                else:
                    same = _lattice_close(r, rep)
                if not same:
                    continue
                # 原子数不同 → 视为同一结构的扩胞/畸变变体，不合并，只提示
                if st is not None and rep_st is not None and len(st) != len(rep_st):
                    near_of = rep
                    continue
                dup_of = rep
                break
            if dup_of:
                groups.append({"kept": dup_of["mp_id"], "dup": r["mp_id"],
                               "formula": r["formula"], "batch": r["batch"]})
            else:
                if near_of:
                    similar.append({"base": near_of["mp_id"], "variant": r["mp_id"],
                                    "formula": r["formula"],
                                    "n_sites": [near_of["n_sites"], r["n_sites"]]})
                reps.append((r, st))
        kept.extend(r for r, _ in reps)
    state.log_event("curate_dedup", {"n_in": len(rows)},
                    {"n_kept": len(kept), "n_dup": len(groups)})
    return {"kept": kept, "duplicates": groups, "similar": similar,
            "n_in": len(rows), "n_kept": len(kept), "n_dup": len(groups)}


# ---------------------------------------------------------------- 规则筛选
_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Compare,
    ast.Name, ast.Load, ast.Constant,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Call, ast.keyword,
)
_ALLOWED_CALLS = {"has"}


def _compile_expr(expr: str):
    """把筛选表达式编译成 AST 白名单版本。

    不用 eval + 空 __builtins__ —— 那条路仍能通过
    `().__class__.__bases__[0].__subclasses__()` 之类的属性链逃逸。
    这里先静态检查语法树：只允许比较/布尔/算术、字段名、字面量，
    以及 has(...) 调用，其余节点（下标、推导式、lambda、真实属性访问）一律拒绝。
    """
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise SyntaxError(f"不允许的语法：{type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
                raise SyntaxError("只允许调用 has(...)")
    return compile(tree, "<where>", "eval")


def _env(r: dict) -> dict:
    # 元素判断走完整符号（has('N') 只匹配氮，不会命中 Na）
    elems = _elements_of(r["formula"]) | frozenset(_ELEM_TOKEN.findall(r["mag"] or ""))
    return {"mp_id": r["mp_id"], "formula": r["formula"], "n_sites": r["n_sites"],
            "spacegroup": r["spacegroup"], "dimensionality": r["dimensionality"],
            "vol": r["vol"], "a": r["a"], "b": r["b"], "c": r["c"],
            "is_2d": r["is_2d"], "mag": r["mag"], "batch": r["batch"],
            "ehull": r["ehull"] if r["ehull"] is not None else 9.99,
            "gap": r["gap"] if r["gap"] is not None else -1.0,
            "has": lambda *els: any(e in elems for e in els)}


def apply_where(rows: list, expr: str):
    """安全表达式筛选；可用字段见 COLUMNS，另提供 has('Mn','Cr') 辅助函数。"""
    try:
        code = _compile_expr(expr)
    except SyntaxError as e:
        return None, f"条件语法错误：{e}"
    out = []
    for r in rows:
        try:
            if bool(eval(code, {"__builtins__": {}}, _env(r))):  # noqa: S307
                out.append(r)
        except Exception as e:  # noqa: BLE001
            return None, f"条件求值失败（{r['mp_id']}）：{type(e).__name__}: {e}"
    return out, None


# ---------------------------------------------------------------- sklearn
def _feature_matrix(rows: list):
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from .ml import FEATURE_NAMES, STRUCT_FEATURE_NAMES, featurize_row
    names = FEATURE_NAMES + STRUCT_FEATURE_NAMES
    X = np.asarray([[featurize_row({"formula": r["formula"], "n_sites": r["n_sites"],
                                    "volume_A3": r["vol"], "a_A": r["a"], "b_A": r["b"],
                                    "c_A": r["c"],
                                    "likely_2d": r["is_2d"],
                                    "magnetic_elements": r["mag"]})[k]
                     for k in names] for r in rows], dtype=float)
    return StandardScaler().fit_transform(X), names


def diversity_select(rows: list, k: int) -> dict:
    """最远点采样：从最稳定的结构出发，每次挑离已选集合最远的一个。"""
    if k <= 0:
        return {"selected": [], "error": "k 必须为正"}
    if len(rows) <= k:
        return {"selected": list(rows)}
    try:
        import numpy as np
        X, _ = _feature_matrix(rows)
    except Exception as e:  # noqa: BLE001
        return {"selected": rows[:k], "error": f"特征化失败，退回顺序截取：{e}"}
    start = min(range(len(rows)), key=lambda i: _rank(rows[i]))
    sel = [start]
    d = np.linalg.norm(X - X[start], axis=1)
    while len(sel) < k:
        i = int(np.argmax(d))
        if i in sel:
            break
        sel.append(i)
        d = np.minimum(d, np.linalg.norm(X - X[i], axis=1))
    state.log_event("curate_diverse", {"n": len(rows), "k": k}, {"picked": len(sel)})
    return {"selected": [rows[i] for i in sel]}


def find_outliers(rows: list, contamination: float = 0.1) -> dict:
    """IsolationForest 标出特征空间中的离群结构（可能是数据异常或真正的新相）。"""
    if len(rows) < 10:
        return {"outliers": [], "note": "样本 < 10，跳过离群检测"}
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
        X, _ = _feature_matrix(rows)
        model = IsolationForest(random_state=42, contamination=contamination)
        flag = model.fit_predict(X)
        score = model.decision_function(X)
        idx = np.where(flag == -1)[0]
        idx = idx[np.argsort(score[idx])]
        return {"outliers": [{"mp_id": rows[i]["mp_id"], "formula": rows[i]["formula"],
                              "batch": rows[i]["batch"],
                              "score": round(float(score[i]), 3)} for i in idx]}
    except Exception as e:  # noqa: BLE001
        return {"outliers": [], "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- LLM 计划
PLAN_PROMPT = """你是材料数据库策展助手。用户会给一句自然语言要求，你要把它翻译成
一个 JSON 筛选计划，供程序执行。**只输出 JSON，不要解释**。

可用字段：mp_id, formula, n_sites, spacegroup, dimensionality(3D/2D/1D),
vol, a, b, c, is_2d(布尔), mag(磁性元素字符串，如 "MnCr"), ehull(能量高于凸包,
eV/atom), gap(带隙 eV), batch。另可用 has('Mn','Cr') 判断是否含某元素。

JSON 结构（缺省项可省略）：
{
  "where": "Python 布尔表达式，如 ehull<=0.05 and is_2d and has('Mn')",
  "dedup": true,
  "diverse": 8,              // 按特征空间多样性挑几个；null 表示不挑
  "sort": "ehull",           // 结果排序字段，可选 ehull/gap/n_sites/formula
  "name": "curated-name",    // 输出包名，小写字母数字连字符
  "top_up": {"chemsys": "Mn-P-S", "n": 5}   // 需要补下载时才给，否则省略
}

规则：
- 用户没提阈值就不要臆造（如没提带隙就别加 gap 条件）；
- "二维/层状" 用 is_2d 或 dimensionality=='2D'；
- "磁性" 用 mag!='' ；
- 用户要求"多找几个/补充下载"时给 top_up，n 取用户说的数量；
- 不要生成删除、清空类操作。"""


def llm_plan(client, task: str, rows: list) -> dict:
    """把自然语言要求转成 JSON 计划；不合法时返回 {'error':...}。"""
    sample = [{
        "mp_id": r["mp_id"], "formula": r["formula"], "spacegroup": r["spacegroup"],
        "dimensionality": r["dimensionality"], "is_2d": r["is_2d"],
        "mag": r["mag"], "ehull": r["ehull"], "gap": r["gap"],
    } for r in rows[:5]]
    user = (f"当前本地数据集共 {len(rows)} 条，字段样例：\n"
            f"{json.dumps(sample, ensure_ascii=False)}\n\n用户要求：{task}")
    try:
        resp = None
        try:
            resp = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "system", "content": PLAN_PROMPT},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"})
        except Exception:  # noqa: BLE001  部分端点不支持 response_format
            resp = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "system", "content": PLAN_PROMPT},
                          {"role": "user", "content": user}])
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{"):text.rfind("}") + 1]
        plan = json.loads(text)
        if not isinstance(plan, dict):
            return {"error": "LLM 未返回 JSON 对象"}
        state.log_event("curate_plan", {"task": task}, plan)
        return {"plan": plan}
    except Exception as e:  # noqa: BLE001
        return {"error": f"LLM 计划失败：{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- 补下载
def top_up(n: int, chemsys: str = None, formula: str = None,
           exclude=(), formats=None, with_job_template: bool = False,
           max_ehull: float = 0.05) -> dict:
    """按化学体系/化学式再下载 n 个本地没有的结构。"""
    from .tools import get_structure, search_mp, write_structure_files
    if not (chemsys or formula):
        return {"error": "补下载需要 --chems 或 --frmla（或让 LLM 计划给出 top_up.chemsys）"}
    exclude = set(exclude)
    found = search_mp(chemsys=chemsys, formula=formula, limit=max(n * 4, 10),
                      max_ehull=max_ehull)
    if "error" in found:
        return found
    if not found.get("candidates"):
        return {"error": f"{chemsys or formula} 在 ehull<={max_ehull} eV/atom 内没有候选相；"
                         f"可放宽 -m/--maxeh"} 
    entries, skipped = [], []
    for c in found.get("candidates", []):
        if len(entries) >= n:
            break
        if c["mp_id"] in exclude:
            skipped.append(c["mp_id"])
            continue
        got = get_structure(c["mp_id"])
        if "error" in got:
            continue
        w = write_structure_files(c["mp_id"], got["structure_dict"], formats=formats,
                                  with_job_template=with_job_template)
        if "error" in w:
            continue
        w["e_above_hull_eV"] = c.get("e_above_hull_eV")
        w["band_gap_eV"] = c.get("band_gap_eV")
        entries.append(w)
    state.log_event("curate_top_up", {"chemsys": chemsys, "formula": formula, "n": n},
                    {"got": len(entries)})
    return {"entries": entries, "skipped_existing": skipped,
            "n_requested": n, "n_got": len(entries)}


# ---------------------------------------------------------------- 导出
def _meta_of(r: dict) -> dict:
    return {"formula": r["formula"], "n_sites": r["n_sites"],
            "spacegroup": r["spacegroup"], "dimensionality": r["dimensionality"],
            "volume_A3": r["vol"], "lattice": [r["a"], r["b"], r["c"]],
            "likely_2d": r["is_2d"],
            "magnetic_elements": list(r["mag"]) if r["mag"] else []}


def export_curated(rows: list, name: str = None, extra_entries=()) -> dict:
    """把策展结果打包成新的 exports/<name>，结构与 manifest 一并可 scp。"""
    from .tools import make_bundle
    if not rows and not extra_entries:
        return {"error": "策展结果为空，未导出"}
    name = name or datetime.now().strftime("curated-%m%d-%H%M")
    # 防止覆盖源批次目录（make_bundle 会先删目标目录）
    if (config.EXPORT_ROOT / name).exists():
        name = f"{name}-{datetime.now().strftime('%H%M%S')}"
    entries = [{"mp_id": r["mp_id"], "export_dir": r["_dir"], "meta": _meta_of(r),
                "e_above_hull_eV": r["ehull"] if r["ehull"] is not None else "",
                "band_gap_eV": r["gap"] if r["gap"] is not None else ""}
               for r in rows]
    for e in extra_entries:
        entries.append({"mp_id": e["mp_id"], "export_dir": e["export_dir"],
                        "meta": e["meta"],
                        "e_above_hull_eV": e.get("e_above_hull_eV", ""),
                        "band_gap_eV": e.get("band_gap_eV", "")})
    b = make_bundle(name, entries)
    state.log_event("curate_export", {"name": name, "n": len(entries)}, b)
    return b


# ---------------------------------------------------------------- 主流程
def run(task: str = None, where: str = None, do_dedup: bool = False,
        diverse_k: int = 0, outliers: bool = False, top_n: int = 0,
        chemsys: str = None, formula: str = None, out: str = None,
        dry_run: bool = False, client=None, formats=None,
        with_job_template: bool = False, max_ehull: float = 0.05) -> dict:
    """执行一次策展：LLM 计划 → 筛选 → 去重 → 多样性 → 补下载 → 导出。"""
    rows = load_dataset()
    if not rows and not top_n and not task:
        return {"error": "本地还没有数据：先运行 mt.seeker --chems ... 导出结构；"
                         "或用 -T N -c X 直接下载"}
    lines = [f"本地数据集：{len(rows)} 个结构"
             f"（批次 {len({r['batch'] for r in rows})} 个）"]
    steps = []            # 每步的记录，便于审计
    plan = {}

    # 1) LLM 计划（自然语言 -> 结构化条件）
    if task:
        if client is None:
            return {"error": "LLM 计划需要密钥：请设置 MT_SEEKER_API_KEY（或用 "
                             "-w 表达式代替 -u）"}
        got = llm_plan(client, task, rows)
        if "error" in got:
            return got
        plan = got["plan"]
        where = plan.get("where") or where
        do_dedup = bool(plan.get("dedup", do_dedup))
        diverse_k = int(plan.get("diverse") or diverse_k or 0)
        out = out or plan.get("name")
        if plan.get("top_up") and not top_n:
            top_n = int(plan["top_up"].get("n") or 0)
            chemsys = plan["top_up"].get("chemsys") or chemsys
            formula = plan["top_up"].get("formula") or formula
        lines.append(f"LLM 计划：{json.dumps(plan, ensure_ascii=False)}")

    # 2) 规则筛选
    if where:
        filtered, err = apply_where(rows, where)
        if err:
            return {"error": err}
        lines.append(f"筛选条件 `{where}`：{len(rows)} → {len(filtered)}")
        steps.append({"step": "where", "n": len(filtered)})
        rows = filtered

    if not rows:
        if top_n:
            # 本地没有可筛选的数据，但用户要补下载：跳过后续本地处理，直接去下载
            lines.append("本地无可筛选的结构，跳过筛选/去重/多样性，直接补下载")
        else:
            return {"error": "筛选后为空，放宽条件再试", "report": "\n".join(lines)}

    # 3) 去重
    dup_groups = []
    if do_dedup:
        d = dedup(rows)
        dup_groups = d["duplicates"]
        lines.append(f"去重：{d['n_in']} → {d['n_kept']}（移除重复 {d['n_dup']} 个）")
        for g in dup_groups[:8]:
            lines.append(f"  - {g['dup']} 与 {g['kept']} 结构重复（{g['formula']}，{g['batch']}）")
        for s in d.get("similar", [])[:5]:
            lines.append(f"  · {s['variant']} 与 {s['base']} 同构但原子数不同 "
                         f"（{s['n_sites'][1]} vs {s['n_sites'][0]}，视为扩胞/畸变，保留）")
        rows = d["kept"]
        steps.append({"step": "dedup", "n": len(rows)})

    # 4) 离群检测（只报告，不删）
    if outliers:
        o = find_outliers(rows)
        if o.get("outliers"):
            lines.append(f"离群结构（IsolationForest，{len(o['outliers'])} 个，仅提示）：")
            for it in o["outliers"][:6]:
                lines.append(f"  - {it['mp_id']} {it['formula']} score={it['score']}")
        elif o.get("note"):
            lines.append(o["note"])

    # 5) 多样性挑选
    if diverse_k:
        dv = diversity_select(rows, diverse_k)
        if dv.get("error"):
            lines.append(f"多样性挑选提示：{dv['error']}")
        rows = dv["selected"]
        lines.append(f"多样性挑选：保留 {len(rows)} 个（特征空间最远点采样）")
        steps.append({"step": "diverse", "n": len(rows)})

    # 6) 补下载（-R/--dryrn 不做真实下载，也不落缓存）
    extra = []
    if top_n and dry_run:
        lines.append(f"补下载：请求 {top_n} 个（-R 仅预览，未联网、未落盘）")
    elif top_n:
        cached = {p.stem for p in config.STRUCT_CACHE.glob("*.json")} if \
            config.STRUCT_CACHE.exists() else set()
        tu = top_up(top_n, chemsys=chemsys, formula=formula,
                    exclude={r["mp_id"] for r in rows} | cached,
                    formats=formats, with_job_template=with_job_template,
                    max_ehull=max_ehull)
        if "error" in tu:
            lines.append(f"补下载失败：{tu['error']}")
        else:
            extra = tu["entries"]
            lines.append(f"补下载：请求 {tu['n_requested']}，成功 {tu['n_got']}"
                         f"（跳过已有 {len(tu['skipped_existing'])}）")
            if tu["n_got"] == 0:
                lines.append("  · 该体系在阈值内没有更多新相，可放宽 -m/--maxeh")
            for e in extra:
                lines.append(f"  + {e['mp_id']} {e['meta'].get('formula', '?')}")
            steps.append({"step": "top_up", "n": len(extra)})

    # 7) 结果预览
    if rows:
        from .tools import pad
        lines.append("")
        lines.append(pad("mp_id", 12) + pad("化学式", 16) + pad("维", 5)
                     + pad("原子", 6) + pad("ehull", 9) + pad("gap", 7)
                     + pad("磁性", 6))
        for r in rows[:25]:
            e = "-" if r["ehull"] is None else round(r["ehull"], 3)
            g = "-" if r["gap"] is None else round(r["gap"], 2)
            lines.append(pad(r["mp_id"], 12) + pad(r["formula"], 16)
                         + pad(r["dimensionality"], 5) + pad(r["n_sites"], 6)
                         + pad(e, 9) + pad(g, 7) + pad(r["mag"] or "-", 6))
        if len(rows) > 25:
            lines.append(f"... 其余 {len(rows) - 25} 个见清单 CSV")

    if dry_run:
        lines.append("\n（-R/--dryrn：仅预览，未写清单、未导出）")
        return {"report": "\n".join(lines), "n": len(rows), "steps": steps,
                "duplicates": dup_groups, "bundle": {}, "csv": "", "plan": plan}

    csv_path = None
    if rows:
        csv_path = config.WORKROOT / "curated" / (f"{out or 'curated'}.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore",
                               lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        lines.append(f"\n策展清单：{csv_path}")

    bundle = export_curated(rows, name=out, extra_entries=extra)
    if "error" in bundle:
        lines.append(f"导出失败：{bundle['error']}")
    else:
        lines.append(f"策展包：{bundle['bundle_dir']}")
        lines.append(f"压缩包：{bundle['tar_gz']}")
        lines.append(f"共 {bundle['n_structures']} 个结构，可直接 scp 上传")

    return {"report": "\n".join(lines), "n": len(rows), "steps": steps,
            "duplicates": dup_groups, "bundle": bundle,
            "csv": str(csv_path) if csv_path else "", "plan": plan}


def summary() -> dict:
    """-d/--dataset：本地数据集概况。"""
    from .tools import pad
    rows = load_dataset()
    if not rows:
        if config.EXPORT_ROOT.exists() and any(config.EXPORT_ROOT.glob("*/manifest.csv")):
            return {"error": "本地只有 SQS 包或策展包，没有 MP 检索批次"
                             "（这两类默认不计入 -d 统计）。\n"
                             "  先用 mt.seeker -c Ti-C / -f MoS2 / -I mp-149 导出一些 MP 结构。"}
        return {"error": "本地还没有数据：先 mt.seeker --chems ... 导出结构"}
    batches = {}
    for r in rows:
        batches[r["batch"]] = batches.get(r["batch"], 0) + 1
    n2d = sum(1 for r in rows if r["is_2d"])
    nmag = sum(1 for r in rows if r["mag"])
    stable = [r for r in rows if r["ehull"] is not None and r["ehull"] <= 0.05]
    gaps = [r["gap"] for r in rows if r["gap"] is not None]
    metals = sum(1 for g in gaps if g <= 0.01)
    lines = [f"本地数据集：{len(rows)} 个结构，{len(batches)} 个批次",
             "批次：" + "，".join(f"{k}({v})" for k, v in sorted(batches.items())),
             f"二维 {n2d} | 含磁性元素 {nmag} | ehull<=0.05 {len(stable)} | "
             f"金属(gap<=0) {metals} | 有带隙数据 {len(gaps)}",
             "",
             pad("mp_id", 12) + pad("化学式", 16) + pad("空间群", 12)
             + pad("维", 5) + pad("ehull", 9) + pad("gap", 7) + pad("磁性", 6)]
    for r in sorted(rows, key=_rank)[:15]:
        e = "-" if r["ehull"] is None else round(r["ehull"], 3)
        g = "-" if r["gap"] is None else round(r["gap"], 2)
        lines.append(pad(r["mp_id"], 12) + pad(r["formula"], 16)
                     + pad(r["spacegroup"], 12) + pad(r["dimensionality"], 5)
                     + pad(e, 9) + pad(g, 7) + pad(r["mag"] or "-", 6))
    if len(rows) > 15:
        lines.append("...（按稳定性排序，仅列前 15）")
    lines.append("\n提示：mt.seeker -w \"ehull<=0.05 and is_2d\" -r -D 8")
    return {"report": "\n".join(lines), "n": len(rows)}
