"""机器学习层：用 scikit-learn 对已导出的结构清单做数据驱动分析。

设计约束（与整体定位一致）：
  * **离线**：只吃 exports/*/manifest.csv 里已有的数据，不联网、不调 MP；
  * **轻量**：组成特征直接用 pymatgen 的元素性质加权统计，不引入 matminer；
  * 两个回归任务：ehull（稳定性）与 band_gap（电子结构），随机森林 + 5 折交叉验证；
  * 产物落在 <home>/ml/：特征表、预测表、模型文件（joblib）、分析报告，
    报告中给出"按预测 ehull 排序的候选"，辅助挑选下一批要送服务器算的结构。
"""
import csv
from datetime import datetime

# 组成特征名（顺序即模型输入顺序）
FEATURE_NAMES = [
    "n_elements", "mean_Z", "std_Z", "mean_mass", "std_mass",
    "mean_X", "std_X", "mean_radius", "std_radius",
    "mean_row", "std_row", "mean_group", "std_group",
    "mean_mendeleev", "std_mendeleev",
    "mag_fraction",
]
STRUCT_FEATURE_NAMES = ["n_sites", "volume_per_atom", "mean_a", "mean_b",
                        "mean_c", "is_2d", "has_magnetic"]


# ---------------------------------------------------------------- 数据收集
def collect_rows() -> list:
    """扫描 exports/*/manifest.csv，按 mp_id 去重（后出现的覆盖先出现的）。"""
    from . import config
    rows = {}
    if not config.EXPORT_ROOT.exists():
        return []
    for manifest in sorted(config.EXPORT_ROOT.glob("*/manifest.csv")):
        # SQS 包来自用户自定义晶胞、没有 ehull/带隙，拉进来只会把样本带偏。
        # 认 sqs.json 而不只是名字前缀：用户可能把包改名成任意名字
        if (manifest.parent / "sqs.json").exists() or \
                manifest.parent.name.startswith("sqs-"):
            continue
        try:
            with manifest.open(encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("mp_id") and r.get("formula") not in (None, "", "?"):
                        r["_batch"] = manifest.parent.name
                        rows[r["mp_id"]] = r
        except Exception:  # noqa: BLE001
            continue
    return list(rows.values())


def composition_features(formula: str) -> dict:
    """把化学式转成元素性质加权统计特征（均值/标准差）。"""
    from pymatgen.core import Composition

    def _num(el, attr, default=0.0):
        v = getattr(el, attr, None)
        return float(v) if v is not None else default

    comp = Composition(formula)
    per_el = []
    for el, amt in comp.element_composition.items():
        per_el.append({
            "symbol": el.symbol,
            "Z": _num(el, "Z"), "mass": _num(el, "atomic_mass"),
            "X": _num(el, "X"), "radius": _num(el, "atomic_radius", _num(el, "Z") * 0.01),
            "row": _num(el, "row"), "group": _num(el, "group"),
            "mendeleev": _num(el, "mendeleev_no"),
        })
    feats = {"n_elements": len(per_el)}
    for key in ("Z", "mass", "X", "radius", "row", "group", "mendeleev"):
        vals = [e[key] for e in per_el]
        m = sum(vals) / len(vals)
        feats[f"mean_{key}"] = m
        feats[f"std_{key}"] = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5
    # 磁性元素占比
    from . import config
    mag = sum(1 for e in per_el if e["symbol"] in config.MAGNETIC_ELEMENTS)
    feats["mag_fraction"] = mag / len(per_el)
    return feats


def featurize_row(r: dict) -> dict:
    """清单行 -> 完整特征向量（组成特征 + 结构特征）。"""
    f = composition_features(r["formula"])

    def _f(key, default=0.0):
        try:
            return float(r.get(key, "") or default)
        except (TypeError, ValueError):
            return default

    n_sites = _f("n_sites")
    vol = _f("volume_A3")
    feats = {
        **f,
        "n_sites": n_sites,
        "volume_per_atom": (vol / n_sites) if n_sites else 0.0,
        "mean_a": _f("a_A"), "mean_b": _f("b_A"), "mean_c": _f("c_A"),
        "is_2d": 1.0 if str(r.get("likely_2d", "")).lower() in ("true", "1", "yes") else 0.0,
        "has_magnetic": 1.0 if str(r.get("magnetic_elements", "")).strip() else 0.0,
    }
    return feats


def _targets(r: dict) -> dict:
    def _f(key):
        try:
            v = r.get(key, "")
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    return {"ehull": _f("e_above_hull_eV"), "gap": _f("band_gap_eV")}


# ---------------------------------------------------------------- 训练
def run_ml() -> dict:
    """全流程：收集 -> 特征化 -> 训练评估 -> 落盘 -> 返回文本报告。"""
    try:
        try:
            import numpy as np
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.metrics import mean_absolute_error, r2_score
            from sklearn.model_selection import KFold, cross_val_predict
        except ImportError:
            return {"error": "未安装 scikit-learn：pip install scikit-learn joblib"}

        from . import config, state

        rows = collect_rows()
        if len(rows) < 8:
            return {"error": f"有效样本只有 {len(rows)} 条（需 >= 8）。"
                             f"先用 mt.seeker -c ... 多导出几批结构，再运行 mt.skl。"}

        X, meta, ys = [], [], {"ehull": [], "gap": []}
        for r in rows:
            t = _targets(r)
            feats = featurize_row(r)
            X.append([feats[k] for k in FEATURE_NAMES + STRUCT_FEATURE_NAMES])
            meta.append((r["mp_id"], r["formula"], r.get("spacegroup", "?"),
                         r.get("_batch", "?")))
            for k in ys:
                ys[k].append(t[k])
        X = np.asarray(X, dtype=float)
        feature_names = FEATURE_NAMES + STRUCT_FEATURE_NAMES

        out_dir = config.WORKROOT / "ml"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 特征表落盘，便于复现
        with (out_dir / "features.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["mp_id", "formula", "batch"] + feature_names)
            for (mp_id, formula, _, batch), x in zip(meta, X):
                w.writerow([mp_id, formula, batch] + [round(v, 5) for v in x])

        lines = [
            "== mt.seeker 机器学习分析（随机森林 + 5 折交叉验证）==",
            f"样本：{len(rows)} 条（来自 exports/ 各批清单，按 mp_id 去重）",
            f"特征：{len(feature_names)} 维（元素性质加权统计 + 结构几何）",
            "",
        ]

        model_paths, results = {}, {}
        for key, label in (("ehull", "能垒 e_above_hull (eV/atom)"),
                           ("gap", "带隙 band_gap (eV)")):
            y = np.asarray([np.nan if v is None else v for v in ys[key]], dtype=float)
            mask = ~np.isnan(y)
            if mask.sum() < 8:
                lines.append(f"[{label}] 有效样本 {int(mask.sum())} 条，不足 8，跳过。")
                continue
            Xk, yk, mk = X[mask], y[mask], [m for m, ok in zip(meta, mask) if ok]
            model = RandomForestRegressor(n_estimators=300, random_state=42,
                                          n_jobs=-1)
            kf = KFold(n_splits=5, shuffle=True, random_state=42)
            pred = cross_val_predict(model, Xk, yk, cv=kf, n_jobs=-1)
            r2, mae = r2_score(yk, pred), mean_absolute_error(yk, pred)
            model.fit(Xk, yk)

            import joblib
            p_model = out_dir / f"model_{key}.joblib"
            joblib.dump({"model": model, "features": feature_names}, p_model)
            model_paths[key] = str(p_model)

            imp = sorted(zip(feature_names, model.feature_importances_),
                         key=lambda kv: -kv[1])[:8]
            lines.append(f"[{label}] 有效样本 {int(mask.sum())} | "
                         f"5折CV: R²={r2:.3f}, MAE={mae:.4f}")
            lines.append("  重要特征: " + ", ".join(f"{n}({v:.3f})" for n, v in imp))

            # 预测值落盘 + 按 ehull 给出推荐
            with (out_dir / f"predictions_{key}.csv").open(
                    "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(["mp_id", "formula", "spacegroup", "batch",
                            f"{key}_actual", f"{key}_pred_cv"])
                for m, a, pv in zip(mk, yk, pred):
                    w.writerow([m[0], m[1], m[2], m[3],
                                f"{a:.4f}", f"{pv:.4f}"])
            if key == "ehull":
                order = np.argsort(pred)
                lines.append("  按预测 ehull 最稳定的前 5 个：")
                for i in order[:5]:
                    m = mk[i]
                    lines.append(f"    {m[0]:<10} {m[1]:<14} 实际 {yk[i]:.3f}  "
                                 f"预测 {pred[i]:.3f}  ({m[3]})")
            lines.append("")
            results[key] = {"r2": round(float(r2), 3), "mae": round(float(mae), 4),
                            "n": int(mask.sum())}

        if not results:
            n_e = sum(1 for v in ys["ehull"] if v is not None)
            n_g = sum(1 for v in ys["gap"] if v is not None)
            if n_e == 0 and n_g == 0:
                return {"error": "清单里没有 ehull / 带隙数据，无法训练。"
                                 "只有 -c/-f 检索导出的批次带这两列；"
                                 "-I 直接导出、以及离线自检的批次没有。"}
            return {"error": f"有效样本不足：ehull {n_e} 条、带隙 {n_g} 条（各需 >= 8）。"
                             f"当前共 {len(rows)} 条，多导出几批结构再运行 mt.skl。"}

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        (out_dir / "report.md").write_text(
            f"# mt.skl 结构清单机器学习报告\n\n生成时间：{ts}\n\n```\n"
            + "\n".join(lines) + "\n```\n", encoding="utf-8")
        state.log_event("run_ml", {"n_samples": len(rows)}, results)
        lines.append(f"产物目录: {out_dir}")
        lines.append("  特征表: features.csv")
        lines.append(f"  模型:   {', '.join(model_paths.values()) or '-'}")
        lines.append("  报告:   report.md")
        return {"report": "\n".join(lines), "results": results,
                "n_samples": len(rows), "out_dir": str(out_dir)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
