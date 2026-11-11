"""mt.ph: phonopy 声子谱计算流程（命令形态按本机 phonopy 版本选 v4+/v3）

    扩胞   phonopy-init -d --dim="2 2 1" -c POSCAR-unitcell  (supercell)
    力数据 一份 vasprun.xml -> --fc；多份 -> --sp -f         (fs)
    能带   phonopy --config band.conf [输入 yaml]            (band)
    态密度 phonopy --config mesh.conf [输入 yaml]            (dos)
    其它   tprop 热学性质(.dat) / born(NAC) / symmetry / qha / gruneisen
    词库   v / V 查本地 phonopy 用法（英文/中文）

输入 yaml 优先 phonopy_params.yaml（fs 的 --sp -f 生成），其次 phonopy_disp.yaml / phonopy.yaml（配合 FORCE_CONSTANTS / FORCE_SETS）。
结构文件自动探测 POSCAR-unitcell -> CONTCAR -> POSCAR（-c 指定）；DIM 取 1~3 个整数（-s，缺省补 1，默认 1 1 1）。
-n 给位移目录/后缀/范围（001-003、dir-{001..003}，花括号留给 bash 展开）；-x 单独用是单份力文件，配 -n 是各目录内的文件名。-b/-d 写 band.conf / mesh.conf（文件名 -B/-D，band/dos 也读它们；内容用 -p/-l/-N/-m）。

交互提示 B=返回上一层、Q=退出；执行命令需回车确认，-Y 跳过，-R 只打印。
无子命令默认扩胞；只给 -n 或 -x 执行 fs；只给 -b/-d 只写配置。
"""

import argparse
import functools
import os
import platform
import re
import shutil
import subprocess
import sys

from mcta import version_string


class StepBack(Exception):
    """用户输入 B：返回上一层。"""


class QuitFlow(Exception):
    """用户输入 Q：直接退出。"""

BAND_TEMPLATE = """\
DIM = {dim}
BAND = {band}
BAND_LABELS = {labels}
BAND_POINTS = {points}
"""

MESH_TEMPLATE = """\
DIM = {dim}
MP = {mp}
{pdos}"""

DEFAULT_DIM = "1 1 1"
DEFAULT_BAND = "0.0 0.0 0.0  0.5 0.0 0.0  0.5 0.5 0.5  0.0 0.0 0.0"
DEFAULT_LABELS = "G X M G"
DEFAULT_MP = "20 20 20"


def _parse_dim(text, default=DEFAULT_DIM):
    """把用户输入规范化为 "a b c" 三个整数。

    取输入中的前 3 个数字，不足补 1；忽略括号、引号与各种标点分隔符
    （空格 , ; / x X × * 等）。无数字时用默认值。
    """
    if text is None:
        return default
    nums = re.findall(r"\d+", str(text))
    if not nums:
        return default
    nums = nums[:3] + ["1"] * (3 - min(len(nums), 3))
    return " ".join(nums[:3])


# ---------------------------------------------------------------- helpers ---
def _fmt(cmd):
    """把命令列表拼成可读的命令行，含空格的参数自动加引号。"""
    return " ".join('"%s"' % c if " " in c else c for c in cmd)


def _ask(prompt, default):
    while True:
        suffix = " [%s]" % default if default not in (None, "") else ""
        try:
            answer = input("%s%s (B/b=返回, Q/q=退出): "
                           % (prompt, suffix)).strip()
        except EOFError:
            answer = ""
        if answer.upper() == "Q":
            print("已退出。")
            raise QuitFlow
        if answer.upper() == "B":
            raise StepBack
        return answer or default


def _read_conf_value(path, key):
    """从 conf 文件里取 ``KEY = value`` 的 value；文件不存在返回 None。"""
    if not os.path.exists(path):
        return None
    with open(path, "r", errors="ignore") as handle:
        for line in handle:
            if line.strip().upper().startswith(key.upper()):
                if "=" in line:
                    return line.split("=", 1)[1].strip()
    return None


def _write_file(path, content, yes, dry=False):
    if dry:
        # -R/--dryrn：只打印将要写入的内容，不创建文件
        print("--- %s（dry-run，未写入）" % path)
        print(content, end="")
        return True
    if os.path.exists(path) and not yes:
        while True:
            try:
                answer = (_ask("%s 已存在，覆盖？(y/N)" % path, None)
                          or "n").strip().lower()
                break
            except StepBack:
                continue  # B：重新询问
        if answer not in ("y", "yess"):
            print("保留原 %s。" % path)
            return False
    with open(path, "w") as handle:
        handle.write(content)
    print("已生成 %s" % path)
    return True


def _spawn(cmd, shell, stdout):
    """执行命令；含 {a..b} 花括号展开时优先用 bash（/bin/sh 多为 dash，不展开）。"""
    argv = None
    if shell and "{" in cmd and "}" in cmd:
        bash = shutil.which("bash")
        if bash:
            argv = [bash, "-c", cmd]
    if argv:
        return subprocess.run(argv, stdout=stdout, check=False)
    return subprocess.run(cmd, shell=shell, stdout=stdout, check=False)


def _run(cmd, yes, dry, stdout=None, quiet_fail=False):
    """打印命令并（确认后）执行；返回 'ok' / 'skip' / 'fail'。

    cmd 为字符串时经 shell 执行（支持 {001..020} 等 bash 展开）；
    quiet_fail=True 时由调用方自己判断失败原因（如 mt.band 固定返回 1）。
    """
    shell = isinstance(cmd, str)
    print("$ " + (cmd if shell else _fmt(cmd)) +
          (" > %s" % stdout if stdout else ""), flush=True)
    if not dry:
        if yes:
            answer = "y"
        else:
            try:
                answer = input("执行该命令？[Y/n]（B/b=返回上一层，Q/q=退出） ").strip()
            except EOFError:
                answer = ""
            if answer.upper() == "Q":
                print("已退出。")
                raise QuitFlow
            if answer.upper() == "B":
                raise StepBack
            answer = answer.lower()
        if answer not in ("", "y", "yess"):
            print("已跳过。")
            return "skip"
    if dry:
        return "ok"
    try:
        if stdout:
            with open(stdout, "w") as handle:
                result = _spawn(cmd, shell, handle)
        else:
            result = _spawn(cmd, shell, None)
    except FileNotFoundError as error:
        print("ERROR: 找不到可执行程序：%s" % error.filename)
        return "fail"
    if result.returncode != 0:
        if not quiet_fail:
            print("ERROR: 命令执行失败（返回码 %d）。" % result.returncode)
        return "fail"
    if stdout:
        print("已写入 %s" % stdout)
    return "ok"


RANGE_RE = re.compile(r"^(.*?)\{?(\d+)(?:\.\.|-)(\d+)\}?(.*)$")
FILE_PREFIX = "vasprun.xml"


def _parse_range(text):
    """解析 "001-003"、"{001..003}"、"dir-{001..003}"。

    返回 (head, lo, hi, width, tail)；不是范围形式时返回 None。
    head/tail 是数字前后的固定字符（如 "dir-"），width 是首位数字的宽度。
    """
    match = RANGE_RE.match(text)
    if not match:
        return None
    head, first, last, tail = match.groups()
    return head, int(first), int(last), len(first), tail


def _range_parts(text):
    """把一段取值拆成 (名字列表, 命令中的紧凑写法)。

    例如 "001-003" -> (["001","002","003"], "{001..003}")，
    "dir-{001..003}" -> (["dir-001",...], "dir-{001..003}")，
    普通名字 -> (["disp"], "disp")。
    """
    parsed = _parse_range(text)
    if parsed is None:
        return [text], text
    head, lo, hi, width, tail = parsed
    step = 1 if hi >= lo else -1
    stop = hi + 1 if step > 0 else hi - 1
    names = [head + str(i).zfill(width) + tail for i in range(lo, stop, step)]
    brace = "%s{%s..%s}%s" % (head, str(lo).zfill(width),
                              str(hi).zfill(width), tail)
    return names, brace


def _match_suffix_file(name):
    """同级目录中是否有 vasprun.xml-<name> 或 vasprun.xml_<name>。"""
    for sep in ("-", "_"):
        filename = FILE_PREFIX + sep + name
        if os.path.isfile(filename):
            return filename
    return None


def _need(cmd, name):
    if shutil.which(cmd) is None:
        print("ERROR: 未找到 %s 命令，请先安装 %s。" % (cmd, name))
        return False
    return True


DEFAULT_CELLS = ("POSCAR-unitcell", "CONTCAR", "POSCAR")
SUBCOMMANDS = ("supercell", "fs", "band", "dos", "tprop",
               "born", "symmetry", "qha", "gruneisen")


def _detect_cell():
    """按优先级自动探测结构文件，找不到返回 None。"""
    for name in DEFAULT_CELLS:
        if os.path.exists(name):
            return name
    return None


@functools.lru_cache(maxsize=1)
def _phonopy_version():
    """本机 phonopy 版本号（如 '4.10.0'），取不到返回 None。"""
    try:
        from importlib.metadata import version
        return version("phonopy")
    except Exception:
        pass
    try:
        import phonopy
        return getattr(phonopy, "__version__", None)
    except Exception:
        return None


def _phonopy_is_v4():
    """按本机 phonopy 版本判断命令形态：v4+ 用 phonopy-init / --config。"""
    v = _phonopy_version()
    if v:
        m = re.match(r"\s*(\d+)", str(v))
        if m:
            return int(m.group(1)) >= 4
    # 版本不可用时退化为能力探测：phonopy-init 是 v4+ 才提供的
    if shutil.which("phonopy-init"):
        return True
    if shutil.which("phonopy"):
        return False
    return True        # 完全没装 phonopy 时默认按 v4+ 显示


def _phonopy_prog(ctx):
    """setup 命令（-d/--fc/-f）：v4+ 用 phonopy-init，v3 用 phonopy。"""
    return "phonopy" if ctx.old else "phonopy-init"


def _yaml_arg(ctx):
    """v4 ``phonopy`` 后处理的输入文件。

    优先 phonopy_params.yaml（由 --sp 生成）；否则用 phonopy_disp.yaml /
    phonopy.yaml 配合同目录的 FORCE_CONSTANTS 或 FORCE_SETS（实测可行）；
    都没有时不传位置参数，让 phonopy 自行探测并给出报错。
    """
    for name in ("phonopy_params.yaml", "phonopy_disp.yaml", "phonopy.yaml"):
        if os.path.exists(name):
            return [name]
    return []


def _require_yaml(ctx):
    """非 dry-run 时要求至少有一个 phonopy 输入文件。"""
    if ctx.dry or _yaml_arg(ctx):
        return True
    print("ERROR: 找不到 phonopy 输入文件（phonopy_params.yaml / "
          "phonopy_disp.yaml / phonopy.yaml）；请先运行 mt.ph supercell，"
          "再运行 mt.ph fs。")
    return False


def _atom_count(path):
    """从 VASP 结构文件（POSCAR/CONTCAR）统计原子总数，失败返回 None。"""
    try:
        with open(path, "r", errors="ignore") as handle:
            lines = [handle.readline() for _ in range(7)]
    except OSError:
        return None
    for line in (lines[6], lines[5]):  # VASP5: 第7行是原子数；旧格式：第6行
        parts = line.split()
        try:
            return sum(int(x) for x in parts)
        except (ValueError, IndexError):
            continue
    return None


def _pdos_line(ctx):
    """mesh.conf 的 PDOS 行：v3/v4 都要原子序号列表（.TRUE. 会被当序号解析）。"""
    cell = getattr(ctx.args, "cells", None) or _detect_cell() or DEFAULT_CELLS[0]
    count = _atom_count(cell)
    if count:
        return "PDOS = " + " ".join(str(i) for i in range(1, count + 1)) + "\n"
    print("提示：未能从 %s 统计原子数，mesh.conf 未写 PDOS（仅输出总 DOS）。" % cell)
    return ""


# ------------------------------------------------------------------ steps ---
DIM_PROMPT = "超胞尺寸 DIM（1~3 个整数，其余补 1）"


def _dim_value(ctx):
    """取 DIM（命令行 -s 可传多个 token），规范化为 "a b c"。"""
    raw = ctx.get("dimns", DIM_PROMPT, DEFAULT_DIM)
    if isinstance(raw, (list, tuple)):
        raw = " ".join(str(x) for x in raw)
    return _parse_dim(raw)


def _band_conf_text(ctx):
    """band.conf 的内容（按需交互询问 DIM / BAND / BAND_LABELS / BAND_POINTS）。"""
    dim = _dim_value(ctx)
    band = ctx.get("bpath", "高对称点路径 BAND（分数坐标）", DEFAULT_BAND)
    labels = ctx.get("xlabl", "路径标签 BAND_LABELS", DEFAULT_LABELS)
    points = ctx.get("point", "每段路径取样点数 BAND_POINTS", "101")
    return BAND_TEMPLATE.format(dim=dim, band=band, labels=labels, points=points)


def _mesh_conf_text(ctx):
    """mesh.conf 的内容（按需交互询问 DIM / MP）。"""
    dim = _dim_value(ctx)
    mp = ctx.get("mgrid", "mesh 网格 MP", DEFAULT_MP)
    # v3/v4 的 PDOS 都只接受 "auto" 或原子序号列表，写 .TRUE. 会被当成序号解析
    pdos = _pdos_line(ctx)
    return MESH_TEMPLATE.format(dim=dim, mp=mp, pdos=pdos)


def make_band_conf(ctx, name):
    """mt.ph -b：只生成 band.conf（文件名由 -B 指定，默认 band.conf）。"""
    return _write_file(name, _band_conf_text(ctx), ctx.yes, ctx.dry)


def make_mesh_conf(ctx, name):
    """mt.ph -d：只生成 mesh.conf（文件名由 -D 指定，默认 mesh.conf）。"""
    return _write_file(name, _mesh_conf_text(ctx), ctx.yes, ctx.dry)


def step_supercell(ctx):
    """扩胞：phonopy(-init) -d --dim="..." -c CELL"""
    prog = _phonopy_prog(ctx)
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    cell = ctx.cell()
    if not ctx.dry and not os.path.exists(cell):
        print("ERROR: 找不到结构文件 %s（支持：%s，或用 -c 指定）。"
              % (cell, "/".join(DEFAULT_CELLS)))
        return False
    dim = _dim_value(ctx)
    # -d 生成 phonopy_disp.yaml；phonopy_params.yaml 由 mt.ph fs 的 --sp -f 生成
    cmd = [prog, "-d", "--dim=" + dim, "-c", cell]
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def _find_forces_file(directory, name="vasprun.xml"):
    """在目录中查找力计算文件：精确 name 优先，其次 name-数字（如 vasprun.xml-1）。

    找到返回文件名（相对 directory），没有返回 None。
    """
    if os.path.exists(os.path.join(directory, name)):
        return name
    cands = []
    try:
        for fn in os.listdir(directory):
            if fn.startswith(name) and re.match(r"^-\d+$", fn[len(name):]):
                cands.append(fn)
    except OSError:
        return None
    return sorted(cands)[0] if cands else None


def _probe_forces(directory, fname=None):
    """目录中的力计算文件：给了 fname 就只认它，否则自动查找。"""
    if fname:
        return fname if os.path.exists(os.path.join(directory, fname)) else None
    return _find_forces_file(directory)


def _fs_fc(ctx, given=None):
    """fs 的单份力文件分支 -> phonopy(-init) --fc FILE

    given 显式指定力文件（fs 已经数好只有一份时传入）；不给时用 -x：
    裸 -x / 不给 -x 都指当前目录的 vasprun.xml（不匹配 vasprun.xml-数字），
    给了文件就照用，给了目录则用其中的 vasprun.xml。
    """
    prog = _phonopy_prog(ctx)
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    if given is None:
        given = getattr(ctx.args, "xname", None)   # 裸 -x 为 ""，按默认处理
    if not given:
        if not ctx.dry and not os.path.isfile(FILE_PREFIX):
            print("ERROR: 当前目录没有 %s；可用 -x 指定文件或目录。" % FILE_PREFIX)
            return False
        fcfile = FILE_PREFIX
    elif os.path.isdir(given):
        fcfile = os.path.join(given, FILE_PREFIX)
        if not ctx.dry:
            if not os.path.isfile(fcfile):
                print("ERROR: 目录 %s 中没有 %s。" % (given, FILE_PREFIX))
                return False
            print("在目录 %s 中找到力计算文件 %s。" % (given, FILE_PREFIX))
    else:
        if not ctx.dry and not os.path.exists(given):
            print("ERROR: 找不到 %s。" % given)
            return False
        fcfile = given
    return _run([prog, "--fc", fcfile], ctx.yes, ctx.dry) != "fail"


def _split_tail(name):
    """把名字拆成 (前缀, 尾部数字串)；没有尾部数字时数字串为 None。

    例如 "001" -> ("", "001")，"dir-001" -> ("dir-", "001")。
    """
    match = re.match(r"^(.*?)(\d+)$", name)
    if not match:
        return name, None
    return match.group(1), match.group(2)


def _is_consecutive(prev, cur):
    """两个名字是否同前缀、同宽、尾号连续（如 002 -> 003、dir-002 -> dir-003）。"""
    head_prev, num_prev = _split_tail(prev)
    head_cur, num_cur = _split_tail(cur)
    if num_prev is None or num_cur is None:
        return False
    if head_prev != head_cur or len(num_prev) != len(num_cur):
        return False
    return int(num_cur) == int(num_prev) + 1


def _brace_of(names):
    """把一串连续名字写成花括号形式：[dir-001, dir-002] -> "dir-{001..002}"。"""
    head, first = _split_tail(names[0])
    _, last = _split_tail(names[-1])
    if first is None:
        return " ".join(names)
    return "%s{%s..%s}" % (head, first, last)


def _fdir_groups(tokens):
    """把 -n 的多个取值整理成若干组。

    每组是 {"names": [...], "brace": "..."}：names 是展开后的名字，
    brace 是命令中的紧凑写法（如 "{001..003}"、"dir-{001..003}"）。
    范围（001-003、{001..003}、dir-{001..003}）自成一组；连续的数字
    也自动合并——包括被 shell 提前展开成 dir-001 dir-002 dir-003 的情况。
    """
    groups = []
    for token in tokens:
        names, brace = _range_parts(token)
        if len(names) > 1:
            groups.append({"names": names, "brace": brace})
        elif groups and _is_consecutive(groups[-1]["names"][-1], names[0]):
            group = groups[-1]
            group["names"].append(names[0])
            group["brace"] = _brace_of(group["names"])
        else:
            groups.append({"names": names, "brace": names[0]})
    return groups


def _resolve_fdir_group(group, dry, fname=None):
    """判定一组名字是「同级 vasprun.xml 后缀文件」还是「含力文件的目录」。

    每个名字依次尝试：
      1) 同级文件 vasprun.xml-<名字> / vasprun.xml_<名字>（如 vasprun.xml-001）；
      2) 直接给出的完整文件名（如 vasprun.xml-001）；
      3) 目录 <名字>，且其中有 fname（未给 fname 时查找 vasprun.xml 或
         vasprun.xml-数字）。
    1/2/3 都没有才报错。返回 (kind, items, inner)：
      kind="file" -> items 是文件名列表，inner 为 None；
      kind="dir"  -> items 是目录列表，inner 是各目录中的力文件名。
    失败时返回 (None, None, None)。
    """
    kind = None
    items = []
    inner = []
    for name in group["names"]:
        found = _match_suffix_file(name)
        if found:
            current, item, sub = "file", found, None
        elif os.path.isfile(name):
            current, item, sub = "file", name, None   # 直接给了完整文件名
        elif os.path.isdir(name):
            sub = _probe_forces(name, fname)
            if sub is None:
                if not dry:
                    print("ERROR: 目录 %s 中没有 %s%s。"
                          % (name, fname or FILE_PREFIX,
                             "" if fname else "（或 %s-数字）" % FILE_PREFIX))
                    return None, None, None
                sub = fname or FILE_PREFIX        # dry-run 时目录可能还没准备
            current, item = "dir", name
        elif dry:
            current, item, sub = "dir", name, fname or FILE_PREFIX
        else:
            print("ERROR: %s 既不是含 %s 的目录，也没有同级的 %s-%s / %s_%s 文件。"
                  % (name, fname or FILE_PREFIX, FILE_PREFIX, name,
                     FILE_PREFIX, name))
            return None, None, None
        if kind and current != kind:
            print("ERROR: %s 这组同时包含目录和 %s 后缀文件，请分开指定。"
                  % (group["brace"], FILE_PREFIX))
            return None, None, None
        kind = current
        items.append(item)
        inner.append(sub)
    return kind, items, (inner if kind == "dir" else None)


def _fs_f(ctx, tokens=None):
    """fs 的多份力文件分支 -> phonopy(-init) [--sp] -f ...

    tokens 由 step_fs 传入；不给时回退到 -n / 交互询问。每个取值既可能
    是位移目录，也可能是同级 vasprun.xml 的后缀：先找同级
    vasprun.xml-<取值> / vasprun.xml_<取值>（如 vasprun.xml-001），
    再找目录 <取值>（且目录里要有力文件，如 001/vasprun.xml）；两者都没有
    才报错。dir-{001..003} 表示 dir-001、dir-002、dir-003 三个目录。
    命令中不逐个展开，写成花括号紧凑形式，展开交给 bash。
    """
    prog = _phonopy_prog(ctx)
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    raw = tokens
    if not raw:
        raw = getattr(ctx.args, "fdirs", None)
    if not raw:
        raw = ctx.get("fdirs",
                      "位移目录或 vasprun.xml 后缀，可多个（如 001-003）", None)
    if not raw:
        print("ERROR: 未指定位移目录（用 mt.ph fs 的位置参数或 -n 指定，"
              "例如 fs 001-003 或 -n dir-{001..003}）。")
        return False
    tokens = re.split(r"[,\s]+", raw) if isinstance(raw, str) else list(raw)
    groups = _fdir_groups([t for t in tokens if t])
    if not groups:
        print("ERROR: 未能解析位移目录：%s" % raw)
        return False

    # -x 指定各目录中的力文件名；不给时逐个目录自动查找 vasprun.xml
    fname = getattr(ctx.args, "xname", None)
    resolved = []
    for group in groups:
        kind, items, inner = _resolve_fdir_group(group, ctx.dry, fname)
        if kind is None:
            return False
        resolved.append((group, kind, items, inner))

    parts = []
    dir_count = file_count = 0
    for group, kind, items, inner in resolved:
        brace = group["brace"]
        if kind == "file":
            file_count += len(items)
            head, name = items[0], group["names"][0]
            prefix = head[:len(head) - len(name)] if head.endswith(name) else ""
            uniform = (prefix.startswith(FILE_PREFIX)
                       and prefix[len(FILE_PREFIX):] in ("-", "_")
                       and all(fn == prefix + n
                               for fn, n in zip(items, group["names"])))
            if uniform:
                # 命名统一：vasprun.xml-{001..003}
                parts.append(prefix + brace)
            else:
                parts += items          # 命名不统一：逐个列出
            continue
        dir_count += len(items)
        if len(set(inner)) == 1:
            parts.append("%s/%s" % (brace.rstrip("/"), inner[0]))
        else:
            parts += [os.path.join(d, n) for d, n in zip(items, inner)]

    # v4：--sp 把位移-力数据写进 phonopy_params.yaml，而不是 FORCE_SETS
    save = "--sp " if not ctx.old else ""
    cmd = "%s %s-f %s" % (prog, save, " ".join(parts))
    print("共 %d 个目录、%d 个同级 %s 后缀文件、%d 组；命令中不逐个展开"
          "（由 bash 展开花括号）。" % (dir_count, file_count, FILE_PREFIX,
                                        len(groups)))
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def step_fs(ctx):
    """力数据一步到位（原 fc 与 f 合并）：mt.ph fs

    数一共有几份 vasprun.xml 力文件：只有一份 -> --fc（力常数，
    FORCE_CONSTANTS 路径）；多于一份 -> [--sp] -f（FORCE_SETS /
    phonopy_params.yaml 路径）。力文件来源：

    * 位置参数（fs 的 NAME）：文件、含 vasprun.xml 的目录、位移目录 /
      后缀 / 范围（001-003、dir-{001..003}）；
    * -n/--fdirs：同位置参数，多个取值；
    * -x/--xname：单独使用 = 单份力文件（文件或目录）；与多个目录连用
      = 各目录内的力文件名（同 -f 分支）。

    什么都不给时：当前目录有 vasprun.xml 就走 --fc，否则交互询问。
    """
    tokens = [t for t in (getattr(ctx.args, "names", None) or []) if t]
    tokens += [t for t in (getattr(ctx.args, "fdirs", None) or []) if t]
    xname = getattr(ctx.args, "xname", None)

    if xname is not None and not tokens:
        # 只给 -x（或裸 -x -> ./vasprun.xml）：单份力文件
        return _fs_fc(ctx)
    if xname not in (None, "") and tokens:
        # -x 与多个目录连用：xname 是各目录内的力文件名
        return _fs_f(ctx, tokens)

    if not tokens:
        if os.path.isfile(FILE_PREFIX) or ctx.dry:
            return _fs_fc(ctx)         # 当前目录有 vasprun.xml（dry 预览默认）
        raw = ctx.get("fdirs",
                      "力文件 / 位移目录，可多个（如 vasprun.xml、001-003）",
                      None)
        if not raw:
            print("ERROR: 未指定力文件（可用 mt.ph fs 的位置参数、-n 或 -x）。")
            return False
        if isinstance(raw, str):
            tokens = [t for t in re.split(r"[,\s]+", raw) if t]
        else:
            tokens = [t for t in raw if t]
        if len(tokens) == 1 and os.path.isfile(tokens[0]):
            return _fs_fc(ctx, given=tokens[0])     # 只给了一份文件

    groups = _fdir_groups(tokens)
    if not groups:
        print("ERROR: 未能解析力文件：%s" % " ".join(tokens))
        return False
    total = 0
    resolved = []
    for group in groups:
        kind, items, inner = _resolve_fdir_group(group, ctx.dry, None)
        if kind is None:
            return False
        resolved.append((group, kind, items, inner))
        total += len(items)

    if total == 1:
        # 只有一份力文件：直接把它的路径交给 --fc
        group, kind, items, inner = resolved[0]
        if kind == "file" or not os.path.isdir(items[0]):
            fcfile = items[0]       # dry-run 时名字可能还不存在，按文件预览
        else:
            fcfile = os.path.join(items[0], inner[0])
        print("只有一份力文件 %s，执行 --fc。" % fcfile)
        return _fs_fc(ctx, given=fcfile)
    return _fs_f(ctx, tokens)


def step_band(ctx):
    """能带：计算 band.yaml，再导出 BAND.dat。"""
    if not ctx.dry and not _need("phonopy", "phonopy"):
        return False
    conf = getattr(ctx.args, "bfile", None) or "band.conf"
    if not ctx.dry and not os.path.exists(conf):
        print("ERROR: 找不到 %s；请先运行 mt.ph -b。" % conf)
        return False

    if not ctx.old:
        if not _require_yaml(ctx):
            return False
        status = _run(["phonopy", "--config", conf] + _yaml_arg(ctx),
                      ctx.yes, ctx.dry)
    else:
        cell = ctx.cell()
        if not ctx.dry and not os.path.exists(cell):
            print("ERROR: 找不到结构文件 %s（用 -c 指定）。" % cell)
            return False
        dim = _dim_value(ctx)
        status = _run(["phonopy", "--dim=" + dim, "-c", cell, conf], ctx.yes, ctx.dry)

    if status == "fail":
        return False
    if status == "ok" and not ctx.dry:
        if not os.path.exists("band.yaml"):
            print("ERROR: 未生成 band.yaml，无法导出 BAND.dat。")
            return False
    if not ctx.dry and not _need("phonopy-bandplot", "phonopy"):
        return False
    # v3/v4 的 phonopy-bandplot 都只认 --gnuplot（--legacy 是更老版本才有的）
    plot_cmd = ["phonopy-bandplot", "--gnuplot"]
    result = _run(plot_cmd, ctx.yes, ctx.dry, stdout="BAND.dat", quiet_fail=True)
    if result == "fail":
        # 新版 phonopy-bandplot --gnuplot 写出文件后固定返回退出码 1
        if (not ctx.dry and os.path.exists("BAND.dat")
                and os.path.getsize("BAND.dat") > 0):
            print("BAND.dat 已生成（phonopy-bandplot 退出码非 0，已忽略）。")
            return True
        print("ERROR: 未能生成 BAND.dat。")
        return False
    return True


def step_dos(ctx):
    """态密度：projected_dos.dat（可选 total_dos.dat）。"""
    if not ctx.dry and not _need("phonopy", "phonopy"):
        return False
    conf = getattr(ctx.args, "mfile", None) or "mesh.conf"
    if not ctx.dry and not os.path.exists(conf):
        print("ERROR: 找不到 %s；请先运行 mt.ph -d。" % conf)
        return False

    if not ctx.old:
        if not _require_yaml(ctx):
            return False
        yamls = _yaml_arg(ctx)
        projected = _read_conf_value(conf, "PDOS") is not None
        if not projected:
            # conf 中没有 PDOS：只输出总 DOS，跑一次即可，不必再问 total
            return _run(["phonopy", "--config", conf] + yamls,
                        ctx.yes, ctx.dry) != "fail"
        status = _run(["phonopy", "--config", conf] + yamls, ctx.yes, ctx.dry)
        if status == "fail":
            return False
        want_total = ctx.total
        if want_total is None and not ctx.dry and not ctx.yes:
            answer = _ask("是否同时输出 total_dos.dat？y/n", "n")
            want_total = answer.strip().lower() in ("y", "yess")
        if want_total:
            # conf 里的 PDOS 会让 --dos 转为投影 DOS，需临时去掉
            total_conf = conf + ".total-tmp"
            if not ctx.dry:
                with open(conf, "r", errors="ignore") as src, \
                     open(total_conf, "w") as dst:
                    for line in src:
                        if not line.strip().upper().startswith("PDOS"):
                            dst.write(line)
            ok = _run(["phonopy", "--dos", "--config", total_conf] + yamls,
                      ctx.yes, ctx.dry) != "fail"
            if not ctx.dry:
                os.remove(total_conf)
            return ok
        return True

    status = _run(["phonopy", "-p", conf], ctx.yes, ctx.dry)
    if status == "fail":
        return False
    want_total = ctx.total
    if want_total is None and not ctx.dry and not ctx.yes:
        answer = _ask("同时输出 total_dos.dat？y/n", "n")
        want_total = answer.strip().lower() in ("y", "yess")
    if want_total:
        return _run(["phonopy", "-t", conf], ctx.yes, ctx.dry) != "fail"
    return True



# ------------------------------------------------------- 常用扩展命令 ---
DEFAULT_PROPS = "thermal_properties.yaml"


def _dat_output(ctx):
    """热学性质数据文件：-o 优先，否则 thermal_properties.dat。"""
    return getattr(ctx.args, "outpt", None) or "thermal_properties.dat"


def _temp_opts(ctx):
    """热学温度选项（phonopy 原生长名，原样透传）。"""
    opts = []
    for key in ("tmin", "tmax", "tstep"):
        value = getattr(ctx.args, key, None)
        if value is not None:
            opts += ["--" + key, str(value)]
    return opts


def _grid_tokens(ctx):
    raw = getattr(ctx.args, "mgrid", None)
    if raw:
        nums = re.findall(r"\d+", str(raw))
        if nums:
            return nums[:3]
    return DEFAULT_MP.split()


def _prop_dat_cmd(ctx, inputs=None):
    """phonopy-propplot --gnuplot：只导出数据列，不调用绘图后端。"""
    return ["phonopy-propplot", "--gnuplot"] + (inputs or [DEFAULT_PROPS])


def step_tprop(ctx):
    """热学性质：phonopy -t -> thermal_properties.yaml，再导出 .dat 数据列。

    不生成图片；phonopy-propplot --gnuplot 只把温度、自由能、熵、热容、
    能量写成纯文本列，供后续自行绘图或 phonopy-qha 使用。
    """
    if not ctx.dry and not _need("phonopy", "phonopy"):
        return False
    if not ctx.old:
        if not _require_yaml(ctx):
            return False
        cmd = (["phonopy", "--mesh"] + _grid_tokens(ctx) + ["-t"]
               + _temp_opts(ctx) + _yaml_arg(ctx))
    else:
        conf = getattr(ctx.args, "mfile", None) or "mesh.conf"
        if not ctx.dry and not os.path.exists(conf):
            print("ERROR: 找不到 %s；请先运行 mt.ph -d。" % conf)
            return False
        cmd = ["phonopy", "-t", conf] + _temp_opts(ctx)
    if _run(cmd, ctx.yes, ctx.dry) == "fail":
        return False
    if not ctx.dry and not _need("phonopy-propplot", "phonopy"):
        return False
    # --gnuplot 输出到 stdout，重定向为 .dat；全程不产生图片
    return _run(_prop_dat_cmd(ctx), ctx.yes, ctx.dry,
                stdout=_dat_output(ctx)) != "fail"


def step_symmetry(ctx):
    """对称性检查：phonopy(-init) --symmetry -c CELL -> BPOSCAR / PPOSCAR。"""
    prog = _phonopy_prog(ctx)
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    cell = ctx.cell()
    if not ctx.dry and not os.path.exists(cell):
        print("ERROR: 找不到结构文件 %s（用 -c 指定）。" % cell)
        return False
    return _run([prog, "--symmetry", "-c", cell], ctx.yes, ctx.dry) != "fail"


def step_born(ctx):
    """BORN / NAC：phonopy-vasp-born -> BORN（极性体系 LO-TO 分裂必需）。"""
    prog = "phonopy-vasp-born"
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    cmd = [prog]
    if getattr(ctx.args, "nost", False):
        cmd.append("--nost")
    if getattr(ctx.args, "dimns", None) is not None:
        cmd.append("--dim=" + _dim_value(ctx))
    if getattr(ctx.args, "outcar", False):
        # OUTCAR 模式需要同时给出 OUTCAR 与含结构信息的文件
        inputs = ["OUTCAR", ctx.cell()]
        cmd += ["--outcar"] + inputs
    else:
        inputs = [getattr(ctx.args, "xname", None) or FILE_PREFIX]
        cmd += inputs
    if not ctx.dry:
        missing = [f for f in inputs if not os.path.exists(f)]
        if missing:
            print("ERROR: 找不到 %s；BORN 需要 VASP 的 vasprun.xml / "
                  "vaspout.h5，或 --outcar 时的 OUTCAR + POSCAR。"
                  % ", ".join(missing))
            return False
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def step_qha(ctx):
    """准谐近似：phonopy-qha e-v.dat thermal_properties.yaml-*。"""
    prog = "phonopy-qha"
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    raw = getattr(ctx.args, "files", None)
    if not raw:
        raw = ctx.get("files",
                      "e-v.dat 与各体积的 thermal_properties.yaml（空格分隔）", None)
    if not raw:
        print("ERROR: 未提供输入文件（用 -F 指定 e-v.dat 与各体积的 "
              "thermal_properties.yaml）。")
        return False
    tokens = re.split(r"[,\s]+", raw) if isinstance(raw, str) else list(raw)
    names = [t for t in tokens if t]
    if len(names) < 2 and not ctx.dry:
        print("ERROR: 至少需要 e-v.dat 与 1 个 thermal_properties.yaml；"
              "EOS 拟合要求至少 5 个体积点。")
        return False
    cmd = prog
    if getattr(ctx.args, "plots", False):
        cmd += " -p"
    if getattr(ctx.args, "saved", False):
        cmd += " -s"
    for key in ("tmax", "eos", "sparse", "pressure", "efe"):
        value = getattr(ctx.args, key, None)
        if value is not None:
            cmd += " --%s=%s" % (key, value)
    cmd += " " + " ".join(names)
    # 字符串命令：保留 {00..10} 之类的花括号，交给 bash 展开
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def step_gruneisen(ctx):
    """模式 Grüneisen 参数：三个体积点 -> gruneisen.yaml。"""
    prog = "phonopy-gruneisen"
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    dirs = getattr(ctx.args, "gdirs", None) or ["orig", "plus", "minus"]
    if len(dirs) != 3:
        print("ERROR: -G 需要正好 3 个目录（平衡体积、较大体积、较小体积）。")
        return False
    # phonopy-gruneisen 会在每个体积目录里查找与 -c 同名的结构文件，
    # 以及 FORCE_SETS（默认）或 FORCE_CONSTANTS（需 --readfc）。
    cell_name = os.path.basename(ctx.cell())
    use_readfc = False
    for name in dirs:
        if not os.path.isdir(name):
            if ctx.dry:
                continue
            print("ERROR: 找不到体积目录 %s。" % name)
            return False
        has_fs = os.path.exists(os.path.join(name, "FORCE_SETS"))
        has_fc = os.path.exists(os.path.join(name, "FORCE_CONSTANTS"))
        if has_fc and not has_fs:
            use_readfc = True
        if ctx.dry:
            continue
        if not os.path.exists(os.path.join(name, cell_name)):
            print("ERROR: 目录 %s 中缺少结构文件 %s（-c 指定的文件名需与"
                  "各体积目录内的结构文件同名）。" % (name, cell_name))
            return False
        if not has_fs and not has_fc:
            print("ERROR: 目录 %s 中缺少 FORCE_SETS 或 FORCE_CONSTANTS。" % name)
            return False
    cmd = [prog] + list(dirs) + ["--dim=" + _dim_value(ctx)]
    if use_readfc:
        cmd.append("--readfc")
    if getattr(ctx.args, "mgrid", None) is not None:
        cmd.append("--mp=" + " ".join(_grid_tokens(ctx)))
    if getattr(ctx.args, "band", None):
        cmd.append("--band=" + str(ctx.args.band))
    if getattr(ctx.args, "plots", False):
        cmd.append("-p")
    if getattr(ctx.args, "outpt", None):
        cmd += ["-o", ctx.args.outpt]
    cmd += ["-c", ctx.cell()]
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


# -------------------------------------------------------------------- ctx ---
class Ctx:
    """收集命令行参数与交互输入，同一取值只问一次。"""

    def __init__(self, args):
        self.args = args
        self.yes = getattr(args, "yesal", False)
        self.dry = getattr(args, "dryrn", False)
        # --total / --no-total 不再共用 dest：在这里合成
        # None（未指定，交互询问）/ True（写）/ False（不写）
        if getattr(args, "no_total", False):
            self.total = False
        elif getattr(args, "total", False):
            self.total = True
        else:
            self.total = None
        # 命令形态按本机 phonopy 版本自动选择：v4+ 用 phonopy-init +
        # --config + phonopy_params.yaml，v3 用 phonopy 的旧式选项
        self.old = not _phonopy_is_v4()
        self._cache = {}
        self._order = []   # 交互提问的 key 顺序，供 B 回退使用

    def get(self, key, prompt, default=None):
        if key in self._cache:
            return self._cache[key]
        value = getattr(self.args, key, None)
        if value == "":
            # 裸 -b/-d（不带文件名）：使用默认文件执行该步骤
            value = None
        if value is None and not self.dry and not self.yes:
            self._order.append(key)
            try:
                value = _ask(prompt, default)
            except (StepBack, QuitFlow):
                # 回退/退出时把自己从栈里拿掉，让 back() 弹出上一个问题
                self._order.remove(key)
                raise
        elif value is None:
            value = default
        self._cache[key] = value
        return value

    def cell(self, prompt="原胞结构文件（POSCAR-unitcell/CONTCAR/POSCAR）"):
        """结构文件：-c 优先，其次自动探测，都没有才交互询问。"""
        given = getattr(self.args, "cells", None)
        if given:
            return given
        found = _detect_cell()
        if found:
            return found          # 目录里有就直接用，不再提问
        return self.get("cells", prompt, DEFAULT_CELLS[0])

    def back(self):
        """B：撤销最近一个交互提问，供步骤重走；无可回退时返回 False。"""
        if not self._order:
            return False
        key = self._order.pop()
        self._cache.pop(key, None)
        return True


# ------------------------------------------------------------------- main ---
def main():
    # mt.ph v / V：查询词常是 --dim、-t 这类选项形式，argparse 会把它们
    # 误解析为选项，因此在 parser 之前直接处理，保留全部原始 token。
    argv = sys.argv[1:]
    if argv and argv[0] in ("v", "V"):
        from mcta.bandplot import phdoc
        sys.exit(phdoc.run(argv[1:]))

    parser = argparse.ArgumentParser(
        prog="mt.ph",
        add_help=False,
        # 开头的模块说明直接作为 -h 的 description
        description=(__doc__ or "").strip(),
        epilog=r'''
Example（命令按本机 phonopy 版本自动选择）:
mt.ph                               # 扩胞（默认步骤）
mt.ph -b -d -p "0 0 0 0.5 0 0" -l "G X" -N 51 -m "20 20 20"
mt.ph fs vasprun.xml                # 单份力文件 -> --fc
mt.ph -n 001-003                    # 多份 -> --sp -f vasprun.xml-{001..003}
mt.ph band                          # band.conf -> band.yaml -> BAND.dat
mt.ph -R supercell -s 2 2 1         # 只预览命令，不执行
mt.ph v --dim BAND_LABELS           # 查词库
''',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",       action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version", action="version", version=version_string())

    def common(p):
        # 子命令里重复定义顶层已有的选项时用 SUPPRESS 默认值，
        # 避免未给出时覆盖顶层解析结果；两种书写位置均可：
        # mt.ph -c POSCAR band  与  mt.ph band -c POSCAR
        p.add_argument('-Y', "--yesal", action="store_true",
                       default=argparse.SUPPRESS,
                       help="do not ask before running commands")
        p.add_argument('-R', "--dryrn", action="store_true",
                       default=argparse.SUPPRESS,
                       help="only print the commands, do not run them")
        p.add_argument('-s', "--dimns", nargs="+", default=argparse.SUPPRESS, metavar="N",
                       help='supercell dimension, 1-3 integers, default "1 1 1"')
        p.add_argument('-c', "--cells", default=argparse.SUPPRESS, metavar="FILE",
                       help="unit cell file (auto-detected)")
        p.add_argument('-x', "--xname", nargs="?", const="",
                       default=argparse.SUPPRESS, metavar="FILE",
                       help="forces file; alone -> --fc route (file or dir), "
                            "with -n -> name inside each dir")

    common(parser)
    parser.add_argument('-n', "--fdirs", nargs="+", default=None, metavar="dir",
                        help="displaced dirs / suffixes / ranges (implied fs), "
                             "e.g. 001-003, dir-{001..003}")
    parser.add_argument('-b', "--bconf", action="store_true",
                        help="write band.conf (name from -B)")
    parser.add_argument('-d', "--mconf", action="store_true",
                        help="write mesh.conf (name from -D)")
    parser.add_argument('-B', "--bfile", default=None,
                        metavar="FILE",
                        help="band.conf name (written by -b, read by mt.ph band)")
    parser.add_argument('-D', "--mfile", default=None,
                        metavar="FILE",
                        help="mesh.conf name (written by -d, read by mt.ph dos)")
    parser.add_argument('-p', "--bpath", default=None,
                        help='BAND path in fractional coordinates (with -b)')
    parser.add_argument('-l', "--xlabl", default=None,
                        help='BAND_LABELS of the path (with -b)')
    parser.add_argument('-N', "--point", default=None, metavar="N",
                        help='BAND_POINTS per segment, default: 101 (with -b)')
    parser.add_argument('-m', "--mgrid", default=None,
                        help='mesh grid for DOS, e.g. "20 20 20" (with -d)')
    sub = parser.add_subparsers()

    p_sc = sub.add_parser('supercell', help='phonopy-init -d --dim=... -c CELL')
    p_sc.set_defaults(cmd='supercell')
    common(p_sc)

    p_fs = sub.add_parser(
        'fs', help='one vasprun.xml -> --fc, many -> [--sp] -f')
    p_fs.set_defaults(cmd='fs')
    common(p_fs)
    p_fs.add_argument('names', nargs='*', default=argparse.SUPPRESS,
                      metavar="NAME",
                      help="force sources: one vasprun.xml (file or directory "
                           "holding it) runs --fc; several run -f")
    p_fs.add_argument('-n', "--fdirs", nargs="+", default=argparse.SUPPRESS,
                      metavar="NAME",
                      help="same as the top-level -n")

    p_band = sub.add_parser('band', help='band.conf -> band.yaml -> BAND.dat')
    p_band.set_defaults(cmd='band')
    common(p_band)
    p_band.add_argument('-B', "--bfile", nargs="?", const="",
                        default=argparse.SUPPRESS, metavar="FILE",
                        help="band setting file, default: band.conf")

    p_dos = sub.add_parser('dos', help='mesh.conf -> projected_dos.dat')
    p_dos.set_defaults(cmd='dos')
    common(p_dos)
    p_dos.add_argument('-D', "--mfile", nargs="?", const="",
                       default=argparse.SUPPRESS, metavar="FILE",
                       help="mesh setting file, default: mesh.conf")
    total_group = p_dos.add_mutually_exclusive_group()
    total_group.add_argument('--total', action='store_true', default=None,
                             help="also write total_dos.dat (phonopy -t)")
    total_group.add_argument('--no-total', action='store_true', default=False,
                             help="do not ask about total_dos.dat")

    p_tp = sub.add_parser('tprop',
                          help='thermal properties -> thermal_properties.yaml + .dat')
    p_tp.set_defaults(cmd='tprop')
    common(p_tp)
    p_tp.add_argument('-m', "--mgrid", default=argparse.SUPPRESS,
                      metavar='"20 20 20"',
                      help='mesh grid for thermal properties (default "20 20 20")')
    p_tp.add_argument('-o', "--outpt", default=argparse.SUPPRESS, metavar="FILE",
                      help='output .dat data file (default thermal_properties.dat)')
    p_tp.add_argument('--tmin', default=argparse.SUPPRESS, metavar="T",
                      help='TMIN, phonopy native option')
    p_tp.add_argument('--tmax', default=argparse.SUPPRESS, metavar="T",
                      help='TMAX, phonopy native option')
    p_tp.add_argument('--tstep', default=argparse.SUPPRESS, metavar="T",
                      help='TSTEP, phonopy native option')

    p_sy = sub.add_parser('symmetry',
                          help='phonopy-init --symmetry -> BPOSCAR / PPOSCAR')
    p_sy.set_defaults(cmd='symmetry')
    common(p_sy)

    p_bn = sub.add_parser('born',
                          help='phonopy-vasp-born -> BORN (NAC / LO-TO splitting)')
    p_bn.set_defaults(cmd='born')
    common(p_bn)
    p_bn.add_argument('--outcar', action='store_true',
                      default=argparse.SUPPRESS,
                      help='read OUTCAR + POSCAR instead of vasprun.xml')
    p_bn.add_argument('--nost', action='store_true', default=argparse.SUPPRESS,
                      help='do not symmetrize Born charges / dielectric tensor')

    p_qh = sub.add_parser('qha', help='quasi-harmonic approximation (phonopy-qha)')
    p_qh.set_defaults(cmd='qha')
    common(p_qh)
    p_qh.add_argument('-F', "--files", nargs="+", default=argparse.SUPPRESS,
                      metavar="FILE",
                      help='e-v.dat followed by thermal_properties.yaml-* '
                           '(>= 5 volume points)')
    p_qh.add_argument('-P', "--plots", action="store_true",
                      default=argparse.SUPPRESS, help='show plots (phonopy-qha -p)')
    p_qh.add_argument('-S', "--saved", action="store_true",
                      default=argparse.SUPPRESS,
                      help='save plot data in PDF (phonopy-qha -s)')
    for _key, _help in (("tmax", "maximum temperature"),
                        ("eos", "vinet / birch_murnaghan / murnaghan"),
                        ("sparse", "thin out F-V plots"),
                        ("pressure", "pressure in GPa"),
                        ("efe", "electronic free energy file")):
        p_qh.add_argument("--" + _key, default=argparse.SUPPRESS, metavar="VAL",
                          help=_help)

    p_gr = sub.add_parser('gruneisen',
                          help='mode Gruneisen parameters (phonopy-gruneisen)')
    p_gr.set_defaults(cmd='gruneisen')
    common(p_gr)
    p_gr.add_argument('-G', "--gdirs", nargs=3, default=argparse.SUPPRESS,
                      metavar="DIR",
                      help='three volume dirs: equilibrium, plus, minus '
                           '(default orig plus minus); each needs the -c '
                           'cell file and FORCE_SETS / FORCE_CONSTANTS')
    p_gr.add_argument('-P', "--plots", action="store_true",
                      default=argparse.SUPPRESS,
                      help='plot (phonopy-gruneisen -p)')
    p_gr.add_argument('-o', "--outpt", default=argparse.SUPPRESS, metavar="FILE",
                      help='output filename (phonopy-gruneisen -o)')
    p_gr.add_argument('-m', "--mgrid", default=argparse.SUPPRESS,
                      metavar='"20 20 20"',
                      help='sampling mesh (phonopy-gruneisen --mp)')
    p_gr.add_argument('--band', default=argparse.SUPPRESS,
                      metavar='"0 0 0 0.5 0 0"',
                      help='band path in reduced coordinates')

    # v / V 放在最后；真正解析在 main() 开头（词形 --dim 等会干扰 argparse）
    p_doc = sub.add_parser(
        'v', aliases=['V'],
        help='phonopy wordbook (no word: list; EN first, then ZH)')
    p_doc.set_defaults(cmd='docs')
    p_doc.add_argument('words', nargs=argparse.REMAINDER,
                       help='commands / options / tags to look up, e.g. '
                            '--dim BAND_LABELS; --all prints the whole file')

    args = parser.parse_args()
    if not hasattr(args, "cmd"):
        args.cmd = None               # 无子命令时 add_subparsers 不写 cmd
    if args.cmd == "docs":
        from mcta.bandplot import phdoc
        sys.exit(phdoc.run(getattr(args, "words", [])))
    # -b/-d 只写配置文件，与 -n（执行 fs）/ -x（执行 fs）混用容易误以为会跑计算
    if args.cmd is None and (args.bconf or args.mconf):
        if getattr(args, "fdirs", None) or getattr(args, "xname", None) is not None:
            print("ERROR: -b/-d 只写配置文件，不能与 -n / -x 同时使用。")
            sys.exit(1)
    # -n/--fdirs 是 nargs="+"，若把子命令写在它后面会被吞掉，这里还原：
    # mt.ph -n 001-003 fs  ->  cmd="fs", fdir=["001-003"]
    if args.cmd is None and isinstance(getattr(args, "fdirs", None), list):
        if len(args.fdirs) > 1 and args.fdirs[-1] in SUBCOMMANDS:
            args.cmd = args.fdirs.pop()
        if args.cmd is None:
            args.cmd = "fs"           # 给了 -n 就默认执行 mt.ph fs
    # -x 是 nargs="?"，同样可能吞掉后面的子命令：mt.ph -x calc/ fc
    if args.cmd is None and getattr(args, "xname", None) in SUBCOMMANDS:
        args.cmd = args.xname
        args.xname = ""
    ctx = Ctx(args)
    print("检测到 phonopy %s，命令形态：%s。" %
          (_phonopy_version() or "版本未知", "v3 旧版" if ctx.old else "v4+ 新版"))

    def run_step(step):
        """运行一个步骤；捕获 B（回退一个提问后重走该步骤）与 Q（退出）。"""
        while True:
            try:
                return step(ctx)
            except StepBack:
                if ctx.back():
                    print("(返回上一层)")
                else:
                    print("(已是最上层，重新开始本步骤)")
            except QuitFlow:
                sys.exit(0)

    gen_options = (args.bpath or args.xlabl or args.point or args.mgrid
                   or args.bfile or args.mfile)
    if args.cmd is None and (args.bconf or args.mconf):
        # mt.ph -b / -d：只生成对应的配置文件（文件名 -B / -D，或默认名）
        if not args.bconf and (args.bpath or args.xlabl or args.point):
            print("ERROR: --bpath/--xlabl/--point 需与 -b 一起使用。")
            sys.exit(1)
        if not args.mconf and args.mgrid:
            print("ERROR: --mgrid 需与 -d 一起使用。")
            sys.exit(1)

        def gen_band(c):
            return make_band_conf(c, args.bfile or "band.conf")

        def gen_mesh(c):
            return make_mesh_conf(c, args.mfile or "mesh.conf")

        ok = True
        if args.bconf:
            ok = run_step(gen_band)
        if args.mconf:
            ok = run_step(gen_mesh) and ok
        sys.exit(0 if ok else 1)

    if args.cmd is None and gen_options:
        print("ERROR: --bpath/--xlabl/--point/--mgrid/-B/-D 需与 -b 或 -d 一起使用，"
              "例如 mt.ph -b -B band-new.conf。")
        sys.exit(1)

    if args.cmd is None and getattr(args, "xname", None) is not None:
        args.cmd = "fs"               # 只给 -x（没有 -n）时执行 mt.ph fs

    if args.cmd in ("supercell", None):
        # 不带子命令默认执行扩胞
        if not run_step(step_supercell):
            sys.exit(1)

    steps = {
        "fs": step_fs,
        "band": step_band,
        "dos": step_dos,
        "tprop": step_tprop,
        "symmetry": step_symmetry,
        "born": step_born,
        "qha": step_qha,
        "gruneisen": step_gruneisen,
    }
    if args.cmd in steps and not run_step(steps[args.cmd]):
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
