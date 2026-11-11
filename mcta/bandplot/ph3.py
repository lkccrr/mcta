"""mt.ph3: phono3py 晶格热导率计算流程（init/主命令分工，按步骤提示执行）

    扩胞    phono3py-init -d --dim 2 2 2 [--dim-fc2 4 4 4] -c CELL   (supercell)
    收集力  --cf3 ... -> FORCES_FC3；可选 cf2 -> FORCES_FC2、
            --cfz 扣残余力、--sp -> phono3py_params.yaml
    互转    cfs: FORCES_FC3 -> FORCE_SETS；fs2f2: FORCE_SETS -> FORCES_FC2
    热导率  phono3py --mesh 11 11 11 --br -> kappa-m*.hdf5           (kappa)
    绘图    kaccum 累积热导率；kdeplot 声子寿命分布
    词库    v / V 查本地 phono3py 用法（英文/中文）

-s/-S 给 fc3/fc2 超胞维数（1~3 个整数，默认 2 2 2，缺省补 1，分隔符不限）；-c 结构文件（POSCAR-unitcell -> CONTCAR -> POSCAR 自动探测，无则询问）；-n 位移目录/后缀/范围（00001-00755、disp-{00001..00755}），先查 vasprun.xml-取值 再查目录，花括号交给 bash 展开；-x 各目录力文件（默认 vasprun.xml）；-m mesh 网格（默认 11 11 11）；-k kappa-m*.hdf5（kaccum/kdeplot 输入，缺省自动探测）；--rd/--rd-fc2 随机方向位移（配 --symfc 可大幅减少超胞），--random-seed/--amplitude 控制种子与幅度。
kappa 子命令另有 --lbte/--sigma/--isotope/--ts/--symfc/--gp 等选项（mt.ph3 kappa -h 查看）；
--cutoff-pair 属于 setup 阶段，请在 supercell/cf3/cf2 里给。

提示中 B/b+回车 = 返回上一层，Q/q+回车 = 退出；-Y 跳过确认，-R 只打印。
无子命令默认扩胞；只给 -n 执行 cf3；只给 -k/-m 执行 kappa。
"""

import argparse
import functools
import os
import re
import shutil
import subprocess
import sys

from mcta import version_string

from mcta.bandplot.ph import (
    QuitFlow,
    StepBack,
    _ask,
    _fmt,
    _fdir_groups,
    _match_suffix_file,
    _need,
    _parse_dim,
    _probe_forces,
    _run,
)

DEFAULT_DIM = "2 2 2"
DEFAULT_MESH = "11 11 11"
FILE_PREFIX = "vasprun.xml"
DEFAULT_CELLS = ("POSCAR-unitcell", "CONTCAR", "POSCAR")
SUBCOMMANDS = ("supercell", "cf3", "cf2", "cfs", "fs2f2",
               "kappa", "kaccum", "kdeplot", "v", "V")


def _detect_cell():
    """按优先级自动探测结构文件，找不到返回 None。"""
    for name in DEFAULT_CELLS:
        if os.path.exists(name):
            return name
    return None


@functools.lru_cache(maxsize=1)
def _phono3py_version():
    """本机 phono3py 版本号（如 '3.12.0'），取不到返回 None。"""
    try:
        from importlib.metadata import version
        return version("phono3py")
    except Exception:
        pass
    try:
        import phono3py
        return getattr(phono3py, "__version__", None)
    except Exception:
        return None


def _phono3py_is_v4():
    """按本机 phono3py 版本判断命令形态：v4+ 用 phono3py-init / --nonac。"""
    v = _phono3py_version()
    if v:
        m = re.match(r"\s*(\d+)", str(v))
        if m:
            return int(m.group(1)) >= 4
    # 版本不可用时退化为能力探测：phono3py-init 是 v4+ 才提供的
    if shutil.which("phono3py-init"):
        return True
    if shutil.which("phono3py"):
        return False
    return True        # 完全没装时默认按 v4+ 显示


def _init_prog():
    """setup 命令（-d/--rd/--cf3/--cf2/--cfs/--fs2f2）：v4+ 用 phono3py-init。"""
    return "phono3py-init" if _phono3py_is_v4() else "phono3py"


def _resolve_fdir_group(group, dry, fname=None):
    """判定一组名字是「同级 vasprun.xml 后缀文件」还是「含力文件的目录」。

    与 mt.ph 的 f 步骤相同的查找规则：
      1) 同级文件 vasprun.xml-<名字> / vasprun.xml_<名字>；
      2) 直接给出的完整文件名；
      3) 目录 <名字>，且其中有 fname（未给时查找 vasprun.xml 或
         vasprun.xml-数字）。
    返回 (kind, items, inner)，失败时返回 (None, None, None)。
    """
    kind = None
    items = []
    inner = []
    for name in group["names"]:
        found = _match_suffix_file(name)
        if found:
            current, item, sub = "file", found, None
        elif os.path.isfile(name):
            current, item, sub = "file", name, None
        elif os.path.isdir(name):
            sub = _probe_forces(name, fname)
            if sub is None:
                if not dry:
                    print("ERROR: 目录 %s 中没有 %s%s。"
                          % (name, fname or FILE_PREFIX,
                             "" if fname else "（或 %s-数字）" % FILE_PREFIX))
                    return None, None, None
                sub = fname or FILE_PREFIX
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


def _collect_cmd(ctx, flag, raw):
    """把 -n 的取值整理成 --cf3 / --cf2 后面的文件列表（bash 花括号紧凑形式）。"""
    tokens = re.split(r"[,\s]+", raw) if isinstance(raw, str) else list(raw)
    groups = _fdir_groups([t for t in tokens if t])
    if not groups:
        print("ERROR: 未能解析位移目录：%s" % raw)
        return None

    fname = getattr(ctx.args, "xname", None)
    resolved = []
    for group in groups:
        kind, items, inner = _resolve_fdir_group(group, ctx.dry, fname)
        if kind is None:
            return None
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
                parts.append(prefix + brace)
            else:
                parts += items
            continue
        dir_count += len(items)
        if len(set(inner)) == 1:
            parts.append("%s/%s" % (brace, inner[0]))
        else:
            parts += [os.path.join(d, n) for d, n in zip(items, inner)]

    print("共 %d 个目录、%d 个同级 %s 后缀文件、%d 组；命令中不逐个展开"
          "（由 bash 展开花括号）。" % (dir_count, file_count, FILE_PREFIX,
                                        len(groups)))
    return "%s %s %s" % (_init_prog(), flag, " ".join(parts))


# ------------------------------------------------------------------ steps ---
DIM_PROMPT = "fc3 超胞尺寸 DIM（1~3 个整数，其余补 1）"
DIM_FC2_PROMPT = "fc2 超胞尺寸 DIM_FC2（留空表示与 fc3 相同）"
MESH_PROMPT = "热导率 mesh 网格（1~3 个整数，其余补最后一个值）"


def _dim_value(ctx):
    """取 fc3 的 DIM（-s 可传多个 token），规范化为 "a b c"。"""
    raw = ctx.get("dimns", DIM_PROMPT, DEFAULT_DIM)
    if isinstance(raw, (list, tuple)):
        raw = " ".join(str(x) for x in raw)
    return _parse_dim(raw)


def _dim_fc2_value(ctx):
    """取 fc2 的 DIM_FC2（-S）；留空（或为空串）表示不启用更大的 fc2 超胞。"""
    raw = ctx.get("dimf2", DIM_FC2_PROMPT, None)
    if not raw:
        return None
    if isinstance(raw, (list, tuple)):
        raw = " ".join(str(x) for x in raw)
    return _parse_dim(raw)


def _mesh_value(ctx):
    """取 mesh 网格：1~3 个整数，缺省时重复最后一个补齐（-m）。无输入用默认。"""
    raw = ctx.get("mgrid", MESH_PROMPT, DEFAULT_MESH)
    if isinstance(raw, (list, tuple)):
        raw = " ".join(str(x) for x in raw)
    nums = re.findall(r"\d+", str(raw or ""))
    if not nums:
        return DEFAULT_MESH
    nums = nums[:3] + [nums[-1]] * (3 - min(len(nums), 3))
    return " ".join(nums[:3])


def step_supercell(ctx):
    """扩胞：phono3py-init -d/--rd ... --dim ... [--dim-fc2 ...] --pa auto -c CELL

    默认 -d 系统位移；--rd NUM 改用 NUM 个随机方向位移的超胞（文档推荐
    配合 symfc 求解器）；--rd-fc2 需与 -S/--dimf2 一起使用。
    """
    if not ctx.dry and not _need(_init_prog(), "phono3py"):
        return False
    cell = ctx.cell()
    if not ctx.dry and not os.path.exists(cell):
        print("ERROR: 找不到结构文件 %s（支持：%s，或用 -c 指定）。"
              % (cell, "/".join(DEFAULT_CELLS)))
        return False
    dim = _dim_value(ctx)
    dim_fc2 = _dim_fc2_value(ctx)
    args = ctx.args
    rd = getattr(args, "rd", None)
    rd_fc2 = getattr(args, "rd_fc2", None)
    if rd_fc2 and not dim_fc2:
        print("ERROR: --rd-fc2 需与 -S/--dimf2（fc2 超胞）一起使用。")
        return False
    cmd = [_init_prog()]
    if rd:
        cmd += ["--rd", str(rd)]
    else:
        cmd.append("-d")
    cmd += ["--dim"] + dim.split()
    if dim_fc2:
        cmd += ["--dim-fc2"] + dim_fc2.split()
    if rd_fc2:
        cmd += ["--rd-fc2", str(rd_fc2)]
    if getattr(args, "random_seed", None) is not None:
        cmd += ["--random-seed", str(args.random_seed)]
    if getattr(args, "amplitude", None) is not None:
        cmd += ["--amplitude", str(args.amplitude)]
    if getattr(args, "cutoff_pair", None) is not None:
        cmd += ["--cutoff-pair", str(args.cutoff_pair)]
    cmd += ["--pa", "auto", "-c", cell]
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def _step_collect(ctx, flag, prompt, out_name):
    """收集力：phono3py-init --cf3/--cf2 FILE...（需要 phono3py_disp.yaml）。

    加 --sp 改写 phono3py_params.yaml（只能与 --cf3 同用）；
    加 --cfz FILE 扣除完美超胞的残余力。
    """
    args = ctx.args
    if not ctx.dry and not _need(_init_prog(), "phono3py"):
        return False
    if not ctx.dry and not os.path.exists("phono3py_disp.yaml"):
        print("ERROR: 当前目录没有 phono3py_disp.yaml；请先运行 mt.ph3 supercell。")
        return False
    save = getattr(args, "sp", False)
    if save and flag != "--cf3":
        print("ERROR: --sp 只能与 --cf3 一起使用（可同时给 --cf2）。")
        return False
    raw = getattr(args, "fdirs", None)
    if not raw:
        raw = ctx.get("fdirs", prompt, None)
    if not raw:
        print("ERROR: 未指定位移目录（用 -n 指定，例如 -n 00001-00755 或 "
              "-n disp-{00001..00755}）。")
        return False
    cmd = _collect_cmd(ctx, flag, raw)
    if cmd is None:
        return False
    cfz = getattr(args, "cfz", None)
    if cfz:
        if not ctx.dry and not os.path.exists(cfz):
            print("ERROR: 找不到残余力文件 %s（--cfz）。" % cfz)
            return False
        cmd += " --cfz " + cfz
    cutoff = getattr(args, "cutoff_pair", None)
    if cutoff is not None:
        cmd += " --cutoff-pair " + str(cutoff)
    if save:
        cmd += " --sp"
        out_name = "phono3py_params.yaml"
    print("输出：%s" % out_name)
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def step_cf3(ctx):
    """FORCES_FC3：mt.ph3 cf3 -> phono3py-init --cf3 ..."""
    return _step_collect(ctx, "--cf3",
                         "位移目录或 vasprun.xml 后缀，可多个"
                         "（如 disp-00001-00755）", "FORCES_FC3")


def step_cf2(ctx):
    """FORCES_FC2：mt.ph3 cf2 -> phono3py-init --cf2 ...（--dim-fc2 扩胞时才有）。"""
    return _step_collect(ctx, "--cf2",
                         "fc2 位移目录或 vasprun.xml 后缀，可多个"
                         "（如 disp_fc2-00001-00002）", "FORCES_FC2")


def step_cfs(ctx):
    """FORCE_SETS：phono3py-init --cfs [--dim-fc2 a b c]

    由 FORCES_FC3 与 phono3py_disp.yaml 反算 phonopy 的 FORCE_SETS；
    给了 -S/--dimf2 时改用 FORCES_FC2（对应更大的声子超胞）。
    """
    if not ctx.dry and not _need(_init_prog(), "phono3py"):
        return False
    if not ctx.dry and not os.path.exists("phono3py_disp.yaml"):
        print("ERROR: 当前目录没有 phono3py_disp.yaml；请先运行 mt.ph3 supercell。")
        return False
    dim_fc2 = _dim_fc2_value(ctx) if getattr(ctx.args, "dimf2", None) else None
    source = "FORCES_FC2" if dim_fc2 else "FORCES_FC3"
    if not ctx.dry and not os.path.exists(source):
        print("ERROR: 当前目录没有 %s。" % source)
        return False
    cmd = [_init_prog(), "--cfs"]
    if dim_fc2:
        cmd += ["--dim-fc2"] + dim_fc2.split()
    print("输出：FORCE_SETS（来源 %s）" % source)
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def step_fs2f2(ctx):
    """FORCES_FC2：phono3py-init --fs2f2（由 phonopy 的 FORCE_SETS 反算）。"""
    if not ctx.dry and not _need(_init_prog(), "phono3py"):
        return False
    if not ctx.dry and not os.path.exists("FORCE_SETS"):
        print("ERROR: 当前目录没有 FORCE_SETS（phonopy 的位移-力数据文件）。")
        return False
    print("输出：FORCES_FC2（并打印 phono3py_disp.yaml 所需的行）")
    return _run([_init_prog(), "--fs2f2"], ctx.yes, ctx.dry) != "fail"


def _kappa_cmd(ctx):
    """组装 kappa 主计算命令的参数列表。"""
    args = ctx.args
    mesh = _mesh_value(ctx)
    cmd = ["phono3py", "--mesh"] + mesh.split()
    # 力常数求解器与截断（symfc/alm、cutoff、对称化、全尺寸）
    if getattr(args, "symfc", False):
        cmd.append("--symfc")
    if getattr(args, "alm", False):
        cmd.append("--alm")
    # --cutoff-pair 在 v3/v4 都属于 setup 阶段（生成位移/力常数），
    # 计算命令里带上无效，v4 更会直接报错，所以统一在 cf3/supercell 里传。
    if getattr(args, "cutoff_pair", None) is not None:
        print("提示：--cutoff-pair 属于 setup 选项，已忽略；"
              "请改用 mt.ph3 cf3 --cutoff-pair %s（或 supercell）。"
              % args.cutoff_pair)
    if getattr(args, "fc_calc_opt", None):
        cmd += ["--fc-calc-opt", args.fc_calc_opt]
    # --fc-symmetry：v3 需要显式开启；v4 默认就做，且该选项已被删除
    if getattr(args, "fc_symmetry", False):
        if _phono3py_is_v4():
            print("提示：phono3py v4 默认已对称化力常数，--fc-symmetry 已忽略。")
        else:
            cmd.append("--fc-symmetry")
    # --full-fc 是 v4 才有的（v3 默认就是全尺寸力常数）
    if getattr(args, "full_fc", False) and _phono3py_is_v4():
        cmd.append("--full-fc")
    # 计算模式：--lbte 直接求解；--ise/--rse/--jdos 是自能/JDOS 计算，
    # 给出这些时不加默认的 --br（RTA 热导率）
    if getattr(args, "lbte", False):
        cmd.append("--lbte")
    elif getattr(args, "ise", False) or getattr(args, "rse", False) \
            or getattr(args, "jdos", False):
        pass
    else:
        cmd.append("--br")
    if getattr(args, "sigma", None):
        cmd += ["--sigma", args.sigma]
    if getattr(args, "isotope", False):
        cmd.append("--isotope")
    # NAC：v4 有 BORN 就自动启用（--nonac 关闭）；v3 反过来，要显式 --nac
    if _phono3py_is_v4():
        if getattr(args, "nonac", False):
            cmd.append("--nonac")
    elif os.path.exists("BORN") and not getattr(args, "nonac", False):
        cmd.append("--nac")
    # 温度：--ts 离散温度优先，否则 --tmin/--tmax/--tstep 区间
    if getattr(args, "ts", None):
        cmd += ["--ts"] + [str(t) for t in args.ts]
    else:
        for flag, key in (("--tmin", "tmin"), ("--tmax", "tmax"),
                          ("--tstep", "tstep")):
            value = getattr(args, key, None)
            if value is not None:
                cmd += [flag, str(value)]
    if getattr(args, "boundary_mfp", None) is not None:
        cmd += ["--boundary-mfp", str(args.boundary_mfp)]
    if getattr(args, "mass_variances", None):
        cmd += ["--mass-variances"] + [str(v) for v in args.mass_variances]
    if getattr(args, "nu", False):
        cmd.append("--nu")
    if getattr(args, "ave_pp", False):
        cmd.append("--ave-pp")
    if getattr(args, "ise", False):
        cmd.append("--ise")
    if getattr(args, "rse", False):
        cmd.append("--rse")
    if getattr(args, "jdos", False):
        cmd.append("--jdos")
    if getattr(args, "gp", None):
        cmd += ["--gp"] + [str(g) for g in args.gp]
    if getattr(args, "write_gamma", False):
        cmd.append("--write-gamma")
    if getattr(args, "read_gamma", False):
        cmd.append("--read-gamma")
    if getattr(args, "wgp", False):
        cmd.append("--wgp")
    if getattr(args, "gruneisen", False):
        cmd.append("--gruneisen")
    return cmd


def step_kappa(ctx):
    """热导率：phono3py --mesh ... --br/--lbte ... -> kappa-m<m>-g*.hdf5"""
    args = ctx.args
    if not ctx.dry and not _need("phono3py", "phono3py"):
        return False
    if not ctx.dry and not os.path.exists("FORCES_FC3") \
            and not os.path.exists("fc3.hdf5"):
        print("ERROR: 当前目录没有 FORCES_FC3（或 fc3.hdf5）；"
              "请先运行 mt.ph3 cf3 收集力。")
        return False
    if getattr(args, "symfc", False) and getattr(args, "alm", False):
        print("ERROR: --symfc 与 --alm 只能选一个。")
        return False
    if getattr(args, "ts", None) and any(
            getattr(args, k, None) is not None
            for k in ("tmin", "tmax", "tstep")):
        print("ERROR: --ts 与 --tmin/--tmax/--tstep 只能选一种温度设置。")
        return False
    if not ctx.dry and os.path.exists("BORN") \
            and not getattr(args, "nonac", False):
        if _phono3py_is_v4():
            print("提示：检测到 BORN 文件，phono3py v4 会自动启用 NAC"
                  "（--nonac 可显式关闭）。")
        else:
            print("提示：检测到 BORN 文件，v3 需显式 --nac 才启用 NAC"
                  "（已在命令中加入）。")
    cmd = _kappa_cmd(ctx)
    gparts = " ".join(str(g) for g in getattr(ctx.args, "gp", []) or [])
    suffix = ("（只算网格点 %s，完成后可用 --read-gamma 汇总）" % gparts) \
        if gparts else ""
    print("说明：FORCES_FC3 存在时会先计算 fc3/fc2（可加 --fc-calc symfc "
          "加速），再算热导率%s。" % suffix)
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


def _find_kappa_hdf5():
    """当前目录中的 kappa-m*.hdf5（优先按 mesh 数字最大者）。"""
    cands = [fn for fn in os.listdir(".")
             if re.match(r"^kappa-m\d+.*\.hdf5$", fn)]
    if not cands:
        return None

    def _key(fn):
        m = re.match(r"^kappa-m(\d+)", fn)
        return int(m.group(1)) if m else 0

    return sorted(cands, key=_key)[-1]


def _kappa_file(ctx):
    """确定绘图用的 kappa hdf5 文件：-k 指定，否则自动探测。"""
    given = getattr(ctx.args, "kfile", None)
    if given:
        if not ctx.dry and not os.path.exists(given):
            print("ERROR: 找不到 %s。" % given)
            return None
        return given
    found = _find_kappa_hdf5()
    if found:
        return found
    if ctx.dry:
        return "kappa-m111111.hdf5"
    return ctx.get("kfile", "kappa-m*.hdf5 文件（mt.ph3 kappa 的输出）", None)


def step_kaccum(ctx):
    """累积热导率：phono3py-kaccum kappa-m*.hdf5 -> kaccum.dat"""
    if not ctx.dry and not _need("phono3py-kaccum", "phono3py"):
        return False
    kfile = _kappa_file(ctx)
    if not kfile:
        print("ERROR: 找不到 kappa-m*.hdf5；请先运行 mt.ph3 kappa，或用 -k 指定。")
        return False
    cmd = ["phono3py-kaccum", kfile]
    if getattr(ctx.args, "temperature", None) is not None:
        cmd += ["--temperature", str(ctx.args.temperature)]
    out = getattr(ctx.args, "outpt", None) or "kaccum.dat"
    return _run(" ".join(cmd), ctx.yes, ctx.dry, stdout=out) != "fail"


def step_kdeplot(ctx):
    """寿命分布：phono3py-kdeplot kappa-m*.hdf5（打开图形窗口）。"""
    if not ctx.dry and not _need("phono3py-kdeplot", "phono3py"):
        return False
    kfile = _kappa_file(ctx)
    if not kfile:
        print("ERROR: 找不到 kappa-m*.hdf5；请先运行 mt.ph3 kappa，或用 -k 指定。")
        return False
    cmd = ["phono3py-kdeplot", kfile]
    if getattr(ctx.args, "temperature", None) is not None:
        cmd += ["--temperature", str(ctx.args.temperature)]
    return _run(cmd, ctx.yes, ctx.dry) != "fail"


# -------------------------------------------------------------------- ctx ---
class Ctx:
    """收集命令行参数与交互输入，同一取值只问一次（与 mt.ph 的 Ctx 一致）。"""

    def __init__(self, args):
        self.args = args
        self.yes = getattr(args, "yesal", False)
        self.dry = getattr(args, "dryrn", False)
        self._cache = {}
        self._order = []

    def get(self, key, prompt, default=None):
        if key in self._cache:
            return self._cache[key]
        value = getattr(self.args, key, None)
        if value == "":
            value = None
        if value is None and not self.dry and not self.yes:
            self._order.append(key)
            try:
                value = _ask(prompt, default)
            except (StepBack, QuitFlow):
                self._order.remove(key)
                raise
        elif value is None:
            value = default
        self._cache[key] = value
        return value

    def cell(self, prompt="原胞结构文件（POSCAR-unitcell/CONTCAR/POSCAR）"):
        given = getattr(self.args, "cells", None)
        if given:
            return given
        found = _detect_cell()
        if found:
            return found
        return self.get("cells", prompt, DEFAULT_CELLS[0])

    def back(self):
        if not self._order:
            return False
        key = self._order.pop()
        self._cache.pop(key, None)
        return True


# ------------------------------------------------------------------- main ---
def main():
    # mt.ph3 v / V：查询词常是 --dim、--br 这类选项形式，argparse 会把它们
    # 误解析为选项，因此在 parser 之前直接处理，保留全部原始 token。
    argv = sys.argv[1:]
    if argv and argv[0] in ("v", "V"):
        from mcta.bandplot import ph3doc
        sys.exit(ph3doc.run(argv[1:]))

    parser = argparse.ArgumentParser(
        prog="mt.ph3",
        add_help=False,
        description=(__doc__ or "").strip(),
        epilog=r'''
Example:
mt.ph3                                   # 扩胞（默认步骤）
mt.ph3 supercell -s 2 2 2 -S 4 4 4
mt.ph3 cf3 -n disp-{00001..00755}        # FORCES_FC3（--sp -> params.yaml）
mt.ph3 kappa -m 11 11 11                 # RTA -> kappa-m111111.hdf5（选项见 kappa -h）
mt.ph3 kaccum -k kappa-m111111.hdf5      # 累积热导率 -> kaccum.dat
mt.ph3 -R supercell -s 2 2 2             # 只打印命令，不执行
mt.ph3 v --br --symfc                    # 查词库
''',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-h', '-H', "--help", action="help",
                        help='show this help message and exit')
    # -v / -V = 版本号（与其它 mt.* 一致）；词库用 v / V 子命令（见 main 开头）
    parser.add_argument('-v', '-V', "--version", action="version",
                        version=version_string())

    def common(p):
        # 子命令里重复定义顶层已有的选项时用 SUPPRESS 默认值，
        # 避免未给出时覆盖顶层解析结果；两种书写位置均可：
        # mt.ph3 -c POSCAR cf3  与  mt.ph3 cf3 -c POSCAR
        p.add_argument('-Y', "--yesal", action="store_true",
                       default=argparse.SUPPRESS,
                       help="do not ask before running commands")
        p.add_argument('-R', "--dryrn", action="store_true",
                       default=argparse.SUPPRESS,
                       help="only print the commands, do not run them")
        p.add_argument('-s', "--dimns", nargs="+", default=argparse.SUPPRESS,
                       metavar="N",
                       help='fc3 supercell dims, 1-3 ints, default "2 2 2"; '
                            '-s 2 2 2 / 2x2x2 / 2,2,2')
        p.add_argument('-S', "--dimf2", nargs="+", default=argparse.SUPPRESS,
                       metavar="N",
                       help='fc2 supercell dims, same syntax as -s '
                            '(omit = same size as fc3)')
        p.add_argument('-c', "--cells", default=argparse.SUPPRESS, metavar="FILE",
                       help="unit cell file (auto-detect POSCAR-unitcell/CONTCAR/POSCAR)")
        p.add_argument('-x', "--xname", nargs="?", const="",
                       default=argparse.SUPPRESS, metavar="FILE",
                       help="forces file in each displacement dir (default vasprun.xml)")
        p.add_argument('-m', "--mgrid", nargs="+", default=argparse.SUPPRESS,
                       metavar="N",
                       help='mesh grid for kappa, 1-3 ints, default "11 11 11"')
        p.add_argument('-n', "--fdirs", nargs="+", default=argparse.SUPPRESS,
                       metavar="NAME",
                       help="displacement dirs / suffixes / ranges, e.g. "
                            "-n disp-{00001..00755}; brace form left to bash")
        p.add_argument('-k', "--kfile", default=argparse.SUPPRESS,
                       metavar="HDF5",
                       help="kappa-m*.hdf5 for kaccum/kdeplot (auto-detected)")

    common(parser)

    def supercell_opts(p):
        # supercell 步骤的位移生成选项；顶层也定义一份，使
        # mt.ph3 --rd 100（无子命令）与 mt.ph3 supercell --rd 100 均可
        p.add_argument("--rd", type=int, default=argparse.SUPPRESS,
                       metavar="NUM",
                       help="random-direction displacements instead of -d "
                            "(use with --symfc at kappa step)")
        p.add_argument("--rd-fc2", type=int,
                       default=argparse.SUPPRESS, metavar="NUM",
                       help="fc2 random displacements (needs -S/--dimf2)")
        p.add_argument("--random-seed", type=int,
                       default=argparse.SUPPRESS, metavar="N",
                       help="random seed for --rd/--rd-fc2")
        p.add_argument("--amplitude", type=float, default=argparse.SUPPRESS,
                       metavar="A",
                       help="displacement distance in Angstrom (VASP 0.03)")

    supercell_opts(parser)
    sub = parser.add_subparsers()

    def collect_opts(p):
        # cf3 / cf2 共用的输出改写选项；顶层也定义，便于
        # mt.ph3 -n ... --sp 这种「只给 -n 即 cf3」的写法
        p.add_argument("--sp", "--save-params",
                       action="store_true", default=argparse.SUPPRESS,
                       help="write phono3py_params.yaml instead of FORCES_FC3 "
                            "(cf3 only)")
        p.add_argument("--cfz", default=argparse.SUPPRESS, metavar="FILE",
                       help="subtract residual forces (undisplaced-supercell force file)")
        p.add_argument("--cutoff-pair", type=float,
                       default=argparse.SUPPRESS, metavar="D",
                       help="cutoff distance between displaced-atom pairs "
                            "(setup option; on v3/v4 it belongs to this step, "
                            "not to kappa)")

    collect_opts(parser)
    # 与 phono3py-init 的选项同名：只给 --cfs / --fs2f2 时直接执行该步骤，
    # 省去写子命令（mt.ph3 --cfs 等价于 mt.ph3 cfs）
    parser.add_argument("--cfs", "--create-force-sets",
                        action="store_true", default=argparse.SUPPRESS,
                        help="FORCE_SETS from FORCES_FC3 (-S: from FORCES_FC2)")
    parser.add_argument("--fs2f2", "--force-sets-to-forces-fc2",
                        action="store_true", default=argparse.SUPPRESS,
                        help="FORCES_FC2 from FORCE_SETS")

    p_sc = sub.add_parser('supercell',
                          help='phono3py-init -d/--rd --dim ... -c CELL')
    p_sc.set_defaults(cmd='supercell')
    common(p_sc)
    supercell_opts(p_sc)
    p_sc.add_argument("--cutoff-pair", type=float,
                      default=argparse.SUPPRESS, metavar="D",
                      help="cutoff distance between displaced-atom pairs")

    p_cf3 = sub.add_parser('cf3',
                           help='phono3py-init --cf3 ... -> FORCES_FC3')
    p_cf3.set_defaults(cmd='cf3')
    common(p_cf3)
    collect_opts(p_cf3)

    p_cf2 = sub.add_parser('cf2',
                           help='phono3py-init --cf2 ... -> FORCES_FC2')
    p_cf2.set_defaults(cmd='cf2')
    common(p_cf2)
    collect_opts(p_cf2)

    p_cfs = sub.add_parser('cfs',
                           help='phono3py-init --cfs -> FORCE_SETS '
                                '(-S uses FORCES_FC2)')
    p_cfs.set_defaults(cmd='cfs')
    common(p_cfs)

    p_fs2f2 = sub.add_parser('fs2f2',
                             help='phono3py-init --fs2f2 -> FORCES_FC2 '
                                  '(from FORCE_SETS)')
    p_fs2f2.set_defaults(cmd='fs2f2')
    common(p_fs2f2)

    p_kappa = sub.add_parser('kappa',
                             help='phono3py --mesh ... --br/--lbte -> kappa-m*.hdf5')
    p_kappa.set_defaults(cmd='kappa')
    common(p_kappa)
    p_kappa.add_argument("--lbte", action="store_true", default=False,
                         help="direct solution of LBTE (default: --br, RTA)")
    p_kappa.add_argument("--symfc", action="store_true", default=False,
                         help="compute force constants with symfc "
                              "(recommended with --rd supercells)")
    p_kappa.add_argument("--alm", action="store_true", default=False,
                         help="compute force constants with ALM")
    p_kappa.add_argument("--cutoff-pair", type=float,
                         default=None, metavar="DIST",
                         help="cutoff pair distance for fc3 "
                              "(shortcut of --fc-calc-opt \"cutoff=DIST\")")
    p_kappa.add_argument("--fc-calc-opt", default=None,
                         metavar='"cutoff=8"',
                         help='options for the fc calculator, e.g. "cutoff=8"')
    p_kappa.add_argument("--fc-symmetry",
                         action="store_true", default=False,
                         help="symmetrize force constants (traditional solver)")
    p_kappa.add_argument("--full-fc", action="store_true",
                         default=False,
                         help="full-size force constants (v4 default: compact; "
                              "ignored on v3, where full is the default)")
    p_kappa.add_argument("--sigma", default=None, metavar="SIGMA",
                         help="smearing width instead of tetrahedron method")
    p_kappa.add_argument("--isotope", action="store_true", default=False,
                         help="isotope scattering (natural abundance)")
    p_kappa.add_argument("--nonac", action="store_true", default=False,
                         help="disable NAC (v4 auto-enables it when BORN "
                              "exists; on v3 NAC is off unless BORN is present, "
                              "in which case --nac is added for you)")
    p_kappa.add_argument("--ts", nargs="+", type=float,
                         default=None, metavar="T",
                         help="temperatures in K, e.g. --ts 100 300 500")
    p_kappa.add_argument("--tmin", type=float, default=None, metavar="T",
                         help="minimum temperature in K")
    p_kappa.add_argument("--tmax", type=float, default=None, metavar="T",
                         help="maximum temperature in K")
    p_kappa.add_argument("--tstep", type=float, default=None, metavar="DT",
                         help="temperature step in K")
    p_kappa.add_argument("--boundary-mfp", "--bmfp",
                         type=float, default=None, metavar="L",
                         help="boundary scattering mean free path")
    p_kappa.add_argument("--mass-variances", "--mv",
                         nargs="+", type=float, default=None, metavar="V",
                         help="isotope mass variances, one per element")
    p_kappa.add_argument("--nu", action="store_true", default=False,
                         help="decompose kappa into N/U processes")
    p_kappa.add_argument("--ave-pp", action="store_true",
                         default=False,
                         help="use averaged phonon-phonon interaction")
    p_kappa.add_argument("--ise", action="store_true", default=False,
                         help="imaginary self energy / linewidth (no --br added)")
    p_kappa.add_argument("--rse", action="store_true", default=False,
                         help="real part of self energy (no --br added)")
    p_kappa.add_argument("--jdos", action="store_true", default=False,
                         help="joint density of states (no --br added)")
    p_kappa.add_argument("--gp", nargs="+", type=int,
                         default=None, metavar="N",
                         help="only these irreducible grid points "
                             "(distributed computing)")
    p_kappa.add_argument("--wgp", action="store_true", default=False,
                         help="write ir_grid_points.yaml (before --gp runs)")
    p_kappa.add_argument("--write-gamma",
                         action="store_true", default=False,
                         help="write gamma at each --gp grid point to hdf5")
    p_kappa.add_argument("--read-gamma",
                         action="store_true", default=False,
                         help="collect --write-gamma outputs and write kappa-m*.hdf5")
    p_kappa.add_argument("--gruneisen", action="store_true", default=False,
                         help="mode-Gruneisen parameters from fc3")

    p_kaccum = sub.add_parser('kaccum',
                              help='phono3py-kaccum kappa-m*.hdf5 > kaccum.dat')
    p_kaccum.set_defaults(cmd='kaccum')
    common(p_kaccum)
    p_kaccum.add_argument("--temperature", type=float, default=None,
                          metavar="T", help="temperature in K (default: 300)")
    p_kaccum.add_argument('-o', "--outpt", default=argparse.SUPPRESS,
                          metavar="FILE", help="output file, default: kaccum.dat")

    p_kdeplot = sub.add_parser('kdeplot',
                               help='phono3py-kdeplot kappa-m*.hdf5 (GUI)')
    p_kdeplot.set_defaults(cmd='kdeplot')
    common(p_kdeplot)
    p_kdeplot.add_argument("--temperature", type=float, default=None,
                           metavar="T", help="temperature in K (default: 300)")

    # v / V 合并为一行；真正解析在 main() 开头（词形 --dim 等会干扰 argparse）
    p_v = sub.add_parser('v', aliases=['V'],
                         help='phono3py wordbook (no word: list; EN, then ZH)')
    p_v.set_defaults(cmd='v')

    args = parser.parse_args()
    if not hasattr(args, "cmd"):
        args.cmd = None
    # -n/--fdirs 是 nargs="+"，若把子命令写在它后面会被吞掉，这里还原：
    # mt.ph3 -n 00001-00755 cf3  ->  cmd="cf3", fdirs=["00001-00755"]
    if args.cmd is None and isinstance(getattr(args, "fdirs", None), list):
        if len(args.fdirs) > 1 and args.fdirs[-1] in SUBCOMMANDS:
            args.cmd = args.fdirs.pop()
        if args.cmd is None:
            args.cmd = "cf3"
    if args.cmd == "v":
        from mcta.bandplot import ph3doc
        sys.exit(ph3doc.run([]))
    # 只给了 --cfs / --fs2f2 时按对应步骤执行
    if args.cmd is None and getattr(args, "fs2f2", False):
        args.cmd = "fs2f2"
    if args.cmd is None and getattr(args, "cfs", False):
        args.cmd = "cfs"
    ctx = Ctx(args)
    print("检测到 phono3py %s，命令形态：%s。"
          % (_phono3py_version() or "版本未知",
             "v4+ 新版" if _phono3py_is_v4() else "v3 旧版"))

    def run_step(step):
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

    if args.cmd in ("supercell", None):
        # 不带子命令默认执行扩胞；但只给了 -n 则收集力，只给了 -k/-m 则算热导率
        if getattr(args, "fdirs", None):
            args.cmd = "cf3"
        elif getattr(args, "kfile", None) is not None \
                or getattr(args, "mgrid", None) is not None:
            args.cmd = "kappa"
        else:
            if not run_step(step_supercell):
                sys.exit(1)

    if args.cmd == "cf3":
        if not run_step(step_cf3):
            sys.exit(1)

    if args.cmd == "cf2":
        if not run_step(step_cf2):
            sys.exit(1)

    if args.cmd == "cfs":
        if not run_step(step_cfs):
            sys.exit(1)

    if args.cmd == "fs2f2":
        if not run_step(step_fs2f2):
            sys.exit(1)

    if args.cmd == "kappa":
        if not run_step(step_kappa):
            sys.exit(1)

    if args.cmd == "kaccum":
        if not run_step(step_kaccum):
            sys.exit(1)

    if args.cmd == "kdeplot":
        if not run_step(step_kdeplot):
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
