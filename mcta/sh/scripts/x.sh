#!/bin/bash
# 应变扫描：对 POSCAR 晶格做 ±4×0.02 扫描，生成 1/<factor>/POSCAR 目录
if [ -s "$1" ]; then
  sq=0.02
  list=`seq -4 4`  #'-4 4'
  L1=(`sed -n '3p' $1 | awk '{print $1,$2}'`)
  L2=(`sed -n '4p' $1 | awk '{print $1,$2}'`)
  L3=(`sed -n '5p' $1 | awk '{print $1,$2}'`)
  mkdir 1
  for i in $list; do
    dir=$(echo "1.0+$sq*$i" |bc |awk '{printf "%.3f", $0}')
    mkdir 1/$dir; cp $1 1/$dir/POSCAR
    x1=`echo $dir ${L1[0]} | awk '{printf "%.16f", $1*$2}'`
    x2=`echo $dir ${L2[0]} | awk '{printf "%.16f", $1*$2}'`
    x3=`echo $dir ${L3[0]} | awk '{printf "%.16f", $1*$2}'`
    sed -i -e "3s;\S[^ ]*\S;$x1;" -e "4s;\S[^ ]*\S;$x2;" -e "5s;\S[^ ]*\S;$x3;" 1/$dir/POSCAR
  done
  cp -R 1 2
  cp -R 1 3
  cp -R 1 4
  echo "finished"
fi
