#!/bin/bash
# po：按 POSCAR 顺序（或给定元素顺序）拼接赝势生成 POTCAR
#   po            按 POSCAR 第六行顺序
#   po pos        同上
#   po Fe Ni O    按给定元素顺序
#
# 赝势目录查找优先级：
#   1. 环境变量 PBE_PATH / LDA_PATH / GGA_PATH（按此次序检查）
#   2. ~/.config/mcta/config 里同名 KEY=VALUE

PO=sh.sh; [ -f "$PO" ] || PO="$(dirname "${BASH_SOURCE[0]}")/sh.sh"

# 从 ~/.config/mcta/config 读一个 KEY 的值，返回空字符串表示未找到
_read_conf() {
  local key="$1" val=""
  if [[ -f "$HOME/.config/mcta/config" ]]; then
    val=$(grep -E "^\s*${key}\s*=" "$HOME/.config/mcta/config" 2>/dev/null \
          | head -1 | sed "s/^[^=]*=\s*//" | tr -d '[:space:]' \
          | sed "s/^['\"]//;s/['\"]$//")
  fi
  echo "$val"
}

# 按 PBE_PATH > LDA_PATH > GGA_PATH 优先级找一个存在的赝势目录
_find_psp_path() {
  local key path
  for key in PBE_PATH LDA_PATH GGA_PATH; do
    path="${!key}"
    [[ -z "$path" ]] && path=$(_read_conf "$key")
    # 展开 ~
    path="${path/#\~/$HOME}"
    if [[ -n "$path" && -d "$path" ]]; then
      echo "$path"
      return 0
    fi
  done
  return 1
}

psp_path=$(_find_psp_path)

if [[ -n "$psp_path" ]]; then
  if [[ -z "$1" || "$1" == "pos" ]]; then
    test -s POSCAR && val=`sed -n 6p POSCAR` || { echo 'No POSCAR file!'; exit 1; }
  else val=`echo $@`
  fi
  for element in $val
  do
    element1=`find "$psp_path" -type d -name "$element"`
    element2=(`find "$psp_path" -type d -name "$element[_]*" | sort`)
    element3=(`find "$psp_path" -type d -name "$element*" | sort`)
    element=($element1 ${element2[@]} ${element3[@]})
    if [[ -n "$element" ]]; then cat "$element"/POTCAR; fi
  done > POTCAR
  "$PO"
else
  echo 'No pseudopotential path found!'
  echo 'Set one of: PBE_PATH / LDA_PATH / GGA_PATH (env vars or in ~/.config/mcta/config)'
  exit 1
fi
