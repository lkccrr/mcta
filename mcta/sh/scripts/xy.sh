#!/bin/bash
# xy：x 与 y 方向同时施加应变
#   xy POSCAR [NPOINTS] [STEP]
#     POSCAR   晶格文件（默认 POSCAR）
#     NPOINTS  正负各取几个点（默认 4），实际扫描 2*N 个点，不含 0 应变
#     STEP     相邻点的应变间隔（默认 0.01）
#   生成 xy/<factor>/POSCAR，其中 factor = 1 + k*STEP（k 取 -N..-1, 1..N）
#   x、y 两个分量按同一个 factor 缩放（等双轴应变）
pos=${1:-POSCAR}
if [ -s "$pos" ]; then
  n=${2:-4}
  sq=${3:-0.01}
  [ "$n" -gt 0 ] 2> /dev/null || { echo 'Parameter missing!'; exit 1; }
  L1=(`sed -n '3p' $pos | awk '{print $1,$2}'`)
  L2=(`sed -n '4p' $pos | awk '{print $1,$2}'`)
  L3=(`sed -n '5p' $pos | awk '{print $1,$2}'`)
  mkdir -p xy
  for i in `seq -$n -1` `seq 1 $n`; do
    dir=$(echo "1.0+$sq*$i" |bc |awk '{printf "%.3f", $0}')
    mkdir -p xy/$dir; cp $pos xy/$dir/POSCAR
    x1=`echo $dir ${L1[0]} | awk '{printf "%.16f", $1*$2}'`
    x2=`echo $dir ${L2[0]} | awk '{printf "%.16f", $1*$2}'`
    x3=`echo $dir ${L3[0]} | awk '{printf "%.16f", $1*$2}'`
    y1=`echo $dir ${L1[1]} | awk '{printf "%.16f", $1*$2}'`
    y2=`echo $dir ${L2[1]} | awk '{printf "%.16f", $1*$2}'`
    y3=`echo $dir ${L3[1]} | awk '{printf "%.16f", $1*$2}'`
    # 每行的 x 分量（第 1 个）与 y 分量（第 2 个）一起替换
    sed -i -E -e "3s/^([[:space:]]*)[^[:space:]]+[[:space:]]+[^[:space:]]+/\1 $x1 $y1/" \
           -e "4s/^([[:space:]]*)[^[:space:]]+[[:space:]]+[^[:space:]]+/\1 $x2 $y2/" \
           -e "5s/^([[:space:]]*)[^[:space:]]+[[:space:]]+[^[:space:]]+/\1 $x3 $y3/" xy/$dir/POSCAR
  done
  echo "finished"
fi
