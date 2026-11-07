"""mt.ph —— phonopy 声子谱计算流程

生成 band.conf / mesh.conf，并按步骤提示、执行 phonopy 命令。
默认新版（phonopy v4+）命令，加 -O/--old 改用旧版（v3）：

    扩胞    phonopy-init -d --dim="2 2 1" -c POSCAR-unitcell     (mt.ph supercell)
    力常数  phonopy-init --fc vasprun.xml                        (mt.ph fc)
    位移力  phonopy-init -f {001..020}/vasprun.xml               (mt.ph f)
    能带    phonopy --config band.conf phonopy_params.yaml
    态密度  phonopy --config mesh.conf phonopy_params.yaml
    -O      phonopy -d / --fc / -f、-c --dim、-p / -t

结构文件按 POSCAR-unitcell -> CONTCAR -> POSCAR 自动探测，找到即用，
都没有才询问（-c 可指定）。DIM 取 1~3 个整数，缺省补 1（默认 1 1 1），
分隔符不限（空格 , ; / x × * 等），-s 后可跟多个数字。
-n 给多个目录/后缀/范围（-n 001-003、-n dir-{001..003}）：先查同级
vasprun.xml-取值 / vasprun.xml_取值，再查含力文件的目录；命令保留
{001..003} 花括号形式，展开交给 bash。
-r/--xname 力文件（默认 vasprun.xml）：无 -n 时执行 fc（文件或目录，
目录中只认 vasprun.xml）；有 -n 时执行 f（各目录内的力文件名）。
-b 写 band.conf、-d 写 mesh.conf，文件名由 -B / -D 指定（可同时给）；
mt.ph band / dos 也用 -B / -D 指定要读的配置文件。

提示中 B/b+回车 = 返回上一层，Q/q+回车 = 退出；
执行命令需回车确认，-Y 跳过确认，-y 只打印不执行。
无子命令默认扩胞；只给 -n 执行 f；只给 -r 执行 fc；只给 -b/-d 只写配置。
"""

import argparse
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
        # -y/--dry-run：只打印将要写入的内容，不创建文件
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
        if answer not in ("y", "yes"):
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
        if answer not in ("", "y", "yes"):
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
SUBCOMMANDS = ("supercell", "fc", "f", "band", "dos")


def _detect_cell():
    """按优先级自动探测结构文件，找不到返回 None。"""
    for name in DEFAULT_CELLS:
        if os.path.exists(name):
            return name
    return None


def _phonopy_prog(ctx):
    """setup 命令（-d/--fc/-f）：新版默认 phonopy-init，-O 时用 phonopy。"""
    return "phonopy" if ctx.old else "phonopy-init"


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
    """v4 的 mesh.conf 需要 PDOS = 原子序号列表。"""
    cell = getattr(ctx.args, "cell", None) or _detect_cell() or DEFAULT_CELLS[0]
    count = _atom_count(cell)
    if count:
        return "PDOS = " + " ".join(str(i) for i in range(1, count + 1)) + "\n"
    print("提示：未能从 %s 统计原子数，mesh.conf 未写 PDOS（仅输出总 DOS）。" % cell)
    return ""


# ------------------------------------------------------------------ steps ---
DIM_PROMPT = "超胞尺寸 DIM（1~3 个整数，其余补 1）"


def _dim_value(ctx):
    """取 DIM（命令行 -s 可传多个 token），规范化为 "a b c"。"""
    raw = ctx.get("dim", DIM_PROMPT, DEFAULT_DIM)
    if isinstance(raw, (list, tuple)):
        raw = " ".join(str(x) for x in raw)
    return _parse_dim(raw)


def _band_conf_text(ctx):
    """band.conf 的内容（按需交互询问 DIM / BAND / BAND_LABELS / BAND_POINTS）。"""
    dim = _dim_value(ctx)
    band = ctx.get("band", "高对称点路径 BAND（分数坐标）", DEFAULT_BAND)
    labels = ctx.get("labels", "路径标签 BAND_LABELS", DEFAULT_LABELS)
    points = ctx.get("points", "每段路径取样点数 BAND_POINTS", "101")
    return BAND_TEMPLATE.format(dim=dim, band=band, labels=labels, points=points)


def _mesh_conf_text(ctx):
    """mesh.conf 的内容（按需交互询问 DIM / MP）。"""
    dim = _dim_value(ctx)
    mp = ctx.get("mp", "mesh 网格 MP", DEFAULT_MP)
    pdos = "PDOS = .TRUE.\n" if ctx.old else _pdos_line(ctx)
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
    return _run([prog, "-d", "--dim=" + dim, "-c", cell],
                ctx.yes, ctx.dry) != "fail"


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


def step_fc(ctx):
    """力常数：mt.ph fc（或只给 -r）-> phonopy(-init) --fc FILE

    -r 默认为 vasprun.xml：不给 -r 时只看当前目录的 vasprun.xml
    （不匹配 vasprun.xml-数字）；给了文件就照用，给了目录则用其中的
    vasprun.xml。
    """
    prog = _phonopy_prog(ctx)
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    given = getattr(ctx.args, "fc", None)          # 裸 -r 为 ""，按默认处理
    if not given:
        if not ctx.dry and not os.path.isfile(FILE_PREFIX):
            print("ERROR: 当前目录没有 %s；可用 -r 指定文件或目录。" % FILE_PREFIX)
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


def step_f(ctx):
    """FORCE_SETS：mt.ph f -> phonopy(-init) -f ...

    -n 的每个取值既可能是位移目录，也可能是同级 vasprun.xml 的后缀：
    先找同级 vasprun.xml-<取值> / vasprun.xml_<取值>（如 vasprun.xml-001），
    再找目录 <取值>（且目录里要有力文件，如 001/vasprun.xml）；两者都没有
    才报错。dir-{001..003} 表示 dir-001、dir-002、dir-003 三个目录。
    命令中不逐个展开，写成花括号紧凑形式，展开交给 bash。
    """
    prog = _phonopy_prog(ctx)
    if not ctx.dry and not _need(prog, "phonopy"):
        return False
    raw = getattr(ctx.args, "fdirs", None)
    if not raw:
        raw = ctx.get("fdirs",
                      "位移目录或 vasprun.xml 后缀，可多个（如 001-003）", None)
    if not raw:
        print("ERROR: 未指定位移目录（用 -n 指定，例如 -n 001-003 或 "
              "-n dir-{001..003}）。")
        return False
    tokens = re.split(r"[,\s]+", raw) if isinstance(raw, str) else list(raw)
    groups = _fdir_groups([t for t in tokens if t])
    if not groups:
        print("ERROR: 未能解析位移目录：%s" % raw)
        return False

    # -r 指定各目录中的力文件名；不给时逐个目录自动查找 vasprun.xml
    fname = getattr(ctx.args, "fc", None)
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
            parts.append("%s/%s" % (brace, inner[0]))
        else:
            parts += [os.path.join(d, n) for d, n in zip(items, inner)]

    cmd = "%s -f %s" % (prog, " ".join(parts))
    print("共 %d 个目录、%d 个同级 %s 后缀文件、%d 组；命令中不逐个展开"
          "（由 bash 展开花括号）。" % (dir_count, file_count, FILE_PREFIX,
                                        len(groups)))
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def step_band(ctx):
    """能带：计算 band.yaml，再导出 BAND.dat。"""
    if not ctx.dry and not _need("phonopy", "phonopy"):
        return False
    conf = (getattr(ctx.args, "conf", None)
            or getattr(ctx.args, "band_name", None) or "band.conf")
    if not ctx.dry and not os.path.exists(conf):
        print("ERROR: 找不到 %s；请先运行 mt.ph -b。" % conf)
        return False

    if not ctx.old:
        params = "phonopy_params.yaml"
        if not ctx.dry and not os.path.exists(params):
            print("ERROR: 找不到 %s；请先运行 mt.ph fc（phonopy-init 会生成它）。" % params)
            return False
        status = _run(["phonopy", "--config", conf, params], ctx.yes, ctx.dry)
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
    # 旧版的 phonopy-bandplot 需要 --legacy，新版已移除该选项
    plot_cmd = ["phonopy-bandplot"] + (["--legacy"] if ctx.old else []) + ["--gnuplot"]
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
    conf = (getattr(ctx.args, "meshconf", None)
            or getattr(ctx.args, "mesh_name", None) or "mesh.conf")
    if not ctx.dry and not os.path.exists(conf):
        print("ERROR: 找不到 %s；请先运行 mt.ph -d。" % conf)
        return False

    if not ctx.old:
        params = "phonopy_params.yaml"
        if not ctx.dry and not os.path.exists(params):
            print("ERROR: 找不到 %s；请先运行 mt.ph fc（phonopy-init 会生成它）。" % params)
            return False
        projected = _read_conf_value(conf, "PDOS") is not None
        if not projected:
            # conf 中没有 PDOS：只输出总 DOS，跑一次即可，不必再问 total
            return _run(["phonopy", "--config", conf, params],
                        ctx.yes, ctx.dry) != "fail"
        status = _run(["phonopy", "--config", conf, params], ctx.yes, ctx.dry)
        if status == "fail":
            return False
        want_total = ctx.total
        if want_total is None and not ctx.dry and not ctx.yes:
            answer = _ask("是否同时输出 total_dos.dat？y/n", "n")
            want_total = answer.strip().lower() in ("y", "yes")
        if want_total:
            # conf 里的 PDOS 会让 --dos 转为投影 DOS，需临时去掉
            total_conf = conf + ".total-tmp"
            if not ctx.dry:
                with open(conf, "r", errors="ignore") as src, \
                     open(total_conf, "w") as dst:
                    for line in src:
                        if not line.strip().upper().startswith("PDOS"):
                            dst.write(line)
            ok = _run(["phonopy", "--dos", "--config", total_conf, params],
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
        want_total = answer.strip().lower() in ("y", "yes")
    if want_total:
        return _run(["phonopy", "-t", conf], ctx.yes, ctx.dry) != "fail"
    return True


# -------------------------------------------------------------------- ctx ---
class Ctx:
    """收集命令行参数与交互输入，同一取值只问一次。"""

    def __init__(self, args):
        self.args = args
        self.yes = getattr(args, "yes", False)
        self.dry = getattr(args, "dry_run", False)
        self.total = getattr(args, "total", None)
        # 默认按新版（phonopy v4+）流程：setup 用 phonopy-init，
        # 能带/态密度用 --config + phonopy_params.yaml；-O 切回旧版命令
        self.old = bool(getattr(args, "old", False))
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
        given = getattr(self.args, "cell", None)
        if given:
            return given
        found = _detect_cell()
        if found:
            return found          # 目录里有就直接用，不再提问
        return self.get("cell", prompt, DEFAULT_CELLS[0])

    def back(self):
        """B：撤销最近一个交互提问，供步骤重走；无可回退时返回 False。"""
        if not self._order:
            return False
        key = self._order.pop()
        self._cache.pop(key, None)
        return True


# ------------------------------------------------------------------- main ---
def main():
    parser = argparse.ArgumentParser(
        prog="mt.ph",
        add_help=False,
        # 开头的模块说明直接作为 -h 的 description
        description=(__doc__ or "").strip(),
        epilog=r'''
Example (默认 v4+ 命令，旧版加 -O):
mt.ph                               # 扩胞（默认步骤）
mt.ph supercell -s 2 2 1 -c POSCAR-unitcell
mt.ph -b -d                          # 写 band.conf + mesh.conf
mt.ph -r                             # fc：同目录 vasprun.xml
mt.ph -r calc/                       # fc：目录中的 vasprun.xml
mt.ph -n 001-003                     # f：vasprun.xml-{001..003}
mt.ph band                           # 能带 -> BAND.dat
mt.ph dos --total                    # 态密度 -> projected/total_dos.dat
mt.ph -O -y supercell -s 2 2 1       # 旧版命令预览
''',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help",       action="help",        help='show this help message and exit')
    parser.add_argument('-v', '-V', "--version", action="version", version=version_string())

    def common(p):
        # 子命令里重复定义顶层已有的选项时用 SUPPRESS 默认值，
        # 避免未给出时覆盖顶层解析结果；两种书写位置均可：
        # mt.ph -c POSCAR band  与  mt.ph band -c POSCAR
        p.add_argument('-Y', "--yes", action="store_true",
                       default=argparse.SUPPRESS,
                       help="do not ask before running commands")
        p.add_argument('-y', "--dry-run", dest="dry_run", action="store_true",
                       default=argparse.SUPPRESS,
                       help="only print the commands, do not run them")
        p.add_argument('-s', "--dim", nargs="+", default=argparse.SUPPRESS,
                       metavar="N",
                       help='supercell dimension, 1-3 integers (missing -> 1), '
                            'default "1 1 1"; -s 2 2 1 / 2x2x1 / 2,2,1')
        p.add_argument('-c', "--cell", default=argparse.SUPPRESS, metavar="FILE",
                       help="unit cell file, default: auto-detect "
                            "POSCAR-unitcell -> CONTCAR -> POSCAR")
        p.add_argument('-O', "--old", action="store_true",
                       default=argparse.SUPPRESS,
                       help="legacy (v3) commands: phonopy instead of "
                            "phonopy-init, -c/--dim, -p/-t")
        p.add_argument('-r', "--xname", dest="fc", nargs="?", const="",
                       default=argparse.SUPPRESS, metavar="FILE",
                       help="forces file, default: vasprun.xml; alone (no -n) "
                            "runs mt.ph fc (file or directory holding vasprun.xml), "
                            "with -n runs mt.ph f (name inside each directory)")

    common(parser)
    parser.add_argument('-n', "--fdirs", nargs="+", default=None,
                        metavar="NAME",
                        help="displaced dirs / suffixes / ranges for mt.ph f "
                             "(implied), e.g. -n 001-003, -n dir-{001..003}; tried "
                             "as vasprun.xml-NAME first, then as a directory; "
                             "brace form left to bash")
    parser.add_argument('-b', "--band-conf", dest="gen_band", action="store_true",
                        help="write band.conf (name from -B); with -d writes both")
    parser.add_argument('-d', "--mesh-conf", dest="gen_mesh", action="store_true",
                        help="write mesh.conf (name from -D); with -b writes both")
    parser.add_argument('-B', "--band-file", dest="band_name", default=None,
                        metavar="FILE",
                        help="file name written by -b (default band.conf); also the "
                             "band.conf read by mt.ph band")
    parser.add_argument('-D', "--mesh-file", dest="mesh_name", default=None,
                        metavar="FILE",
                        help="file name written by -d (default mesh.conf); also the "
                             "mesh.conf read by mt.ph dos")
    parser.add_argument('--band', default=None, metavar='"0 0 0 0.5 0 0 ..."',
                        help='BAND path in fractional coordinates (with -b)')
    parser.add_argument('--labels', default=None, metavar='"G X M G"',
                        help='BAND_LABELS of the path (with -b)')
    parser.add_argument('--points', default=None, metavar="N",
                        help='BAND_POINTS per segment, default: 101 (with -b)')
    parser.add_argument('--mp', default=None, metavar='"20 20 20"',
                        help='mesh grid for DOS, e.g. "20 20 20" (with -d)')
    sub = parser.add_subparsers(dest="cmd")

    p_sc = sub.add_parser('supercell', help='phonopy -d --dim=... -c CELL')
    common(p_sc)

    p_fc = sub.add_parser('fc', help='phonopy --fc vasprun.xml (single file)')
    common(p_fc)

    p_f = sub.add_parser('f', help='phonopy -f {001..020}/vasprun.xml (FORCE_SETS)')
    common(p_f)
    p_f.add_argument('-n', "--fdirs", nargs="+", default=argparse.SUPPRESS,
                     metavar="NAME",
                     help="same as the top-level -n")

    p_band = sub.add_parser('band', help='phonopy ... band.conf -> band.yaml -> BAND.dat')
    common(p_band)
    p_band.add_argument('-B', "--band-file", dest="conf", nargs="?", const="",
                        default=argparse.SUPPRESS, metavar="FILE",
                        help="band setting file, default: band.conf")

    p_dos = sub.add_parser('dos', help='phonopy -p mesh.conf -> projected_dos.dat')
    common(p_dos)
    p_dos.add_argument('-D', "--mesh-file", dest="meshconf", nargs="?", const="",
                       default=argparse.SUPPRESS, metavar="FILE",
                       help="mesh setting file, default: mesh.conf")
    p_dos.add_argument('--total', dest="total", action="store_true", default=None,
                       help="also write total_dos.dat (phonopy -t)")
    p_dos.add_argument('--no-total', dest="total", action="store_false",
                       help="do not ask about total_dos.dat")

    args = parser.parse_args()
    # -b/-d 只写配置文件，与 -n（执行 f）/ -r（执行 fc）混用容易误以为会跑计算
    if args.cmd is None and (args.gen_band or args.gen_mesh):
        if getattr(args, "fdirs", None) or getattr(args, "fc", None) is not None:
            print("ERROR: -b/-d 只写配置文件，不能与 -n / -r 同时使用。")
            sys.exit(1)
    # -n/--fdirs 是 nargs="+"，若把子命令写在它后面会被吞掉，这里还原：
    # mt.ph -n 001-003 f  ->  cmd="f", fdirs=["001-003"]
    if args.cmd is None and isinstance(getattr(args, "fdirs", None), list):
        if len(args.fdirs) > 1 and args.fdirs[-1] in SUBCOMMANDS:
            args.cmd = args.fdirs.pop()
        if args.cmd is None:
            args.cmd = "f"            # 给了 -n 就默认执行 mt.ph f
    # -r 是 nargs="?"，同样可能吞掉后面的子命令：mt.ph -r calc/ fc
    if args.cmd is None and getattr(args, "fc", None) in SUBCOMMANDS:
        args.cmd = args.fc
        args.fc = ""
    ctx = Ctx(args)
    if ctx.old:
        print("使用旧版命令（phonopy）。")

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

    gen_options = (args.band or args.labels or args.points or args.mp
                   or args.band_name or args.mesh_name)
    if args.cmd is None and (args.gen_band or args.gen_mesh):
        # mt.ph -b / -d：只生成对应的配置文件（文件名 -B / -D，或默认名）
        if not args.gen_band and (args.band or args.labels or args.points):
            print("ERROR: --band/--labels/--points 需与 -b 一起使用。")
            sys.exit(1)
        if not args.gen_mesh and args.mp:
            print("ERROR: --mp 需与 -d 一起使用。")
            sys.exit(1)

        def gen_band(c):
            return make_band_conf(c, args.band_name or "band.conf")

        def gen_mesh(c):
            return make_mesh_conf(c, args.mesh_name or "mesh.conf")

        ok = True
        if args.gen_band:
            ok = run_step(gen_band)
        if args.gen_mesh:
            ok = run_step(gen_mesh) and ok
        sys.exit(0 if ok else 1)

    if args.cmd is None and gen_options:
        print("ERROR: --band/--labels/--points/--mp/-B/-D 需与 -b 或 -d 一起使用，"
              "例如 mt.ph -b -B band-new.conf。")
        sys.exit(1)

    if args.cmd is None and getattr(args, "fc", None) is not None:
        args.cmd = "fc"               # 只给 -r（没有 -n）时执行 mt.ph fc

    if args.cmd in ("supercell", None):
        # 不带子命令默认执行扩胞
        if not run_step(step_supercell):
            sys.exit(1)

    if args.cmd == "fc":
        if not run_step(step_fc):
            sys.exit(1)

    if args.cmd == "f":
        if not run_step(step_f):
            sys.exit(1)

    if args.cmd == "band":
        if not run_step(step_band):
            sys.exit(1)

    if args.cmd == "dos":
        if not run_step(step_dos):
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
