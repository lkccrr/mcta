import os
import numpy as np
import re
import matplotlib.pyplot as plt

def bands(PLOT):
    ARR = []
    BAN = []
    COM = []
    s_elements = []
    for bandf in PLOT:
        with open(bandf, "r") as main_file:
            lines = main_file.readlines()
        str0 = lines[0].split()[2:]
        # 元素名只取文件名本身：`-i .` 或绝对路径会把目录前缀带进来，
        # 导致 `-p Mo-d` 变成 `./PBAND_Mo`、`/tmp/x/PBAND_Mo` 而匹配失败
        bandname = re.sub('.dat$|^[A-Za-z]+_', '', os.path.basename(bandf))
        s_elements.append([bandname] + str0)
        nkps = re.sub(':', ' ', lines[1]).split()
        m, n = int(nkps[-2]), int(nkps[-1])
        arr = np.zeros(m)
        ban = np.zeros((n,m))
        com = np.zeros((len(str0),n,m))
        ncol = len(str0)
        reverse = False
        for i in lines[2:]:
            str = i.split()
            if i[0] == '#':
                j = int(str[-1])
                k = 0
            elif len(str) > 0:
                str = np.array([float(x) for x in str])
                if str.size - 2 != ncol:
                    raise ValueError(
                        "%s 第 %d 条能带有 %d 列投影，与表头声明的 %d 列（%s）不一致；"
                        "表头应为「#KPT Energy 轨道1 轨道2 ...」，"
                        "数据行应为「k 能量 轨道1 轨道2 ...」"
                        % (os.path.basename(bandf), j, str.size - 2, ncol, " ".join(str0)))
                if j == 1:
                    arr[k]     = str[0]
                    ban[0,k]   = str[1]
                    com[:,0,k] = str[2:]
                    k += 1
                else:
                    N = j - 1
                    if k == 0:
                        if str[0] == 0:
                            reverse = False
                        else:
                            reverse = True
                    if reverse:
                        K = m-k-1
                    else:
                        K = k
                    ban[N,K] = str[1]
                    com[:,N,K] = str[2:]
                    k += 1
            else:
                pass
        ARR.append(arr)
        BAN.append(ban)
        COM.append(com)
    return ARR, BAN, COM, s_elements

def select(s_elements, partial):
    partial = [i for i in partial if i.strip()]
    num = len(s_elements)
    index = []
    if not partial or partial[0] == 'all':
        for i in range(num):
            if re.sub('_DW$|_UP$', '', s_elements[i][0]) == 'ELEMENTS':
                index += [(i, j) for j in range(1, len(s_elements[i]))]
            else:
                index.append((i, -1))
    else:
        index = []
        for str0 in partial:
            if str0.islower():
                str_list = str0.split(',')
                for i, elem in enumerate(s_elements):
                    index += [(i, j) for j, sub_elem in enumerate(elem) if j > 0 and sub_elem in str_list]
            else:
                str_list = [i.strip() for i in str0.split('-') if i.strip()]
                if len(str_list) == 1:
                    for i, elem in enumerate(s_elements):
                        if re.sub('_DW$|_UP$', '', elem[0]) in str_list[0].split(','):
                            index.append((i, -1))
                        elif re.sub('_DW$|_UP$', '', elem[0]) == 'ELEMENTS':
                            index += [(i, j) for j, sub_elem in enumerate(elem) if j > 0 and sub_elem in str_list[0].split(',')]
                elif len(str_list) == 2:
                    for i, elem in enumerate(s_elements):
                        if re.sub('_DW$|_UP$', '', elem[0]) in str_list[0].split(','):
                            index += [(i, j) for j, sub_elem in enumerate(elem) if j > 0 and sub_elem in str_list[1].split(',')]
    labels_elements = []
    for i, j in index:
        if s_elements[i][0].endswith('_DW'):
            if s_elements[i][0] == 'ELEMENTS_DW':
                labels_elements.append(s_elements[i][j]+' ($dw$)')
            else:
                labels_elements.append(s_elements[i][0].replace('_DW','')+'-$'+s_elements[i][j]+'$'+' ($dw$)')
        elif s_elements[i][0].endswith('_UP'):
            if s_elements[i][0] == 'ELEMENTS_UP':
                labels_elements.append(s_elements[i][j]+' ($up$)')
            else:
                labels_elements.append(s_elements[i][0].replace('_UP','')+'-$'+s_elements[i][j]+'$'+' ($up$)')
        else:
            if s_elements[i][0] == 'ELEMENTS':
                labels_elements.append(s_elements[i][j])
            else:
                labels_elements.append(s_elements[i][0]+'-$'+s_elements[i][j]+'$')
    index_f = [(i, j-1) if j > 0 else (i, j) for i, j in index]
    return index_f, labels_elements

def pplot(darr, dbands, composition, ticks, labels, index_f, elements, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['dimgray', 'b']
    linestyle = fig_p.linestyle or ['-']
    linewidth = fig_p.linewidth or [0.1]
    location  = fig_p.location + [0] * (2 - len(fig_p.location)) if len(fig_p.location) < 2 else fig_p.location
    num = len(index_f)
    if len(color) == 1:
        color = [color[0], 'b']

    plt.plot(darr[0], dbands[0].T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    L = plt.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    plt.gca().add_artist(L)
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = darr[0][0],darr[0][-1]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.xlim(darr[0][0], darr[0][-1])
    plt.ylim(fig_p.vertical)
    plt.ylabel('Energy (eV)')
    m = len(elements)
    elements =  elements + [''] * (num - m) if m < num else elements[:num]
    for i in range(num):
        if i == 0:
            bands = dbands[index_f[0][0]]
            compositions = composition[index_f[0][0]][index_f[0][1]]
            elem = elements[0]
        else:
            compositions += composition[index_f[i][0]][index_f[i][1]]
            elem = elem + '\n' + elements[i]
    n = bands.shape[0]
    p = [''] * n
    for x in range(n):
        p[x] = plt.scatter(darr[0], bands[x,:], compositions[x,:] * 20, color=color[1], marker='o', facecolor='none', linewidth=0.4)
    plt.legend([p[0]], [elem], frameon=False, prop={'size':'medium'}, loc=location[1], markerfirst=False, markerscale=1.5)
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def pplot2(darr, dbands, composition, ticks, labels, index_f, elements, ispin, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['dimgray', 'darkblue', 'b', 'r']
    linestyle = fig_p.linestyle or ['-'] * 2
    linewidth = fig_p.linewidth or [0.1] * 2
    location  = fig_p.location + [0] * (3 - len(fig_p.location)) if len(fig_p.location) < 3 else fig_p.location
    num = len(index_f)
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax2.tick_params(axis='y', which='minor', color='gray')
    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.set_yticklabels([])
    if len(ticks) > 2:
        ticks[0],ticks[-1] = darr[0][0],darr[0][-1]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax2.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    ax1.set_xlim(darr[0][0],darr[0][-1])
    ax1.set_ylim(fig_p.vertical)
    ax2.set_xlim(darr[0][0],darr[0][-1])
    ax2.set_ylim(fig_p.vertical)
    if len(labels) > 0:
        ax1.set_xticks(ticks,labels[:-1]+[''])
    else:
        ax1.set_xticks(ticks,labels)
    ax2.set_xticks(ticks,labels)
    ax1.set_ylabel('Energy (eV)')
    L = ax1.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    ax1.add_artist(L)
    m = len(elements)
    elements =  elements + [''] * (num - m) if m < num else elements[:num]
    ax1_p = True
    ax2_p = True
    for i in range(num):
        if ispin[i] == 1:
            if ax1_p:
                bands_u = dbands[index_f[i][0]]
                ax1_p = False
                compositions_u = composition[index_f[i][0]][index_f[i][1]]
                elem1 = elements[i]
            else:
                compositions_u += composition[index_f[i][0]][index_f[i][1]]
                elem1 = elem1 + '\n' + elements[i]
        else:
            if ax2_p:
                bands_d = dbands[index_f[i][0]]
                ax2_p = False
                compositions_d = composition[index_f[i][0]][index_f[i][1]]
                elem2 = elements[i]
            else:
                compositions_d += composition[index_f[i][0]][index_f[i][1]]
                elem2 = elem2 + '\n' + elements[i]
    n, m = bands_u.shape[0], bands_d.shape[0]
    p = [''] * n
    o = [''] * m
    ax1.plot(darr[0], bands_u.T, color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    ax2.plot(darr[0], bands_d.T, color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    for x in range(n):
        p[x] = ax1.scatter(darr[0], bands_u[x,:], compositions_u[x,:] * 20, color=color[2], marker='o', facecolor='none', linewidth=0.4)
    for x in range(m):
        o[x] = ax2.scatter(darr[0], bands_d[x,:], compositions_d[x,:] * 20, color=color[3], marker='o', facecolor='none', linewidth=0.4)
    ax1.legend([p[0]], [elem1], frameon=False, prop={'size':'small'}, loc=location[1], markerfirst=False, markerscale=1.5)
    ax2.legend([o[0]], [elem2], frameon=False, prop={'size':'small'}, loc=location[2], markerfirst=False, markerscale=1.5)
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

