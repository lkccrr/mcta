"""智能体层：两种大脑，职责相同 —— 找到结构、写出文件、打好包。

- LLM 模式：ReAct 循环，模型通过 function calling 调用四个工具；
- 规则模式：无密钥时的确定性流水线，零自由度。

硬规则（写死在提示词与代码里）：
  1. 本智能体不执行任何计算，禁止尝试本地运行 VASP/提交作业；
  2. 每个 mp_id 必须实际落盘文件后才允许进入清单；
  3. 最后一步必须给出包裹路径与结构清单，便于直接 scp 上传。
"""
import json
import re

from mcta.seeker import config, state
from mcta.seeker.tools import (get_structure, make_bundle, pad,
                                      search_mp, write_structure_files)

SYSTEM_PROMPT = """你是「MicroCrystalSeeker」，材料结构检索助手。工具：\
search_mp / get_structure / write_structure_files / make_bundle。

铁律：
1. 你只负责检索结构与生成结构文件，**绝不执行计算**（不运行 VASP、不提交作业）；
2. 流程固定为：search_mp 找候选 → get_structure 取结构 → write_structure_files 落盘
   → make_bundle 打包；用户直接给 mp_id 时跳过第一步；
3. 含磁性元素（Fe/Co/Ni/Mn/Cr/V/稀土等）的结构，必须在结果中标注
   "服务器端建议 FM/AFM/NM 多初态"，不要自行决定磁序；
4. 工具返回 error 时先分析原因再重试，同一错误最多重试 2 次；
5. 最终回复必须包含：包裹目录、tar.gz 路径、结构数量、以及每个结构的
   mp_id / 化学式 / 原子数 / 空间群 / 维度（3D/2D/1D） / 磁性元素；
6. 若用户未指定输出格式，默认 cif + poscar + json。
现在开始处理用户任务。"""


def _tool_schemas():
    return [
        {"type": "function", "function": {
            "name": "search_mp",
            "description": "在 Materials Project 按化学体系或化学式检索近稳定相，返回候选 mp_id",
            "parameters": {"type": "object", "properties": {
                "chemsys": {"type": "string", "description": "如 Ti-C、Li-Fe-P-O"},
                "formula": {"type": "string", "description": "如 MoS2，与 chemsys 二选一"},
                "max_ehull": {"type": "number", "description": "能量高于凸包上限，默认 0.05"},
                "limit": {"type": "integer", "description": "返回候选数上限"}}}}},
        {"type": "function", "function": {
            "name": "get_structure",
            "description": "按 mp_id 取结构并缓存，返回结构字典与元信息",
            "parameters": {"type": "object", "properties": {
                "mp_id": {"type": "string"}}, "required": ["mp_id"]}}},
        {"type": "function", "function": {
            "name": "write_structure_files",
            "description": "把结构写成 CIF/POSCAR/JSON/XYZ 文件，可选同时生成服务器作业模板",
            "parameters": {"type": "object", "properties": {
                "mp_id": {"type": "string"},
                "formats": {"type": "array", "items": {"type": "string"}},
                "with_job_template": {"type": "boolean",
                                      "description": "是否附带 INCAR/KPOINTS/slurm 模板"}},
                "required": ["mp_id"]}}},
        {"type": "function", "function": {
            "name": "make_bundle",
            "description": "把已导出的结构目录打包成可 scp 上传的 tar.gz（含 manifest.csv）",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "包裹名，如 ti-c-batch"},
                "mp_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["name", "mp_ids"]}}},
    ]


_TOOL_IMPL = {
    "search_mp": search_mp,
    "get_structure": get_structure,
    "write_structure_files": lambda mp_id, formats=None, with_job_template=False:
        _write_with_structure(mp_id, formats, with_job_template),
    "make_bundle": lambda name, mp_ids: _bundle_from_cache(name, mp_ids),
}

# mp_id -> {"export_dir":..., "meta":...}，供 make_bundle 复用，避免重复下载
_EXPORTED: dict = {}


def _write_with_structure(mp_id: str, formats=None, with_job_template=False) -> dict:
    got = get_structure(mp_id)
    if "error" in got:
        return got
    w = write_structure_files(mp_id, got["structure_dict"], formats=formats,
                              with_job_template=with_job_template)
    if "error" not in w:
        _EXPORTED[mp_id] = {"export_dir": w["export_dir"], "meta": w["meta"]}
    return w


def _bundle_from_cache(name: str, mp_ids: list) -> dict:
    entries = []
    missing = []
    for mid in mp_ids:
        if mid in _EXPORTED:
            entries.append({"mp_id": mid, **_EXPORTED[mid]})
        else:
            missing.append(mid)
    if missing:
        return {"error": f"以下结构尚未导出文件，请先调用 write_structure_files：{missing}"}
    return make_bundle(name, entries)


# ---------------------------------------------------------------- LLM 模式
def run_with_llm(client, task: str) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task}]
    for turn in range(config.MAX_LLM_TURNS):
        try:
            resp = client.chat.completions.create(
                model=config.LLM_MODEL, messages=messages,
                tools=_tool_schemas(), tool_choice="auto")
        except Exception as e:  # noqa: BLE001
            # 网络/鉴权/额度/端点不可达：给出可读原因，不要甩 traceback
            name = type(e).__name__
            hint = ""
            if "Authentication" in name or "401" in str(e):
                hint = "\n  密钥无效或已过期，检查 MT_SEEKER_API_KEY / 该引擎的专属变量。"
            elif "Connection" in name or "502" in str(e) or "Refused" in str(e):
                hint = (f"\n  端点 {config.LLM_BASE_URL} 不可达；"
                        "本地引擎请先启动 ollama/vllm，云端检查网络或代理。")
            elif "RateLimit" in name or "429" in str(e):
                hint = "\n  触发限流，稍后重试或换模型。"
            return f"LLM 调用失败（第 {turn + 1} 轮）：{name}: {e}{hint}"
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or "(空回复)"
        messages.append(msg)
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            impl = _TOOL_IMPL.get(name)
            if impl is None:
                result = {"error": f"未知工具 {name}"}
            else:
                try:
                    result = impl(**args)
                except TypeError as e:
                    # 模型偶尔会传多余/缺失参数，工具层约定"绝不抛异常"
                    result = {"error": f"参数不匹配：{e}；可用参数见工具定义"}
                except Exception as e:  # noqa: BLE001
                    result = {"error": f"{type(e).__name__}: {e}"}
            state.log_event("tool", {"name": name, "args": args}, result)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False,
                                                   default=str)[:4000]})
    return "(达到最大轮数，强制停止)"


# ---------------------------------------------------------------- 规则模式
def pipeline(chemsys: str = None, formula: str = None, mp_ids: list = None,
             name: str = None, top_k: int = 3, formats=None,
             with_job_template: bool = False, progress=None,
             refresh: bool = False) -> dict:
    """确定性流水线：检索（可选）→ 取结构 → 写文件 → 打包。

    progress: 可选回调，形如 progress(已完成数, 总数, mp_id, 是否命中缓存)，
              用于边下载边报进度（串行下载期间不再长时间无输出）。
    返回结构化结果，CLI 负责打印，便于被其他程序复用。
    """
    formats = formats or list(config.DEFAULT_FORMATS)
    items = []
    matched = None
    search_cached = False

    def _tick(i: int, total: int, mid: str, cached: bool) -> None:
        if progress:
            progress(i, total, mid, cached)

    if mp_ids:
        target = [m for m in mp_ids]
        # 先确认缓存命中情况，便于进度显示
        for i, mid in enumerate(target, 1):
            got = get_structure(mid)
            _tick(i, len(target), mid, bool(got.get("cached")))
            if "error" in got:
                items.append({"mp_id": mid, "error": got["error"]})
                continue
            w = write_structure_files(mid, got["structure_dict"], formats=formats,
                                      with_job_template=with_job_template)
            items.append(w if "error" not in w else {"mp_id": mid, "error": w["error"]})
    else:
        found = search_mp(chemsys=chemsys, formula=formula, limit=top_k,
                          refresh=refresh)
        if "error" in found:
            return {"error": found["error"]}
        cands = found.get("candidates", [])[:top_k]
        matched = found.get("n_matched")
        search_cached = bool(found.get("cached"))
        if not cands:
            return {"error": f"{chemsys or formula} 在 ehull 阈值内无候选相"}
        for i, c in enumerate(cands, 1):
            got = get_structure(c["mp_id"])
            _tick(i, len(cands), c["mp_id"], bool(got.get("cached")))
            if "error" in got:
                items.append({"mp_id": c["mp_id"], "error": got["error"]})
                continue
            w = write_structure_files(c["mp_id"], got["structure_dict"],
                                      formats=formats,
                                      with_job_template=with_job_template)
            if "error" in w:
                items.append({"mp_id": c["mp_id"], "error": w["error"]})
                continue
            w["e_above_hull_eV"] = c.get("e_above_hull_eV")
            w["band_gap_eV"] = c.get("band_gap_eV")
            items.append(w)

    ok = [i for i in items if "error" not in i]
    if not ok:
        return {"error": "全部结构处理失败", "items": items}

    bundle_name = name or _safe_batch_name(chemsys or formula, ok)
    entries = [{"mp_id": i["mp_id"], "export_dir": i["export_dir"],
                "meta": i["meta"], "e_above_hull_eV": i.get("e_above_hull_eV", ""),
                "band_gap_eV": i.get("band_gap_eV", "")} for i in ok]
    b = make_bundle(bundle_name, entries)
    return {"items": items, "bundle": b, "n_ok": len(ok),
            "n_fail": len(items) - len(ok), "n_matched": matched, "top_k": top_k,
            "search_cached": search_cached}


def _safe_batch_name(prefix: str, items: list) -> str:
    base = re.sub(r"[^A-Za-z0-9.-]+", "-", prefix or "batch").strip("-")
    return f"{base.lower()}-{len(items)}"


def format_report(result: dict) -> str:
    """把 pipeline 结果渲染成给用户看的文本报告。"""
    if "error" in result:
        lines = [f"失败：{result['error']}"]
        for it in result.get("items", []):
            if "error" in it:
                lines.append(f"  - {it['mp_id']}: {it['error']}")
        return "\n".join(lines)
    lines = ["== MicroCrystalSeeker 导出报告 =="]
    lines.append(pad("mp_id", 12) + pad("化学式", 16) + pad("原子数", 8)
                 + pad("空间群", 12) + pad("维度", 6) + pad("磁性元素", 10))
    ok = 0
    for it in result["items"]:
        if "error" in it:
            lines.append(f"{it['mp_id']:<12}处理失败：{it['error']}")
            continue
        ok += 1
        m = it["meta"]
        lines.append(pad(it["mp_id"], 12) + pad(m.get("formula", "?"), 16)
                     + pad(m.get("n_sites", ""), 8)
                     + pad(m.get("spacegroup", "?"), 12)
                     + pad(m.get("dimensionality", "?"), 6)
                     + pad("".join(m.get("magnetic_elements", [])) or "-", 10))
    b = result.get("bundle", {})
    if "error" in b:
        lines.append(f"\n打包失败：{b['error']}")
    else:
        lines.append(f"\n成功导出 {ok} 个结构")
        matched, top_k = result.get("n_matched"), result.get("top_k")
        if matched is not None and top_k and matched < top_k:
            lines.append(f"提示：ehull 阈值内只匹配到 {matched} 个相，"
                         f"--top-k {top_k} 未用满")
        if result.get("search_cached"):
            lines.append("提示：检索结果来自本地缓存（12 小时内有效），"
                         "-R/--refresh 可强制刷新")
        lines.append(f"包裹目录：{b['bundle_dir']}")
        lines.append(f"压缩包：  {b['tar_gz']}")
        lines.append(f"清单：    {b['manifest']}")
        lines.append("\n上传服务器：")
        lines.append(f"  scp \"{b['tar_gz']}\" user@server:~/calc/")
    return "\n".join(lines)
