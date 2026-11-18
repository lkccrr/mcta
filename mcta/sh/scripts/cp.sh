#!/bin/bash
# cp：把 CONTCAR 复制为 POSCAR
[ -s CONTCAR ] && { cp CONTCAR POSCAR; echo -n "cp CONTCAR POSCAR: "; pwd; } || echo 'No CONTCAR file!'
