import time
import numpy as np
from numba import njit, prange
from mcta.mc import functions

def iteration3(latt, X_s, Y_s, J0, J1, Ja, Aa, Ab, val, nequilibrium, nworks):
    t0 = time.time()
    Nw = np.zeros((nworks, 2, 8))
    Ew = np.zeros(nworks)
    for i in range(nequilibrium):
        laRn = functions.NormalrandNN(2, 8, Y_s, X_s)
        randvals = np.random.rand(2, 8, Y_s, X_s)
        latZ = energy_A(latt, Aa, Ab)
        laRZ = energy_A(laRn, Aa, Ab)
        E0   = update3(latt, latZ, laRn, laRZ, randvals, X_s, Y_s, J0, J1, Ja, val)
    for i in range(nworks):
        laRn = functions.NormalrandNN(2, 8, Y_s, X_s)
        randvals = np.random.rand(2, 8, Y_s, X_s)
        latZ = energy_A(latt, Aa, Ab)
        laRZ = energy_A(laRn, Aa, Ab)
        E0   = update3(latt, latZ, laRn, laRZ, randvals, X_s, Y_s, J0, J1, Ja, val)
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
def update3(latt, latZ, laRn, laRZ, randvals, X_s, Y_s, J0, J1, Ja, val):
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
                    f_4  =  f % 4
                    f_2  =  f % 2

                    if f_4 < 2:
                        f0 = f - 2
                        if f0 < 0: f0 = f0 + 8
                        x__a = i
                        x__b = i if f_2 == 1 else inn
                    else:
                        f0 = f - 1
                        if f0 % 2 == 0: f0 = f0 - 2
                        x__a = i if f_2 == 0 else ipp
                        x__b = i

                    f1 = f0 + 4 if f0      < 4 else f0 - 4
                    f2 = f1 - 1 if f1 % 2 == 1 else f1 + 1
                    f3 = f0 - 1 if f0 % 2 == 1 else f0 + 1

                    if f_2 == 0:
                        fp   = f + 1
                        x_ap = i
                        x_an = inn
                    else:
                        fp   = f - 1
                        x_ap = ipp
                        x_an = i

                    if f < 2:
                        y__a = jnn
                        y__b = j
                    elif f > 5:
                        y__a = j
                        y__b = jpp
                    else:
                        y__a = j
                        y__b = j

                    if g == 0:
                        x_0  = x_an
                        fo2  = f2
                        y__0 = y__b
                        x__0 = x__b
                        foa  = f3
                        y_1  = y__a
                        x_1  = x__b
                        fob  = f1
                        y_b  = y__b
                        x_b  = x__a
                        foc  = fo2 - 1 if fo2 % 2 == 1 else fo2 + 1
                        x_c  = inn
                    else:
                        x_0  = x_ap
                        fo2  = f0
                        y__0 = y__a
                        x__0 = x__a
                        foa  = f1
                        y_1  = y__b
                        x_1  = x__a
                        fob  = f3
                        y_b  = y__a
                        x_b  = x__b
                        foc  = fo2 + 1 if fo2 % 2 == 0 else fo2 - 1
                        x_c  = ipp

                    energy0 = ( -J0  * ( latt[go,f  ,j   ,i   ,0] + latt[go,fp ,j   ,x_0 ,0] +
                                         latt[go,fo2,y__0,x__0,0] ) -
                                 J1  * ( latt[go,foa,y_1 ,x_1 ,0] +
                                         latt[go,fob,y_b ,x_b ,0] + latt[go,foc,y__0,x_c ,0] ) -
                                 Ja  * ( latt[g ,f0 ,y__a,x__a,0] + latt[g ,f3 ,y__a,x__b,0] +
                                         latt[g ,f1 ,y__b,x__a,0] + latt[g ,f2 ,y__b,x__b,0] +
                                         latt[g ,fp ,j   ,x_ap,0] + latt[g ,fp ,j   ,x_an,0] )
                              ) * 2.25

                    energy1 = ( -J0  * ( latt[go,f  ,j   ,i   ,1] + latt[go,fp ,j   ,x_0 ,1] +
                                         latt[go,fo2,y__0,x__0,1] ) -
                                 J1  * ( latt[go,foa,y_1 ,x_1 ,1] +
                                         latt[go,fob,y_b ,x_b ,1] + latt[go,foc,y__0,x_c ,1] ) -
                                 Ja  * ( latt[g ,f0 ,y__a,x__a,1] + latt[g ,f3 ,y__a,x__b,1] +
                                         latt[g ,f1 ,y__b,x__a,1] + latt[g ,f2 ,y__b,x__b,1] +
                                         latt[g ,fp ,j   ,x_ap,1] + latt[g ,fp ,j   ,x_an,1] )
                              ) * 2.25

                    energy2 = ( -J0  * ( latt[go,f  ,j   ,i   ,2] + latt[go,fp ,j   ,x_0 ,2] +
                                         latt[go,fo2,y__0,x__0,2] ) -
                                 J1  * ( latt[go,foa,y_1 ,x_1 ,2] +
                                         latt[go,fob,y_b ,x_b ,2] + latt[go,foc,y__0,x_c ,2] ) -
                                 Ja  * ( latt[g ,f0 ,y__a,x__a,2] + latt[g ,f3 ,y__a,x__b,2] +
                                         latt[g ,f1 ,y__b,x__a,2] + latt[g ,f2 ,y__b,x__b,2] +
                                         latt[g ,fp ,j   ,x_ap,2] + latt[g ,fp ,j   ,x_an,2] )
                              ) * 2.25
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
                        if energy < 0:
                            if e2 >= 0 or randvals[g,f,j,i] < np.exp( 2.0 * val * e2 ):
                                latt[g,f,j,i,2] *= -1
                                DeltaE = ez + e0 + e1 - e2 - Erandn
                            else:
                                DeltaE = ez + energy - Erandn
                        else:
                            latt[g,f,j,i] *= -1
                            DeltaE = ez - energy - Erandn

                        if DeltaE >= 0 or randvals[g,f,j,i] < np.exp( val * DeltaE ): latt[g,f,j,i] = laRn[g,f,j,i]

                    nn_sum += ( -J0  * ( np.sign(latt[go,f  ,j   ,i   ,2]) + np.sign(latt[go,fp ,j   ,x_0 ,2]) +
                                         np.sign(latt[go,fo2,y__0,x__0,2]) ) -
                                 J1  * ( np.sign(latt[go,foa,y_1 ,x_1 ,2]) +
                                         np.sign(latt[go,fob,y_b ,x_b ,2]) + np.sign(latt[go,foc,y__0,x_c ,2]) ) -
                                 Ja  * ( np.sign(latt[g ,f0 ,y__a,x__a,2]) + np.sign(latt[g ,f3 ,y__a,x__b,2]) +
                                         np.sign(latt[g ,f1 ,y__b,x__a,2]) + np.sign(latt[g ,f2 ,y__b,x__b,2]) +
                                         np.sign(latt[g ,fp ,j   ,x_ap,2]) + np.sign(latt[g ,fp ,j   ,x_an,2]) )
                              ) * np.sign(latt[g,f,j,i,2])

    return nn_sum
