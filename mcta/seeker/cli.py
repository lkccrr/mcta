"""命令行入口：安装后即为 `mt.seeker` 可执行文件。

pip install . 之后直接：
    mt.seeker --offline
    mt.seeker --chems Mo-S --topks 5
"""
import argparse
import re
import sys

from . import agent, config, curate, llm
from .tools import (_disp_width, _safe_name, describe_structure, list_exports,
                    make_bundle, pad, write_structure_files)


def _table(rows, gap: int = 2) -> list:
    """把 (左栏, 右栏) 对齐成两列，按终端显示宽度算（中文占 2 列）。

    手写空格对齐在中文/英文混排时一定错位，所以这里统一走 pad()。
    """
    if not rows:
        return []
    width = max(_disp_width(left) for left, _ in rows) + gap
    return ["  " + pad(left, width) + right for left, right in rows]


def _epilog() -> str:
    examples = _table([
        ("mt.seeker --offline", "离线自检（无需 MP_API_KEY）"),
        ("mt.seeker -c Ti-C -k 3", "按化学体系检索近稳定相"),
        ("mt.seeker -f MoS2 -k 5", "按化学式精确检索"),
        ("mt.seeker -I mp-149 mp-2658", "直接指定结构，不检索（逗号分隔也行）"),
        ("mt.seeker -c Mn-P-S --job-template", "附带 INCAR/KPOINTS/slurm 模板"),
        ("mt.seeker -Q -c Ti-C", "忽略检索缓存（12h），强制重新查询"),
        ("mt.seeker -t \"找 Cr-I 的二维磁性候选\"", "自然语言模式（需 LLM 密钥）"),
        ("mt.seeker -t \"...\" -p deepseek", "指定 LLM 引擎（默认 openai）"),
        ("mt.seeker -L", "查看历史导出包"),
        ("mt.seeker -d", "查看本地数据集概况"),
        ("mt.seeker -w \"ehull<=0.05 and is_2d\"", "规则筛选本地数据（可叠 -r/-D）"),
        ("mt.seeker -r -D 8", "去重 + 多样性挑 8 个，导出策展包"),
        ("mt.seeker -u \"要二维含 Mn 的，去重挑 8 个\"", "自然语言策展（LLM）"),
        ("mt.seeker -T 5 -c Mn-P-S", "只补下载本地没有的结构"),
    ])
    envs = _table([
        ("MP_API_KEY", "Materials Project 密钥（检索必填，也可写配置文件）"),
        ("MT_SEEKER_CONFIG", "密钥配置文件路径，默认 ~/.config/mcta/config"),
        ("MT_SEEKER_HOME", "工作根目录，默认当前目录"),
        ("MT_SEEKER_API_KEY", "LLM 密钥（仅 -t/--tasks 需要）"),
        ("MT_SEEKER_PROVIDER", "LLM 引擎：openai(默认)/deepseek/qwen/glm/kimi/"),
        ("", "siliconflow/gemini/openrouter/ollama/vllm"),
        ("MT_SEEKER_BASE_URL", "覆盖预设端点"),
        ("MT_SEEKER_MODEL", "覆盖预设模型"),
    ])
    return "\n".join(
        ["常用示例："] + examples
        + ["", "短选项：-c 体系  -f 化学式  -I mp_id  -k 前 k 个  -n 包名  -F 格式",
           "        -t 任务  -p 引擎  -L 历史包  -Q 刷新  -d 概况",
           "        -w 筛选  -r 去重  -D 多样性  -u 策展  -T 补下载  -m ehull",
           "        -o 包名  -R 预览  -v/-V 版本",
           "注意：短写区分大小写 —— -t 是 --tasks、-T 是 --topup；",
           "      -r 是 --dedup、-R 是 --dryrn、-Q 是 --refsh。",
           "", "环境变量："] + envs
        + ["", "LLM 引擎预设见 README「LLM 引擎选项」；各引擎也认自己的密钥变量",
           "（DEEPSEEK_API_KEY、DASHSCOPE_API_KEY、ZHIPU_API_KEY、MOONSHOT_API_KEY 等）。"]
    )


def _version() -> str:
    """-V 输出统一用 mcta.version_string()（单一来源，格式全局一致）。

    早先优先读安装元数据，结果源码已是新版、机器上还留着旧版安装时，
    `-V` 会报出与实际运行的代码不一致的版本号。这里改成单一来源。
    """
    from mcta import version_string
    return version_string()


def demo_structures() -> list:
    """内置示例结构，离线自检用（不联网）。"""
    from pymatgen.core import Lattice, Structure
    # 1) 2H-MoS2 单层，20 A 真空 —— 二维示例
    mos2 = Structure(Lattice.hexagonal(3.16, 20.0),
                     ["Mo", "S", "S"],
                     [[0, 0, 0.5], [1 / 3, 2 / 3, 0.545], [2 / 3, 1 / 3, 0.455]])
    # 2) NaCl 岩盐结构 —— 三维绝缘体示例
    nacl = Structure(Lattice.cubic(5.64), ["Na", "Cl"],
                     [[0, 0, 0], [0.5, 0.5, 0.5]])
    # 3) bcc Fe —— 磁性金属示例（触发 magnetic_elements 标记）
    fe = Structure(Lattice.cubic(2.87), ["Fe", "Fe"],
                   [[0, 0, 0], [0.5, 0.5, 0.5]])
    return [("demo-MoS2", mos2), ("demo-NaCl", nacl), ("demo-Fe", fe)]


def offline_demo(with_job_template: bool = False, fmts=None) -> None:
    print("== MicroCrystalSeeker 离线自检（不联网，结构为内置示例）==")
    entries = []
    for mp_id, st in demo_structures():
        sd = st.as_dict()
        info = describe_structure(sd)
        w = write_structure_files(mp_id, sd, formats=fmts,
                                  with_job_template=with_job_template)
        if "error" in w:
            print(f"[{mp_id}] 写文件失败: {w['error']}")
            continue
        print(f"[{mp_id}] {info["formula"]:<6} {info['n_sites']:>2} 原子  "
              f"{info['spacegroup']:<8} {info.get('dimensionality', '?'):<4}  "
              f"磁性={''.join(info['magnetic_elements']) or '-'}")
        print(f"          文件: {', '.join(w['files'].keys())}  ->  {w['export_dir']}")
        entries.append({"mp_id": mp_id, "export_dir": w["export_dir"], "meta": info})
        assert (w["export_dir"]), "导出目录为空"

    b = make_bundle("offline-demo", entries)
    if "error" in b:
        print("打包失败:", b["error"])
        return
    print(f"\n包裹目录: {b['bundle_dir']}")
    print(f"压缩包:   {b['tar_gz']}")
    print(f"清单:     {b['manifest']}")
    print("\n自检通过：检索之外的写文件/打包链路可用。")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mt.seeker",
        add_help=False,
        description="MicroCrystalSeeker — 从 Materials Project 检索结构并导出结构文件包"
                    "（不执行计算，计算在服务器上完成）",
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('-h', '-H', "--help", action="help",
                    help='show this help message and exit')
    ap.add_argument('-v', '-V', "--version", action="version",
                    version=_version())
    ap.add_argument("--offline", action="store_true", help="离线自检（内置结构）")
    ap.add_argument('-c', "--chems", type=str, help="化学体系，如 Ti-C")
    ap.add_argument('-f', "--frmla", type=str, help="化学式，如 MoS2")
    ap.add_argument('-I', "--mpids", nargs="+", help="直接指定 mp_id，可多个")
    ap.add_argument('-n', "--names", type=str, help="导出包名称（默认按输入自动生成）")
    ap.add_argument('-k', "--topks", type=int, default=3, help="检索取前 k 个（默认 3）")
    ap.add_argument('-Q', "--refsh", action="store_true",
                    help="忽略本地检索缓存，强制重新查询 Materials Project")
    ap.add_argument('-F', "--formt", type=str,
                    default=",".join(config.DEFAULT_FORMATS),
                    help="结构文件格式，逗号分隔：cif,poscar,json,xyz"
                         "（poscar 也可写 vasp）")
    ap.add_argument("--job-template", action="store_true",
                    help="同时生成 INCAR/KPOINTS/slurm 模板，供服务器使用")
    ap.add_argument('-t', "--tasks", type=str, help="自然语言任务（LLM 模式）")
    ap.add_argument('-p', "--provs", type=str, default=None,
                    choices=sorted(config.LLM_PROVIDERS),
                    help="LLM 引擎（默认 openai；本地用 ollama/vllm）")
    ap.add_argument('-L', "--lists", action="store_true", help="列出历史导出包")
    # --- 本地数据集策展（对已下载数据筛选/去重/补下载）---
    cur = ap.add_argument_group("本地策展（筛选 / 去重 / 补下载）")
    cur.add_argument('-d', "--dsets", action="store_true",
                     help="查看本地数据集概况（条数、维度、磁性、稳定性）")
    cur.add_argument('-w', "--where", type=str, metavar="EXPR",
                     help="规则筛选：ehull/gap/n_sites/is_2d/mag 等字段，支持 has('Mn')")
    cur.add_argument('-r', "--dedup", action="store_true",
                     help="结构级去重（StructureMatcher，同式不同相保留）")
    cur.add_argument('-D', "--diver", type=int, default=0, metavar="K",
                     help="sklearn 多样性挑选 K 个（最远点采样）")
    cur.add_argument("--outliers", action="store_true",
                     help="IsolationForest 标出离群结构（仅提示不删除）")
    cur.add_argument('-u', "--curat", type=str, metavar="TASK",
                     help="自然语言策展要求（LLM 转成筛选计划，需密钥）")
    cur.add_argument('-T', "--topup", type=int, default=0, metavar="N",
                     help="再下载 N 个（需 -c/-f）；大写 -T，小写 -t 是 --tasks")
    cur.add_argument('-m', "--maxeh", type=float, default=0.05, metavar="E",
                     help="补下载的 ehull 上限，默认 0.05 eV/atom")
    cur.add_argument('-o', "--outdr", type=str, metavar="NAME",
                     help="策展包名称（默认 curated-MMDD-HHMM）")
    cur.add_argument('-R', "--dryrn", action="store_true",
                     help="只预览不导出")
    ap.add_argument("--home", type=str, metavar="DIR",
                    help="工作根目录（exports/cache/db 落在此处），默认当前目录")
    return ap


def _llm_unavailable_hint(d: dict) -> str:
    """根据 get_client 的真实失败原因给出对应提示。

    no_key 是"没配密钥"的内部标记，不能直接抛给用户看，
    要落到下面的可操作提示里。
    """
    err = d.get("last_error", "")
    if err == "no_package":
        return ("缺少 openai 客户端包：pip install \"mcta[seeker]\""
                "（或 pip install openai）。")
    if err and err != "no_key":
        return f"LLM 客户端创建失败：{err}"
    return (f"LLM 模式不可用：引擎 {d["provider"]}（{d['model']}）未配置密钥。"
            "\n  设置 MT_SEEKER_API_KEY，或该引擎专属变量"
            "（DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / ZHIPU_API_KEY …）；"
            "\n  只跑一次可临时用 -p 指定引擎；本地模型用 -p ollama（无需密钥）。"
            "\n  不打算用自然语言模式的话，改用 -c / -f / -I。")


def _all_cached(mp_ids) -> bool:
    """所有 mp_id 都已在本地缓存时，无需 MP_API_KEY 也能重跑导出。"""
    if not mp_ids:
        return False
    return all((config.STRUCT_CACHE / f"{_safe_name(m)}.json").exists()
               for m in mp_ids)


def _ensure_utf8_output() -> None:
    """让中文输出在非 UTF-8 locale 下也不崩。

    HPC 集群常见 LANG=C/POSIX，此时 stdout 编码是 ascii，
    直接 print 中文会抛 UnicodeEncodeError。这里优先切成 UTF-8，
    切不动就退化为 errors="replace"（显示成 ? 但流程照常跑完）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            try:
                stream.reconfigure(errors="replace")
            except Exception:  # noqa: BLE001
                pass


def main(argv=None) -> int:
    _ensure_utf8_output()
    ap = build_parser()
    args = ap.parse_args(argv)

    # 工作根目录优先级：--home > MT_SEEKER_HOME > 当前目录
    if args.home:
        config.set_home(args.home)

    # 格式校验前置：除 --offline 外的任何路径都必须先过这一关，
    # 否则 `--offline --formt bogus` 会静默用默认格式
    formats = [f.strip().lower() for f in args.formt.split(",") if f.strip()]
    unknown = [f for f in formats if f not in config.STRUCT_FORMATS]
    if not formats or unknown:
        print(f"无效的结构格式：{', '.join(unknown) or '(空)'}；"
              f"可选 {', '.join(config.STRUCT_FORMATS)}", file=sys.stderr)
        return 1

    if args.lists:
        r = list_exports()
        if not r["exports"]:
            print(f"暂无导出包（根目录：{config.WORKROOT}）")
        for e in r["exports"]:
            print(f"{e['name']:<20} {e['dir']}")
        return 0

    if args.offline:
        offline_demo(with_job_template=args.job_template, fmts=formats)
        return 0

    # --- 本地策展：筛选 / 去重 / 多样性 / 补下载 ---
    curate_actions = (args.where or args.dedup or args.diver or args.outliers
                      or args.curat or args.topup)
    if args.dsets and not curate_actions:
        r = curate.summary()
        print(r.get("report") or r.get("error", ""))
        return 0 if "report" in r else 1
    if curate_actions:
        client = None
        if args.curat:
            client = llm.get_client(args.provs)
            if client is None:
                print(_llm_unavailable_hint(llm.describe()), file=sys.stderr)
                return 1
            print(f"LLM 引擎：{llm.describe()["provider"]}  "
                  f"model={config.LLM_MODEL}")
        r = curate.run(task=args.curat, where=args.where, do_dedup=args.dedup,
                       diverse_k=args.diver, outliers=args.outliers,
                       top_n=args.topup, chemsys=args.chems,
                       formula=args.frmla, out=args.outdr, dry_run=args.dryrn,
                       client=client, formats=formats,
                       with_job_template=args.job_template,
                       max_ehull=args.maxeh)
        if "error" in r:
            print(r["error"], file=sys.stderr)
            if r.get("report"):
                print(r["report"], file=sys.stderr)
            return 1
        print(r["report"])
        return 0

    if args.tasks:
        client = llm.get_client(args.provs)
        if client is None:
            print(_llm_unavailable_hint(llm.describe()), file=sys.stderr)
            return 1
        d = llm.describe()
        print(f"LLM 引擎：{d["provider"]}  model={d['model']}  {d['base_url']}")
        print(agent.run_with_llm(client, args.tasks))
        return 0

    if not (args.chems or args.frmla or args.mpids):
        ap.print_help()
        return 0

    # --mpids 同时接受空格与逗号分隔（逗号写法很常见，直接拒绝会让人困惑）
    mp_ids = None
    if args.mpids:
        mp_ids = [x for chunk in args.mpids for x in re.split(r"[,\s]+", chunk) if x]
        bad = [m for m in mp_ids if not re.fullmatch(r"mp-\d+", m)]
        if bad:
            print(f"mp_id 格式不对：{', '.join(bad)}"
                  f"\n  应形如 mp-149（Materials Project 页面上的编号），"
                  f"可用空格或逗号分隔多个", file=sys.stderr)
            return 1

    if not config.MP_API_KEY and not _all_cached(mp_ids):
        cfgdir = config.CONFIG_FILE.parent
        if sys.platform.startswith("win"):
            howto = (f"\n      New-Item -ItemType Directory -Force '{cfgdir}' | Out-Null"
                     f"\n      'MP_API_KEY=你的key' | Set-Content '{config.CONFIG_FILE}'"
                     "\n  或设环境变量：setx MP_API_KEY \"你的key\"（重开终端生效）")
        else:
            howto = (f"\n      mkdir -p {cfgdir}"
                     f"\n      echo 'MP_API_KEY=你的key' >> {config.CONFIG_FILE}"
                     "\n  或设环境变量：export MP_API_KEY=你的key")
        print("未设置 MP_API_KEY：到 https://next-gen.materialsproject.org 免费注册后，"
              "\n  写进配置文件（推荐，cron/远程执行也能用）：" + howto,
              file=sys.stderr)
        return 1

    def _progress(i, total, mp_id, cached):
        tag = "缓存" if cached else "下载"
        print(f"[{i}/{total}] {mp_id} {tag}…", file=sys.stderr, flush=True)

    result = agent.pipeline(chemsys=args.chems, formula=args.frmla,
                            mp_ids=mp_ids, name=args.names,
                            top_k=args.topks, formats=formats,
                            with_job_template=args.job_template,
                            progress=_progress, refresh=args.refsh)
    print(agent.format_report(result))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
