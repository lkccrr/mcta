import time
import numpy as np
from numba import njit, prange
from mcta.mc import functions

def iteration3(latt, X_s, Y_s, Ja, Jb, Jc, val, nequilibrium, nworks):
    Nw = np.zeros((nworks, 2, 8))
    Ew = np.zeros(nworks)
    t0 = time.time()
    for i in range(nequilibrium):
        randvals = np.random.rand(2, 8, Y_s, X_s)
        E0 = update3(latt, randvals, X_s, Y_s, Ja, Jb, Jc, val)
    for i in range(nworks):
        randvals = np.random.rand(2, 8, Y_s, X_s)
        E0 = update3(latt, randvals, X_s, Y_s, Ja, Jb, Jc, val)
        Ew[i] = E0 / 2
        Nw[i,0] = functions.Average(latt[0,0]), functions.Average(latt[0,1]), functions.Average(latt[0,2]), functions.Average(latt[0,3]),\
                  functions.Average(latt[0,4]), functions.Average(latt[0,5]), functions.Average(latt[0,6]), functions.Average(latt[0,7])
        Nw[i,1] = functions.Average(latt[1,0]), functions.Average(latt[1,1]), functions.Average(latt[1,2]), functions.Average(latt[1,3]),\
                  functions.Average(latt[1,4]), functions.Average(latt[1,5]), functions.Average(latt[1,6]), functions.Average(latt[1,7])
    t = time.time() - t0
    return t, Nw, Ew

@njit(cache=True, parallel=True)
def update3(latt, randvals, X_s, Y_s, Ja, Jb, Jc, val):
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

                    energy  = ( -Ja * ( latt[ga,fo,j   ,x__a] + latt[gb,fo,j   ,x__b] + latt[g ,fu,y__u,i   ] + latt[g ,fd,y__d,i   ] ) -
                                 Jb * ( latt[ga,f0,y__u,x__a] + latt[ga,f1,y__d,x__a] + latt[gb,f0,y__u,x__b] + latt[gb,f1,y__d,x__b] ) -
                                 Jc * ( latt[go,f ,j   ,x__o] + latt[go,f ,j   ,x__p] + latt[g ,fq,y__q,i   ] + latt[g ,fr,y__r,i   ] )
                              )
                    energy *= latt[g,f,j,i]

                    if val == 0:
                        if energy >  0: latt[g,f,j,i] *= -1
                    else:
                        if energy >= 0 or randvals[g,f,j,i] < np.exp( 2.0 * val * energy ): latt[g,f,j,i] *= -1

                    nn_sum += energy
    return nn_sum
