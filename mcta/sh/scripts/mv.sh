#!/bin/bash
# mv：把 CONTCAR 移动为 POSCAR
[ -s CONTCAR ] && { mv CONTCAR POSCAR; echo -n "mv CONTCAR POSCAR: "; pwd; } || echo 'No CONTCAR file!'
