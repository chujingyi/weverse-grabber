"""
Weverse 预约 API 客户端（纯逻辑，无 UI 依赖）

封装已验证的全流程：
  - 解析活动链接（短链自动跳转）
  - 获取展位列表 / 日期队列 / 时段余量
  - 登录验证 / Token 自动刷新（refresh token 轮换保存）
  - 下单预约
"""
import os
import re
import json
import time
import base64
import requests
from datetime import datetime, timezone, timedelta

BASE_API = "https://waiting-api.weverse.io"
TOKEN_REFRESH_URL = "https://queues.weverse.io/account-api/v1/token/refresh"

KST = timezone(timedelta(hours=9))  # 首尔时间（活动所在地）

COMMON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "ko-KR,ko;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
    "referer": "https://queues.weverse.io/",
    "origin": "https://queues.weverse.io",
    "x-wev-service-id": "biz-queues-web",
}


class ApiError(Exception):
    """带状态码的 API 异常"""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _safe_request(method, url, retries=2, **kwargs):
    """带重试的请求，处理偶发 SSL/网络错误"""
    last_exc = None
    for i in range(retries):
        try:
            return requests.request(method, url, timeout=10, **kwargs)
        except Exception as e:
            last_exc = e
            if i < retries - 1:
                time.sleep(0.8)
    raise last_exc


class WeverseAPI:
    def __init__(self, token_cache_path=None):
        self.access_token = None
        self.refresh_token = None
        self.token_cache_path = token_cache_path
        self._load_tokens()

    # ================= Token 管理 =================

    def _load_tokens(self):
        if self.token_cache_path and os.path.exists(self.token_cache_path):
            try:
                with open(self.token_cache_path, encoding="utf-8") as f:
                    d = json.load(f)
                self.access_token = d.get("accessToken")
                self.refresh_token = d.get("refreshToken")
            except Exception:
                pass

    def _save_tokens(self):
        if not self.token_cache_path:
            return
        try:
            with open(self.token_cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"accessToken": self.access_token, "refreshToken": self.refresh_token},
                    f,
                )
        except Exception:
            pass

    def set_cookie_string(self, cookie_str):
        """从浏览器复制的整段 Cookie 中提取双 token"""
        for part in cookie_str.split(";"):
            part = part.strip()
            if part.startswith("we2_access_token="):
                self.access_token = part.split("=", 1)[1]
            elif part.startswith("we2_refresh_token="):
                self.refresh_token = part.split("=", 1)[1]
        self._save_tokens()

    def refresh_tokens(self):
        """用 refresh_token 刷新（会轮换，成功后自动保存新 token）"""
        if not self.refresh_token:
            return False
        for attempt in range(3):
            try:
                resp = _safe_request(
                    "POST",
                    TOKEN_REFRESH_URL,
                    json={"refreshToken": self.refresh_token},
                    headers={
                        "content-type": "application/json",
                        "user-agent": COMMON_HEADERS["user-agent"],
                        "origin": "https://queues.weverse.io",
                        "referer": "https://queues.weverse.io/",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self.access_token = data.get("accessToken", "")
                    self.refresh_token = data.get("refreshToken", "")
                    self._save_tokens()
                    return True
                return False
            except Exception:
                if attempt < 2:
                    time.sleep(1)
                else:
                    return False
        return False

    def token_expiry(self):
        """解码 JWT 返回 access_token 过期时间（本地时间 datetime），失败返回 None"""
        if not self.access_token:
            return None
        try:
            payload = self.access_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            d = json.loads(base64.urlsafe_b64decode(payload))
            return datetime.fromtimestamp(d["exp"])
        except Exception:
            return None

    def _auth_headers(self):
        """带认证的请求头（monitor 无需认证，下单/登录需要）"""
        headers = dict(COMMON_HEADERS)
        headers["content-type"] = "application/json"
        if self.access_token:
            headers["cookie"] = (
                f"we2_access_token={self.access_token}; "
                f"we2_refresh_token={self.refresh_token or ''}; we2_service_lang=ko"
            )
            headers["authorization"] = f"Bearer {self.access_token}"
        return headers

    # ================= 登录 =================

    def test_login(self):
        """验证登录态。返回 (是否成功, 用户信息dict或错误消息)"""
        try:
            resp = _safe_request(
                "GET", f"{BASE_API}/api/v2/user/me", headers=self._auth_headers()
            )
            if resp.status_code == 200:
                return True, resp.json()
            return False, f"登录验证失败 [{resp.status_code}] {resp.text[:120]}"
        except Exception as e:
            return False, f"网络异常: {e}"

    # ================= 活动解析 =================

    def parse_event_link(self, url):
        """
        解析活动链接 → (venue_id, booth_id 或 None)
        支持：go.weverse.io 短链（自动跳转解析）、booth-list、booth-detail 完整链接
        """
        url = (url or "").strip()
        if not url:
            raise ApiError("链接为空")
        if not url.startswith("http"):
            url = "https://" + url
        # 短链 → 跟随跳转拿最终地址
        if "go.weverse.io" in url:
            try:
                resp = _safe_request(
                    "GET", url, headers={"user-agent": COMMON_HEADERS["user-agent"]}
                )
                url = resp.url
            except Exception:
                raise ApiError(
                    "短链暂时无法解析，请先在浏览器打开该链接，"
                    "再把浏览器地址栏的完整链接粘贴进来"
                )
        m = re.search(r"venue-id=(\d+)", url)
        if not m:
            raise ApiError("链接中未找到 venue-id，请粘贴完整的 Weverse 排队链接")
        venue_id = int(m.group(1))
        m2 = re.search(r"booth-detail/(?:timed|fifo)/(\d+)", url)
        booth_id = int(m2.group(1)) if m2 else None
        return venue_id, booth_id

    # ================= 展位/日期/时段 =================

    def get_booth_list(self, venue_id):
        """
        获取场馆下所有展位。
        返回 list[{boothId, name, reserveType, availabilityStatus, ...}]
        """
        resp = _safe_request(
            "GET",
            f"{BASE_API}/api/v3/venues/{venue_id}/booth-queues",
            params={"language": "zh_cn"},
            headers=dict(COMMON_HEADERS),
        )
        if resp.status_code != 200:
            raise ApiError(f"获取展位列表失败 [{resp.status_code}]", resp.status_code)
        return resp.json().get("contents", [])

    def get_timed_queues(self, venue_id, booth_id):
        """
        获取 TIMED 展位的日期队列。
        返回 dict{boothName, description, locationDescription, queues:[{id, queuingDate, ...}]}
        """
        resp = _safe_request(
            "GET",
            f"{BASE_API}/api/v1/venues/{venue_id}/timed-booths/{booth_id}/queues",
            params={"language": "zh_cn"},
            headers=dict(COMMON_HEADERS),
        )
        if resp.status_code != 200:
            raise ApiError(f"获取日期列表失败 [{resp.status_code}]", resp.status_code)
        return resp.json()

    def get_groups(self, venue_id, booth_id, queue_id):
        """
        获取某日期的时段详情。
        返回 list[{id, name(如"15:00"), reservable(bool), ...}]
        """
        resp = _safe_request(
            "GET",
            f"{BASE_API}/api/v2/venues/{venue_id}/timed-booths/{booth_id}/queues/{queue_id}/groups",
            headers=dict(COMMON_HEADERS),
        )
        if resp.status_code != 200:
            raise ApiError(f"获取时段失败 [{resp.status_code}]", resp.status_code)
        return resp.json().get("groups", [])

    # ================= 下单 =================

    def reserve(self, venue_id, booth_id, queue_id, group_id, email=None):
        """
        预约下单。返回 (成功bool, reservationId或错误消息, 状态码)
        """
        body = {
            "venueId": venue_id,
            "boothId": booth_id,
            "queueId": queue_id,
            "groupId": group_id,
            "applicantsCount": 1,
            "language": "ko",
            "email": email if email else None,
        }
        try:
            resp = _safe_request(
                "POST",
                f"{BASE_API}/api/v1/reservation/email",
                json=body,
                headers=self._auth_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                return True, data.get("reservationId"), 200
            # 401 → 尝试刷新后让调用方重试
            return False, f"[{resp.status_code}] {resp.text[:200]}", resp.status_code
        except Exception as e:
            return False, f"网络异常: {e}", None
