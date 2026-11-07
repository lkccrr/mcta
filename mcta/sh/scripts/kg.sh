#!/bin/bash
# kg：KPOINTS 网格不够大时按倍数扩大到给定值
#   kg NUMBER
[ "$1" -gt 1 ] && {
  val0=(`sed -n '4p' KPOINTS`)
  [[ "${val0[0]}" =~ ^[0-9]+$ ]] && {
    val[0]=${val0[0]}; val[1]=${val0[1]}; val[2]=${val0[2]}
    for ((i=2;i<41;i++))
    do
      for ((j=0;j<3;j++))
      do
        value=0; if [[ "${val[j]}" -ge "$1" || "${val[j]}" -eq 1 ]]; then :; else value=1; break; fi
      done
      if [[ "$value" -eq 1 ]]; then for ((j=0;j<3;j++)); do if [[ "${val[j]}" -eq 1 ]]; then :; else val[j]=$[${val0[j]}*i]; fi; done; else break; fi
    done
    sed -i "4c ${val[0]} ${val[1]} ${val[2]}" KPOINTS
  }
}
