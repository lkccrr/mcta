"""命令行入口：安装后即为 `mt.skl` 可执行文件。

pip install "mcta[seeker]" 之后直接：
    mt.skl                   对 exports/ 下全部清单做随机森林预测（ehull + 带隙）
"""
import argparse
import sys


def _version() -> str:
    from mcta import version_string
    return version_string()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mt.skl",
        add_help=False,
        description="mt.skl — 用 scikit-learn 对已导出的结构清单做数据驱动分析。\n"
                    "两个回归任务：ehull（稳定性）与 band_gap（电子结构），\n"
                    "随机森林 + 5 折交叉验证；产物落在 <home>/ml/。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
用法：
    mt.skl                   扫描 exports/*/manifest.csv，跑默认分析
    mt.skl -h                查看完整参数

算法本体仍在 mcta.seeker.ml；mt.seeker 自身已不再直接依赖 scikit-learn。
        """.strip(),
    )
    ap.add_argument('-h', '-H', "--help", action="help",
                    help='show this help message and exit')
    ap.add_argument('-v', '-V', "--version", action="version", version=_version())
    ap.add_argument("--home", type=str, metavar="DIR",
                    help="工作根目录（exports/ 与 ml/ 落在此处），默认当前目录")
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    if args.home:
        from mcta.seeker import config
        config.set_home(args.home)

    # 延迟导入：scikit-learn 在 extras "skl" 里，没装时 mt.skl 会给出干净的错误
    # 注意：ml.run_ml() 本身不需要 pymatgen/mp-api，所以只装 mcta[skl] 就够了
    try:
        from mcta.seeker import ml
    except ImportError as e:  # noqa: BLE001
        print("ERROR: 缺少 scikit-learn / joblib。请：", file=sys.stderr)
        print("    pip install \"mcta[skl]\"     # 只装 mt.skl 需要的（scikit-learn + joblib）",
              file=sys.stderr)
        print("    pip install \"mcta[seeker]\"  # 如果还需要 mt.seeker 结构检索/策展",
              file=sys.stderr)
        print("原始错误：%s" % e, file=sys.stderr)
        return 1

    r = ml.run_ml()
    if "error" in r:
        print(r["error"], file=sys.stderr)
        return 1
    print(r["report"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
