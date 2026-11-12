import glob
import numpy as np
import matplotlib.pyplot as plt

hp = 1.0545726663e-34  # 约化普朗克常数(J·s)
me = 9.10956e-31       # 电子质量(kg)
e  = 1.602176634e-19   # 电荷(C)

def get_vbm_cbm(BAND_GAP):
    with open(BAND_GAP, "r") as main_file:
        lines = main_file.readlines()
    if lines[1].split()[0]=="Band":
        lumo = np.array([lines[6].split()[-1]]).astype(int)
        homo = np.array([lines[6].split()[-2]]).astype(int)
        filename = glob.glob("REFORMATTED_BAND.dat")
    elif lines[1].split()[0]=="Spin":
        lumo = np.array(lines[7].split()[-3:-1]).astype(int)
        homo = np.array(lines[6].split()[-3:-1]).astype(int)
        filename = [f for i in ["REFORMATTED_BAND_UP.dat", "REFORMATTED_BAND_DW.dat"] for f in glob.glob(i)]
    homo_c = homo - 1
    return lumo.tolist(), homo.tolist(), homo_c.tolist(), filename

def bs_dat_read(input):
    data = []
    for i in input:
        data.append(np.loadtxt(i))
    return np.array(data)

def dat_read(data, lumo, homo, homo_c, scale):
    p_range = data.shape[0] - 1
    N = int(scale*(p_range+1)/abs(data[-1,0]-data[0,0]))
    if N < 5:
        N = 5
    points = [''] * 6
    data_s = data[:,homo_c:lumo+1]
    data_s = data_s[:,::-1]
    for i in range(3):
        if i == 0:
            points[i*2] = points[i*2+1] = np.argmin(data_s[:,i])
        else:
            points[i*2] = points[i*2+1] = np.argmax(data_s[:,i])
        if points[i*2] == 0:
            points[i*2] = p_range
        elif data[points[i*2],0]==data[points[i*2]-1,0]:
            points[i*2] += -1
        if points[i*2+1] == p_range:
            points[i*2+1] = 0
        elif data[points[i*2+1],0]==data[points[i*2+1]+1,0]:
            points[i*2+1] += 1
    calM = [''] * 4 if abs(data_s[points[3],1]-data_s[points[5],2]) > 0.1 else [''] * 6
    for i in range(len(calM)):
        if i%2 == 0:
            calM[i]=[data[points[i]-N+1:points[i]+1,0].copy(), data_s[points[i]-N+1:points[i]+1,int(i/2)].copy()]
        else:
            calM[i]=[data[points[i]:points[i]+N,0].copy(), data_s[points[i]:points[i]+N,int(i/2)].copy()]
    calM = np.array(calM)
    if len(calM) > 4:
        exchange(calM[2], calM[4])
        exchange(calM[3], calM[5])
    return calM
# 调整能带交错
def exchange(A_a, A_b):
    Length = len(A_a[0])
    for i in range(5, Length):
        fun1 = np.polyfit(A_a[0,i-5:i], A_a[1,i-5:i], 2)
        fun2 = np.polyfit(A_b[0,i-5:i], A_b[1,i-5:i], 2)
        p1 = np.poly1d(fun1)
        p2 = np.poly1d(fun2)
        if abs(p1(A_a[0,i]) - A_a[1,i]) > abs(p1(A_a[0,i]) - A_b[1,i]) or abs(p2(A_b[0,i]) - A_b[1,i]) > abs(p2(A_b[0,i]) - A_a[1,i]):
            A_a[1,i], A_b[1,i] = A_b[1,i], A_a[1,i]

def npfit(calM):
    pltlabel=[''] * 6
    for i in range(len(calM)):
        if abs(np.corrcoef(calM[i,0], calM[i,1])[0,1]) > 0.99:
            pltlabel[i] = 0.0
        else:
            fun = np.polyfit(calM[i,0], calM[i,1], 4)
            x = calM[i,0,-1] if i%2 == 0 else calM[i,0,0]
            le = 12*fun[0]*x**2 + 6*fun[1]*x + 2*fun[2]
            pltlabel[i] = (hp**2/(le*e*1e-20))/me
    if len(calM) > 4:
        if pltlabel[2] > pltlabel[4]:
            pltlabel[2], pltlabel[4] = pltlabel[4], pltlabel[2]
            calM[2], calM[4] = calM[4], calM[2]
        if pltlabel[3] > pltlabel[5]:
            pltlabel[3], pltlabel[5] = pltlabel[5], pltlabel[3]
            calM[3], calM[5] = calM[5], calM[3]
    return pltlabel

def plot(data, calM, pltlabel, ticks, labels, legend, fig_p):
    plt.figure(figsize=fig_p.size)
    color = fig_p.color or ['red']
    linestyle = fig_p.linestyle or [':']
    linewidth = fig_p.linewidth or [0.8]
    location  = fig_p.location or [1, 2]
    if len(location) == 1:
        location = [location[0], 2]
    plt.tick_params(axis='y', which='minor', color='gray')
    plt.axhline(linewidth=0.4, linestyle='-.', c='gray')
    if len(ticks) > 2:
        ticks[0],ticks[-1] = data[0,0],data[-1,0]
        for i in ticks[1:-1]:
            plt.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    plt.xticks(ticks,labels)
    plt.xlim(data[0,0],data[-1,0])
    plt.ylim(fig_p.vertical)
    plt.plot(data[:,0], data[:,1:], color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    L = plt.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    plt.gca().add_artist(L)
    for i in range(len(calM)):
        plt.plot(calM[i][0],calM[i][1], label='%7.3f'%pltlabel[i])
    plt.ylabel('Energy (eV)')
    plt.legend(frameon=False, loc=location[1], alignment='left', title='$LUMO$ & $HOMO$', title_fontproperties={'size':'medium'})
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

def plot2(data, calM_u, pltlabel_u, calM_d, pltlabel_d, ticks, labels, legend, fig_p):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=fig_p.size)
    fig.subplots_adjust(wspace=0.0)
    color = fig_p.color or ['darkred', 'red']
    linestyle = fig_p.linestyle or [':', ':']
    linewidth = fig_p.linewidth or [0.8, 0.8]
    location  = fig_p.location or [1, 2, 2]
    if len(color) == 1:
        color = [color[0], 'red']
    if len(linestyle) == 1:
        linestyle = [linestyle[0], ':']
    if len(linewidth) == 1:
        linewidth = [linewidth[0], 0.8]
    if len(location) < 3:
        location += [2] * (3 - len(location))
    ax1.tick_params(axis='y', which='minor', color='gray')
    ax2.tick_params(axis='y', which='minor', color='gray')
    ax1.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.axhline(linewidth=0.4, linestyle='-.', c='gray')
    ax2.set_yticklabels([])
    L = ax1.legend([], frameon=False, loc=location[0], bbox_to_anchor=(0.5, 0., 0.5, 0.5), title=legend[0], title_fontproperties={'size':'medium'})
    ax1.add_artist(L)
    if len(ticks) > 2:
        ticks[0],ticks[-1] = data[0,0,0],data[0,-1,0]
        for i in ticks[1:-1]:
            ax1.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
            ax2.axvline(i, linewidth=0.4, linestyle='-.', c='gray')
    ax1.set_xlim(data[0,0,0], data[0,-1,0])
    ax1.set_ylim(fig_p.vertical)
    ax2.set_xlim(data[1,0,0], data[1,-1,0])
    ax2.set_ylim(fig_p.vertical)
    if len(labels) > 0:
        ax1.set_xticks(ticks,labels[:-1]+[''])
    else:
        ax1.set_xticks(ticks,labels)
    ax2.set_xticks(ticks,labels)
    ax1.set_ylabel('Energy (eV)')
    ax1.plot(data[0,:,0], data[0,:,1:], color=color[0], linewidth=linewidth[0], linestyle=linestyle[0])
    ax2.plot(data[1,:,0], data[1,:,1:], color=color[1], linewidth=linewidth[1], linestyle=linestyle[1])
    for i in range(len(calM_u)):
        ax1.plot(calM_u[i,0], calM_u[i,1], label='%7.3f'%pltlabel_u[i])
    for i in range(len(calM_d)):
        ax2.plot(calM_d[i,0], calM_d[i,1], label='%7.3f'%pltlabel_d[i])
    ax1.legend(frameon=False, loc=location[1], alignment='left', title='$LUMO$ & $HOMO$', title_fontproperties={'size':'small'})
    ax2.legend(frameon=False, loc=location[2], alignment='left', title='$LUMO$ & $HOMO$', title_fontproperties={'size':'small'})
    plt.savefig(fig_p.output, dpi=fig_p.dpi, transparent=True, bbox_inches='tight')

