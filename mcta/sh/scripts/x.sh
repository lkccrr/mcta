#!/bin/bash
# x ：x 方向应变扫描
#   x POSCAR [NPOINTS] [STEP]
#     POSCAR   晶格文件（默认 POSCAR）
#     NPOINTS  正负各取几个点（默认 4），实际扫描 2*N 个点，不含 0 应变
#     STEP     相邻点的应变间隔（默认 0.01）
#   生成 x/<factor>/POSCAR，其中 factor = 1 + k*STEP（k 取 -N..-1, 1..N）
pos=${1:-POSCAR}
if [ -s "$pos" ]; then
  n=${2:-4}
  sq=${3:-0.01}
  [ "$n" -gt 0 ] 2> /dev/null || { echo 'Parameter missing!'; exit 1; }
  L1=(`sed -n '3p' $pos | awk '{print $1,$2}'`)
  L2=(`sed -n '4p' $pos | awk '{print $1,$2}'`)
  L3=(`sed -n '5p' $pos | awk '{print $1,$2}'`)
  mkdir -p x
  for i in `seq -$n -1` `seq 1 $n`; do
    dir=$(echo "1.0+$sq*$i" |bc |awk '{printf "%.3f", $0}')
    mkdir -p x/$dir; cp $pos x/$dir/POSCAR
    x1=`echo $dir ${L1[0]} | awk '{printf "%.16f", $1*$2}'`
    x2=`echo $dir ${L2[0]} | awk '{printf "%.16f", $1*$2}'`
    x3=`echo $dir ${L3[0]} | awk '{printf "%.16f", $1*$2}'`
    # 只替换晶格矢量每行的第 1 个分量（x 分量）
    sed -i -E -e "3s/^([[:space:]]*)[^[:space:]]+/\1 $x1/" \
           -e "4s/^([[:space:]]*)[^[:space:]]+/\1 $x2/" \
           -e "5s/^([[:space:]]*)[^[:space:]]+/\1 $x3/" x/$dir/POSCAR
  done
  echo "finished"
fi
