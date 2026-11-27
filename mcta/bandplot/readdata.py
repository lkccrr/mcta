import numpy as np
import re

def klabels(KLABELS):
    with open(KLABELS, "r") as main_file:
        lines = main_file.readlines()[1:]
    LABELS = [line.split() for line in lines if len(line.split()) == 2]
    ticks  = [float(label[1]) for label in LABELS]
    labels = [label[0] for label in LABELS]
    return ticks, labels

def bandset(bandconf):
    with open(bandconf, "r") as main_file:
        lines = main_file.readlines()
    LABELS = [line for line in lines if line.strip().startswith('BAND_LABELS')]
    if LABELS:
        LABELS = LABELS[-1].split("=")[-1].replace('\\','').upper().split()
    return LABELS

def dos(DOS):
    ARR = []
    ELE = []
    s_elements = []
    for pdos in DOS:
        with open(pdos, "r") as main_file:
            first_line = next(main_file)
        dat = np.loadtxt(pdos)
        arr = dat[:, 0]
        ele = dat[:, 1:]
        ARR.append(arr)
        ELE.append(ele)
        s_elements.append([re.sub('.dat$|^.+DOS_|^.+/', '', pdos)] + first_line.split()[1:])
    return ARR, ELE, s_elements

def select(s_elements, partial):
    partial = [i for i in partial if i.strip()]
    num = len(s_elements)
    if not partial:
        index = []
        for i in range(num):
            if s_elements[i][0] == "TDOS":
                index += [(i, j) for j in range(1, len(s_elements[i]))]
            else:
                index.append((i, -1))
    elif partial[0] == 'all':
        index = [(i, j) for i in range(num) for j in range(1, len(s_elements[i]))]
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
                            index += [(i, j) for j in range(1, len(elem))]
                elif len(str_list) == 2:
                    for i, elem in enumerate(s_elements):
                        if re.sub('_DW$|_UP$', '', elem[0]) in str_list[0].split(','):
                            index += [(i, j) for j, sub_elem in enumerate(elem) if j > 0 and sub_elem in str_list[1].split(',')]
    labels_elements = [s_elements[i][0].replace('_DW','')+'-$'+s_elements[i][j]+'$'+' ($dw$)' if s_elements[i][0].endswith('_DW')
                  else s_elements[i][0].replace('_UP','')+'-$'+s_elements[i][j]+'$'+' ($up$)' if s_elements[i][0].endswith('_UP')
                  else s_elements[i][0]+'-$'+s_elements[i][j]+'$' for i, j in index]
    index_f = [(i, j-1) if j > 0 else (i, j) for i, j in index]
    return index_f, labels_elements

def bands(PLOT):
    with open(PLOT, "r") as main_file:
        lines = main_file.readlines()
    str0 = lines[0].split()
    if len(str0) == 3 and str0[1] == "Spin-Up(eV)" and str0[2] == "Spin-down(eV)":
        nkps = re.sub(':', ' ', lines[1]).split()
        m, n = int(nkps[-2]), int(nkps[-1])
        arr = np.zeros(m)
        ban = np.zeros((2,n,m))
        reverse = False
        for i in lines[2:]:
            str = i.split()
            if i[0] == '#':
                j = int(str[-1])
                k = 0
            elif len(str) > 0:
                if j == 1:
                    arr[k], ban[0,0,k], ban[1,0,k] = float(str[0]), float(str[1]), float(str[2])
                    k += 1
                else:
                    N = j - 1
                    if k == 0:
                        if float(str[0]) == 0:
                            reverse = False
                        else:
                            reverse = True
                    if reverse:
                        K = m-k-1
                    else:
                        K = k
                    ban[0,N,K], ban[1,N,K] = float(str[1]), float(str[2])
                    k += 1
            else:
                pass
        return arr, ban, "Ispin"
    else:
        nkps = re.sub(':', ' ', lines[1]).split()
        m, n = int(nkps[-2]), int(nkps[-1])
        arr = np.zeros(m)
        ban = np.zeros((n,m))
        reverse = False
        for i in lines[2:]:
            str = i.split()
            if i[0] == '#':
                j = int(str[-1])
                k = 0
            elif len(str) > 0:
                if j == 1:
                    arr[k], ban[0,k] = float(str[0]), float(str[1])
                    k += 1
                else:
                    N = j - 1
                    if k == 0:
                        if float(str[0]) == 0:
                            reverse = False
                        else:
                            reverse = True
                    if reverse:
                        K = m-k-1
                    else:
                        K = k
                    ban[N,K] = float(str[1])
                    k += 1
            else:
                pass
        return arr, ban, "Noneispin"

def symbols(POSCAR):
    """POSCAR 的元素名与数目，解析交给 ASE（见 vaspread.read_poscar）。

    VASP4 把元素名写在标题行、缩放系数为负（给定体积）等情形都能处理；
    元素名无法确定时返回空列表，调用方回退为用目录名做图例。
    """
    from mcta.bandplot.vaspread import read_poscar
    struct = read_poscar(POSCAR)
    return struct["species"], struct["counts"]

def pbands(PLOT):
    with open(PLOT, "r") as main_file:
        lines = main_file.readlines()
    ticks = [float(i) for i in lines[1].replace("#","").split()]
    arr = []
    fre = []
    k = 0
    for i in lines[2:]:
        str = i.split()
        if len(str) > 0:
            j = float(str[0])
            if j == 0.0:
                k += 1
            if k == 1:
                arr.append(j)
                fre.append(float(str[1]))
            else:
                fre.append(float(str[1]))
    arr = np.array(arr)
    fre = np.array(fre).reshape(-1,len(arr))
    return arr, fre, ticks

def pdos(DOS):
    data = np.loadtxt(DOS)
    arr = data[:, 0]
    ele = data[:, 1:]
    return arr, ele

