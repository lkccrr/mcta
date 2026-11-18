#!/bin/bash
# sh：显示 POTCAR 中的 TITEL（元素与赝势类型）
test -s POTCAR && grep TITEL POTCAR || echo 'No POTCAR file!'
