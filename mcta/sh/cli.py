"""mt.sh 入口：执行内置 bash 脚本。

用法：
    mt.sh                  列出内置脚本
    mt.sh NAME [args...]   执行 NAME 脚本，如 mt.sh xy 即执行 xy.sh，参数原样转给脚本

（脚本用到 sed/awk/bc 等 Unix 工具，建议在 Linux/WSL 上运行）。
"""
import shutil
import subprocess
import sys
from pathlib import Path

from mcta import __version__

BUILTIN_DIR = Path(__file__).resolve().parent / "scripts"
SUFFIXES = (".sh",)         # NAME 不带后缀时逐个尝试


def _variants(name):
    """给 NAME 生成候选文件名：原名优先，再补已知后缀。"""
    return [name] + [name + s for s in SUFFIXES if not name.endswith(SUFFIXES)]


def find(name):
    """在内置 scripts/ 目录定位脚本，返回路径或 None。"""
    for cand in _variants(name):
        p = BUILTIN_DIR / cand
        if p.is_file():
            return p
    return None


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
    """列出内置脚本：{文件名: (路径, 简介)}。"""
    found = {}
    if not BUILTIN_DIR.is_dir():
        return found
    for p in sorted(BUILTIN_DIR.iterdir()):
        if p.is_file() and (p.suffix in SUFFIXES or p.name.endswith(".zhe")):
            found[p.name] = (p, _description(p))
    return found


def _list_scripts():
    scripts = available()
    if not scripts:
        print("内置 scripts/ 目录为空")
        return 0
    width = max(len(n) for n in scripts) + 2
    for name, (_p, desc) in scripts.items():
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
    path = find(name)
    if path is None:
        print(f"ERROR: 找不到内置脚本 {name!r}（尝试了 " +
              "/".join(_variants(name)) + "）", file=sys.stderr)
        print("可用脚本：mt.sh", file=sys.stderr)
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
