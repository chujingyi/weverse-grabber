#!/bin/bash
# ============================================================
# Weverse 抢号助手 · 打包脚本
# 用法：bash build.sh
# 产物：
#   macOS  → dist/Weverse抢号助手.app + dist/Weverse抢号助手-v0.2-mac.dmg
#   Windows→ dist/Weverse抢号助手.exe
# 提示：Windows 的 exe 请在 Windows 机器上跑本脚本，或使用 GitHub Actions（见 .github/workflows/build.yml）
# ============================================================
set -e

echo "==> 1/4 生成图标（若无）"
if [ ! -f assets/app.icns ] || [ ! -f assets/app.ico ]; then
  python3 make_icon.py
fi

echo "==> 2/4 安装 PyInstaller"
pip3 install pyinstaller >/dev/null 2>&1 || pip3 install --user pyinstaller

echo "==> 3/4 打包中…"
# macOS 用 onedir（.app 标准形态，避免 onefile 启动器双 Dock 图标问题）
# Windows 用 onefile（单 exe 便于分发）
if [ "$(uname)" = "Darwin" ]; then
  ICON="assets/app.icns"
  MODE="--onedir"
else
  ICON="assets/app.ico"
  MODE="--onefile"
fi
pyinstaller \
  --name "Weverse抢号助手" \
  $MODE \
  --windowed \
  --noconfirm \
  --clean \
  --icon "$ICON" \
  --exclude-module PySide6_WebEngine \
  --exclude-module tkinter \
  app.py

echo "==> 4/4 生成 DMG（仅 macOS）"
if [ "$(uname)" = "Darwin" ]; then
  hdiutil create \
    -volname "Weverse抢号助手" \
    -srcfolder "dist/Weverse抢号助手.app" \
    -ov -format UDZO \
    "dist/Weverse抢号助手-v0.2-mac.dmg"
  echo ""
  echo "✅ 完成："
  echo "   dist/Weverse抢号助手.app"
  echo "   dist/Weverse抢号助手-v0.2-mac.dmg（发买家用这个）"
else
  echo "✅ 完成：dist/Weverse抢号助手.exe"
fi
echo ""
echo "⚠️ 发售前检查清单："
echo "   1. app.py 的 SECRET 与「激活码清单」一致（本批码已绑定，请勿再改）"
echo "   2. 已生成的激活码发买家即可，无需再要机器码"
echo "   3. 打包产物务必在另一台电脑实测一遍五步流程"
echo "   4. 未签名应用：买家首次打开需右键→打开（mac）或点「仍要运行」（Win）"