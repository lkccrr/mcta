import time
import numpy as np
from numba import njit, prange
from mcta.mc import functions

def iteration3(latt, X_s, Y_s, Ja, Jb, Jc, Aa, Ab, val, nequilibrium, nworks):
    t0 = time.time()
    Nw = np.zeros((nworks, 2, 8))
    Ew = np.zeros(nworks)
    for i in range(nequilibrium):
        laRn = functions.NormalrandNN(2, 8, Y_s, X_s)
        randvals = np.random.rand(2, 8, Y_s, X_s)
        latZ = energy_A(latt, Aa, Ab)
        laRZ = energy_A(laRn, Aa, Ab)
        E0   = update3(latt, latZ, laRn, laRZ, randvals, X_s, Y_s, Ja, Jb, Jc, val)
    for i in range(nworks):
        laRn = functions.NormalrandNN(2, 8, Y_s, X_s)
        randvals = np.random.rand(2, 8, Y_s, X_s)
        latZ = energy_A(latt, Aa, Ab)
        laRZ = energy_A(laRn, Aa, Ab)
        E0   = update3(latt, latZ, laRn, laRZ, randvals, X_s, Y_s, Ja, Jb, Jc, val)
        Ew[i] = E0 / 2.0
        Nw[i,0] = functions.Average(latt[0,0,:,:,2]), functions.Average(latt[0,1,:,:,2]), functions.Average(latt[0,2,:,:,2]), functions.Average(latt[0,3,:,:,2]),\
                  functions.Average(latt[0,4,:,:,2]), functions.Average(latt[0,5,:,:,2]), functions.Average(latt[0,6,:,:,2]), functions.Average(latt[0,7,:,:,2])
        Nw[i,1] = functions.Average(latt[1,0,:,:,2]), functions.Average(latt[1,1,:,:,2]), functions.Average(latt[1,2,:,:,2]), functions.Average(latt[1,3,:,:,2]),\
                  functions.Average(latt[1,4,:,:,2]), functions.Average(latt[1,5,:,:,2]), functions.Average(latt[1,6,:,:,2]), functions.Average(latt[1,7,:,:,2])
    t = time.time() - t0
    return t, Nw, Ew

def energy_A(latt, Aa, Ab):
    latt_2 = latt ** 2
    if Aa < 0:
        if Aa == Ab:
            L_x_2 = latt_2[:,:,:,:,0]
            return ( -Aa * L_x_2 )
        else:
            L_y_2 = latt_2[:,:,:,:,1]
            L_z_2 = latt_2[:,:,:,:,2]
            return ( Aa * L_y_2 + Ab * L_z_2 )
    else:
        if Aa == Ab:
            L_z_2 = latt_2[:,:,:,:,2]
            return ( -Aa * L_z_2 )
        else:
            L_x_2 = latt_2[:,:,:,:,0]
            L_y_2 = latt_2[:,:,:,:,1]
            return ( Aa * L_x_2 + Ab * L_y_2 )

@njit(cache=True, parallel=True)
def update3(latt, latZ, laRn, laRZ, randvals, X_s, Y_s, Ja, Jb, Jc, val):
    nn_sum = 0
    for f in prange(8):
        for g in range(2):
            for j in range(Y_s):
                for i in range(X_s):
                    ipp  = (i + 1) if (i + 1) < X_s else 0
                    inn  = (i - 1) if (i - 1) > -1  else (X_s - 1)
                    jpp  = (j + 1) if (j + 1) < Y_s else 0
                    jnn  = (j - 1) if (j - 1) > -1  else (Y_s - 1)
                    go   =  1 - g
                    f_2  =  f % 2
                    fp   =  f + 1
                    fn   =  f - 1

                    if g == 0:
                        x__o = i
                        x__p = inn
                    else:
                        x__o = ipp
                        x__p = i

                    if f_2 == 0:
                        fo   = fp
                        x__a = i
                        ga   = g
                        gb   = go
                        if g == 0:
                            x__b = inn
                        else:
                            x__b = i
                    else:
                        fo   = fn
                        x__b = i
                        ga   = go
                        gb   = g
                        if g == 0:
                            x__a = i
                        else:
                            x__a = ipp

                    fq = f + 4
                    if fq > 7:
                        fq = fq - 8
                        y__q = jpp
                    else:
                        y__q = j
                    fr = f - 4
                    if fr < 0:
                        fr = fr + 8
                        y__r = jnn
                    else:
                        y__r = j

                    fu = f + 2
                    if fu > 7:
                        fu   = fu - 8
                        y__u = jpp
                    else:
                        y__u = j
                    fd = f - 2
                    if fd < 0:
                        fd = fd + 8
                        y__d = jnn
                    else:
                        y__d = j

                    f0 = fo + 2 if fo < 6 else fo - 6
                    f1 = fo - 2 if fo > 1 else fo + 6

                    energy0 = ( -Ja * ( latt[ga,fo,j   ,x__a,0] + latt[gb,fo,j   ,x__b,0] + latt[g ,fu,y__u,i   ,0] + latt[g ,fd,y__d,i   ,0] ) -
                                 Jb * ( latt[ga,f0,y__u,x__a,0] + latt[ga,f1,y__d,x__a,0] + latt[gb,f0,y__u,x__b,0] + latt[gb,f1,y__d,x__b,0] ) -
                                 Jc * ( latt[go,f ,j   ,x__o,0] + latt[go,f ,j   ,x__p,0] + latt[g ,fq,y__q,i   ,0] + latt[g ,fr,y__r,i   ,0] )
                              )

                    energy1 = ( -Ja * ( latt[ga,fo,j   ,x__a,1] + latt[gb,fo,j   ,x__b,1] + latt[g ,fu,y__u,i   ,1] + latt[g ,fd,y__d,i   ,1] ) -
                                 Jb * ( latt[ga,f0,y__u,x__a,1] + latt[ga,f1,y__d,x__a,1] + latt[gb,f0,y__u,x__b,1] + latt[gb,f1,y__d,x__b,1] ) -
                                 Jc * ( latt[go,f ,j   ,x__o,1] + latt[go,f ,j   ,x__p,1] + latt[g ,fq,y__q,i   ,1] + latt[g ,fr,y__r,i   ,1] )
                              )

                    energy2 = ( -Ja * ( latt[ga,fo,j   ,x__a,2] + latt[gb,fo,j   ,x__b,2] + latt[g ,fu,y__u,i   ,2] + latt[g ,fd,y__d,i   ,2] ) -
                                 Jb * ( latt[ga,f0,y__u,x__a,2] + latt[ga,f1,y__d,x__a,2] + latt[gb,f0,y__u,x__b,2] + latt[gb,f1,y__d,x__b,2] ) -
                                 Jc * ( latt[go,f ,j   ,x__o,2] + latt[go,f ,j   ,x__p,2] + latt[g ,fq,y__q,i   ,2] + latt[g ,fr,y__r,i   ,2] )
                              )
                    e0 = energy0 * latt[g,f,j,i,0]
                    e1 = energy1 * latt[g,f,j,i,1]
                    e2 = energy2 * latt[g,f,j,i,2]

                    ez = latZ[g,f,j,i]
                    Ez = laRZ[g,f,j,i]

                    energy  = e0 + e1 + e2
                    Erandn  = energy0 * laRn[g,f,j,i,0] + energy1 * laRn[g,f,j,i,1] + energy2 * laRn[g,f,j,i,2] + Ez

                    if val == 0:
                        if energy < 0:
                            DeltaE = ez + energy - Erandn
                        else:
                            latt[g,f,j,i] *= -1
                            DeltaE = ez - energy - Erandn
                        if DeltaE > 0: latt[g,f,j,i] = laRn[g,f,j,i]
                    else:
                        if energy <  0:
                            if e2 >= 0 or randvals[g,f,j,i] < np.exp( 2.0 * val * e2 ):
                                latt[g,f,j,i,2] *= -1
                                DeltaE = ez + e0 + e1 - e2 - Erandn
                            else:
                                DeltaE = ez + energy - Erandn
                        else:
                            latt[g,f,j,i] *= -1
                            DeltaE = ez - energy - Erandn

                        if DeltaE >= 0 or randvals[g,f,j,i] < np.exp( val * DeltaE ): latt[g,f,j,i] = laRn[g,f,j,i]

                    nn_sum += ( -Ja * ( np.sign(latt[ga,fo,j   ,x__a,2]) + np.sign(latt[gb,fo,j   ,x__b,2]) + np.sign(latt[g ,fu,y__u,i   ,2]) + np.sign(latt[g ,fd,y__d,i   ,2]) ) -
                                 Jb * ( np.sign(latt[ga,f0,y__u,x__a,2]) + np.sign(latt[ga,f1,y__d,x__a,2]) + np.sign(latt[gb,f0,y__u,x__b,2]) + np.sign(latt[gb,f1,y__d,x__b,2]) ) -
                                 Jc * ( np.sign(latt[go,f ,j   ,x__o,2]) + np.sign(latt[go,f ,j   ,x__p,2]) + np.sign(latt[g ,fq,y__q,i   ,2]) + np.sign(latt[g ,fr,y__r,i   ,2]) )
                              ) * np.sign(latt[g,f,j,i,2])

    return nn_sum
