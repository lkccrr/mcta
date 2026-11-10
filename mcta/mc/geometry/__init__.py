"""构型层：把"原子排布"翻译成一张表。

这一层只做一件事——描述谁和谁相邻。**没有任何物理公式**：
能量怎么算、接受判据怎么写、怎么采样，都不在这里。

每个构型模块提供 ``build(X, Y, Z=None)``，返回一个
:class:`mcta.mc.engine.Lattice`：邻居表 + 耦合通道 + 子晶格分组 + 初态。
计算层（``mcta.mc.engine``）只读这张表，不认识任何具体几何。

新增一个构型 = 在本目录加一个模块，实现 ``build(X, Y, Z=None)``，
然后在下面的注册表里登记。计算层的代码一行都不用动。
"""

from . import square
from . import triangular
from . import bilayer_aa
from . import bilayer_ab
from . import bilayer_ab_u_3
from . import simple_cubic

# CLI 的 -c 参数名 -> 表生成器
REGISTRY = {
    "square": square.build,
    "triangular": triangular.build,
    "bilayer-aa": bilayer_aa.build,
    "bilayer-ab": bilayer_ab.build,
    "bilayer-ab-u-3": bilayer_ab_u_3.build,
    "simple-cubic": simple_cubic.build,
}


def build(config, X, Y, Z=None):
    """按名字生成构型表。

    参数
    ----
    config : 构型名（"square" / "simple-cubic" 等）
    X, Y   : 用户层面的晶格尺寸
    Z      : z 方向尺寸，某些构型要用（simple-cubic）；其余忽略

    返回 :class:`mcta.mc.engine.Lattice`
    """
    if config not in REGISTRY:
        raise KeyError("未知构型 %r（可选：%s）"
                       % (config, ", ".join(sorted(REGISTRY))))
    return REGISTRY[config](X, Y, Z)


__all__ = ["REGISTRY", "build"]
