#!/usr/bin/env python3
"""
Weverse 抢号助手 · 密钥池生成器（卖家专用）
============================================

【模式一：批量生成激活码】（密钥池模式）
  python3 keygen.py 100
  → 生成 100 个激活码，输出到「激活码清单_时间戳.csv / .txt」
  卖出时直接从清单复制一个码发给买家即可，零操作交割。

【模式二：校验单个激活码】
  python3 keygen.py --verify XXXX-XXXX-XXXX-XXXX
  → 校验该激活码格式是否有效（买家说激活不了时先用这个排查）

【重要】
  ★ SECRET 自动从 app.py 读取，两边永远一致，发售前请勿再改 app.py 的 SECRET
  ★ 已生成的激活码绑定当前 SECRET，改 SECRET 会让已发出去的码全部失效
  ★ 激活码清单请妥善保管，切勿上传 GitHub（仓库必须私有）
"""
import sys
import csv
import hmac
import hashlib
import secrets
import re
from datetime import datetime

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 32字符表（排除 0/O/1/I）


def load_secret():
    """从 app.py 读取 SECRET，保证单一来源"""
    try:
        src = open("app.py", encoding="utf-8").read()
    except FileNotFoundError:
        src = open("抢号助手/app.py", encoding="utf-8").read()
    m = re.search(r'SECRET = "([0-9a-f]{16,})"', src)
    if not m:
        raise SystemExit("未在 app.py 中找到 SECRET，请确认脚本位置")
    return m.group(1)


SECRET = load_secret()


def derive(serial: str) -> str:
    h = hmac.new(SECRET.encode(), serial.encode(), hashlib.sha256).hexdigest()
    n = int(h[:5], 16)
    return "".join(ALPHABET[(n >> (5 * i)) & 0x1F] for i in range(4))


def gen_one() -> str:
    serial = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{serial[0:4]}-{serial[4:8]}-{serial[8:12]}-{derive(serial)}"


def is_valid(key: str) -> bool:
    k = key.strip().upper().replace(" ", "")
    parts = k.split("-")
    if len(parts) != 4 or any(len(p) != 4 for p in parts):
        return False
    if any(c not in ALPHABET for c in "".join(parts)):
        return False
    return derive("".join(parts[:3])) == parts[3]


def batch(n: int):
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    keys = []
    seen = set()
    while len(keys) < n:
        k = gen_one()
        if k not in seen:
            seen.add(k)
            keys.append(k)

    # CSV（含编号/状态列，便于记录销售情况）
    csv_name = f"激活码清单_{ts}.csv"
    with open(csv_name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["编号", "激活码", "售出状态", "买家备注"])
        for i, k in enumerate(keys, 1):
            w.writerow([i, k, "", ""])

    # TXT（每行一个，方便直接复制发买家）
    txt_name = f"激活码清单_{ts}.txt"
    with open(txt_name, "w", encoding="utf-8") as f:
        for i, k in enumerate(keys, 1):
            f.write(f"{i:>3}. {k}\n")

    print(f"✅ 已生成 {n} 个激活码：")
    print(f"   CSV: {csv_name}")
    print(f"   TXT: {txt_name}")
    print(f"   示例：{keys[0]}")
    print()
    print("⚠️ 提醒：本批密钥绑定当前 SECRET，请在 app.py 中保持不变；")
    print("   激活码清单请勿上传 GitHub。")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--verify":
        if len(args) < 2:
            print("用法: python3 keygen.py --verify XXXX-XXXX-XXXX-XXXX")
            return
        key = " ".join(args[1:])
        print("✅ 有效激活码" if is_valid(key) else "❌ 无效激活码（格式错误或校验失败）")
        return
    try:
        n = int(args[0])
        if not 1 <= n <= 5000:
            raise ValueError
        batch(n)
    except ValueError:
        print("请输入 1~5000 之间的数量，例如：python3 keygen.py 100")


if __name__ == "__main__":
    main()