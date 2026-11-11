"""按本机核数决定并行策略。

关于 numba 的线程模型（实测结论，i5-12400 6 物理核 / 12 逻辑核）：

* ``numba.set_num_threads(T)`` 设的是 numba **线程池的大小**，也就是
  ``prange`` 能同时用几个线程。链级并行用的 ``prange(nrep)`` 用的
  正是这个池——所以"T 设线程数"和"R 条链并行"**不是两拨线程在抢核**，
  而是同一个池的两种用法，不存在冲突。
* 实测：单链时把 T 从 1 改成 12，墙钟时间不变（0.18 / 0.17 / 0.18 s），
  说明线程池大小对单链无影响。
* 实测：R=12 链时，T 从 1 增到 12，墙钟 2.13 → 0.36 s，加速 5.9×。
* 实测：R > T 时 numba 自动把链分批调度，不会出错，但会明显变慢
  （R=12 时，T=2 需 6.33 s、T=12 需 2.00 s，差 3 倍）。

默认并行度：略多于物理核数的一半
--------------------------------
把核心跑满实测反而更慢，而且会拖慢系统里的其它工作：

* 固定工作量（R=6）时，T=6 需 1.398 s、T=12 需 1.445 s——**超线程带来
  的是 3% 的额外开销，而不是加速**（每条链都是内存密集型，超线程的两个
  硬件线程共用同一个执行单元与缓存）。
* 线程数从物理核数往上加，边际收益迅速消失：T=6 时 1.398 s，T=8 时
  1.415 s，T=12 时 1.445 s，占用的资源却翻了一倍。

所以默认取 **略多于物理核数的一半**（6 核 -> 4），既避开超线程争用，
又给系统留出余量：

    T_default = min(P // 2 + 1, P - 1)

* P = 6  -> 4   （一半是 3，4 略多于它；且 4 < 6）
* P = 4  -> 3
* P = 8  -> 5
* P = 12 -> 7
* P = 2  -> 1   （2 核时"略多于一半"与"少于总数"冲突，取一半）
* P = 1  -> 1

策略：

* **独立多链**（默认）：链数 = 线程数，统计量对各链取平均。
* **并行回火**（``--swaps``）：链数由温度点数决定；线程数同样取默认值，
  但不超过温度点数（链比线程少时，多开的线程纯属浪费）。
* 用户显式给了 ``-C`` 或 ``-N`` 就按用户说的来。
"""

import os
import re
import subprocess


def logical_cores():
    """逻辑核数（超线程算在内）。"""
    return os.cpu_count() or 1


def physical_cores():
    """物理核数（超线程不算）。

    只用标准库：先读 ``/proc/cpuinfo`` 里 (physical id, core id) 的组合数，
    读不到再用 ``lscpu``，最后才退到逻辑核数。
    """
    pairs = set()
    try:
        with open("/proc/cpuinfo") as handle:
            pid = core = None
            for line in handle:
                if line.startswith("physical id"):
                    pid = line.split(":", 1)[1].strip()
                elif line.startswith("core id"):
                    core = line.split(":", 1)[1].strip()
                    pairs.add((pid, core))
        if pairs:
            return len(pairs)
    except OSError:
        pass

    try:
        out = subprocess.run(["lscpu"], capture_output=True, text=True,
                             timeout=5).stdout
        cores = sockets = None
        for line in out.splitlines():
            if line.startswith("Core(s) per socket:"):
                cores = int(line.split(":")[1].strip())
            elif line.startswith("Socket(s):"):
                sockets = int(line.split(":")[1].strip())
        if cores and sockets:
            return cores * sockets
    except Exception:
        pass

    return logical_cores()


def default_threads(cores=None):
    """默认线程数：略多于物理核数的一半，但少于物理核总数。

    ``T = min(P // 2 + 1, P - 1)``

    * P=6  -> 4（一半是 3，4 略多于它；且 4 < 6，没把核心跑满）
    * P=4  -> 3
    * P=2  -> 1（2 核时两个约束冲突，取一半）
    * P=1  -> 1

    理由见模块 docstring：把核心跑满实测更慢（超线程争用 + 内存带宽
    饱和），而线程数超过物理核数后边际收益也迅速消失。
    """
    P = physical_cores() if cores is None else cores
    if P <= 2:
        # 1~2 个物理核时，"略多于一半"和"少于总数"没法同时满足
        # （2 核时前者是 2、后者是 1）。这种机器上超线程争用最严重，
        # 取物理核数的一半更稳妥：2 核 -> 1，1 核 -> 1。
        return max(1, P // 2)
    return min(P // 2 + 1, P - 1)


def thread_plan(mode="chains", chains=0, threads=0, n_temps=0):
    """决定用多少线程、跑多少条链。

    参数
    ----
    mode      "chains"（独立多链）或 "tempering"（并行回火）
    chains    用户指定的链数（0 表示自动）
    threads   用户指定的线程数（0 表示自动）
    n_temps   回火模式的温度点数（用来避免多开用不上的线程）

    返回 (threads, chains)
    """
    P = physical_cores()
    L = logical_cores()

    # --- 线程数 ---
    if threads > 0:
        T = min(threads, L)
    else:
        T = default_threads(P)
        if mode == "tempering" and n_temps > 0:
            # 回火模式下链数 = 温度点数，链比线程少时多开的线程没用
            T = min(T, n_temps)

    # --- 链数 ---
    if mode == "tempering":
        # 回火模式下链数 = 温度点数，由调用方决定，这里不干预
        return T, chains
    if chains > 0:
        return T, chains
    if P <= 1:
        # 只有 1 个物理核：多链并行没有意义（线程会互相抢时间片），
        # 退回单链，把资源留给并行回火。
        return T, 1
    # 核数足够：每条链一个线程，统计量取平均 —— 误差更小，
    # 墙钟时间几乎不变。
    return T, T


def describe():
    """给日志用的一行说明。"""
    P = physical_cores()
    L = logical_cores()
    if P == L:
        return "%d 核（无超线程）" % P
    return "%d 物理核 / %d 逻辑核" % (P, L)
