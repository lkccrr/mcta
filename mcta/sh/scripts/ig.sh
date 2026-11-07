#!/bin/bash
# ig：检测 INCAR 参数值是否小于给定值，若小于则用 md.sh 修改为给定值
#   ig KEY VALUE
MD=md.sh; [ -f "$MD" ] || MD="$(dirname "${BASH_SOURCE[0]}")/md.sh"
[ -n "$1" -a -n "$2" ] 2> /dev/null && {
  val=(`sed -n "/$1/p" INCAR | sed "s/$1\|=//g" | awk '{print $1}'`)
  num=${#val[@]}; if [[ "${val[num-1]}" -ge "$2" ]] 2> /dev/null; then echo 'Condition meet'; else "$MD" "$1" "$2"; fi
} || echo 'Parameter missing!'
