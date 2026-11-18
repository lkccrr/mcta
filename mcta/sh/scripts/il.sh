#!/bin/bash
# il：检测 INCAR 参数值是否大于给定值，若大于则用 md.sh 修改为给定值
#   il KEY VALUE
MD=md.sh; [ -f "$MD" ] || MD="$(dirname "${BASH_SOURCE[0]}")/md.sh"
[ -n "$1" -a -n "$2" ] 2> /dev/null && {
  val=(`sed -n "/$1/p" INCAR | sed "s/$1\|=//g" | awk '{print $1}'`)
  num=${#val[@]}; if [[ "${val[num-1]}" -le "$2" ]] 2> /dev/null; then echo 'Condition meet'; else bash "$MD" "$1" "$2"; fi
} || echo 'Parameter missing!'
