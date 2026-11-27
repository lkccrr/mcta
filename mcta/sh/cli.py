"""mt.sh 入口：执行本地、自定义或内置 bash 脚本。

用法：
    mt.sh                  列出可用脚本及来源
    mt.sh NAME [args...]   在当前目录执行 NAME 脚本，如 mt.sh xy 即执行 xy.sh，
                           参数原样转给脚本
    mt.sh N NAME [args...] 在当前目录下第 N 层每个子目录里执行 NAME 脚本，
                           如 mt.sh 1 mv 会把当前目录下直接子目录（含指向目录
                           的软链接）都遍历一遍，在每个里跑一次 mt.sh mv；
                           N 是自然数，不含前导零

查找顺序：当前目录 ./NAME.sh、$MTSH_SCRIPTS（多个目录用系统路径分隔符分开）、
随包分发的 scripts/。NAME 只是脚本名，不接受路径。
（脚本用到 sed/awk/bc 等 Unix 工具，建议在 Linux/WSL 上运行）。
"""
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

BUILTIN_DIR = Path(__file__).resolve().parent / "scripts"
SUFFIXES = (".sh",)

_DIGITS = re.compile(r"^\d+$")


def _variants(name):
    return [name] + [name + s for s in SUFFIXES if not name.endswith(SUFFIXES)]


def _valid_name(name):
    path = Path(name)
    return bool(name) and not path.is_absolute() and path.name == name \
        and name not in (".", "..")


def _script_dirs():
    dirs = [("local", Path.cwd())]
    custom = os.environ.get("MTSH_SCRIPTS", "")
    for value in custom.split(os.pathsep):
        if value:
            dirs.append(("MTSH_SCRIPTS", Path(value).expanduser()))
    dirs.append(("builtin", BUILTIN_DIR))
    return dirs


def find(name):
    if not _valid_name(name):
        return None
    for _source, directory in _script_dirs():
        for cand in _variants(name):
            path = directory / cand
            if path.is_file():
                return path
    return None


def _description(path):
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
    found = {}
    for source, directory in reversed(_script_dirs()):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix in SUFFIXES:
                found[path.name] = (path, _description(path), source)
    return dict(sorted(found.items()))


def _script_names():
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


def _collect_dirs(root, depth):
    """BFS 返回 root 下 depth 层的所有目录（含 symlink-to-dir），按 inode 去重防循环。

    depth=1 → root 的直接子目录；depth=2 → 孙子目录；
    如果当前层某个目录不可访问或为空就跳过，不会提前中断整个流程。
    """
    if depth <= 0:
        return [root]
    visited = set()
    current = [os.path.abspath(root)]
    for _ in range(depth):
        nxt = []
        for d in current:
            try:
                entries = os.listdir(d)
            except OSError:
                continue
            for child in entries:
                full = os.path.join(d, child)
                try:
                    st = os.stat(full)  # stat 跟随 symlink，能覆盖 symlink-to-dir
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    key = (st.st_dev, st.st_ino)
                    if key not in visited:
                        visited.add(key)
                        nxt.append(full)
        current = nxt
        if not current:
            break
    return current


def _run_at(bash, script_path, rest, cwd, verbose=True):
    if verbose:
        rel = os.path.relpath(cwd, os.getcwd())
        tag = "." if rel == "." else rel
        print(f"--- mt.sh {' '.join(sys.argv[1:])}  @ {tag} ---", flush=True)
    # 子进程 bash 脚本（kb.sh 等）需要能拿到当前正确的 python + ase。
    # 塞 MTA_PYTHON 让脚本的 shebang 解析绕过 PATH 顺序。
    env = os.environ.copy()
    env["MTA_PYTHON"] = sys.executable
    try:
        result = subprocess.run([bash, str(script_path), *rest], cwd=cwd, env=env)
    except KeyboardInterrupt:
        return 130
    return result.returncode


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

    # 首个参数是自然数 → 递归模式
    depth = 0
    first = args[0]
    if _DIGITS.match(first) and int(first) > 0:
        depth = int(first)
        args = args[1:]
        if not args:
            print(f"ERROR: mt.sh {first} 缺少脚本名", file=sys.stderr)
            print("用法：mt.sh N NAME [args...]", file=sys.stderr)
            return 2

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

    if depth == 0:
        return _run_at(bash, path, rest, str(Path.cwd()))

    # 递归模式：收集 depth 层目录，逐个跑
    dirs = _collect_dirs(str(Path.cwd()), depth)
    if not dirs:
        print(f"mt.sh {depth} {name}: 当前目录下第 {depth} 层没有子目录，退出。")
        return 0
    print(f"mt.sh {depth} {name} @ depth={depth}，共 {len(dirs)} 个目录", flush=True)
    max_rc = 0
    for d in dirs:
        rc = _run_at(bash, path, rest, d)
        if rc > max_rc:
            max_rc = rc
    print(f"mt.sh {depth} {name}: 完成 {len(dirs)} 个目录，返回码 {max_rc}", flush=True)
    return max_rc


if __name__ == "__main__":
    sys.exit(main())
