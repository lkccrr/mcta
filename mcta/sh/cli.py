"""mt.sh 入口：执行本地、自定义或内置 bash 脚本。

用法：
    mt.sh                  列出可用脚本及来源
    mt.sh NAME [args...]   执行 NAME 脚本，如 mt.sh xy 即执行 xy.sh，参数原样转给脚本

查找顺序：当前目录 ./NAME.sh、$MTSH_SCRIPTS（多个目录用系统路径分隔符分开）、
随包分发的 scripts/。NAME 只是脚本名，不接受路径。
（脚本用到 sed/awk/bc 等 Unix 工具，建议在 Linux/WSL 上运行）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

BUILTIN_DIR = Path(__file__).resolve().parent / "scripts"
SUFFIXES = (".sh",)         # NAME 不带后缀时逐个尝试


def _variants(name):
    """给 NAME 生成候选文件名：原名优先，再补已知后缀。"""
    return [name] + [name + s for s in SUFFIXES if not name.endswith(SUFFIXES)]


def _valid_name(name):
    """只接受脚本名，避免绝对路径或 ../ 越过脚本目录。"""
    path = Path(name)
    return bool(name) and not path.is_absolute() and path.name == name \
        and name not in (".", "..")


def _script_dirs():
    """按覆盖优先级返回 (来源, 目录)。"""
    dirs = [("local", Path.cwd())]
    custom = os.environ.get("MTSH_SCRIPTS", "")
    for value in custom.split(os.pathsep):
        if value:
            dirs.append(("MTSH_SCRIPTS", Path(value).expanduser()))
    dirs.append(("builtin", BUILTIN_DIR))
    return dirs


def find(name):
    """按本地、自定义、内置顺序定位脚本，返回路径或 None。"""
    if not _valid_name(name):
        return None
    for _source, directory in _script_dirs():
        for cand in _variants(name):
            path = directory / cand
            if path.is_file():
                return path
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
    """列出覆盖后的可用脚本：{文件名: (路径, 简介, 来源)}。"""
    found = {}
    for source, directory in reversed(_script_dirs()):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix in SUFFIXES:
                found[path.name] = (path, _description(path), source)
    return dict(sorted(found.items()))


def _script_names():
    """列出内置脚本的可调用名（去掉 .sh 后缀）。"""
    names = []
    for filename in available():
        name = filename
        for suffix in SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        if name:
            names.append(name)
    return sorted(set(names))


def _list_scripts():
    scripts = available()
    if not scripts:
        print("没有找到可用脚本")
        return 0
    width = max(len(n) for n in scripts) + 2
    for name, (path, desc, source) in scripts.items():
        origin = source if source == "builtin" else "%s: %s" % (source, path.parent)
        print("  " + name.ljust(width) + desc + "  [" + origin + "]")
    print("")
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-v", "-V", "--version", "version"):
        from mcta import version_string
        print(version_string())
        return 0
    if not args or args[0] in ("-h", "-H", "--help", "help"):
        print(__doc__.strip())
        print()
        return _list_scripts()

    name, rest = args[0], args[1:]
    path = find(name)
    if path is None:
        print(f"ERROR: 找不到脚本 {name!r}（尝试了 " +
              "/".join(_variants(name)) + "）", file=sys.stderr)
        names = _script_names()
        if names:
            print("可用脚本：" + " ".join(names), file=sys.stderr)
        else:
            print("可用脚本：（内置 scripts/ 目录为空）", file=sys.stderr)
        print("运行 mt.sh 查看各脚本说明。", file=sys.stderr)
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
