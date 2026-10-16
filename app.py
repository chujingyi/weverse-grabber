#!/usr/bin/env python3
"""
Weverse 抢号助手 · 桌面版 P0
============================
页面流程：激活 → 活动配置 → 登录 → 目标配置 → 监控
核心能力：时段回流监控 + 自动下单 + 弹窗/声音/托盘通知 + Token 自动续期

运行：python3 app.py
打包：见 build.sh
"""
import os
import sys
import json
import time
import hmac
import hashlib
import platform
import subprocess
from datetime import datetime

import requests

from PySide6 import QtCore, QtGui, QtWidgets

from wvs_api import WeverseAPI, ApiError

# ============ 授权配置（与 keygen.py 保持一致，发售前请勿再改！） ============
# ★ 当前 SECRET 已绑定「激活码清单」里的全部密钥，改动会让已生成密钥全部失效
SECRET = "1a305d05de7db7b150e042ece8a8477c"

# 可选：云端核销接口（部署后填入地址，未部署留空 = 离线模式）
# 传入后每个密钥只能激活一台设备，防止密钥被共享
VERIFY_URL = ""

APP_NAME = "Weverse 抢号助手"
BRAND_A, BRAND_B = "#00B4AA", "#2D79E4"


# ============================================================
# 工具函数
# ============================================================

def app_dir():
    """开发时取脚本目录"""
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """配置存储目录：打包后放用户主目录，避免写进 .app 内部"""
    if getattr(sys, "frozen", False):
        base = os.path.expanduser("~/Weverse抢号助手")
        os.makedirs(base, exist_ok=True)
        return base
    return app_dir()


def now_str():
    return datetime.now().strftime("%H:%M:%S")


# ---------- 密钥池授权（预生成激活码模式） ----------

KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 32字符表，排除易混字符


def _key_derive(serial: str) -> str:
    """由序列号部分推导4位校验码（防伪造/防碰撞）"""
    h = hmac.new(SECRET.encode(), serial.encode(), hashlib.sha256).hexdigest()
    n = int(h[:5], 16)
    return "".join(KEY_ALPHABET[(n >> (5 * i)) & 0x1F] for i in range(4))


def normalize_key(key) -> str:
    return (key or "").strip().upper().replace(" ", "")


def valid_key_format(key) -> bool:
    """验证激活码格式（XXXX-XXXX-XXXX-XXXX，末块为校验码）"""
    k = normalize_key(key)
    parts = k.split("-")
    if len(parts) != 4 or any(len(p) != 4 for p in parts):
        return False
    if any(c not in KEY_ALPHABET for c in "".join(parts)):
        return False
    serial = "".join(parts[:3])
    return _key_derive(serial) == parts[3]


def cloud_activate(key) -> tuple:
    """云端单次核销（VERIFY_URL 未配置时直接放行）。返回 (成功?, 说明)"""
    if not VERIFY_URL:
        return True, ""
    try:
        r = requests.get(VERIFY_URL, params={"key": key}, timeout=8)
        r.raise_for_status()
        if r.json().get("used"):
            return False, "该激活码已在其他设备使用"
        r2 = requests.post(VERIFY_URL, json={"key": key}, timeout=8)
        if r2.ok and r2.json().get("ok"):
            return True, ""
        return False, "云端核销失败：" + r2.text[:100]
    except Exception:
        return True, "（云端不可达，已离线激活）"


def play_alert(repeat=3):
    """提示音（macOS: Glass；Windows: 蜂鸣）"""
    try:
        if platform.system() == "Darwin":
            for _ in range(repeat):
                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                time.sleep(0.25)
        elif platform.system() == "Windows":
            import winsound
            for _ in range(repeat):
                winsound.Beep(1000, 250)
                time.sleep(0.1)
    except Exception:
        pass


# ============================================================
# 配置持久化
# ============================================================

CONFIG_PATH = os.path.join(data_dir(), "config.json")

DEFAULT_CONFIG = {
    "activated": False,
    "license_key": "",
    "disclaimer_accepted": False,
    "venue_id": None,
    "booth_id": None,
    "booth_name": "",
    "email": "",
    "targets": [],          # [{date,time,queue_id,group_id}] 顺序=优先级
    "strategy": "stop_first",  # stop_first | all
    "interval": 5,
    "auto_reserve": True,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================================
# 样式
# ============================================================

QSS = f"""
* {{ font-family: 'PingFang SC','Microsoft YaHei','Helvetica Neue',sans-serif; }}
QMainWindow, QDialog {{ background: #F4F7FA; }}
QWidget {{ color: #1F2937; font-size: 13px; }}

#Sidebar {{ background: #FFFFFF; border-right: 1px solid #E8EDF3; }}
QLabel#Brand {{ font-size: 15px; font-weight: 800; color: #0B8F8A; padding: 4px 2px; }}
QLabel#Brand2 {{ font-size: 11px; color: #9CA3AF; }}
QPushButton#NavBtn {{
    text-align: left; border: none; background: transparent;
    padding: 11px 14px; border-radius: 9px; color: #4B5563; font-size: 13.5px;
}}
QPushButton#NavBtn:hover {{ background: #F0FAF9; color: #0B8F8A; }}
QPushButton#NavBtn:checked {{ background: #E6F7F6; color: #0B8F8A; font-weight: 700; }}

QLabel#PageTitle {{ font-size: 20px; font-weight: 800; }}
QLabel#PageSub {{ color: #6B7280; }}
QLabel#Hint {{ color: #6B7280; font-size: 12px; }}
QLabel#OkText {{ color: #059669; font-weight: 600; }}
QLabel#BadText {{ color: #DC2626; }}
QLabel#WarnText {{ color: #D97706; font-weight: 600; }}

QFrame#Card {{ background: #FFFFFF; border: 1px solid #EDF1F6; border-radius: 12px; }}
QLabel#CardTitle {{ font-size: 14px; font-weight: 700; }}

QPushButton {{
    background: #FFFFFF; border: 1px solid #D8E0EA; border-radius: 8px;
    padding: 8px 18px; color: #1F2937;
}}
QPushButton:hover {{ border-color: {BRAND_B}; color: {BRAND_B}; }}
QPushButton:disabled {{ color: #9CA3AF; border-color: #E5E7EB; }}
QPushButton#PrimaryBtn {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {BRAND_A}, stop:1 {BRAND_B});
    color: #FFFFFF; border: none; font-weight: 700; padding: 10px 22px;
}}
QPushButton#PrimaryBtn:hover {{ opacity: 0.9; }}
QPushButton#PrimaryBtn:disabled {{ background: #C9D4E0; }}
QPushButton#DangerBtn {{ color: #DC2626; border-color: #FCA5A5; }}
QPushButton#DangerBtn:hover {{ background: #FEF2F2; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: #FFFFFF; border: 1px solid #D8E0EA; border-radius: 8px; padding: 8px;
    selection-background-color: {BRAND_A};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {BRAND_A}; }}
QLineEdit[readOnly="true"] {{ color: #6B7280; background: #F8FAFC; }}

QPlainTextEdit#LogBox {{
    background: #101828; color: #6EE7B7; border-radius: 10px;
    font-family: 'Menlo','Consolas',monospace; font-size: 12px; padding: 10px;
}}

QTableWidget {{ background: #FFFFFF; border: 1px solid #EDF1F6; border-radius: 10px; gridline-color: #EDF1F6; }}
QTableWidget::item {{ padding: 6px; }}
QHeaderView::section {{ background: #F8FAFC; border: none; padding: 8px 6px; font-weight: 600; color: #6B7280; }}

QSlider::groove:horizontal {{ height: 6px; background: #E5EAF0; border-radius: 3px; }}
QSlider::subpage:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {BRAND_A}, stop:1 {BRAND_B}); border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; background: {BRAND_A}; }}

QCheckBox, QRadioButton {{ spacing: 6px; }}
StatusBar {{ color: #6B7280; font-size: 12px; }}
"""


# ============================================================
# 免责声明弹窗（首次启动）
# ============================================================

class DisclaimerDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("免责声明")
        self.setFixedSize(480, 400)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)

        title = QtWidgets.QLabel("⚠️ 使用前请阅读")
        title.setStyleSheet("font-size:16px;font-weight:800;")
        lay.addWidget(title)

        body = QtWidgets.QLabel(
            "1. 本工具通过自动化方式访问 Weverse 排队系统，可能违反\n"
            "   Weverse 服务条款，由此导致的账号限制、预约失效等风险\n"
            "   由使用者自行承担。\n\n"
            "2. 请使用本人账号、仅为自己预约。请勿多开、代抢、倒卖，\n"
            "   避免被平台认定为异常账号。\n\n"
            "3. 默认轮询间隔 5 秒，请勿调得过快，过快可能触发风控。\n\n"
            "4. 本工具为辅助工具，不保证预约成功。\n\n"
            "5. 虚拟商品，一经售出不退不换。"
        )
        body.setStyleSheet("color:#374151;line-height:1.5;")
        lay.addWidget(body, 1)

        self.chk = QtWidgets.QCheckBox("我已阅读并理解以上内容，风险自担")
        lay.addWidget(self.chk)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        self.btn_refuse = QtWidgets.QPushButton("不同意（退出）")
        self.btn_refuse.setObjectName("DangerBtn")
        self.btn_agree = QtWidgets.QPushButton("同意并继续")
        self.btn_agree.setObjectName("PrimaryBtn")
        self.btn_agree.setEnabled(False)
        btns.addWidget(self.btn_refuse)
        btns.addWidget(self.btn_agree)
        lay.addLayout(btns)

        self.chk.toggled.connect(lambda on: self.btn_agree.setEnabled(on))


# ============================================================
# 监控线程
# ============================================================

class MonitorWorker(QtCore.QThread):
    log = QtCore.Signal(str)
    states = QtCore.Signal(list)          # [{date,time,queue_id,group_id,reservable,error}]
    found = QtCore.Signal(dict)           # 发现空位的目标
    reserved = QtCore.Signal(dict, str)   # 目标 + 预约号
    reserve_failed = QtCore.Signal(dict, str)
    round_done = QtCore.Signal(int)

    def __init__(self, api, venue_id, booth_id, targets, interval,
                 auto_reserve, stop_on_first, email=""):
        super().__init__()
        self.api = api
        self.venue_id = venue_id
        self.booth_id = booth_id
        self.targets = targets
        self.interval = interval
        self.auto_reserve = auto_reserve
        self.stop_on_first = stop_on_first
        self.email = email
        self._running = False

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        rnd = 0
        # 按 queue_id 分组，同日期只请求一次
        queue_map = {}
        for t in self.targets:
            queue_map.setdefault(t["queue_id"], []).append(t)

        while self._running:
            rnd += 1
            results = []
            newly = []
            for qid, tlist in queue_map.items():
                try:
                    groups = self.api.get_groups(self.venue_id, self.booth_id, qid)
                    gmap = {g["id"]: g for g in groups}
                    for t in tlist:
                        g = gmap.get(t["group_id"])
                        ok = bool(g and g.get("reservable"))
                        results.append(dict(t, reservable=ok))
                        if ok:
                            newly.append(t)
                except Exception as e:
                    msg = f"查询失败({tlist[0]['date']}): {e}"
                    self.log.emit(msg)
                    for t in tlist:
                        results.append(dict(t, reservable=None, error=str(e)))

            self.states.emit(results)

            for t in newly:
                self.found.emit(dict(t))
                if self.auto_reserve:
                    self.log.emit(f"发现空位 {t['date']} {t['time']}，正在下单…")
                    ok, info, code = self.api.reserve(
                        self.venue_id, self.booth_id,
                        t["queue_id"], t["group_id"], self.email or None,
                    )
                    if not ok and code == 401:
                        self.log.emit("登录态过期，自动刷新后重试…")
                        if self.api.refresh_tokens():
                            ok, info, code = self.api.reserve(
                                self.venue_id, self.booth_id,
                                t["queue_id"], t["group_id"], self.email or None,
                            )
                    if ok:
                        self.reserved.emit(dict(t), str(info))
                        if self.stop_on_first:
                            self._running = False
                            return
                        else:
                            # 已抢到的目标从监控列表移除
                            self.targets = [x for x in self.targets if x != t]
                            queue_map = {}
                            for x in self.targets:
                                queue_map.setdefault(x["queue_id"], []).append(x)
                    else:
                        self.reserve_failed.emit(dict(t), str(info))

            self.round_done.emit(rnd)

            # 可中断的间隔等待
            end = time.time() + self.interval
            while self._running and time.time() < end:
                time.sleep(0.2)


# ============================================================
# 页面组件
# ============================================================

def card(title=None):
    """白色圆角卡片容器，返回 (frame, 内部VBoxLayout)"""
    frame = QtWidgets.QFrame()
    frame.setObjectName("Card")
    lay = QtWidgets.QVBoxLayout(frame)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(10)
    if title:
        lab = QtWidgets.QLabel(title)
        lab.setObjectName("CardTitle")
        lay.addWidget(lab)
    return frame, lay


class ActivationPage(QtWidgets.QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(14)

        lay.addWidget(self._title("激活", "粘贴卖家提供的激活码即可解锁自动下单；未激活可正常使用监控与提醒"))

        c, cl = card("激活")
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("激活码"))
        self.ed_key = QtWidgets.QLineEdit()
        self.ed_key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX（向卖家购买）")
        self.ed_key.setText(self.mw.cfg.get("license_key", ""))
        row2.addWidget(self.ed_key, 1)
        btn_paste = QtWidgets.QPushButton("粘贴")
        btn_paste.clicked.connect(
            lambda: self.ed_key.setText(
                normalize_key(QtWidgets.QApplication.clipboard().text())
            )
        )
        row2.addWidget(btn_paste)
        cl.addLayout(row2)

        self.lab_status = QtWidgets.QLabel()
        cl.addWidget(self.lab_status)

        rowbtn = QtWidgets.QHBoxLayout()
        self.btn_activate = QtWidgets.QPushButton("激 活")
        self.btn_activate.setObjectName("PrimaryBtn")
        self.btn_activate.clicked.connect(self.do_activate)
        self.btn_skip = QtWidgets.QPushButton("跳过，先试用监控功能 →")
        self.btn_skip.clicked.connect(lambda: self.mw.goto(1))
        rowbtn.addWidget(self.btn_activate)
        rowbtn.addWidget(self.btn_skip)
        rowbtn.addStretch(1)
        cl.addLayout(rowbtn)
        lay.addWidget(c)

        tip, tl = card("说明")
        tl.addWidget(QtWidgets.QLabel(
            "· 未激活：可监控余量、弹窗提醒（发现空位你手动去抢）\n"
            "· 已激活：发现空位自动下单，7×24 挂机不掉线\n"
            "· 每个激活码仅限一台设备，请勿外传共享"
        ))
        lay.addWidget(tip)
        lay.addStretch(1)
        self.refresh()

    def _title(self, t, sub):
        box = QtWidgets.QVBoxLayout()
        lab = QtWidgets.QLabel(t)
        lab.setObjectName("PageTitle")
        box.addWidget(lab)
        s = QtWidgets.QLabel(sub)
        s.setObjectName("PageSub")
        box.addWidget(s)
        w = QtWidgets.QWidget()
        w.setLayout(box)
        return w

    def refresh(self):
        if self.mw.cfg["activated"]:
            self.lab_status.setText("✅ 已激活（自动下单已解锁）")
            self.lab_status.setObjectName("OkText")
            self.btn_activate.setEnabled(False)
            self.btn_activate.setText("已激活")
        else:
            self.lab_status.setText("⭕ 未激活 — 当前为试用模式（仅监控提醒）")
            self.lab_status.setObjectName("WarnText")
            self.btn_activate.setEnabled(True)
            self.btn_activate.setText("激 活")
        self.lab_status.style().unpolish(self.lab_status)
        self.lab_status.style().polish(self.lab_status)

    def do_activate(self):
        key = normalize_key(self.ed_key.text())
        if not key:
            QtWidgets.QMessageBox.warning(self, "提示", "请输入激活码")
            return
        if not valid_key_format(key):
            QtWidgets.QMessageBox.warning(
                self, "激活失败",
                "激活码无效，请检查是否复制完整\n（格式：XXXX-XXXX-XXXX-XXXX）",
            )
            return
        ok, note = cloud_activate(key)
        if ok:
            self.mw.cfg["activated"] = True
            self.mw.cfg["license_key"] = key
            save_config(self.mw.cfg)
            self.refresh()
            self.mw.update_nav()
            msg = "🎉 已解锁自动下单功能！"
            if note:
                msg += "\n\n" + note
            QtWidgets.QMessageBox.information(self, "激活成功", msg)
        else:
            QtWidgets.QMessageBox.warning(self, "激活失败", note)


class EventPage(QtWidgets.QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(14)

        t = QtWidgets.QLabel("活动配置")
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        s = QtWidgets.QLabel("粘贴 Weverse 排队链接（短链会自动解析）")
        s.setObjectName("PageSub")
        lay.addWidget(s)

        c, cl = card("活动链接")
        row = QtWidgets.QHBoxLayout()
        self.ed_link = QtWidgets.QLineEdit()
        self.ed_link.setPlaceholderText(
            "例如：https://queues.weverse.io/booth-list/?venue-id=106 … 或 go.weverse.io 短链"
        )
        row.addWidget(self.ed_link, 1)
        self.btn_parse = QtWidgets.QPushButton("解析活动")
        self.btn_parse.setObjectName("PrimaryBtn")
        self.btn_parse.clicked.connect(self.do_parse)
        row.addWidget(self.btn_parse)
        cl.addLayout(row)
        lay.addWidget(c)

        self.card_info, cil = card("活动信息")
        self.card_info.setVisible(False)
        self.lab_booth = QtWidgets.QLabel()
        self.lab_booth.setStyleSheet("font-size:15px;font-weight:700;")
        cil.addWidget(self.lab_booth)
        self.lab_loc = QtWidgets.QLabel()
        self.lab_loc.setObjectName("Hint")
        cil.addWidget(self.lab_loc)
        row_booth = QtWidgets.QHBoxLayout()
        row_booth.addWidget(QtWidgets.QLabel("选择展位"))
        self.cb_booth = QtWidgets.QComboBox()
        self.cb_booth.setMinimumWidth(320)
        row_booth.addWidget(self.cb_booth)
        self.row_booth = row_booth
        cil.addLayout(row_booth)
        self.btn_next = QtWidgets.QPushButton("下一步：登录账号 →")
        self.btn_next.setObjectName("PrimaryBtn")
        self.btn_next.clicked.connect(self.do_next)
        cil.addWidget(self.btn_next)
        lay.addWidget(self.card_info)

        tip, tl = card("支持的活动类型")
        tl.addWidget(QtWidgets.QLabel(
            "支持「时段预约型（TIMED）」展位：按日期+时间段预约的线下展位/设施。\n"
            "不支持排队型（FIFO）活动。"
        ))
        lay.addWidget(tip)
        lay.addStretch(1)

    def showEvent(self, ev):
        super().showEvent(ev)
        # 回显已保存活动
        if self.mw.cfg.get("venue_id") and self.mw.cfg.get("booth_name"):
            self.lab_booth.setText(self.mw.cfg["booth_name"])
            self.lab_loc.setText(
                f"Venue ID: {self.mw.cfg['venue_id']}  ·  Booth ID: {self.mw.cfg['booth_id']}"
            )
            self.card_info.setVisible(True)

    def do_parse(self):
        link = self.ed_link.text().strip()
        if not link:
            QtWidgets.QMessageBox.warning(self, "提示", "请粘贴活动链接")
            return
        self.btn_parse.setEnabled(False)
        QtWidgets.QApplication.processEvents()
        try:
            venue_id, booth_id = self.mw.api.parse_event_link(link)
            booths = [b for b in self.mw.api.get_booth_list(venue_id)
                      if b.get("reserveType") == "TIMED"]
            if not booths:
                raise ApiError("该活动没有「时段预约型」展位，暂不支持")
            self._booths = booths
            self.cb_booth.clear()
            for b in booths:
                self.cb_booth.addItem(b.get("name", "?"), b["boothId"])
            if booth_id:
                idx = self.cb_booth.findData(booth_id)
                if idx >= 0:
                    self.cb_booth.setCurrentIndex(idx)
            b = booths[self.cb_booth.currentIndex()] if self.cb_booth.count() else None
            if b:
                self._apply_booth(venue_id, b)
            self.card_info.setVisible(True)
            self.btn_parse.setText("重新解析")
        except ApiError as e:
            QtWidgets.QMessageBox.warning(self, "解析失败", str(e))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "解析失败", f"网络异常: {e}")
        finally:
            self.btn_parse.setEnabled(True)

    def _apply_booth(self, venue_id, booth):
        self.mw.cfg["venue_id"] = venue_id
        self.mw.cfg["booth_id"] = booth["boothId"]
        self.mw.cfg["booth_name"] = booth.get("name", "")
        save_config(self.mw.cfg)
        self.lab_booth.setText(booth.get("name", ""))
        loc = booth.get("locationDescription", "")
        self.lab_loc.setText(f"{loc}   ·   Venue {venue_id} / Booth {booth['boothId']}")
        self.mw.update_nav()

    def do_next(self):
        b_idx = self.cb_booth.currentIndex()
        if b_idx < 0:
            return
        booths = getattr(self, "_booths", None)
        if booths:
            self._apply_booth(self.mw.cfg["venue_id"], booths[b_idx])
        self.mw.goto(2)


class LoginPage(QtWidgets.QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(14)

        t = QtWidgets.QLabel("登录 Weverse 账号")
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        s = QtWidgets.QLabel("登录态仅保存在本机，用于自动下单")
        s.setObjectName("PageSub")
        lay.addWidget(s)

        c, cl = card("Cookie 登录")
        row = QtWidgets.QHBoxLayout()
        btn_help = QtWidgets.QPushButton("❓ Cookie 获取教程")
        btn_help.clicked.connect(self.show_help)
        row.addWidget(btn_help)
        row.addStretch(1)
        self.btn_refresh_tok = QtWidgets.QPushButton("🔄 刷新登录态")
        self.btn_refresh_tok.clicked.connect(self.do_refresh)
        row.addWidget(self.btn_refresh_tok)
        cl.addLayout(row)

        self.ed_cookie = QtWidgets.QPlainTextEdit()
        self.ed_cookie.setPlaceholderText(
            "登录 queues.weverse.io 后，F12 → Network → 筛选 waiting-api → "
            "任意请求 → Request Headers → 复制 cookie 整行值，粘贴到这里"
        )
        self.ed_cookie.setFixedHeight(110)
        cl.addWidget(self.ed_cookie)

        row2 = QtWidgets.QHBoxLayout()
        self.btn_test = QtWidgets.QPushButton("测试登录")
        self.btn_test.setObjectName("PrimaryBtn")
        self.btn_test.clicked.connect(self.do_test)
        row2.addWidget(self.btn_test)
        row2.addStretch(1)
        cl.addLayout(row2)

        self.lab_status = QtWidgets.QLabel("未验证")
        self.lab_status.setObjectName("Hint")
        cl.addWidget(self.lab_status)

        rowmail = QtWidgets.QHBoxLayout()
        rowmail.addWidget(QtWidgets.QLabel("通知邮箱（可留空）"))
        self.ed_email = QtWidgets.QLineEdit()
        self.ed_email.setPlaceholderText("留空则使用账号默认邮箱")
        self.ed_email.setText(self.mw.cfg.get("email", ""))
        rowmail.addWidget(self.ed_email, 1)
        cl.addLayout(rowmail)
        lay.addWidget(c)

        self.btn_next = QtWidgets.QPushButton("下一步：选择目标 →")
        self.btn_next.setObjectName("PrimaryBtn")
        self.btn_next.clicked.connect(lambda: self.mw.goto(3))
        lay.addWidget(self.btn_next)
        lay.addStretch(1)

        # 若已有缓存 token，尝试直接验证
        QtCore.QTimer.singleShot(300, self.try_cached)

    def show_help(self):
        QtWidgets.QMessageBox.information(
            self, "Cookie 获取教程",
            "1. 用浏览器打开活动页面（queues.weverse.io）\n"
            "2. 点击「신청/申请」完成登录\n"
            "3. 登录后回到 queues.weverse.io 页面，按 F12\n"
            "4. 切到 Network（网络）标签，在筛选框输入 waiting-api\n"
            "5. 刷新页面，点任意一个请求\n"
            "6. Request Headers 里找到 cookie: 整行，右键复制值\n"
            "7. 粘贴到左侧输入框，点「测试登录」\n\n"
            "提示：登录态会自动续期，正常情况下无需重复操作。",
        )

    def try_cached(self):
        if self.mw.api.access_token:
            ok, info = self.mw.api.test_login()
            if ok:
                self._mark_ok(info)
                return
            # 缓存 token 失效 → 尝试刷新
            if self.mw.api.refresh_tokens():
                ok, info = self.mw.api.test_login()
                if ok:
                    self._mark_ok(info)
                    return
        self.lab_status.setText("未验证 — 请粘贴 Cookie 并测试登录")
        self.lab_status.setObjectName("BadText")
        self._repolish()

    def _repolish(self):
        self.lab_status.style().unpolish(self.lab_status)
        self.lab_status.style().polish(self.lab_status)

    def _mark_ok(self, info):
        email = info.get("maskedEmail", "")
        exp = self.mw.api.token_expiry()
        exp_s = exp.strftime("%m-%d %H:%M") if exp else "未知"
        self.lab_status.setText(f"✅ 已登录（{email}）· 登录态自动续期至 {exp_s}")
        self.lab_status.setObjectName("OkText")
        self._repolish()
        self.mw.login_valid = True
        self.mw.update_nav()

    def _mark_bad(self, msg):
        self.lab_status.setText(f"❌ {msg}")
        self.lab_status.setObjectName("BadText")
        self._repolish()
        self.mw.login_valid = False
        self.mw.update_nav()

    def do_test(self):
        cookie = self.ed_cookie.toPlainText().strip()
        if not cookie and not self.mw.api.access_token:
            QtWidgets.QMessageBox.warning(self, "提示", "请先粘贴 Cookie")
            return
        if cookie:
            self.mw.api.set_cookie_string(cookie)
        self.btn_test.setEnabled(False)
        ok, info = self.mw.api.test_login()
        if not ok and self.mw.api.refresh_tokens():
            ok, info = self.mw.api.test_login()
        self.btn_test.setEnabled(True)
        if ok:
            self._mark_ok(info)
        else:
            self._mark_bad(str(info))

    def do_refresh(self):
        if not self.mw.api.refresh_token:
            QtWidgets.QMessageBox.warning(self, "提示", "请先粘贴 Cookie")
            return
        if self.mw.api.refresh_tokens():
            ok, info = self.mw.api.test_login()
            if ok:
                self._mark_ok(info)
            else:
                self._mark_bad("刷新成功但验证失败，请重新粘贴 Cookie")
        else:
            self._mark_bad("刷新失败，Cookie 已过期，请重新登录获取")


class TargetPage(QtWidgets.QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self._slot_checks = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(14)

        t = QtWidgets.QLabel("目标配置")
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        s = QtWidgets.QLabel("添加想要抢的日期和时段，排在前面的优先抢")
        s.setObjectName("PageSub")
        lay.addWidget(s)

        c, cl = card("添加目标")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("日期"))
        self.cb_date = QtWidgets.QComboBox()
        self.cb_date.setMinimumWidth(160)
        self.cb_date.currentIndexChanged.connect(self.load_slots)
        row.addWidget(self.cb_date)
        self.btn_reload = QtWidgets.QPushButton("刷新日期")
        self.btn_reload.clicked.connect(self.load_dates)
        row.addWidget(self.btn_reload)
        row.addStretch(1)
        cl.addLayout(row)

        self.slot_box = QtWidgets.QHBoxLayout()
        self.slot_holder = QtWidgets.QWidget()
        self.slot_holder.setLayout(self.slot_box)
        cl.addWidget(self.slot_holder)

        rowbtn = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("＋ 添加所选时段")
        self.btn_add.setObjectName("PrimaryBtn")
        self.btn_add.clicked.connect(self.do_add)
        rowbtn.addWidget(self.btn_add)
        rowbtn.addStretch(1)
        cl.addLayout(rowbtn)
        lay.addWidget(c)

        c2, cl2 = card("监控列表（顺序 = 优先级）")
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["优先级", "日期", "时段", "当前状态"])
        self.table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 90)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(160)
        cl2.addWidget(self.table)

        rowop = QtWidgets.QHBoxLayout()
        self.btn_up = QtWidgets.QPushButton("↑ 上移")
        self.btn_up.clicked.connect(lambda: self.move(-1))
        self.btn_down = QtWidgets.QPushButton("↓ 下移")
        self.btn_down.clicked.connect(lambda: self.move(1))
        self.btn_del = QtWidgets.QPushButton("删除选中")
        self.btn_del.setObjectName("DangerBtn")
        self.btn_del.clicked.connect(self.do_del)
        self.btn_status = QtWidgets.QPushButton("刷新状态")
        self.btn_status.clicked.connect(self.refresh_status)
        for b in (self.btn_up, self.btn_down, self.btn_del, self.btn_status):
            rowop.addWidget(b)
        rowop.addStretch(1)
        self.btn_next = QtWidgets.QPushButton("去监控页 →")
        self.btn_next.setObjectName("PrimaryBtn")
        self.btn_next.clicked.connect(lambda: self.mw.goto(4))
        rowop.addWidget(self.btn_next)
        cl2.addLayout(rowop)
        lay.addWidget(c2)
        lay.addStretch(1)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh_table()
        if self.cb_date.count() == 0:
            self.load_dates()

    # ---- 日期/时段加载 ----

    def load_dates(self):
        self.cb_date.blockSignals(True)
        self.cb_date.clear()
        self.cb_date.blockSignals(False)
        if not self.mw.cfg.get("venue_id") or not self.mw.cfg.get("booth_id"):
            return
        try:
            data = self.mw.api.get_timed_queues(
                self.mw.cfg["venue_id"], self.mw.cfg["booth_id"]
            )
            for q in data.get("queues", []):
                self.cb_date.addItem(q["queuingDate"], q["id"])
            self.load_slots()
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "提示", f"加载日期失败，请先在「活动配置」页解析活动\n{e}"
            )

    def load_slots(self):
        # 清空旧控件
        while self.slot_box.count():
            item = self.slot_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._slot_checks = []
        qid = self.cb_date.currentData()
        if not qid:
            return
        try:
            groups = self.mw.api.get_groups(
                self.mw.cfg["venue_id"], self.mw.cfg["booth_id"], qid
            )
        except Exception:
            return
        for g in groups:
            cb = QtWidgets.QCheckBox(g["name"])
            status = "可约" if g.get("reservable") else "已满"
            cb.setText(f"{g['name']}（当前{status}）")
            cb.setProperty("gid", g["id"])
            self._slot_checks.append(cb)
            self.slot_box.addWidget(cb)
        self.slot_box.addStretch(1)

    def do_add(self):
        qid = self.cb_date.currentData()
        date = self.cb_date.currentText()
        if not qid:
            QtWidgets.QMessageBox.warning(self, "提示", "请先选择日期")
            return
        added = 0
        for cb in self._slot_checks:
            if cb.isChecked():
                gid = cb.property("gid")
                exists = any(
                    t["queue_id"] == qid and t["group_id"] == gid
                    for t in self.mw.cfg["targets"]
                )
                if not exists:
                    self.mw.cfg["targets"].append({
                        "date": date, "time": cb.text().split("（")[0],
                        "queue_id": qid, "group_id": gid,
                    })
                    added += 1
                cb.setChecked(False)
        if added:
            save_config(self.mw.cfg)
            self.mw.update_nav()
        self.refresh_table()

    def refresh_table(self):
        targets = self.mw.cfg["targets"]
        self.table.setRowCount(len(targets))
        for i, t in enumerate(targets):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(t["date"]))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(t["time"]))
            item = QtWidgets.QTableWidgetItem("—")
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 3, item)

    def refresh_status(self):
        """手动刷新列表中所有目标的当前状态"""
        targets = self.mw.cfg["targets"]
        queue_map = {}
        for t in targets:
            queue_map.setdefault(t["queue_id"], []).append(t)
        for qid, tlist in queue_map.items():
            try:
                groups = self.mw.api.get_groups(
                    self.mw.cfg["venue_id"], self.mw.cfg["booth_id"], qid
                )
                gmap = {g["id"]: g for g in groups}
                for t in tlist:
                    g = gmap.get(t["group_id"])
                    row = targets.index(t)
                    ok = bool(g and g.get("reservable"))
                    item = self.table.item(row, 3)
                    item.setText("🟢 可预约" if ok else "🔴 已满")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "提示", f"刷新失败: {e}")
                return

    def move(self, delta):
        row = self.table.currentRow()
        if row < 0:
            return
        new = row + delta
        if new < 0 or new >= len(self.mw.cfg["targets"]):
            return
        ts = self.mw.cfg["targets"]
        ts[row], ts[new] = ts[new], ts[row]
        save_config(self.mw.cfg)
        self.refresh_table()
        self.table.setCurrentCell(new, 0)

    def do_del(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.mw.cfg["targets"].pop(row)
        save_config(self.mw.cfg)
        self.mw.update_nav()
        self.refresh_table()


class MonitorPage(QtWidgets.QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.rounds = 0
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(30, 22, 30, 22)
        lay.setSpacing(10)

        t = QtWidgets.QLabel("监控")
        t.setObjectName("PageTitle")
        lay.addWidget(t)

        # 状态卡：大字 + 副信息横排一行（节省垂直空间）
        self.card_status, csl = card()
        csl.setContentsMargins(20, 12, 20, 12)
        row_st = QtWidgets.QHBoxLayout()
        row_st.setSpacing(18)
        self.lab_big = QtWidgets.QLabel("⏸ 未开始")
        self.lab_big.setStyleSheet("font-size:21px;font-weight:800;")
        row_st.addWidget(self.lab_big)
        self.lab_sub = QtWidgets.QLabel("点击「开始监控」即可挂机")
        self.lab_sub.setObjectName("Hint")
        row_st.addWidget(self.lab_sub)
        row_st.addStretch(1)
        csl.addLayout(row_st)
        lay.addWidget(self.card_status)

        # 目标状态表
        c2, c2l = card("目标状态")
        c2l.setContentsMargins(20, 12, 20, 12)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["目标", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setMinimumHeight(96)
        c2l.addWidget(self.table)
        lay.addWidget(c2)

        # 控制区（三行紧凑排布）
        c3, c3l = card()
        c3l.setContentsMargins(20, 12, 20, 12)
        c3l.setSpacing(8)
        rowc = QtWidgets.QHBoxLayout()
        rowc.setSpacing(10)
        self.btn_toggle = QtWidgets.QPushButton("▶ 开始监控")
        self.btn_toggle.setObjectName("PrimaryBtn")
        self.btn_toggle.setFixedSize(150, 38)
        self.btn_toggle.clicked.connect(self.mw.toggle_monitor)
        rowc.addWidget(self.btn_toggle)
        self.btn_refresh_now = QtWidgets.QPushButton("立即检查一轮")
        self.btn_refresh_now.setFixedSize(132, 38)
        self.btn_refresh_now.clicked.connect(self.mw.manual_round)
        rowc.addWidget(self.btn_refresh_now)
        rowc.addStretch(1)
        c3l.addLayout(rowc)

        rowi = QtWidgets.QHBoxLayout()
        rowi.setSpacing(10)
        lab_in = QtWidgets.QLabel("轮询间隔")
        rowi.addWidget(lab_in)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(3, 30)
        self.slider.setValue(self.mw.cfg.get("interval", 5))
        self.slider.setFixedWidth(180)
        self.lab_interval = QtWidgets.QLabel(f"{self.slider.value()} 秒")
        self.lab_interval.setMinimumWidth(42)
        self.slider.valueChanged.connect(
            lambda v: self.lab_interval.setText(f"{v} 秒")
        )
        rowi.addWidget(self.slider)
        rowi.addWidget(self.lab_interval)
        rowi.addSpacing(18)
        self.chk_auto = QtWidgets.QCheckBox("自动下单")
        self.chk_auto.setChecked(self.mw.cfg.get("auto_reserve", True))
        self.chk_auto.toggled.connect(self._sync_auto)
        rowi.addWidget(self.chk_auto)
        rowi.addSpacing(18)
        self.lab_lic = QtWidgets.QLabel()
        rowi.addWidget(self.lab_lic)
        rowi.addStretch(1)
        c3l.addLayout(rowi)

        rowstrat = QtWidgets.QHBoxLayout()
        rowstrat.setSpacing(10)
        rowstrat.addWidget(QtWidgets.QLabel("抢到策略"))
        self.radio_stop = QtWidgets.QRadioButton("抢到任一即停（推荐）")
        self.radio_all = QtWidgets.QRadioButton("继续抢全部目标")
        if self.mw.cfg.get("strategy") == "all":
            self.radio_all.setChecked(True)
        else:
            self.radio_stop.setChecked(True)
        self.radio_stop.toggled.connect(self._sync_strategy)
        for w in (self.radio_stop, self.radio_all):
            rowstrat.addWidget(w)
        rowstrat.addStretch(1)
        c3l.addLayout(rowstrat)
        lay.addWidget(c3)

        # 日志：标题行内联操作按钮，日志框占剩余全部空间
        c4, c4l = card()
        c4l.setContentsMargins(20, 12, 20, 12)
        c4l.setSpacing(8)
        self.logbox = QtWidgets.QPlainTextEdit()
        self.logbox.setObjectName("LogBox")
        self.logbox.setReadOnly(True)
        self.logbox.setMinimumHeight(150)
        self.logbox.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        rowtitle = QtWidgets.QHBoxLayout()
        lab_log = QtWidgets.QLabel("运行日志")
        lab_log.setObjectName("CardTitle")
        rowtitle.addWidget(lab_log)
        rowtitle.addStretch(1)
        btn_copylog = QtWidgets.QPushButton("复制日志")
        btn_copylog.setFixedSize(88, 30)
        btn_copylog.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(self.logbox.toPlainText())
        )
        btn_clear = QtWidgets.QPushButton("清空")
        btn_clear.setFixedSize(64, 30)
        btn_clear.clicked.connect(self.logbox.clear)
        rowtitle.addWidget(btn_copylog)
        rowtitle.addWidget(btn_clear)
        c4l.addLayout(rowtitle)
        c4l.addWidget(self.logbox, 1)
        lay.addWidget(c4, 1)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_elapsed)
        self.start_time = None

    def _sync_auto(self, on):
        self.mw.cfg["auto_reserve"] = on
        save_config(self.mw.cfg)

    def _sync_strategy(self):
        self.mw.cfg["strategy"] = "stop_first" if self.radio_stop.isChecked() else "all"
        save_config(self.mw.cfg)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh_lic_label()
        self.mw.monitor_page_refresh_targets()

    def refresh_lic_label(self):
        if not self.mw.cfg["activated"]:
            self.lab_lic.setText("⭕ 未激活：仅监控提醒，不自动下单")
            self.lab_lic.setObjectName("WarnText")
            self.chk_auto.setChecked(False)
            self.chk_auto.setEnabled(False)
        else:
            self.lab_lic.setText("")
            self.chk_auto.setEnabled(True)
            self.chk_auto.setChecked(self.mw.cfg.get("auto_reserve", True))
        self.lab_lic.style().unpolish(self.lab_lic)
        self.lab_lic.style().polish(self.lab_lic)

    def set_big(self, big, sub):
        self.lab_big.setText(big)
        self.lab_sub.setText(sub)

    def update_elapsed(self):
        if self.start_time:
            secs = int(time.time() - self.start_time)
            m, s = divmod(secs, 60)
            self.lab_sub.setText(f"第 {self.rounds} 轮 · 已运行 {m} 分 {s} 秒")

    def refresh_targets_table(self):
        targets = self.mw.cfg["targets"]
        self.table.setRowCount(len(targets))
        for i, t in enumerate(targets):
            self.table.setItem(
                i, 0, QtWidgets.QTableWidgetItem(f"{t['date']}  {t['time']}")
            )
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem("⏳"))

    def apply_states(self, states):
        targets = self.mw.cfg["targets"]
        self.table.setRowCount(len(targets))
        for i, t in enumerate(targets):
            self.table.setItem(
                i, 0, QtWidgets.QTableWidgetItem(f"{t['date']}  {t['time']}")
            )
            st = next(
                (s for s in states if s["queue_id"] == t["queue_id"]
                 and s["group_id"] == t["group_id"]),
                None,
            )
            if st is None:
                txt = "—"
            elif st.get("reservable"):
                txt = "🟢 可预约!"
            elif st.get("reservable") is None:
                txt = "⚠️ 查询失败"
            else:
                txt = "🔴 已满"
            item = QtWidgets.QTableWidgetItem(txt)
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 1, item)


# ============================================================
# 主窗口
# ============================================================

class MainWindow(QtWidgets.QMainWindow):
    NAV = ["① 激活", "② 活动配置", "③ 登录账号", "④ 目标配置", "⑤ 监控"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1080, 760)
        self.setMinimumSize(1020, 700)

        self.cfg = load_config()
        self.api = WeverseAPI(
            token_cache_path=os.path.join(data_dir(), ".token_cache.json")
        )
        self.login_valid = False
        self.worker = None

        icon = self._make_icon()
        self.setWindowIcon(icon)
        self._setup_tray(icon)

        # 布局：左侧导航 + 右侧页面
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 侧栏
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(190)
        sl = QtWidgets.QVBoxLayout(sidebar)
        sl.setContentsMargins(14, 20, 14, 16)
        sl.setSpacing(4)
        brand = QtWidgets.QLabel("Weverse")
        brand.setObjectName("Brand")
        sl.addWidget(brand)
        brand2 = QtWidgets.QLabel("抢号助手 v0.1")
        brand2.setObjectName("Brand2")
        sl.addWidget(brand2)
        sl.addSpacing(14)

        self.nav_btns = []
        for i, name in enumerate(self.NAV):
            b = QtWidgets.QPushButton(name)
            b.setObjectName("NavBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, idx=i: self.goto(idx))
            sl.addWidget(b)
            self.nav_btns.append(b)
        sl.addStretch(1)
        self.lab_nav_status = QtWidgets.QLabel()
        self.lab_nav_status.setObjectName("Hint")
        sl.addWidget(self.lab_nav_status)
        root.addWidget(sidebar)

        # 页面栈
        self.stack = QtWidgets.QStackedWidget()
        self.page_activation = ActivationPage(self)
        self.page_event = EventPage(self)
        self.page_login = LoginPage(self)
        self.page_target = TargetPage(self)
        self.page_monitor = MonitorPage(self)
        for p in (self.page_activation, self.page_event, self.page_login,
                  self.page_target, self.page_monitor):
            self.stack.addWidget(p)
        root.addWidget(self.stack, 1)

        self.goto(0)
        self.update_nav()

    # ---------- 图标/托盘 ----------

    def _make_icon(self):
        pm = QtGui.QPixmap(64, 64)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        grad = QtGui.QLinearGradient(0, 0, 64, 64)
        grad.setColorAt(0, QtGui.QColor(BRAND_A))
        grad.setColorAt(1, QtGui.QColor(BRAND_B))
        p.setBrush(QtGui.QBrush(grad))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawRoundedRect(2, 2, 60, 60, 14, 14)
        p.setPen(QtGui.QPen(QtGui.QColor("white")))
        f = QtGui.QFont()
        f.setBold(True)
        f.setPixelSize(32)
        p.setFont(f)
        p.drawText(pm.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "抢")
        p.end()
        return QtGui.QIcon(pm)

    def _setup_tray(self, icon):
        self.tray = QtWidgets.QSystemTrayIcon(icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QtWidgets.QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self.show_up)
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_up()
            if reason == QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        self.tray.show()

    def show_up(self):
        self.showNormal()
        self.raise_()

    def quit_app(self):
        self.stop_monitor(silent=True)
        QtWidgets.QApplication.quit()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
            self.hide()
            self.tray.showMessage(
                APP_NAME, "监控仍在运行，已最小化到系统托盘\n双击托盘图标恢复",
                QtWidgets.QSystemTrayIcon.MessageIcon.Information, 4000,
            )
        else:
            event.accept()

    # ---------- 导航 ----------

    def goto(self, idx):
        for i, b in enumerate(self.nav_btns):
            b.setChecked(i == idx)
        self.stack.setCurrentIndex(idx)

    def update_nav(self):
        done = [
            self.cfg["activated"],
            bool(self.cfg.get("venue_id") and self.cfg.get("booth_id")),
            self.login_valid,
            len(self.cfg.get("targets", [])) > 0,
            False,
        ]
        for i, b in enumerate(self.nav_btns):
            base = self.NAV[i]
            b.setText(f"{base} ✓" if done[i] else base)
        flags = "  ".join("●" if d else "○" for d in done[:4])
        self.lab_nav_status.setText(f"步骤进度 {flags}")

    def mlog(self, msg):
        self.page_monitor.logbox.appendPlainText(f"[{now_str()}] {msg}")
        self.page_monitor.logbox.ensureCursorVisible()

    def monitor_page_refresh_targets(self):
        self.page_monitor.refresh_targets_table()

    # ---------- 监控控制 ----------

    def toggle_monitor(self):
        if self.worker and self.worker.isRunning():
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        # 校验
        if not (self.cfg.get("venue_id") and self.cfg.get("booth_id")):
            QtWidgets.QMessageBox.warning(
                self, "请先配置活动", "请先在「② 活动配置」解析活动链接"
            )
            self.goto(1)
            return
        targets = list(self.cfg.get("targets", []))
        if not targets:
            QtWidgets.QMessageBox.warning(
                self, "请先添加目标", "请先在「④ 目标配置」添加要抢的日期和时段"
            )
            self.goto(3)
            return

        auto = self.cfg.get("auto_reserve", True) and self.cfg["activated"]
        if self.cfg.get("auto_reserve", True) and not self.cfg["activated"]:
            QtWidgets.QMessageBox.warning(
                self, "未激活", "当前为试用模式，只能监控提醒，不会自动下单。\n"
                "如需自动下单请在「① 激活」页输入激活码。"
            )
        if auto and not self.login_valid:
            # 现场验证一次登录态
            ok, info = self.api.test_login()
            if not ok and self.api.refresh_tokens():
                ok, info = self.api.test_login()
            if ok:
                self.page_login._mark_ok(info)
            else:
                QtWidgets.QMessageBox.warning(
                    self, "登录态无效",
                    "自动下单需要有效登录态，请先在「③ 登录账号」更新 Cookie",
                )
                self.goto(2)
                return

        self.cfg["interval"] = self.page_monitor.slider.value()
        save_config(self.cfg)

        self.worker = MonitorWorker(
            self.api, self.cfg["venue_id"], self.cfg["booth_id"], targets,
            self.cfg["interval"], auto,
            self.cfg.get("strategy", "stop_first") == "stop_first",
            self.cfg.get("email", ""),
        )
        self.worker.log.connect(self.mlog)
        self.worker.states.connect(self.page_monitor.apply_states)
        self.worker.found.connect(self.on_found)
        self.worker.reserved.connect(self.on_reserved)
        self.worker.reserve_failed.connect(self.on_reserve_failed)
        self.worker.round_done.connect(
            lambda n: setattr(self.page_monitor, "rounds", n)
        )
        self.worker.start()

        pm = self.page_monitor
        pm.rounds = 0
        pm.start_time = time.time()
        pm.timer.start(1000)
        pm.set_big("🟢 监控中", "第 0 轮")
        pm.btn_toggle.setText("⏹ 停止监控")
        self.mlog(
            f"开始监控 {len(targets)} 个目标，间隔 {self.cfg['interval']} 秒，"
            f"自动下单 {'开' if auto else '关（试用模式）'}"
        )
        self.update_nav()

    def stop_monitor(self, silent=False):
        if self.worker:
            self.worker.stop()
            self.worker.wait(3000)
        pm = self.page_monitor
        pm.timer.stop()
        pm.btn_toggle.setText("▶ 开始监控")
        if not silent:
            pm.set_big("⏸ 已停止", "点击「开始监控」继续")
            self.mlog("监控已停止")

    def manual_round(self):
        """立即手动检查一轮（复用 worker 的单轮逻辑，不常驻线程）"""
        if self.worker and self.worker.isRunning():
            self.mlog("监控进行中，无需手动检查")
            return
        targets = list(self.cfg.get("targets", []))
        if not targets:
            QtWidgets.QMessageBox.warning(self, "提示", "请先添加目标")
            return
        self.mlog("手动检查一轮…")
        try:
            states = []
            queue_map = {}
            for t in targets:
                queue_map.setdefault(t["queue_id"], []).append(t)
            for qid, tl in queue_map.items():
                groups = self.api.get_groups(
                    self.cfg["venue_id"], self.cfg["booth_id"], qid
                )
                gmap = {g["id"]: g for g in groups}
                for t in tl:
                    g = gmap.get(t["group_id"])
                    states.append(dict(t, reservable=bool(g and g.get("reservable"))))
            self.page_monitor.apply_states(states)
            avail = [s for s in states if s["reservable"]]
            if avail:
                for s in avail:
                    self.on_found(s)
            else:
                self.mlog("本轮检查：全部已满")
        except Exception as e:
            self.mlog(f"手动检查失败: {e}")

    # ---------- 事件回调 ----------

    def on_found(self, t):
        msg = f"发现空位：{t['date']} {t['time']}"
        self.mlog(f"🟢 {msg}")
        if not (self.worker and self.worker.auto_reserve):
            play_alert()
            self.tray.showMessage("发现空位！", msg + "，快去手动抢！",
                                  QtWidgets.QSystemTrayIcon.MessageIcon.Warning, 5000)

    def on_reserved(self, t, rid):
        msg = f"{t['date']} {t['time']} 抢到了！预约号: {rid}"
        self.mlog(f"🎉🎉🎉 {msg}")
        play_alert(5)
        self.tray.showMessage("🎉 抢号成功", msg,
                              QtWidgets.QSystemTrayIcon.MessageIcon.Information, 10000)
        self.stop_monitor(silent=True)
        pm = self.page_monitor
        pm.set_big("🎉 抢号成功", msg)
        QtWidgets.QMessageBox.information(
            self, "抢号成功",
            f"已预约：{t['date']} {t['time']}\n预约号：{rid}\n\n"
            f"请前往 Weverse「나의 줄서기 내역(我的记录)」确认预约详情。",
        )
        # 从目标列表移除已抢到的
        self.cfg["targets"] = [
            x for x in self.cfg["targets"]
            if not (x["queue_id"] == t["queue_id"] and x["group_id"] == t["group_id"])
        ]
        save_config(self.cfg)
        self.update_nav()

    def on_reserve_failed(self, t, err):
        self.mlog(f"❌ 下单失败 {t['date']} {t['time']}: {err}")
        self.tray.showMessage("下单失败", f"{t['date']} {t['time']}\n{err[:80]}",
                              QtWidgets.QSystemTrayIcon.MessageIcon.Warning, 5000)


# ============================================================
# 入口
# ============================================================

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(QSS)
    app.setApplicationName(APP_NAME)

    cfg = load_config()
    smoke = "--smoke" in sys.argv
    if not cfg.get("disclaimer_accepted") and not smoke:
        dlg = DisclaimerDialog()
        dlg.btn_agree.clicked.connect(dlg.accept)
        dlg.btn_refuse.clicked.connect(dlg.reject)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            sys.exit(0)
        cfg["disclaimer_accepted"] = True
        save_config(cfg)

    win = MainWindow()
    win.show()

    if smoke:
        # 冒烟测试：逐页截图后自动退出
        def shoot():
            for i in range(5):
                win.goto(i)
                QtWidgets.QApplication.processEvents()
                QtCore.QThread.msleep(150)
                pm = win.grab()
                out = os.path.join(app_dir(), f"smoke_page{i}.png")
                pm.save(out)
                print(f"[smoke] saved {out}")
            app.quit()
        QtCore.QTimer.singleShot(2500, shoot)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
