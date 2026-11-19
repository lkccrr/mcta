"""mt：命令统一入口，负责说明用途并把参数原样转给对应的工具。

    mt < band | dos | phband | phdos | ph | ph3 | seek | skl | sqs | mc | sh | server > [参数]
    等价于 mt.band | mt.dos | mt.phband | mt.phdos | mt.ph | mt.ph3 | mt.seek mt.skl | mt.sqs | mt.sh | mt.server [参数]

环境变量（也可写入 ~/.config/mcta/config，KEY=VALUE；环境变量优先）：

  绘图（mt.band / mt.dos / mt.phband / mt.phdos / mt.mc）：
    MT_FONT_FAMILY         字体族，默认 STIXGeneral
    MT_MATHTEXT_FONTSET    数学文本字体集，默认 cm
    MT_RESOL               图片 DPI，默认 500
    MT_XTICK_DIRECTION     x 轴刻度方向，默认 in
    MT_YTICK_DIRECTION     y 轴刻度方向，默认 in

  结构检索与描述符分析（mt.seek / mt.sqs / mt.skl 共用工作目录与配置文件设置）：
    MP_API_KEY             Materials Project 密钥（在线检索必填）
    MT_SEEK_HOME           工作根目录，默认当前目录
    MT_SEEK_CONFIG         配置文件路径，默认 ~/.config/mcta/config
    MT_SEEK_API_KEY        LLM 密钥（所有引擎统一使用，自然语言模式）
    MT_SEEK_PROVIDER       LLM 引擎，默认 openai；可选 deepseek/qwen/glm/kimi/siliconflow/gemini/openrouter/ollama/vllm
    MT_SEEK_BASE_URL       覆盖所选 LLM 引擎的 API 端点
    MT_SEEK_MODEL          覆盖所选 LLM 引擎的模型
    MT_SEEK_MAX_TURNS      LLM 最大交互轮数，默认 30
    MT_SEEK_MAX_CAND       LLM 最大候选结构数，默认 20

  其他工具：
    MT_PH_DOCS             mt.ph 自定义词库 JSON 路径
    MT_PH3_DOCS            mt.ph3 自定义词库 JSON 路径
    MTSH_SCRIPTS           mt.sh 自定义脚本目录（本地 ./NAME.sh 优先）
    PBE_PATH               PBE 赝势目录（mt.sh/po.sh，优先）
    LDA_PATH               LDA 赝势目录（mt.sh/po.sh）
    GGA_PATH               GGA 赝势目录（mt.sh/po.sh）
"""

import sys

from mcta import version_string
from mcta.flags import TOOLS, _tool, overview, which


def _run(key, argv):
    """在进程内调用对应入口，参数与 ``<命令> [参数]`` 完全一致。

    只导入目标命令所需模块：绘图命令才依赖 matplotlib，其他命令在缺少
    绘图依赖时也应可用（例如 ``mt seek -h`` / ``mt server``）。
    """
    entry = {}
    if key in ("band", "dos", "phband", "phdos", "ph", "ph3"):
        from mcta.bandplot import dos, ph, ph3, phdos, wrapper
        entry.update({"band": wrapper.main, "dos": dos.main, "phband": wrapper.pmain,
                      "phdos": phdos.main, "ph": ph.main, "ph3": ph3.main})
    if key == "seek":
        from mcta.seek import cli as seek_cli
        entry["seek"] = seek_cli.main
    elif key == "skl":
        from mcta.skl import cli as skl_cli
        entry["skl"] = skl_cli.main
    elif key == "sqs":
        from mcta.sqs import cli as sqs_cli
        entry["sqs"] = sqs_cli.main
    elif key == "sh":
        from mcta.sh import cli as sh_cli
        entry["sh"] = sh_cli.main
    elif key == "mc":
        from mcta.mc import wrapper as mc_wrapper
        entry["mc"] = mc_wrapper.main
    elif key == "server":
        from mcta.server import main as server_main
        entry["server"] = server_main
    name = _tool(key)["name"]
    saved = sys.argv
    sys.argv = [name] + list(argv)
    try:
        return entry[key]()
    finally:
        sys.argv = saved


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        overview()
        return 0

    head, rest = args[0], args[1:]
    if head in ("-h", "-H", "--help", "help"):
        print((__doc__ or "").strip())
        print("\n<命令 " + " | ".join(t["key"] for t in TOOLS) + " >")
        print("\nmt <命令> -h 查看该命令的参数；mt -v 版本；mt which 查看安装位置")
        return 0
    if head in ("-v", "-V", "--version", "version"):
        print(version_string())
        return 0
    if head in ("which", "where"):
        return which()

    if _tool(head) is None:
        print("ERROR: 未知命令 %r。" % head)
        print("可用：mt / mt band / mt dos / mt phband / mt phdos / mt ph / mt ph3 / mt seek / mt skl / mt sqs / mt sh / mt mc / mt which / mt -v/-V")
        return 2
    result = _run(head, rest)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
