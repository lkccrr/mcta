#!/bin/bash
# su：按 POTCAR 顺序（或给定顺序）替换 POSCAR 第六行的元素名
#   su            按 POTCAR 的 VRHFIN 顺序
#   su Fe Ni O    按给定顺序
[ -s POSCAR ] && {
  [ -n "$1" ] && vrhfin=(`echo $@`) || {
    vrhfin=(`grep VRHFIN POTCAR | sed 's/[=:]//g' | awk '{print $2}'`); }
  num=${#vrhfin[@]}; elements="0"
  for ((i=0;i<num;i++))
  do
    elements="$elements`printf "%5s" ${vrhfin[i]}`"
  done
  sed -i "6c $elements" POSCAR; sed -i "6s/^.//" POSCAR
  sed -n '6p' POSCAR
} || echo 'No POSCAR file!'
