#!/bin/bash
# 应变扫描：对 POSCAR 晶格做 ±4×0.02 扫描，生成 1/<factor>/POSCAR 目录
if [ -s "$1" ]; then
  sq=0.02
  list='-4 4'
  L1=(`sed -n '3p' $1 | awk '{print $1,$2}'`)
  L2=(`sed -n '4p' $1 | awk '{print $1,$2}'`)

  for i in $list; do
    dir=$(echo "1.0+$sq*$i" |bc |awk '{printf "%.3f", $0}')
#    if [ -d "$dir" ]; then :; else mkdir $dir; mkdir $dir/1; mkdir $dir/2; fi; cp $1 $dir/1/POSCAR
    x1=`echo $dir ${L1[0]} | awk '{printf "%.16f", $1*$2}'`
    x2=`echo $dir ${L2[0]} | awk '{printf "%.16f", $1*$2}'`
    y1=`echo $dir ${L1[1]} | awk '{printf "%.16f", $1*$2}'`
    y2=`echo $dir ${L2[1]} | awk '{printf "%.16f", $1*$2}'`
    sed -i -e "3s;\S[^ ]*\S;$x1;" -e "3s;\S[^ ]*\S;$y1;2" -e "4s;\S[^ ]*\S;$x2;" -e "4s;\S[^ ]*\S;$y2;2" $dir/1/POSCAR; cp $dir/1/POSCAR $dir/2
  done
  echo "finished"
#  echo 0 > log
fi
