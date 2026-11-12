import matplotlib.pyplot as plt

# mt.band

# 自旋向下的曲线画在负半轴（与 VASP/Origin 的常规做法一致）；
# 标签里带 down / dw / ↓ 的视为自旋向下（先去掉 $ 数学标记，兼容 "$dw$" 写法）。
_DOWN_KEYS = ('dw', 'down', '↓')

def is_down_spin(label):
    text = (label or '').lower().replace('$', '').replace(' ', '')
    return any(key in text for key in _DOWN_KEYS)

def mirror_on(fig_p, elements):
    """是否需要把自旋向下取负：默认开启，`--no-mirror` 关闭。"""
    if not getattr(fig_p, 'mirror', True):
        return False
    return any(is_down_spin(element) for element in elements)

def dos_curve(darr, dele, index_f, i, elements, mirror):
    """取第 i 条 DOS 曲线的 ``(DOS, energy)``；自旋向下时把 DOS 取负。"""
    dos = dele[index_f[i][0]].T[index_f[i][1]]
    energy = darr[index_f[i][0]]
    if mirror and i < len(elements) and is_down_spin(elements[i]):
        dos = -dos
    return dos, energy

def symmetric(limits, mirror):
    """镜像后把单边的 DOS 范围补成关于 0 对称，避免负半轴被裁掉。"""
    if not mirror or not limits:
        return limits
    top = max(abs(limits[0]), abs(limits[1]))
    return [-top, top]

def Noneispin(arr, bands, ticks, labels, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['r']
    linestyle = fig_p.linestyle or ['-']
    linewidth = fig_p.linewidth or [0.8]
    location  = fig_p.location  or [0]
    plt.plot(arr, bands.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.legend([legend[0]], frameon=False, prop={'size':'medium'}, loc=location[0])
    plt.xlim(arr[0], arr[-1])
    plt.ylim(fig_p.vertical)
    plt.ylabel('Energy (eV)')
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Noneispin2(arr, bands, ticks, labels, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['r', 'k']
    linestyle = fig_p.linestyle or ['-', '-.']
    linewidth = fig_p.linewidth + [0.8] * (2 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 2 else fig_p.linewidth
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    if len(color) == 1:
        color = [color[0], 'k']
    if len(linestyle) == 1:
        linestyle = [linestyle[0], '-.']
    f = plt.plot(arr[0], bands[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0][0],arr[0][-1]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.xlim(arr[0][0], arr[0][-1])
    plt.ylim(fig_p.vertical)
    plt.ylabel('Energy (eV)')
    ax = plt.axes()
    g = ax.plot(arr[1], bands[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax.set_xlim(arr[1][0], arr[1][-1])
    ax.set_ylim(fig_p.vertical)
    ax.axis('off')
    L = plt.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    plt.gca().add_artist(L)
    plt.legend([f[0], g[0]], [legend[1], legend[2]], frameon=False, prop={'size':'medium'}, loc=location[1])
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Noneispin3(arr, bands, ticks, labels, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['r', 'k', 'b']
    linestyle = fig_p.linestyle or ['-', '-.', ':']
    linewidth = fig_p.linewidth + [0.8] * (3 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 3 else fig_p.linewidth
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    if len(color) < 3:
        color += [''] * (3 - len(color))
    if len(linestyle) < 3:
        linestyle += ['-'] * (3 - len(linestyle))
    f = plt.plot(arr[0], bands[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0][0],arr[0][-1]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.xlim(arr[0][0], arr[0][-1])
    plt.ylim(fig_p.vertical)
    plt.ylabel('Energy (eV)')
    ax = plt.axes()
    g = ax.plot(arr[1], bands[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax.set_xlim(arr[1][0], arr[1][-1])
    ax.set_ylim(fig_p.vertical)
    ax.axis('off')
    af = plt.axes()
    h = af.plot(arr[2], bands[2].T, color=color[2], linewidth=linewidth[2], linestyle=linestyle[2])
    af.set_xlim(arr[2][0], arr[2][-1])
    af.set_ylim(fig_p.vertical)
    af.axis('off')
    L = plt.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    plt.gca().add_artist(L)
    plt.legend([f[0], g[0], h[0]], [legend[1], legend[2], legend[3]], frameon=False, prop={'size':'medium'}, loc=location[1])
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Ispin(arr, bands, ticks, labels, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['r', 'k']
    linestyle = fig_p.linestyle or ['-', '-.']
    linewidth = fig_p.linewidth + [0.8] * (2 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 2 else fig_p.linewidth
    location  = fig_p.location  or [0]
    if len(color) == 1:
        color = [color[0], 'k']
    if len(linestyle) == 1:
        linestyle = [linestyle[0], '-.']
    p_up = plt.plot(arr, bands[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    p_do = plt.plot(arr, bands[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    plt.legend([p_up[0], p_do[0]], ['up', 'down'], frameon=False, prop={'style':'italic', 'size':'medium'}, loc=location[0],
                alignment='left', title=legend[0], title_fontproperties={'size':'medium'})
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')

    plt.xlim(arr[0], arr[-1])
    plt.ylim(fig_p.vertical)
    plt.xticks(ticks,labels)
    plt.ylabel('Energy (eV)')
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Dispin(arr, bands, ticks, labels, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['r', 'k']
    linestyle = fig_p.linestyle or ['-', '-.']
    linewidth = fig_p.linewidth + [0.8] * (2 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 2 else fig_p.linewidth
    location  = fig_p.location + [0] * (3 - len(fig_p.location)) if len(fig_p.location) < 3 else fig_p.location
    if len(color) == 1:
        color = [color[0], 'k']
    if len(linestyle) == 1:
        linestyle = [linestyle[0], '-.']
    ax1.plot(arr, bands[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    ax2.plot(arr, bands[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    L = ax1.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    ax1.add_artist(L)
    ax1.legend(['up'], frameon=False, prop={'style':'italic', 'size':'medium'}, loc=location[1])
    ax2.legend(['down'], frameon=False, prop={'style':'italic', 'size':'medium'}, loc=location[2])
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax2.tick_params(axis='y', which='minor', color='gray')
    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.set_yticklabels([])
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax2.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    ax1.set_xlim(arr[0], arr[-1])
    ax1.set_ylim(fig_p.vertical)
    ax2.set_xlim(arr[0], arr[-1])
    ax2.set_ylim(fig_p.vertical)
    if len(labels) > 0:
        ax1.set_xticks(ticks,labels[:-1]+[''])
    else:
        ax1.set_xticks(ticks,labels)
    ax2.set_xticks(ticks,labels)
    ax1.set_ylabel('Energy (eV)')
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Dispin2(arr, bands, ticks, labels, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['r', 'r', 'k', 'k']
    linestyle = fig_p.linestyle or ['-', '-', '-.', '-.']
    linewidth = fig_p.linewidth + [0.8] * (4 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 4 else fig_p.linewidth
    location  = fig_p.location + [0] * (3 - len(fig_p.location)) if len(fig_p.location) < 3 else fig_p.location
    if len(color) < 4:
        color += [''] * (4 - len(color))
    if len(linestyle) < 4:
        linestyle += ['-'] * (4 - len(linestyle))
    f1 = ax1.plot(arr[0], bands[0][0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    f2 = ax2.plot(arr[0], bands[0][1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    L = ax1.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    ax1.add_artist(L)
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax2.tick_params(axis='y', which='minor', color='gray')
    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.set_yticklabels([])
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0][0],arr[0][-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax2.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    ax1.set_xlim(arr[0][0], arr[0][-1])
    ax1.set_ylim(fig_p.vertical)
    ax2.set_xlim(arr[0][0], arr[0][-1])
    ax2.set_ylim(fig_p.vertical)
    if len(labels) > 0:
        ax1.set_xticks(ticks,labels[:-1]+[''])
    else:
        ax1.set_xticks(ticks,labels)
    ax2.set_xticks(ticks,labels)
    ax1.set_ylabel('Energy (eV)')
    ax1_f = fig.add_subplot(1,2,1)
    g1 = ax1_f.plot(arr[1], bands[1][0].T, color=color[2], linewidth=linewidth[2], linestyle=linestyle[2])
    ax1_f.set_xlim(arr[1][0], arr[1][-1])
    ax1_f.set_ylim(fig_p.vertical)
    ax1_f.axis('off')
    ax2_f = fig.add_subplot(1,2,2)
    g2 = ax2_f.plot(arr[1], bands[1][1].T, color=color[3], linewidth=linewidth[3], linestyle=linestyle[3])
    ax2_f.set_xlim(arr[1][0], arr[1][-1])
    ax2_f.set_ylim(fig_p.vertical)
    ax2_f.axis('off')
    ax1.legend([f1[0], g1[0]], [legend[1], legend[2]], frameon=False, prop={'size':'medium'}, loc=location[1],
                alignment='left', title='up', title_fontproperties={'style':'italic', 'size':'medium'})
    ax2.legend([f2[0], g2[0]], [legend[1], legend[2]], frameon=False, prop={'size':'medium'}, loc=location[2],
                alignment='left', title='down', title_fontproperties={'style':'italic', 'size':'medium'})
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Dispin3(arr, bands, ticks, labels, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['r', 'r', 'k', 'k', 'b', 'b']
    linestyle = fig_p.linestyle or ['-', '-', '-.', '-.', ':', ':']
    linewidth = fig_p.linewidth + [0.8] * (6 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 6 else fig_p.linewidth
    location  = fig_p.location + [0] * (3 - len(fig_p.location)) if len(fig_p.location) < 3 else fig_p.location
    if len(color) < 6:
        color += [''] * (6 - len(color))
    if len(linestyle) < 6:
        linestyle += ['-'] * (6 - len(linestyle))
    f1 = ax1.plot(arr[0], bands[0][0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    f2 = ax2.plot(arr[0], bands[0][1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    L = ax1.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    ax1.add_artist(L)
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax2.tick_params(axis='y', which='minor', color='gray')

    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.set_yticklabels([])
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0][0],arr[0][-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax2.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    ax1.set_xlim(arr[0][0], arr[0][-1])
    ax1.set_ylim(fig_p.vertical)
    ax2.set_xlim(arr[0][0], arr[0][-1])
    ax2.set_ylim(fig_p.vertical)
    if len(labels) > 0:
        ax1.set_xticks(ticks,labels[:-1]+[''])
    else:
        ax1.set_xticks(ticks,labels)
    ax2.set_xticks(ticks,labels)
    ax1.set_ylabel('Energy (eV)')
    ax1_f = fig.add_subplot(1,2,1)
    g1 = ax1_f.plot(arr[1], bands[1][0].T, color=color[2], linewidth=linewidth[2], linestyle=linestyle[2])
    ax1_f.set_xlim(arr[1][0], arr[1][-1])
    ax1_f.set_ylim(fig_p.vertical)
    ax1_f.axis('off')
    ax2_f = fig.add_subplot(1,2,2)
    g2 = ax2_f.plot(arr[1], bands[1][1].T, color=color[3], linewidth=linewidth[3], linestyle=linestyle[3])
    ax2_f.set_xlim(arr[1][0], arr[1][-1])
    ax2_f.set_ylim(fig_p.vertical)
    ax2_f.axis('off')
    ax1_g = fig.add_subplot(1,2,1)
    h1 = ax1_g.plot(arr[2], bands[2][0].T, color=color[4], linewidth=linewidth[4], linestyle=linestyle[4])
    ax1_g.set_xlim(arr[2][0], arr[2][-1])
    ax1_g.set_ylim(fig_p.vertical)
    ax1_g.axis('off')
    ax2_g = fig.add_subplot(1,2,2)
    h2 = ax2_g.plot(arr[2], bands[2][1].T, color=color[5], linewidth=linewidth[5], linestyle=linestyle[5])
    ax2_g.set_xlim(arr[2][0], arr[2][-1])
    ax2_g.set_ylim(fig_p.vertical)
    ax2_g.axis('off')
    ax1.legend([f1[0], g1[0], h1[0]], [legend[1], legend[2], legend[3]], frameon=False, prop={'size':'medium'}, loc=location[1],
                alignment='left', title='up', title_fontproperties={'style':'italic', 'size':'medium'})
    ax2.legend([f2[0], g2[0], h2[0]], [legend[1], legend[2], legend[3]], frameon=False, prop={'size':'medium'}, loc=location[2],
                alignment='left', title='down', title_fontproperties={'style':'italic', 'size':'medium'})
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def NoneispinWd(arr, bands, ticks, labels, darr, dele, index_f, elements, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(1, 2, width_ratios=[1-fig_p.width_ratios, fig_p.width_ratios], figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['r']
    linestyle = fig_p.linestyle or ['-']
    linewidth = fig_p.linewidth or [0.8]
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    ax1.plot(arr, bands.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    num = len(index_f)
    p_dos = []
    if num + 1 > len(color):
        color = color + [''] * (num + 1 - len(color))
    if num + 1 > len(linestyle):
        linestyle = linestyle + ['-'] * (num + 1 - len(linestyle))
    if num + 1 > len(linewidth):
        linewidth = linewidth + [0.8] * (num + 1 - len(linewidth))
    mirror = mirror_on(fig_p, elements)
    for i in range(num):
        x, y = dos_curve(darr, dele, index_f, i, elements, mirror)
        if color[i+1]:
            p_dos += ax2.plot(x, y, linewidth=linewidth[i+1], linestyle=linestyle[i+1], color=color[i+1])
            if fig_p.fill:
                ax2.fill_between(x, y, 0, color=color[i+1], alpha=fig_p.fill)
        else:
            p_dos += ax2.plot(x, y, linewidth=linewidth[i+1], linestyle=linestyle[i+1])
            if fig_p.fill:
                ax2.fill_between(x, y, 0, alpha=fig_p.fill)
    ax1.legend([legend[0]], frameon=False, prop={'size':'small'}, loc=location[0])
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax2.minorticks_on()
    ax2.tick_params(axis='both', which='minor', color='gray')
    ax2.set_yticklabels([])
    ax2.legend(p_dos, elements, frameon=False, prop={'size':'small'}, loc=location[1],
               alignment='left', title="Density of states", title_fontproperties={'size':'small'})
    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axvline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            ax1.axvline(i,linewidth=0.4,linestyle='-.',c='gray')
    ax1.set_xlim(arr[0], arr[-1])
    ax1.set_ylim(fig_p.vertical)
    ax2.set_xlim(symmetric(fig_p.horizontal, mirror))
    ax2.set_ylim(fig_p.vertical)
    ax1.set_xticks(ticks,labels)
    ax2.tick_params(axis='x', labelsize='x-small', labelcolor='dimgray', labelrotation=-90, pad=1.5)
    ax1.set_ylabel('Energy (eV)')
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def IspinWd(arr, bands, ticks, labels, darr, dele, index_f, elements, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(1, 2, width_ratios=[1-fig_p.width_ratios, fig_p.width_ratios], figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['r', 'k']
    linestyle = fig_p.linestyle or ['-', '-.']
    linewidth = fig_p.linewidth or [0.8, 0.8]
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    if len(color) == 1:
        color = [color[0], 'k']
    if len(linestyle) == 1:
        linestyle = [linestyle[0], '-.']
    if len(linewidth) == 1:
        linewidth = [linewidth[0], 0.8]
    p_up = ax1.plot(arr, bands[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    p_do = ax1.plot(arr, bands[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax1.legend([p_up[0], p_do[0]], ['up', 'down'], frameon=False, prop={'style':'italic', 'size':'small'}, loc=location[0], alignment='left', title=legend[0], title_fontproperties={'size':'small'})
    num = len(index_f)
    p_dos = []
    if num + 2 > len(color):
        color += [''] * (num + 2 - len(color))
    if num + 2 > len(linestyle):
        linestyle += ['-'] * (num + 2 - len(linestyle))
    if num + 2 > len(linewidth):
        linewidth += [0.8] * (num + 2 - len(linewidth))
    mirror = mirror_on(fig_p, elements)
    for i in range(num):
        x, y = dos_curve(darr, dele, index_f, i, elements, mirror)
        if color[i+2]:
            p_dos += ax2.plot(x, y, linewidth=linewidth[i+2], linestyle=linestyle[i+2], color=color[i+2])
            if fig_p.fill:
                ax2.fill_between(x, y, 0, color=color[i+2], alpha=fig_p.fill)
        else:
            p_dos += ax2.plot(x, y, linewidth=linewidth[i+2], linestyle=linestyle[i+2])
            if fig_p.fill:
                ax2.fill_between(x, y, 0, alpha=fig_p.fill)
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax2.minorticks_on()
    ax2.tick_params(axis='both', which='minor', color='gray')
    ax2.axvline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.set_yticklabels([])
    ax2.legend(p_dos, elements, frameon=False, prop={'size':'small'}, loc=location[1], alignment='left', title="Density of states", title_fontproperties={'size':'small'})
    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            ax1.axvline(i,linewidth=0.4, linestyle='-.', c='gray')
    ax1.set_xlim(arr[0], arr[-1])
    ax1.set_ylim(fig_p.vertical)
    ax2.set_xlim(symmetric(fig_p.horizontal, mirror))
    ax2.set_ylim(fig_p.vertical)
    ax1.set_xticks(ticks,labels)
    ax2.tick_params(axis='x', labelsize='x-small', labelcolor='dimgray', labelrotation=-90, pad=1.5)
    ax1.set_ylabel('Energy (eV)')
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def DispinWd(arr, bands, ticks, labels, darr, dele, index_f, elements, legend, fig_p):
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, width_ratios=[0.5*(1-fig_p.width_ratios), 0.5*(1-fig_p.width_ratios), fig_p.width_ratios], figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['r', 'k']
    linestyle = fig_p.linestyle or ['-', '-.']
    linewidth = fig_p.linewidth or [0.8, 0.8]
    location  = fig_p.location + [0] * (4 - len(fig_p.location)) if len(fig_p.location) < 4 else fig_p.location
    if len(color) == 1:
        color = [color[0], 'k']
    if len(linestyle) == 1:
        linestyle = [linestyle[0], '-.']
    if len(linewidth) == 1:
        linewidth = [linewidth[0], 0.8]
    ax1.plot(arr, bands[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    ax2.plot(arr, bands[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    L = ax1.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'small'})
    ax1.add_artist(L)
    ax1.legend(['up'], frameon=False, prop={'style':'italic', 'size':'small'}, loc=location[1])
    ax2.legend(['down'], frameon=False, prop={'style':'italic', 'size':'small'}, loc=location[2])
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax2.tick_params(axis='y', which='minor', color='gray')
    ax3.minorticks_on()
    ax3.tick_params(axis='both', which='minor', color='gray')
    num = len(index_f)
    p_dos = []
    if num + 2 > len(color):
        color += [''] * (num + 2 - len(color))
    if num + 2 > len(linestyle):
        linestyle += ['-'] * (num + 2 - len(linestyle))
    if num + 2 > len(linewidth):
        linewidth += [0.8] * (num + 2 - len(linewidth))
    mirror = mirror_on(fig_p, elements)
    for i in range(num):
        x, y = dos_curve(darr, dele, index_f, i, elements, mirror)
        if color[i+2]:
            p_dos += ax3.plot(x, y, linewidth=linewidth[i+2], linestyle=linestyle[i+2], color=color[i+2])
            if fig_p.fill:
                ax3.fill_between(x, y, 0, color=color[i+2], alpha=fig_p.fill)
        else:
            p_dos += ax3.plot(x, y, linewidth=linewidth[i+2], linestyle=linestyle[i+2])
            if fig_p.fill:
                ax3.fill_between(x, y, 0, alpha=fig_p.fill)
    ax3.axvline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.set_yticklabels([])
    ax3.set_yticklabels([])
    ax3.legend(p_dos, elements, frameon=False, prop={'size':'small'}, loc=location[3], alignment='left', title="Density of states", title_fontproperties={'size':'small'})
    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax3.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            ax1.axvline(i,linewidth=0.4,linestyle='-.',c='gray')
            ax2.axvline(i,linewidth=0.4,linestyle='-.',c='gray')
    ax1.set_xlim(arr[0], arr[-1])
    ax1.set_ylim(fig_p.vertical)
    ax2.set_xlim(arr[0], arr[-1])
    ax2.set_ylim(fig_p.vertical)
    ax3.set_xlim(symmetric(fig_p.horizontal, mirror))
    ax3.set_ylim(fig_p.vertical)
    if len(labels) > 0:
        ax1.set_xticks(ticks,labels[:-1]+[''])
    else:
        ax1.set_xticks(ticks,labels)
    ax2.set_xticks(ticks,labels)
    ax3.tick_params(axis='x', labelsize='x-small', labelcolor='dimgray', labelrotation=-90, pad=1.5)
    ax1.set_ylabel('Energy (eV)')
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def pdosfiles(darr, dele, index_f, elements, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    plt.minorticks_on()
    plt.tick_params(axis='both', which='minor', color='gray')
    num = len(index_f)
    p_dos = []
    color = fig_p.color
    linestyle = fig_p.linestyle
    linewidth = fig_p.linewidth
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    if num > len(color):
        color += [''] * (num - len(color))
    if num > len(linestyle):
        linestyle += ['-'] * (num - len(linestyle))
    if num > len(linewidth):
        linewidth += [0.8] * (num - len(linewidth))
    mirror = mirror_on(fig_p, elements)
    if fig_p.exchange:
        # 能量为横轴
        for i in range(num):
            dos, energy = dos_curve(darr, dele, index_f, i, elements, mirror)
            if color[i]:
                p_dos += plt.plot(energy, dos, linewidth=linewidth[i], linestyle=linestyle[i], color=color[i])
                if fig_p.fill:
                    plt.fill_between(energy, dos, 0, color=color[i], alpha=fig_p.fill)
            else:
                p_dos += plt.plot(energy, dos, linewidth=linewidth[i], linestyle=linestyle[i])
                if fig_p.fill:
                    plt.fill_between(energy, dos, 0, alpha=fig_p.fill)
        plt.tick_params(axis='y', labelsize='medium', labelcolor='dimgray')
        plt.xlim(fig_p.vertical)
        plt.ylim(symmetric(fig_p.horizontal, mirror))
        plt.xlabel('Energy (eV)')
        plt.ylabel('Density of states, electrons/eV')
    else:
        # 默认与「能带 + DOS」面板一致：能量为纵轴，DOS 为横轴
        for i in range(num):
            dos, energy = dos_curve(darr, dele, index_f, i, elements, mirror)
            if color[i]:
                p_dos += plt.plot(dos, energy, linewidth=linewidth[i], linestyle=linestyle[i], color=color[i])
                if fig_p.fill:
                    plt.fill_between(dos, energy, 0, color=color[i], alpha=fig_p.fill)
            else:
                p_dos += plt.plot(dos, energy, linewidth=linewidth[i], linestyle=linestyle[i])
                if fig_p.fill:
                    plt.fill_between(dos, energy, 0, alpha=fig_p.fill)
        plt.tick_params(axis='x', labelsize='medium', labelcolor='dimgray')
        plt.xlim(symmetric(fig_p.horizontal, mirror))
        plt.ylim(fig_p.vertical)
        plt.ylabel('Energy (eV)')
        plt.xlabel('Density of states, electrons/eV')
    L = plt.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    plt.gca().add_artist(L)
    plt.axvline(linewidth=0.4, linestyle='-.', c='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    plt.legend(p_dos, elements, frameon=False, prop={'size':'medium'}, loc=location[1])
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

