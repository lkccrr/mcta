#!/bin/bash
# ex：交换两个文件的名字
#   ex FILE1 FILE2
[ -e "$1" -a -e "$2" ] 2> /dev/null && {
  ls -l | grep -E " $1$| $2$" && { echo ""; mv "$1" .test.file; mv "$2" "$1"; mv .test.file "$2"; ls -l | grep -E " $1$| $2$"; }
} || echo 'Parameter missing!'
