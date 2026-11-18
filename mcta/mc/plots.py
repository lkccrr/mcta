import os

import numpy as np
import matplotlib.pyplot as plt

from mcta.flags import (font_family, mathtext_fontset, resol,
                        xtick_direction, ytick_direction)


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


def main(file, format, legend, temperature=None):
    with open(file, "r") as f:
        lines = f.readlines()

    rows = _read_rows(lines)
    if not rows:
        print('No data!')
        return
    # XY 日志表头含 helicity，数据列是 T/mag/chi/cv/Υ/vortex/time，
    # 走专用绘图（含 2kT/π 普适跳变参考线）。
    if any('helicity' in ln for ln in lines):
        from mcta.mc.engine import kB
        arr = np.array([r[0:-1] for r in rows], dtype=float)  # 去掉 time
        plot_xy(arr, format, legend, kB)
        # 同目录若有构型快照 npz，额外绘制指定温度的涡旋状态箭头图
        from mcta.mc.xy_engine import snapshot_path
        snap = snapshot_path(file)
        if os.path.isfile(snap):
            Tsel, nv, name = plot_vortex_state(snap, temperature, format, legend)
            print('涡旋状态图: T = %.2f K, 涡旋核心 %d 个 -> %s.%s'
                  % (Tsel, nv, name, format))
    else:
        arr = np.array([r[0:-1] for r in rows], dtype=float)
        plot(arr, format, legend)


def plot_xy(arr, format, legend, kB):
    """XY 模型四联图：磁化、磁化率、比热、螺旋度（+涡旋）。

    ``arr`` 列：Temperature, magnetism, susceptibility, specific heat,
    helicity(Υ), vortex。螺旋度面板叠加普适跳变参考线 2 k_B T / π，
    与 Υ(T) 的交点即 T_BKT 的有限尺寸估计。
    """
    format = _normalize_format(format)
    plt.rcParams['xtick.direction'] = xtick_direction()
    plt.rcParams['ytick.direction'] = ytick_direction()
    plt.rcParams['font.family'] = font_family()
    plt.rcParams["mathtext.fontset"] = mathtext_fontset()
    T = arr[:, 0]

    panels = (
        ('magnetism', r"$m=|\langle e^{i\theta}\rangle|$", arr[:, 1], 'magnetism'),
        ('susceptibility', 'Susceptibility', arr[:, 2], 'susceptibility'),
        ('specific_heat', 'Specific heat', arr[:, 3], 'specific_heat'),
    )
    for name, ylabel, y, _ in panels:
        plt.figure()
        plt.plot(T, y, linewidth=1, linestyle=':', marker='o', markersize=3,
                 label=legend or None)
        plt.xlabel('Temperature (K)')
        plt.ylabel(ylabel)
        plt.xlim(T[0], T[-1])
        plt.grid(axis="x", ls='--', lw=0.5)
        plt.minorticks_on()
        plt.tick_params(axis='both', which='minor', color='gray')
        if legend:
            plt.legend(loc='upper right', frameon=False)
        _save_figure(name, format)
        plt.close()

    # 螺旋度 + 普适跳变参考线
    plt.figure()
    plt.plot(T, arr[:, 4], linewidth=1, linestyle=':', marker='o',
             markersize=3, label=r'$\Upsilon$')
    plt.plot(T, 2 * kB * T / np.pi, linewidth=1, ls='--',
             label=r'$2k_BT/\pi$')
    plt.xlabel('Temperature (K)')
    plt.ylabel('Helicity modulus (meV)')
    plt.xlim(T[0], T[-1])
    plt.grid(axis="x", ls='--', lw=0.5)
    plt.minorticks_on()
    plt.legend(loc='upper right', frameon=False)
    _save_figure('helicity', format)
    plt.close()

    # 涡旋密度
    plt.figure()
    plt.plot(T, arr[:, 5], linewidth=1, linestyle=':', marker='o',
             markersize=3, color='tab:red')
    plt.xlabel('Temperature (K)')
    plt.ylabel('Vortex density')
    plt.xlim(T[0], T[-1])
    plt.grid(axis="x", ls='--', lw=0.5)
    plt.minorticks_on()
    _save_figure('vortex', format)
    plt.close()


def plot_vortex_state(state_file, temperature=None, format='png', legend=''):
    """读取 XY 构型快照，画指定温度的自旋小箭头图并标出涡旋核心。

    ``state_file`` 是 :func:`mcta.mc.xy_engine.save_snapshots` 写出的 npz，
    含 confg / X / Y / a1 / a2 / basis / temps / states。每个格点的自旋用
    单位小箭头表示（方向 = θ，颜色按 θ 的 hsv 周期着色）；相位绕数非零的
    最小环（涡旋/反涡旋）用空心圈标出，圈内 + 号为正绕数、× 号为负绕数。

    ``temperature`` 为 None 时取最高温度（通常涡旋最活跃）；给定数值时取
    快照里最接近的那个温度。返回 (实际温度, 检测到的涡旋核心数)。
    """
    from mcta.mc.geometry import xy_geometry as xg

    d = np.load(state_file)
    confg = str(d['confg'])
    X, Y = int(d['X']), int(d['Y'])
    a1, a2, basis = d['a1'], d['a2'], d['basis']
    temps = np.asarray(d['temps'], dtype=float)
    states = np.asarray(d['states'])                 # (nT, ncell, Y, X)

    idx = -1 if temperature is None else int(np.argmin(np.abs(temps - float(temperature))))
    Tsel = float(temps[idx])
    theta = states[idx]                              # (ncell, Y, X)
    ncell = basis.shape[0]

    # (cell, j, i) -> 笛卡尔坐标 basis[cell] + j*a2 + i*a1
    px = np.empty((ncell, Y, X), dtype=float)
    py = np.empty_like(px)
    for c in range(ncell):
        for j in range(Y):
            for i in range(X):
                px[c, j, i] = i * a1[0] + j * a2[0] + basis[c, 0]
                py[c, j, i] = i * a1[1] + j * a2[1] + basis[c, 1]

    U = np.cos(theta)
    V = np.sin(theta)
    color = plt.cm.hsv((theta % (2 * np.pi)) / (2 * np.pi)).reshape(-1, 4)

    # 相位绕数 -> 涡旋核心：重建最小环，逐环累加 wrap(Δθ)
    lat = xg.build(confg, X, Y)
    loops, ptr = lat.xy_loops, lat.xy_loop_ptr
    two_pi = 2 * np.pi

    def wrap(a):
        return a - two_pi * np.floor(a / two_pi + 0.5)

    cores = []
    for p in range(ptr.shape[0] - 1):
        seq = loops[ptr[p]:ptr[p + 1]]
        m = len(seq)
        if m == 0:
            continue
        w = 0.0
        cx = cy = 0.0
        for k in range(m):
            c, j, i = (int(v) for v in seq[k])
            c2, j2, i2 = (int(v) for v in seq[(k + 1) % m])
            w += wrap(theta[c2, j2, i2] - theta[c, j, i])
            cx += px[c, j, i]
            cy += py[c, j, i]
        if abs(w) > np.pi:                       # |绕数| >= 1
            cores.append((cx / m, cy / m, 1 if w > 0 else -1))

    # ---- 绘图 ----
    format = _normalize_format(format)
    plt.rcParams['xtick.direction'] = xtick_direction()
    plt.rcParams['ytick.direction'] = ytick_direction()
    plt.rcParams['font.family'] = font_family()
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.quiver(px.ravel(), py.ravel(), U.ravel(), V.ravel(), color=color,
              angles='xy', scale_units='xy', scale=1.3, width=0.004)
    for cx, cy, sgn in cores:
        mark = '+' if sgn > 0 else 'x'
        col = 'red' if sgn > 0 else 'blue'
        ax.plot(cx, cy, marker='o', ms=11, mfc='none', mec=col, mew=1.6)
        ax.plot(cx, cy, marker=mark, ms=7, color=col, mew=1.6)
    ax.set_aspect('equal')
    ax.set_xlabel('x (a_nn)')
    ax.set_ylabel('y (a_nn)')
    title = "%s  T = %.2f K" % (confg, Tsel)
    if legend:
        title += "  " + legend
    ax.set_title(title)
    pad = 0.6
    ax.set_xlim(px.min() - pad, px.max() + pad)
    ax.set_ylim(py.min() - pad, py.max() + pad)
    name = 'vortex_state' if temperature is None else 'vortex_state_T%g' % Tsel
    _save_figure(name, format)
    plt.close(fig)
    return Tsel, len(cores), name


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
        plt.savefig(path, dpi=resol(), transparent=True, bbox_inches='tight')
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
        plt.savefig("%s.png" % name, dpi=resol(), transparent=True, bbox_inches='tight')
        return 'png'


def plot(arr, format, legend):
    format = _normalize_format(format)
    plt.rcParams['xtick.direction'] = xtick_direction()
    plt.rcParams['ytick.direction'] = ytick_direction()
    plt.rcParams['font.family'] = font_family()
    plt.rcParams["mathtext.fontset"] = mathtext_fontset()
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
