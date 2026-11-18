#!/bin/bash
# md：修改 INCAR 内容
#   md KEY VALUE      把 KEY 的值设为 VALUE（不存在则追加）
#   md KEY=d          同上，等号写法
#   md KEY d          注释掉 KEY 所在行
#   md KEY r          去掉 KEY 所在行的注释
#   md KEY            KEY 已注释则取消注释，未注释则注释（切换）
if [[ -n "$1" && -s INCAR ]]; then
  incar=(`echo $* | tr '=' ' '`)
  grep "[ ]*${incar[0]}[ ]*=[ ]*" INCAR > /dev/null && {
    if [[ -z "${incar[1]}" ]]; then
      character=`grep "[ ]*${incar[0]}[ ]*=[ ]*" INCAR | tail -1 | sed 's;^[ ]*\(\S\).*;\1;'`
      [ "$character" = "#" ] && { sed -i "s;^[#|*|@]*\(.*${incar[0]}[ ]*=[ ]*\);\1;g" INCAR && echo "Remove comment ${incar[0]}"; } || {
        sed -i "s;^\(.*${incar[0]}[ ]*=[ ]*\);#\1;g" INCAR && echo "Comment out ${incar[0]}"; }
    else
      if [[ "$2" =~ ^[d|D]+$ ]]; then sed -i "s;\([ ]*${incar[0]}[ ]*=[ ]*\);#\1;g" INCAR && echo "Comment out ${incar[0]}"
      elif [[ "$2" =~ ^[r|R]+$ ]]; then sed -i "s;[#|*|@]*\([ ]*${incar[0]}[ ]*=[ ]*\);\1;g" INCAR && echo "Remove comment ${incar[0]}"
      else val=${incar[@]:1} && sed -i "s;[#|*|@]*\(.*${incar[0]}[ ]*=[ ]*\)[^#|;]*\b;\1$val;g" INCAR && echo "Modify ${incar[0]} = $val"
      fi
    fi
  } || { [ -n "${incar[1]}" ] && echo "  ${incar[0]} = ${incar[@]:1}" >> INCAR && echo "Add ${incar[0]} = ${incar[@]:1}"; }
else
  echo 'No modifications'
fi
