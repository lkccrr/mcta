import numpy as np

def Average(arr):
    return np.sum(arr) / arr.size

def Average2(arr):
    return np.sum(arr**2) / arr.size

def Onesint3(m, Y, X):
    return np.ones((m, Y, X)).astype(np.int8)

def Onesint4(n, m, Y, X):
    return np.ones((n, m, Y, X)).astype(np.int8)

def Onesint5(o, n, m, Y, X):
    return np.ones((o, n, m, Y, X)).astype(np.int8)

def Onesint6(o, n, m, Z, Y, X):
    return np.ones((o, n, m, Z, Y, X)).astype(np.int8)

def Uniformint2(Y, X):
    return (2 * (np.random.randint(0, 2, (Y, X)) - 0.5)).astype(np.int8)

def Uniformint3(m, Y, X):
    return (2 * (np.random.randint(0, 2, (m, Y, X)) - 0.5)).astype(np.int8)

def Uniformint4(n, m, Y, X):
    return (2 * (np.random.randint(0, 2, (n, m, Y, X)) - 0.5)).astype(np.int8)

def NormalrandNN(n, m, Y, X):
    arr = np.zeros((n, m, Y, X, 3)).astype(np.float32)
    for i in range(n):
        for j in range(m):
            arr_t = np.random.randn(3, X, Y)
            arr_t = arr_t / np.sqrt(arr_t[0]**2 + arr_t[1]**2 + arr_t[2]**2)
            arr[i,j] = arr_t.T
    return arr

def NormalrandNNN(o, n, m, Y, X):
    arr = np.zeros((o, n, m, Y, X, 3)).astype(np.float32)
    for k in range(o):
        for i in range(n):
            for j in range(m):
                arr_t = np.random.randn(3, X, Y)
                arr_t = arr_t / np.sqrt(arr_t[0]**2 + arr_t[1]**2 + arr_t[2]**2)
                arr[k,i,j] = arr_t.T
    return arr

def OnesZN(m, Y, X):
    arr = np.zeros((m, Y, X, 3)).astype(np.float32)
    arr[:,:,:,2] = 1
    return arr

def OnesZNN(n, m, Y, X):
    arr = np.zeros((n, m, Y, X, 3)).astype(np.float32)
    arr[:,:,:,:,2] = 1
    return arr

def OnesZNNN(n, m, Z, Y, X):
    arr = np.zeros((n, m, Z, Y, X, 3)).astype(np.float32)
    arr[:,:,:,:,:,2] = 1
    return arr

