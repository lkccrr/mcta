import matplotlib.pyplot as plt

# mt.phband

def Broken(arr, fre, ticks, labels, broken, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, height_ratios=[fig_p.height_ratio, 1-fig_p.height_ratio], figsize=fig_p.size)
    fig.subplots_adjust(hspace=0.0)
    color = fig_p.color or ['r']
    linestyle = fig_p.linestyle or ['-']
    linewidth = fig_p.linewidth or [0.8]
    location  = fig_p.location  or [0]
    ax1.plot(arr, fre.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    ax2.plot(arr, fre.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.xlim(arr[0], arr[-1])
    vertical = fig_p.vertical or plt.ylim()
    ax1.set_ylim(broken[1], vertical[1])
    ax2.set_ylim(vertical[0], broken[0])
    ax1.spines['bottom'].set_visible(False)
    ax2.spines['top'].set_visible(False)
    ax1.xaxis.set_ticks_position(position='none')
    ax1.tick_params(axis='y', which='minor', color='darkgray')
    ax1.tick_params(axis='y', labelsize='small', labelcolor='dimgray', labelrotation=-60)
    ax2.tick_params(axis='y', which='minor', color='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax2.axvline(i, linewidth=0.4, linestyle='-.', c='gray')

    ax2.legend([legend[0]], frameon=False, prop={'size':'medium'}, loc=location[0])
    plt.xticks(ticks,labels)
    plt.suptitle('Frequency (THz)', rotation=90, x=0.06, y=0.6, size='medium')
    kwargs = dict(marker=[(-1, -1), (1, 1)], markersize=6,
                  linestyle='', color='k', mec='k', mew=1, clip_on=False)
    ax1.plot([0, 1], [0.02, 0.02], transform=ax1.transAxes, **kwargs)
    ax2.plot([0, 1], [0.98, 0.98], transform=ax2.transAxes, **kwargs)
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Broken2(arr, fre, ticks, labels, broken, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, height_ratios=[fig_p.height_ratio, 1-fig_p.height_ratio], figsize=fig_p.size)
    fig.subplots_adjust(hspace=0.0)
    color = fig_p.color or ['r', 'k']
    linestyle = fig_p.linestyle or ['-', '-.']
    linewidth = fig_p.linewidth + [0.8] * (2 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 2 else fig_p.linewidth
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    if len(color) == 1:
        color = [color[0], 'k']
    if len(linestyle) == 1:
        linestyle = [linestyle[0], '-.']
    ax1.plot(arr[0], fre[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    f = ax2.plot(arr[0], fre[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.xlim(arr[0][0], arr[0][-1])
    vertical = fig_p.vertical or plt.ylim()
    ax1.set_ylim(broken[1], vertical[1])
    ax2.set_ylim(vertical[0], broken[0])
    ax1.spines['bottom'].set_visible(False)
    ax2.spines['top'].set_visible(False)
    ax1.xaxis.set_ticks_position(position='none')
    ax1.tick_params(axis='y', which='minor', color='darkgray')
    ax1.tick_params(axis='y', labelsize='small', labelcolor='dimgray', labelrotation=-60)
    ax2.tick_params(axis='y', which='minor', color='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0][0],arr[0][-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax2.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.suptitle('Frequency (THz)', rotation=90, x=0.06, y=0.6, size='medium')
    kwargs = dict(marker=[(-1, -1), (1, 1)], markersize=6,
                  linestyle='', color='k', mec='k', mew=1, clip_on=False)
    ax1.plot([0, 1], [0.02, 0.02], transform=ax1.transAxes, **kwargs)
    ax2.plot([0, 1], [0.98, 0.98], transform=ax2.transAxes, **kwargs)
    ax1_f = fig.add_subplot(2,1,1)
    ax1_f.plot(arr[1], fre[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax1_f.set_xlim(arr[1][0], arr[1][-1])
    ax1_f.set_ylim(broken[1], vertical[1])
    ax1_f.axis('off')
    ax2_f = fig.add_subplot(2,1,2)
    g = ax2_f.plot(arr[1], fre[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax2_f.set_xlim(arr[1][0], arr[1][-1])
    ax2_f.set_ylim(vertical[0], broken[0])
    ax2_f.axis('off')
    L = ax2.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0., 0.5, 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    ax2.add_artist(L)
    ax2.legend([f[0], g[0]], [legend[1], legend[2]], frameon=False, prop={'size':'medium'}, loc=location[1])
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Broken3(arr, fre, ticks, labels, broken, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, height_ratios=[fig_p.height_ratio, 1-fig_p.height_ratio], figsize=fig_p.size)
    fig.subplots_adjust(hspace=0.0)
    color = fig_p.color or ['r', 'k', 'b']
    linestyle = fig_p.linestyle or ['-', '-.', ':']
    linewidth = fig_p.linewidth + [0.8] * (3 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 3 else fig_p.linewidth
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    if len(color) < 3:
        color += [''] * (3 - len(color))
    if len(linestyle) < 3:
        linestyle += ['-'] * (3 - len(linestyle))
    ax1.plot(arr[0], fre[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    f = ax2.plot(arr[0], fre[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.xlim(arr[0][0], arr[0][-1])
    vertical = fig_p.vertical or plt.ylim()
    ax1.set_ylim(broken[1], vertical[1])
    ax2.set_ylim(vertical[0], broken[0])
    ax1.spines['bottom'].set_visible(False)
    ax2.spines['top'].set_visible(False)
    ax1.xaxis.set_ticks_position(position='none')
    ax1.tick_params(axis='y', which='minor', color='darkgray')
    ax1.tick_params(axis='y', labelsize='small', labelcolor='dimgray', labelrotation=-60)
    ax2.tick_params(axis='y', which='minor', color='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0][0],arr[0][-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax2.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.suptitle('Frequency (THz)', rotation=90, x=0.06, y=0.6, size='medium')
    kwargs = dict(marker=[(-1, -1), (1, 1)], markersize=6,
                  linestyle='', color='k', mec='k', mew=1, clip_on=False)
    ax1.plot([0, 1], [0.02, 0.02], transform=ax1.transAxes, **kwargs)
    ax2.plot([0, 1], [0.98, 0.98], transform=ax2.transAxes, **kwargs)
    ax1_f = fig.add_subplot(2,1,1)
    ax1_f.plot(arr[1], fre[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax1_f.set_xlim(arr[1][0], arr[1][-1])
    ax1_f.set_ylim(broken[1], vertical[1])
    ax1_f.axis('off')
    ax2_f = fig.add_subplot(2,1,2)
    g = ax2_f.plot(arr[1], fre[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax2_f.set_xlim(arr[1][0], arr[1][-1])
    ax2_f.set_ylim(vertical[0], broken[0])
    ax2_f.axis('off')
    ax1_g = fig.add_subplot(2,1,1)
    ax1_g.plot(arr[2], fre[2].T, color=color[2], linewidth=linewidth[2], linestyle=linestyle[2])
    ax1_g.set_xlim(arr[2][0], arr[2][-1])
    ax1_g.set_ylim(broken[1], vertical[1])
    ax1_g.axis('off')
    ax2_g = fig.add_subplot(2,1,2)
    h = ax2_g.plot(arr[2], fre[2].T, color=color[2], linewidth=linewidth[2], linestyle=linestyle[2])
    ax2_g.set_xlim(arr[2][0], arr[2][-1])
    ax2_g.set_ylim(vertical[0], broken[0])
    ax2_g.axis('off')
    L = ax2.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0., 0.5, 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    ax2.add_artist(L)
    ax2.legend([f[0], g[0], h[0]], [legend[1], legend[2], legend[3]], frameon=False, prop={'size':'medium'}, loc=location[1])
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Nobroken(arr, fre, ticks, labels, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['r']
    linestyle = fig_p.linestyle or ['-']
    linewidth = fig_p.linewidth or [0.8]
    location  = fig_p.location  or [0]
    plt.plot(arr, fre.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.legend([legend[0]], frameon=False, prop={'size':'medium'}, loc=location[0])
    plt.xticks(ticks,labels)
    plt.xlim(arr[0], arr[-1])
    plt.ylim(fig_p.vertical)
    plt.ylabel('Frequency (THz)')
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Nobroken2(arr, fre, ticks, labels, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['r', 'k']
    linestyle = fig_p.linestyle or ['-', '-.']
    linewidth = fig_p.linewidth + [0.8] * (2 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 2 else fig_p.linewidth
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    if len(color) == 1:
        color = [color[0], 'k']
    if len(linestyle) == 1:
        linestyle = [linestyle[0], '-.']
    f = plt.plot(arr[0], fre[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0][0],arr[0][-1]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.xlim(arr[0][0], arr[0][-1])
    ylim=plt.ylim(fig_p.vertical)
    plt.ylabel('Frequency (THz)')
    ax = plt.axes()
    g = ax.plot(arr[1], fre[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax.set_xlim(arr[1][0], arr[1][-1])
    ax.set_ylim(ylim)
    ax.axis('off')
    L = plt.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0., 0.5, 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    plt.gca().add_artist(L)
    plt.legend([f[0], g[0]], [legend[1], legend[2]], frameon=False, prop={'size':'medium'}, loc=location[1])
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def Nobroken3(arr, fre, ticks, labels, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['r', 'k', 'b']
    linestyle = fig_p.linestyle or ['-', '-.', ':']
    linewidth = fig_p.linewidth + [0.8] * (3 - len(fig_p.linewidth)) if len(fig_p.linewidth) < 3 else fig_p.linewidth
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    if len(color) < 3:
        color += [''] * (3 - len(color))
    if len(linestyle) < 3:
        linestyle += ['-'] * (3 - len(linestyle))
    f = plt.plot(arr[0], fre[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0][0],arr[0][-1]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.xlim(arr[0][0], arr[0][-1])
    ylim=plt.ylim(fig_p.vertical)
    plt.ylabel('Frequency (THz)')
    ax = plt.axes()
    g = ax.plot(arr[1], fre[1].T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    ax.set_xlim(arr[1][0], arr[1][-1])
    ax.set_ylim(ylim)
    ax.axis('off')
    af = plt.axes()
    h = af.plot(arr[2], fre[2].T, color=color[2], linewidth=linewidth[2], linestyle=linestyle[2])
    af.set_xlim(arr[2][0], arr[2][-1])
    af.set_ylim(ylim)
    af.axis('off')
    L = plt.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0., 0.5, 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    plt.gca().add_artist(L)
    plt.legend([f[0], g[0], h[0]], [legend[1], legend[2], legend[3]], frameon=False, prop={'size':'medium'}, loc=location[1])
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')


def BrokenWd(arr, fre, ticks, labels, broken, darr, dele, elements, legend, fig_p):
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, height_ratios=[fig_p.height_ratio, 1-fig_p.height_ratio],
                                                 width_ratios=[1-fig_p.width_ratios, fig_p.width_ratios], figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0, hspace=0.0)
    color = fig_p.color or ['r']
    linestyle = fig_p.linestyle or ['-']
    linewidth = fig_p.linewidth or [0.8]
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    ax1.plot(arr, fre.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    ax3.plot(arr, fre.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    num = dele.shape[-1]
    p_dos = []
    if num + 1 > len(color):
        color += [''] * (num - len(color) + 1)
    if num + 1 > len(linestyle):
        linestyle += ['-'] * (num - len(linestyle) + 1)
    if num + 1 > len(linewidth):
        linewidth += [0.8] * (num - len(linewidth) + 1)
    for i in range(num):
        if color[i+1]:
            ax2.plot(dele[:,i], darr, linewidth=linewidth[i+1], linestyle=linestyle[i+1], color=color[i+1])
            p_dos = p_dos + ax4.plot(dele[:,i], darr, linewidth=linewidth[i+1], linestyle=linestyle[i+1], color=color[i+1])
            if fig_p.fill:
                plt.fill_between(dele[:,i], darr, 0, color=color[i+1], alpha=fig_p.fill)
        else:
            ax2.plot(dele[:,i], darr, linewidth=linewidth[i+1], linestyle=linestyle[i+1])
            p_dos = p_dos + ax4.plot(dele[:,i], darr, linewidth=linewidth[i+1], linestyle=linestyle[i+1])
            if fig_p.fill:
                plt.fill_between(dele[:,i], darr, 0, alpha=fig_p.fill)
    ax1.set_xlim(arr[0], arr[-1])
    ax3.set_xlim(arr[0], arr[-1])
    vertical = fig_p.vertical or ax1.get_ylim()
    ax1.set_ylim(broken[1], vertical[1])
    ax2.set_ylim(broken[1], vertical[1])
    ax3.set_ylim(vertical[0], broken[0])
    ax4.set_ylim(vertical[0], broken[0])
    ax2.set_xlim(fig_p.horizontal)
    ax4.set_xlim(fig_p.horizontal)
    ax1.spines['bottom'].set_visible(False)
    ax2.spines['bottom'].set_visible(False)
    ax3.spines['top'].set_visible(False)
    ax4.spines['top'].set_visible(False)
    ax1.xaxis.set_ticks_position('none')
    ax2.xaxis.set_ticks_position('none')
    ax1.tick_params(axis='y', which='minor', color='darkgray')
    ax1.tick_params(axis='y', labelsize='small', labelcolor='dimgray', labelrotation=-60)
    ax3.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax4.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.tick_params(axis='y', which='minor', color='darkgray')
    ax3.tick_params(axis='y', which='minor', color='gray')
    ax4.minorticks_on()
    ax4.tick_params(axis='x', labelsize='small', labelcolor='dimgray', labelrotation=-90, pad=3)
    ax4.tick_params(axis='both', which='minor', color='gray')
    ax1.set_xticklabels([])
    ax2.set_xticklabels([])
    ax2.set_yticklabels([])
    ax4.set_yticklabels([])
    ax2.axvline(linewidth=0.4, linestyle='-.', c='gray')
    ax4.axvline(linewidth=0.4, linestyle='-.', c='gray')
    if num > len(elements):
        elements = elements + [''] * (num - len(elements))
    elif num < len(elements):
        if num == 1:
            elements = ['$tdos$']
        else:
            elements = elements[:num]
    ax3.legend([legend[0]], frameon=False, prop={'size':'small'}, loc=location[0])
    ax4.legend(p_dos, elements, frameon=False, prop={'size':'small'}, loc=location[1],
               alignment='left', title="Phonon DOS", title_fontproperties={'size':'small'})
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax3.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    ax3.set_xticks(ticks,labels)
    plt.suptitle('Frequency (THz)', rotation=90, x=0.06, y=0.6, size='medium')
    kwargs = dict(marker=[(-1, -1), (1, 1)], markersize=6,
                  linestyle='', color='k', mec='k', mew=1, clip_on=False)
    ax1.plot([0, 1], [0.02, 0.02], transform=ax1.transAxes, **kwargs)
    ax3.plot([0, 1], [0.98, 0.98], transform=ax3.transAxes, **kwargs)
    ax2.plot(1, 0.02, transform=ax2.transAxes, **kwargs)
    ax4.plot(1, 0.98, transform=ax4.transAxes, **kwargs)
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def NobrokenWd(arr, fre, ticks, labels, darr, dele, elements, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(1, 2, width_ratios=[1-fig_p.width_ratios, fig_p.width_ratios], figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['r']
    linestyle = fig_p.linestyle or ['-']
    linewidth = fig_p.linewidth or [0.8]
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    ax1.plot(arr, fre.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    num = dele.shape[-1]
    p_dos = []
    if num + 1 > len(color):
        color += [''] * (num - len(color) + 1)
    if num + 1 > len(linestyle):
        linestyle += ['-'] * (num - len(linestyle) + 1)
    if num + 1 > len(linewidth):
        linewidth += [0.8] * (num - len(linewidth) + 1)
    for i in range(num):
        if color[i+1]:
            p_dos = p_dos + ax2.plot(dele[:,i], darr, linewidth=linewidth[i+1], linestyle=linestyle[i+1], color=color[i+1])
            if fig_p.fill:
                plt.fill_between(dele[:,i], darr, 0, color=color[i+1], alpha=fig_p.fill)
        else:
            p_dos = p_dos + ax2.plot(dele[:,i], darr, linewidth=linewidth[i+1], linestyle=linestyle[i+1])
            if fig_p.fill:
                plt.fill_between(dele[:,i], darr, 0, alpha=fig_p.fill)
    ax1.set_xlim(arr[0], arr[-1])
    vertical = fig_p.vertical or ax1.get_ylim()
    ax1.set_ylim(vertical)
    ax2.set_ylim(vertical)
    ax2.set_xlim(fig_p.horizontal)
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.minorticks_on()
    ax2.tick_params(axis='x', labelsize='small', labelcolor='dimgray', labelrotation=-90, pad=3)
    ax2.tick_params(axis='both', which='minor', color='gray')
    ax2.set_yticklabels([])
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if num > len(elements):
        elements = elements + [''] * (num - len(elements))
    elif num < len(elements):
        if num == 1:
            elements = ['$tdos$']
        else:
            elements = elements[:num]
    ax1.legend([legend[0]], frameon=False, prop={'size':'small'}, loc=location[0])
    ax2.axvline(linewidth=0.4,linestyle='-.',c='dimgray')
    ax2.legend(p_dos, elements, frameon=False, prop={'size':'small'}, loc=location[1],
               alignment='left', title="Phonon DOS", title_fontproperties={'size':'small'})
    if len(ticks) > 2:
        ticks[0],ticks[-1] = arr[0],arr[-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    ax1.set_xticks(ticks,labels)
    ax1.set_ylabel('Frequency (THz)')
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def pdosfile(darr, dele, elements, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    plt.minorticks_on()
    plt.tick_params(axis='both', which='minor', color='gray')
    num = dele.shape[-1]
    color = fig_p.color
    linestyle = fig_p.linestyle
    linewidth = fig_p.linewidth
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    p_dos = []
    if num > len(color):
        color += [''] * (num - len(color))
    if num > len(linestyle):
        linestyle += ['-'] * (num - len(linestyle))
    if num > len(linewidth):
        linewidth += [0.8] * (num - len(linewidth))
    if fig_p.exchange:
        for i in range(num):
            if color[i]:
                p_dos = p_dos + plt.plot(darr, dele[:,i], linewidth=linewidth[i], linestyle=linestyle[i], color=color[i])
                if fig_p.fill:
                    plt.fill_between(darr, dele[:,i], 0, color=color[i], alpha=fig_p.fill)
            else:
                p_dos = p_dos + plt.plot(darr, dele[:,i], linewidth=linewidth[i], linestyle=linestyle[i])
                if fig_p.fill:
                    plt.fill_between(darr, dele[:,i], 0, alpha=fig_p.fill)
        plt.xlim(fig_p.vertical)
        plt.ylim(fig_p.horizontal)
        plt.xlabel('Frequency (THz)')
        plt.ylabel('Phonon DOS')
        plt.tick_params(axis='y', labelsize='medium', labelcolor='dimgray')
    else:
        for i in range(num):
            if color[i]:
                p_dos = p_dos + plt.plot(dele[:,i], darr, linewidth=linewidth[i], linestyle=linestyle[i], color=color[i])
                if fig_p.fill:
                    plt.fill_between(dele[:,i], darr, 0, color=color[i], alpha=fig_p.fill)
            else:
                p_dos = p_dos + plt.plot(dele[:,i], darr, linewidth=linewidth[i], linestyle=linestyle[i])
                if fig_p.fill:
                    plt.fill_between(dele[:,i], darr, 0, alpha=fig_p.fill)
        plt.ylim(fig_p.vertical)
        plt.xlim(fig_p.horizontal)
        plt.ylabel('Frequency (THz)')
        plt.xlabel('Phonon DOS')
        plt.tick_params(axis='x', labelsize='medium', labelcolor='dimgray')
    plt.axvline(linewidth=0.4, linestyle='-.', c='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if num > len(elements):
        elements = elements + [''] * (num - len(elements))
    elif num < len(elements):
        if num == 1:
            elements = ['$tdos$']
        else:
            elements = elements[:num]
    plt.legend(p_dos, elements, frameon=False, prop={'size':'medium'}, loc=location[0],
               alignment='left', title=legend[0], title_fontproperties={'size':'medium'})
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

