#!/usr/bin/env python3
"""
Weverse 抢号助手 · 密钥池生成器（卖家专用）
============================================

支持两种激活码（格式相同，程序自动识别类型）：

  永久版（perm）  ：激活后长期有效，后续活动通用
  一次性版（single）：挂机不限时长，抢成功一次后自动失效

【用法】
  python3 keygen.py perm 100      # 生成 100 个永久版激活码
  python3 keygen.py single 100    # 生成 100 个一次性激活码
  python3 keygen.py --verify XXXX-XXXX-XXXX-XXXX
                                  # 校验激活码并显示类型

【重要】
  ★ SECRET 自动从 app.py 读取，两边永远一致，发售前请勿再改 app.py 的 SECRET
  ★ 永久版沿用旧算法 —— 之前已生成的旧永久码全部继续有效
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

TYPE_LABEL = {"perm": "永久版", "single": "一次性"}


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


def derive(serial: str, single: bool = False) -> str:
    """永久版用旧算法（兼容已发出去的永久码）；一次性版追加盐值"""
    msg = (serial + "|SINGLE") if single else serial
    h = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    n = int(h[:5], 16)
    return "".join(ALPHABET[(n >> (5 * i)) & 0x1F] for i in range(4))


def gen_one(single: bool) -> str:
    serial = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{serial[0:4]}-{serial[4:8]}-{serial[8:12]}-{derive(serial, single)}"


def check(key: str):
    """返回 (有效?, 类型)  类型: 'perm' | 'single' | None"""
    k = key.strip().upper().replace(" ", "")
    parts = k.split("-")
    if len(parts) != 4 or any(len(p) != 4 for p in parts):
        return False, None
    if any(c not in ALPHABET for c in "".join(parts)):
        return False, None
    serial = "".join(parts[:3])
    if derive(serial, single=False) == parts[3]:
        return True, "perm"
    if derive(serial, single=True) == parts[3]:
        return True, "single"
    return False, None


def batch(ktype: str, n: int):
    single = (ktype == "single")
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    keys, seen = [], set()
    while len(keys) < n:
        k = gen_one(single)
        if k not in seen:
            seen.add(k)
            keys.append(k)

    label = TYPE_LABEL[ktype]
    csv_name = f"激活码清单_{label}_{ts}.csv"
    with open(csv_name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["编号", "激活码", "类型", "售出状态", "买家备注"])
        for i, k in enumerate(keys, 1):
            w.writerow([i, k, label, "", ""])

    txt_name = f"激活码清单_{label}_{ts}.txt"
    with open(txt_name, "w", encoding="utf-8") as f:
        for i, k in enumerate(keys, 1):
            f.write(f"{i:>3}. {k}\n")

    print(f"✅ 已生成 {n} 个{label}激活码：")
    print(f"   CSV: {csv_name}")
    print(f"   TXT: {txt_name}")
    print(f"   示例：{keys[0]}（{label}）")
    print()
    if single:
        print("ⓘ 一次性码说明：买家激活后可无限挂机，抢成功一次后程序自动失效；")
        print("   复购时再卖一个新码即可。")
    else:
        print("ⓘ 永久码说明：激活后长期有效；旧清单里的永久码继续有效（算法兼容）。")
    print()
    print("⚠️ 提醒：激活码清单请勿上传 GitHub。")


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
        ok, ktype = check(key)
        if ok:
            print(f"✅ 有效激活码 · 类型：{TYPE_LABEL[ktype]}")
        else:
            print("❌ 无效激活码（格式错误或校验失败）")
        return
    if len(args) < 2 or args[0] not in ("perm", "single"):
        print("用法: python3 keygen.py perm 100   或   python3 keygen.py single 100")
        return
    try:
        n = int(args[1])
        if not 1 <= n <= 5000:
            raise ValueError
        batch(args[0], n)
    except ValueError:
        print("请输入 1~5000 之间的数量")


if __name__ == "__main__":
    main()