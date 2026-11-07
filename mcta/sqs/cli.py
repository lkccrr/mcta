"""命令行入口：安装后即为 `mt.sqs` 可执行文件。

pip install . 之后直接：
    mt.sqs -c cell.vasp -a "Cu:0.5,Au:0.5"
"""
import argparse
import sys

from mcta.seeker import config, sqs
from mcta.seeker.tools import _safe_name, make_bundle, pad, write_structure_files


def _epilog() -> str:
    examples = [
        ("mt.sqs -c cell.vasp -a \"Cu:0.5,Au:0.5\"", "自定义晶胞 → SQS 扩胞（默认 3³，10 万次迭代）"),
        ("mt.sqs -c cell.vasp -a Cu,Au -x 4,4,4 --iterations 500000", "4×4×4 超胞 + 50 万次迭代"),
        ("mt.sqs -c LaAlO3.cif --host La -a \"La:0.5,Sr:0.5\"", "A 位随机化，Al/O 保持不变"),
        ("mt.sqs -c cell.vasp -a Cu:0.5,Au:0.5 -y", "-y 预览：只搜索、不写盘"),
        ("mt.sqs -c cell.vasp -a Cu,Au --iterations 1000 --number 5", "多解导出 + 低迭代（快速干跑）"),
        ("mt.sqs -c cell.vasp -a Cu:0.5,Au:0.5 -s 42", "固定随机种子，结果可复现（自动单线程）"),
    ]
    # 复用 seeker 的两列对齐工具
    from mcta.seeker.cli import _table
    lines = _table(examples)
    return "\n".join(
        ["常用示例："] + lines
        + ["", "短选项：-c 晶胞  --host 位点  -a 成分  -x 扩胞  "
           "--iterations 迭代  --number 解数  -s 种子  -n 包名  "
           "-F 格式  --job-template 模板  -y 预览  -v/-V 版本",
           "环境变量：MT_SEEKER_HOME（工作根目录）、MT_SEEKER_CONFIG（配置文件），"
           "用法与 mt.seeker 相同。"]
    )


def _version() -> str:
    from mcta import version_string
    return version_string()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mt.sqs",
        add_help=False,
        description="mt.sqs — 自定义晶胞 → 准随机固溶体结构（SQS）。\n"
                    "核心引擎是 sqsgenerator（C++），不联网、不需要 Materials Project 密钥。",
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('-h', '-H', "--help", action="help",
                    help='show this help message and exit')
    ap.add_argument('-v', '-V', "--version", action="version", version=_version())
    ap.add_argument('-c', "--cell", type=str, metavar="FILE", required=True,
                    help="自定义晶胞文件（POSCAR / CONTCAR / CIF / JSON 等 pymatgen 能读的格式）")
    ap.add_argument("--host", type=str, metavar="SYM",
                    help="要参与随机化的元素位点。晶胞只有一种元素时可省略（自动选）；"
                         "多种元素时必须显式给，否则容易把 O/S 这类亚晶格错误地随机化。")
    ap.add_argument('-a', "--alloy", type=str, metavar="SPEC", required=True,
                    help="该位点上的合金成分：\n"
                         "  Cu:0.5,Au:0.5    按分数写\n"
                         "  Cu,Au            直接等分（自动按目标原子个数折算）\n"
                         "  Cu:27,Au:27      直接按个数写（自动按比例缩放到超胞内实际位点数）\n"
                         "至少两种元素。")
    ap.add_argument('-x', "--supercell", type=str, default="3,3,3", metavar="DIMS",
                    help="扩胞倍数，如 3,3,3 或 3 或 2x2x1（默认 3,3,3）")
    ap.add_argument("--iterations", type=int, default=sqs.DEFAULT_ITERATIONS,
                    metavar="N",
                    help=f"SQS 搜索迭代次数（默认 {sqs.DEFAULT_ITERATIONS}；"
                         f"下限 {sqs.MIN_ITERATIONS}，上限 {sqs.MAX_ITERATIONS}）")
    ap.add_argument("--number", type=int, default=1, metavar="K",
                    help="导出 K 个互不相同的候选，按 objective 从小到大（默认 1）")
    ap.add_argument('-s', "--seed", type=int, default=None, metavar="SEED",
                    help="随机种子，固定后结果可复现（会自动单线程运行）")
    ap.add_argument('-n', "--name", type=str, metavar="NAME",
                    help="导出包名称（默认 sqs-化学式-原子数）")
    ap.add_argument('-F', "--formats", type=str,
                    default=",".join(config.DEFAULT_FORMATS),
                    help="结构文件格式，逗号分隔：cif,poscar,json,xyz（默认 poscar）")
    ap.add_argument("--job-template", action="store_true",
                    help="同时生成 INCAR / KPOINTS / slurm 模板")
    ap.add_argument('-y', "--dry-run", action="store_true",
                    help="只搜索、不写盘、不打包，把候选 objective 打印出来预览")
    ap.add_argument("--home", type=str, metavar="DIR",
                    help="工作根目录（exports/cache/db 落在此处），默认当前目录")
    return ap


def _ensure_utf8_output() -> None:
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

    if args.home:
        config.set_home(args.home)

    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    unknown = [f for f in formats if f not in config.STRUCT_FORMATS]
    if not formats or unknown:
        print(f"无效的结构格式：{', '.join(unknown) or '(空)'}；"
              f"可选 {', '.join(config.STRUCT_FORMATS)}", file=sys.stderr)
        return 1

    eng = sqs.engine_info()
    if not eng["available"]:
        print(sqs.engine_missing_hint(), file=sys.stderr)
        return 1
    print(f"SQS 引擎：sqsgenerator {eng['version']}", file=sys.stderr, flush=True)

    def _plan(stage, p):
        comp = " ".join(f"{k}{v}" for k, v in p["counts"].items())
        print(f"晶胞 {p['formula_in']}（{p['n_cell']} 原子）→ "
              f"{p['dims'][0]}×{p['dims'][1]}×{p['dims'][2]} = "
              f"{p['n_super']} 原子；随机化 {p['host']} 位 {p['n_host']} 个，"
              f"目标 {comp}；迭代 {p['iterations']}…",
              file=sys.stderr, flush=True)

    r = sqs.run(args.cell, host=args.host, alloy=args.alloy,
                supercell=args.supercell, iterations=args.iterations,
                number=args.number, seed=args.seed, name=args.name,
                formats=formats, with_job_template=args.job_template,
                dry_run=args.dry_run, progress=_plan)
    if "error" in r:
        print(r["error"], file=sys.stderr)
        return 1
    print(sqs.format_report(r, r["info"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
