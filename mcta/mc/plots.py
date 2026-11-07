import numpy as np
import matplotlib.pyplot as plt

def main(file, format, legend):
    f = open(file,"r")
    lines = f.readlines()
    f.close()

    j = False
    arr = []
    for i in lines:
        if j:
            if len(i.split()) > 0 and i.split()[0][0].isdigit():
                arr.append(i)
            else:
                j = False
        else:
            k = i.split()
            if k[0] == 'Temperature':
                j = True

    if arr:
        arr = np.array([i.split()[0:-1] for i in arr]).astype(float)
        plot(arr, format, legend)
    else:
        print('No data!')

def plot(arr, format, legend):
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
    plt.savefig("magnetism.%s"%format, dpi=750, transparent=True, bbox_inches='tight')

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
    plt.savefig("susceptibility.%s"%format, dpi=750, transparent=True, bbox_inches='tight')

    plt.clf()
    plt.xlabel('Temperature (K)')
    plt.ylabel('Specific Heat')
    plt.xlim(arr[0,0], arr[-1,0])
    plt.grid(axis="x", ls='--', lw=0.5)
    plt.minorticks_on()
    plt.plot(arr[:,0],arr[:,-1],linewidth=1,linestyle=':',label=r'$specific\ heat$',marker='o',markersize=3)
    plt.tick_params(axis='both', which='minor', color='gray')
    plt.legend(loc='upper left', frameon=False, prop={'style':'italic','size':'medium'}, alignment='left', title=legend, title_fontproperties={'size':'medium'})
    plt.savefig("specific_heat.%s"%format, dpi=750, transparent=True, bbox_inches='tight')
