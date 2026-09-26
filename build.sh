#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install -r requirements.txt
cd Deobfuscator
echo "[*] Compilando Luau desde: $(pwd)"
command -v git >/dev/null || { echo "git no está instalado"; exit 1; }
command -v cmake >/dev/null || { echo "cmake no está instalado"; exit 1; }
if ! command -v g++ >/dev/null && ! command -v c++ >/dev/null; then
  echo "No hay compilador C++ (g++/c++) disponible"
  exit 1
fi
python3 deobf/build_luau.py --portable
cd ..
[ -x Deobfuscator/deobf/bin/luau ] || { echo "luau missing"; exit 1; }
[ -x Deobfuscator/deobf/bin/luau-ast ] || { echo "luau-ast missing"; exit 1; }
echo "Luau runtimes ready: luau + luau-ast"
