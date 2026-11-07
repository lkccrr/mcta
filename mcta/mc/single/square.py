import logging
import numpy as np
from mcta.mc import functions
from mcta.mc.single import square_update

kB = 8.61733e-2 # 玻尔兹曼常数(meV/K)

def run(file, init, X, Y, J, A, arrays_temperatures, nequilibrium, nworks):
    logging.basicConfig(level=logging.INFO,format="%(message)s",filename=file,filemode='w')
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    N   = X *  Y
    X_s = X // 4
    Y_s = Y // 4
    num = N
    Ns  = N /  2
    logging.info("{} {:<12} {} {} × {:<8} {} {} + {:<8} {} {}".format(
        "configuration:", file.split('_')[0], "lattice dimensions:", X, Y, "iterations:", nequilibrium, nworks, "Atom number:", num))
    p = len(J)
    np.seterr(divide='ignore', invalid='ignore')
    arrays_values = np.where(arrays_temperatures < 0.01, 0, 1.0/(arrays_temperatures * kB))
    lav = len(arrays_values)
    arrays_T2 = kB * arrays_values ** 2
    if p == 1:
        J = [J[0], 0.0, 0.0]
    elif p == 2:
        J = [J[0], J[1], 0.0]
    else:
        J = [J[0], J[1], J[2]]

    Ja, Jb, Jc = J[0], J[1], J[2]
    if len(A) == 1:
        Aa, Ab = A[0], A[0]
    else:
        Aa, Ab = A[0], A[1]
    logging.info("{} {:<8} {} {:<8} {:<8} {:<8} {} {:<8} {:<8}".format("init:", init, "parameters(meV):", Ja, Jb, Jc, "anisotropy(meV):", Aa, Ab))
    if init == "fm":
        logging.info("{:>16} {:>16}".format("Round", "magnetism"))
        latt = functions.OnesZNN(2, 8, Y_s, X_s)
        m_ave = functions.Average(latt[:,:,:,:,2])
        logging.info("{:>16} {:>16.6}".format(0, m_ave))
        logging.info("{:>16} {:>16} {:>18} {:>16} {:>16}".format("Temperature", "magnetism(e)", "susceptibility(e)", "specific heat", "time(s)"))
        for i in range(lav):
            t, Nw, Ew = square_update.iteration3(latt, X_s, Y_s, Ja, Jb, Jc, Aa, Ab, arrays_values[i], nequilibrium, nworks)
            m_ave = functions.Average(latt[:,:,:,:,2])
            m_avs = functions.Average(Nw)
            s_avs = functions.Average2(Nw)
            susceptibility = arrays_values[i] * num * (s_avs - m_avs ** 2)
            Cv = arrays_T2[i] * (functions.Average2(Ew) - functions.Average(Ew) ** 2) / num
            logging.info("{:>16.2f} {:>16.6f} {:>18.6f} {:>16.6f} {:>16.6f}".format(arrays_temperatures[i], m_ave, susceptibility, Cv, t))
    elif init == "afm1":
        logging.info("{:>16} {:>16} {:>16}".format("Round", "magnetism0", "magnetism1"))
        latt = functions.OnesZNN(2, 8, Y_s, X_s)
        latt[:,[1,2,5,6],:,:,2] = -1
        m_ave0 = functions.Average(latt[:,[0,3,4,7],:,:,2])
        m_ave1 = functions.Average(latt[:,[1,2,5,6],:,:,2])
        logging.info("{:>16} {:>16.6} {:>16.6}".format(0, m_ave0, m_ave1))
        logging.info("{:>16} {:>16} {:>16} {:>18} {:>18} {:>16} {:>16}".format(
            "Temperature", "magnetism0(e)", "magnetism1(e)", "susceptibility0(e)", "susceptibility1(e)", "specific heat", "time(s)"))
        for i in range(lav):
            t, Nw, Ew = square_update.iteration3(latt, X_s, Y_s, Ja, Jb, Jc, Aa, Ab, arrays_values[i], nequilibrium, nworks)
            m_ave0 = functions.Average(latt[:,[0,3,4,7],:,:,2])
            m_ave1 = functions.Average(latt[:,[1,2,5,6],:,:,2])
            arr_a  = Nw[:,:,[0,3,4,7]]
            arr_b  = Nw[:,:,[1,2,5,6]]
            m_avs0 = functions.Average(arr_a)
            m_avs1 = functions.Average(arr_b)
            s_avs0 = functions.Average2(arr_a)
            s_avs1 = functions.Average2(arr_b)
            susceptibility0 = arrays_values[i] * Ns * (s_avs0 - m_avs0 ** 2)
            susceptibility1 = arrays_values[i] * Ns * (s_avs1 - m_avs1 ** 2)
            Cv = arrays_T2[i] * (functions.Average2(Ew) - functions.Average(Ew) ** 2) / num
            logging.info("{:>16.2f} {:>16.6f} {:>16.6f} {:>18.6f} {:>18.6f} {:>16.6f} {:>16.6f}".format(
                arrays_temperatures[i], m_ave0, m_ave1, susceptibility0, susceptibility1, Cv, t))
    elif init == "afm2":
        logging.info("{:>16} {:>16} {:>16}".format("Round", "magnetism0", "magnetism1"))
        latt = functions.OnesZNN(2, 8, Y_s, X_s)
        latt[:,[2,3,6,7],:,:,2] = -1
        m_ave0 = functions.Average(latt[:,[0,1,4,5],:,:,2])
        m_ave1 = functions.Average(latt[:,[2,3,6,7],:,:,2])
        logging.info("{:>16} {:>16.6} {:>16.6}".format(0, m_ave0, m_ave1))
        logging.info("{:>16} {:>16} {:>16} {:>18} {:>18} {:>16} {:>16}".format(
            "Temperature", "magnetism0(e)", "magnetism1(e)", "susceptibility0(e)", "susceptibility1(e)", "specific heat", "time(s)"))
        for i in range(lav):
            t, Nw, Ew = square_update.iteration3(latt, X_s, Y_s, Ja, Jb, Jc, Aa, Ab, arrays_values[i], nequilibrium, nworks)
            m_ave0 = functions.Average(latt[:,[0,1,4,5],:,:,2])
            m_ave1 = functions.Average(latt[:,[2,3,6,7],:,:,2])
            arr_a  = Nw[:,:,[0,1,4,5]]
            arr_b  = Nw[:,:,[2,3,6,7]]
            m_avs0 = functions.Average(arr_a)
            m_avs1 = functions.Average(arr_b)
            s_avs0 = functions.Average2(arr_a)
            s_avs1 = functions.Average2(arr_b)
            susceptibility0 = arrays_values[i] * Ns * (s_avs0 - m_avs0 ** 2)
            susceptibility1 = arrays_values[i] * Ns * (s_avs1 - m_avs1 ** 2)
            Cv = arrays_T2[i] * (functions.Average2(Ew) - functions.Average(Ew) ** 2) / num
            logging.info("{:>16.2f} {:>16.6f} {:>16.6f} {:>18.6f} {:>18.6f} {:>16.6f} {:>16.6f}".format(
                arrays_temperatures[i], m_ave0, m_ave1, susceptibility0, susceptibility1, Cv, t))
    elif init == "afm3":
        logging.info("{:>16} {:>16} {:>16}".format("Round", "magnetism0", "magnetism1"))
        latt = functions.OnesZNN(2, 8, Y_s, X_s)
        latt[0,[3,4,5,6],:,:,2] = -1
        latt[1,[0,1,2,7],:,:,2] = -1
        m_ave0 = functions.Average(np.append(latt[0,[0,1,2,7],:,:,2], latt[1,[3,4,5,6],:,:,2]))
        m_ave1 = functions.Average(np.append(latt[0,[3,4,5,6],:,:,2], latt[1,[0,1,2,7],:,:,2]))
        logging.info("{:>16} {:>16.6} {:>16.6}".format(0, m_ave0, m_ave1))
        logging.info("{:>16} {:>16} {:>16} {:>18} {:>18} {:>16} {:>16}".format(
            "Temperature", "magnetism0(e)", "magnetism1(e)", "susceptibility0(e)", "susceptibility1(e)", "specific heat", "time(s)"))
        for i in range(lav):
            t, Nw, Ew = square_update.iteration3(latt, X_s, Y_s, Ja, Jb, Jc, Aa, Ab, arrays_values[i], nequilibrium, nworks)
            m_ave0 = functions.Average(np.append(latt[0,[0,1,2,7],:,:,2], latt[1,[3,4,5,6],:,:,2]))
            m_ave1 = functions.Average(np.append(latt[0,[3,4,5,6],:,:,2], latt[1,[0,1,2,7],:,:,2]))
            arr_a  = np.append(Nw[:,0,[0,1,2,7]], Nw[:,1,[3,4,5,6]])
            arr_b  = np.append(Nw[:,0,[3,4,5,6]], Nw[:,1,[0,1,2,7]])
            m_avs0 = functions.Average(arr_a)
            m_avs1 = functions.Average(arr_b)
            s_avs0 = functions.Average2(arr_a)
            s_avs1 = functions.Average2(arr_b)
            susceptibility0 = arrays_values[i] * Ns * (s_avs0 - m_avs0 ** 2)
            susceptibility1 = arrays_values[i] * Ns * (s_avs1 - m_avs1 ** 2)
            Cv = arrays_T2[i] * (functions.Average2(Ew) - functions.Average(Ew) ** 2) / num
            logging.info("{:>16.2f} {:>16.6f} {:>16.6f} {:>18.6f} {:>18.6f} {:>16.6f} {:>16.6f}".format(
                arrays_temperatures[i], m_ave0, m_ave1, susceptibility0, susceptibility1, Cv, t))
    else:
        print("Inconsistent parameters...")
