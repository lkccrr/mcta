"""mt.sh 入口：查找并执行 bash 脚本。

用法：
    mt.sh                  列出可用脚本（内置 + 当前目录 + $MTSH_SCRIPTS）
    mt.sh NAME [args...]   执行 NAME 脚本，如 mt.sh xy 即执行 xy.sh，参数原样转给脚本

查找顺序（先找到先用）：
    1. 当前目录          ./NAME.sh（本地同名脚本优先，便于临时改写）
    2. $MTSH_SCRIPTS     冒号/分号分隔的目录列表
    3. 内置脚本          随 mt 包分发的 scripts/ 目录

脚本用 bash 执行，退出码原样返回；Windows 需要 Git Bash 在 PATH 中
（脚本用到 sed/awk/bc 等 Unix 工具，建议在 Linux/WSL 上运行）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from mcta import __version__

BUILTIN_DIR = Path(__file__).resolve().parent / "scripts"
# 允许的脚本后缀。必须是元组：写成字符串 ".sh" 时 for s in SUFFIXES 会
# 逐字符遍历，得到 '.', 's', 'h'，于是 "mt.sh x" 去找的是 x. / xs / xh，
# 找不到 x.sh。
SUFFIXES = (".sh",)         # NAME 不带后缀时逐个尝试


def search_dirs():
    """脚本查找目录，按优先级返回（不含后缀尝试）。"""
    dirs = [("current dir", Path.cwd())]
    env = os.environ.get("MTSH_SCRIPTS")
    if env:
        for i, p in enumerate(env.split(os.pathsep)):
            if p.strip():
                dirs.append((f"$MTSH_SCRIPTS[{i}]", Path(p).expanduser()))
    dirs.append(("built-in", BUILTIN_DIR))
    return dirs


def _variants(name):
    """给 NAME 生成候选文件名：原名优先，再补已知后缀。"""
    return [name] + [name + s for s in SUFFIXES if not name.endswith(SUFFIXES)]


def find(name):
    """按查找顺序定位脚本，返回 (路径, 来源说明) 或 (None, None)。"""
    for where, d in search_dirs():
        for cand in _variants(name):
            p = d / cand
            if p.is_file():
                return p, where
    return None, None


def _description(path):
    """取脚本里第一行非 shebang 注释作简介，取不到就空。"""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#!"):
                continue
            if s.startswith("#"):
                return s.lstrip("# ").strip()
            break
    except OSError:
        pass
    return ""


def available():
    """列出所有可发现的脚本：{文件名: (路径, 来源, 简介)}，同名取优先级高的。"""
    found = {}
    for where, d in search_dirs():
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and (p.suffix in SUFFIXES or p.name.endswith(".zhe")):
                found.setdefault(p.name, (p, where, _description(p)))
    return found


def _list_scripts():
    scripts = available()
    if not scripts:
        print("没有找到任何脚本（内置 scripts/ 目录为空，当前目录也没有 .sh 文件）")
        return 0
    width = max(len(n) for n in scripts) + 2
    for name, (_p, _where, desc) in scripts.items():
        print("  " + name.ljust(width) + desc)
    print("\n用法: mt.sh NAME [args...]   执行脚本，参数原样转给脚本")
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-v", "-V", "--version", "version"):
        from mcta import version_string
        print(version_string())
        return 0
    if not args or args[0] in ("-h", "-H", "--help", "help", "-l", "--list", "list"):
        if args and args[0] in ("-h", "-H", "--help", "help"):
            print(__doc__.strip())
            print()
        return _list_scripts()

    name, rest = args[0], args[1:]
    path, where = find(name)
    if path is None:
        print(f"ERROR: 找不到脚本 {name!r}（尝试了 " +
              "/".join(_variants(name)) + "）", file=sys.stderr)
        print("可用脚本：mt.sh   （或把脚本目录加进 $MTSH_SCRIPTS）", file=sys.stderr)
        return 2

    bash = shutil.which("bash")
    if bash is None:
        print("ERROR: 没有找到 bash。Linux/WSL 直接可用；Windows 请安装 Git Bash"
              " 并把它的 bin 目录加入 PATH。", file=sys.stderr)
        return 2

    # 参数原样转给脚本；工作目录就是当前目录（脚本按相对路径读写 POSCAR 等文件）
    try:
        result = subprocess.run([bash, str(path), *rest])
    except KeyboardInterrupt:
        return 130
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
