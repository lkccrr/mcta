import os

import numpy as np
import matplotlib.pyplot as plt


def _read_rows(lines):
    """从日志里挑出数据行。

    数据行的特征：第一个字段能解析成浮点数，且**字段数等于日志里
    数据行的最大列数**。

    两个坑（都已修）：
    * 旧实现只找表头 'Temperature' 之后的第一段，遇到别的行就停止
      收集——但回火模式的日志在表头和数据之间还有一行
      'swaps: 15  accepted: 0'，于是数据行一个都收集不到，报
      'No data!'。
    * 表头上面还有一行 'Round  0  1.0'（初态磁化），它的第一个字段
      也是数字，但只有 2 列。若拿它当基准，后面 7 列的真正数据行就
      会因列数不符而被丢掉。

    所以这里先收集所有"首字段是数字"的行，再取其中列数最多的那些
    作为数据行。
    """
    numeric = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        try:
            float(parts[0])
        except ValueError:
            continue
        numeric.append(parts)
    if not numeric:
        return []
    ncol = max(len(r) for r in numeric)
    return [r for r in numeric if len(r) == ncol]


def main(file, format, legend):
    with open(file, "r") as f:
        lines = f.readlines()

    rows = _read_rows(lines)
    if rows:
        # 最后一列是耗时，不参与作图
        arr = np.array([r[0:-1] for r in rows], dtype=float)
        plot(arr, format, legend)
    else:
        print('No data!')


def _normalize_format(fmt):
    """把 -f 收到的任意字符串归一化成格式名；空值回退 png。

    是否真能保存由 matplotlib 在 savefig 时决定（见 _save_figure），
    这里不做白名单，也不预先拦截。
    """
    raw = str(fmt or '').strip().lstrip('.').lower()
    if not raw:
        print("警告：未指定图片格式，已改用 png。")
        return 'png'
    return raw


def _save_figure(name, fmt):
    """保存一张图；真正无法保存时提示并回退 png，返回实际使用的格式。

    get_supported_filetypes() 只反映后端声明的能力，像 pgf（缺 LaTeX）、
    avif（缺 Pillow 插件）这类格式仍会在真实 savefig 时抛异常，所以以
    实际保存结果为准。第一张图失败后，后续两张沿用回退后的格式。
    """
    path = "%s.%s" % (name, fmt)
    try:
        plt.savefig(path, dpi=750, transparent=True, bbox_inches='tight')
        return fmt
    except Exception as e:
        if fmt == 'png':
            raise
        reason = str(e).splitlines()[0] if str(e) else type(e).__name__
        print("警告：无法保存 %r 格式的图片（%s），已改用 png。" % (fmt, reason))
        try:
            os.remove(path)
        except OSError:
            pass
        plt.savefig("%s.png" % name, dpi=750, transparent=True, bbox_inches='tight')
        return 'png'


def plot(arr, format, legend):
    format = _normalize_format(format)
    plt.rcParams['xtick.direction'] = 'in'
    plt.rcParams['ytick.direction'] = 'in'
    plt.rcParams['font.family'] = 'STIXGeneral'
    plt.rcParams["mathtext.fontset"] = 'cm'
    n, m = arr.shape
    l = (m - 2) // 2
    for i in range(1, l+1):
        plt.plot(arr[:,0],arr[:,i],linewidth=1,linestyle=':',label=r"$spin\ %s$"%(i-1),marker='o',markersize=3)

    plt.xlabel('Temperature (K)')
    plt.ylabel('Magnetism')
    plt.xlim(arr[0,0], arr[-1,0])
    plt.grid(axis="x", ls='--', lw=0.5)
    plt.minorticks_on()
    plt.tick_params(axis='both', which='minor', color='gray')
    plt.legend(loc='upper right', frameon=False, prop={'style':'italic','size':'medium'}, alignment='left', title=legend, title_fontproperties={'size':'medium'})
    format = _save_figure('magnetism', format)

    plt.clf()
    plt.xlabel('Temperature (K)')
    plt.ylabel('Susceptibility')
    plt.xlim(arr[0,0], arr[-1,0])
    plt.grid(axis="x", ls='--', lw=0.5)
    plt.minorticks_on()
    for i in range(l+1, m-1):
        plt.plot(arr[:,0],arr[:,i],linewidth=1,linestyle=':',label=r'$spin\ %s$'%(i-l-1),marker='o',markersize=3)

    plt.tick_params(axis='both', which='minor', color='gray')
    plt.legend(loc='upper left', frameon=False, prop={'style':'italic','size':'medium'}, alignment='left', title=legend, title_fontproperties={'size':'medium'})
    format = _save_figure('susceptibility', format)

    plt.clf()
    plt.xlabel('Temperature (K)')
    plt.ylabel('Specific Heat')
    plt.xlim(arr[0,0], arr[-1,0])
    plt.grid(axis="x", ls='--', lw=0.5)
    plt.minorticks_on()
    plt.plot(arr[:,0],arr[:,-1],linewidth=1,linestyle=':',label=r'$specific\ heat$',marker='o',markersize=3)
    plt.tick_params(axis='both', which='minor', color='gray')
    plt.legend(loc='upper left', frameon=False, prop={'style':'italic','size':'medium'}, alignment='left', title=legend, title_fontproperties={'size':'medium'})
    format = _save_figure('specific_heat', format)
