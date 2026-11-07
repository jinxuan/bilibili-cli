"""Authentication for Bilibili.

Strategy:
1. Load the saved credential from ~/.bilibili-cli/credential.json
2. Otherwise the user logs in with `bili login` (QR code in the terminal)

Browser cookie extraction was removed on purpose: reading Chrome's cookie
store needs the "Chrome Safe Storage" Keychain key, which decrypts every
site's cookies, not just Bilibili's.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
from urllib.parse import parse_qs, urlparse
import time
from pathlib import Path
from typing import Literal

import aiohttp
import qrcode
from bilibili_api.utils.network import Credential

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".bilibili-cli"
CREDENTIAL_FILE = CONFIG_DIR / "credential.json"

# Required cookies for a valid Bilibili session
REQUIRED_COOKIES = {"SESSDATA"}

# Extra cookie fields that help bypass Bilibili's 412 anti-scraping checks
EXTRA_COOKIE_FIELDS = ("buvid3", "buvid4", "dedeuserid")

# Credential TTL: warn and attempt refresh after 7 days
CREDENTIAL_TTL_DAYS = 7
_CREDENTIAL_TTL_SECONDS = CREDENTIAL_TTL_DAYS * 86400


AuthMode = Literal["optional", "read", "write"]


def get_credential(mode: AuthMode = "read") -> Credential | None:
    """Try auth methods in order and return credential according to mode.

    - optional: only load saved credential (no network validation)
    - read: prefer validated credential; if validation is indeterminate (network),
      return the saved credential as best effort
    - write: same as read, but require bili_jct capability
    """
    require_write = mode == "write"

    cred = _load_saved_credential()
    if cred is None:
        return None
    if mode == "optional":
        return cred

    if _is_credential_stale():
        logger.info("Credential older than %d days; validating it", CREDENTIAL_TTL_DAYS)

    validation = _validate_credential(cred, require_write=require_write)
    if validation is True:
        logger.info("Loaded valid credential from %s", CREDENTIAL_FILE)
        return cred
    if validation is None:
        logger.warning("Credential validation failed due to network; using saved credential as best effort")
        return cred
    logger.warning("Saved credential is expired or lacks write access; run `bili login`")
    if not require_write:
        clear_credential()
    return None


def _is_credential_stale() -> bool:
    """Check if saved credential file is older than TTL."""
    if not CREDENTIAL_FILE.exists():
        return False
    try:
        data = json.loads(CREDENTIAL_FILE.read_text())
        saved_at = data.get("saved_at", 0)
        if not saved_at:
            # Legacy file without saved_at — treat as stale to add the field
            return True
        return (time.time() - saved_at) > _CREDENTIAL_TTL_SECONDS
    except (json.JSONDecodeError, OSError):
        return False


def _validate_credential(cred: Credential, require_write: bool = False) -> bool | None:
    """Check if a credential is valid.

    Returns:
      - True: credential validated by API
      - False: credential confirmed invalid or missing required fields
      - None: validation is indeterminate due to network/runtime issues
    """
    from bilibili_api import user
    from bilibili_api.exceptions import NetworkException

    if not getattr(cred, "sessdata", ""):
        return False
    if require_write and not getattr(cred, "bili_jct", ""):
        return False

    async def _check():
        try:
            await user.get_self_info(cred)
            return True
        except NetworkException:
            return None
        except Exception:
            return False

    try:
        return asyncio.run(_check())
    except Exception:
        return None


def _load_saved_credential() -> Credential | None:
    """Load credential from saved file."""
    if not CREDENTIAL_FILE.exists():
        return None

    try:
        data = json.loads(CREDENTIAL_FILE.read_text())
        sessdata = data.get("sessdata", "")
        if not sessdata:
            return None
        return Credential(
            sessdata=sessdata,
            bili_jct=data.get("bili_jct", ""),
            ac_time_value=data.get("ac_time_value", ""),
            buvid3=data.get("buvid3", ""),
            buvid4=data.get("buvid4", ""),
            dedeuserid=data.get("dedeuserid", ""),
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to load saved credential: %s", e)
        return None


def save_credential(credential: Credential):
    """Save credential to config file with timestamp for TTL tracking."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "sessdata": credential.sessdata,
        "bili_jct": credential.bili_jct,
        "ac_time_value": credential.ac_time_value or "",
        "buvid3": credential.buvid3 or "",
        "buvid4": credential.buvid4 or "",
        "dedeuserid": credential.dedeuserid or "",
        "saved_at": time.time(),
    }
    CREDENTIAL_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    CREDENTIAL_FILE.chmod(0o600)  # Owner-only read/write
    logger.info("Credential saved to %s", CREDENTIAL_FILE)


def clear_credential():
    """Remove saved credential file."""
    if CREDENTIAL_FILE.exists():
        CREDENTIAL_FILE.unlink()
        logger.info("Credential removed: %s", CREDENTIAL_FILE)


def _supports_unicode_half_blocks() -> bool:
    """Return True when stdout encoding can represent half-block glyphs."""
    encoding = getattr(sys.stdout, "encoding", None)
    if not encoding:
        return False
    try:
        "▀▄█".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def _render_compact_qr(data: str) -> str | None:
    """Render a compact QR code using Unicode half-block characters.

    Uses ▀, ▄, █, and space to encode two vertical modules per character row,
    reducing the QR code height by half compared to full-block rendering.
    Each module is 1 character wide (vs 2 in qrcode-terminal), so total area
    is ~25% of the original.
    """
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    # Add 1-module quiet zone
    size = len(matrix)
    padded = [[False] * (size + 2)]
    for row in matrix:
        padded.append([False] + list(row) + [False])
    padded.append([False] * (size + 2))
    matrix = padded
    rows = len(matrix)

    # Check terminal width and warn if too narrow
    term_cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    qr_width = len(matrix[0])
    if qr_width > term_cols:
        logger.warning(
            "Terminal width (%d) too narrow for compact QR (%d), falling back",
            term_cols,
            qr_width,
        )
        return None

    lines: list[str] = []
    # Process two rows at a time using half-block characters
    # top=black, bottom=black → █ (full block)
    # top=black, bottom=white → ▀ (upper half)
    # top=white, bottom=black → ▄ (lower half)
    # top=white, bottom=white → ' ' (space)
    for y in range(0, rows, 2):
        line = ""
        top_row = matrix[y]
        bottom_row = matrix[y + 1] if y + 1 < rows else [False] * len(top_row)
        for x in range(len(top_row)):
            top = top_row[x]
            bottom = bottom_row[x]
            if top and bottom:
                line += "█"
            elif top and not bottom:
                line += "▀"
            elif not top and bottom:
                line += "▄"
            else:
                line += " "
        lines.append(line)
    return "\n".join(lines)


def _render_ascii_qr(data: str) -> str:
    """Plain ASCII QR code, used when Unicode half blocks are unavailable."""
    import io

    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue()


def _get_qr_terminal_output(qr_link: str) -> str:
    """Choose compact QR rendering when possible, otherwise use ASCII output."""
    if not _supports_unicode_half_blocks():
        logger.warning("stdout encoding cannot render Unicode QR blocks, using ASCII renderer")
        return _render_ascii_qr(qr_link)

    compact_qr = _render_compact_qr(qr_link)
    if compact_qr is None:
        return _render_ascii_qr(qr_link)
    return compact_qr


_QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
_SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"
_LOGIN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

# Poll codes from passport.bilibili.com
_QR_DONE = 0
_QR_EXPIRED = 86038
_QR_SCANNED = 86090
_QR_WAITING = 86101


def _credential_from_login(cookies: dict[str, str], login_url: str, refresh_token: str) -> Credential:
    """Build a credential from the poll response's Set-Cookie headers.

    Bilibili used to put the cookies in the returned URL's query string as
    well; read it as a fallback for any cookie the headers did not carry.
    """
    query = {k: v[0] for k, v in parse_qs(urlparse(login_url).query).items() if v} if login_url else {}

    def pick(name: str) -> str:
        return cookies.get(name) or query.get(name) or ""

    return Credential(
        sessdata=pick("SESSDATA"),
        bili_jct=pick("bili_jct"),
        dedeuserid=pick("DedeUserID"),
        ac_time_value=refresh_token or "",
        buvid3=cookies.get("buvid3", ""),
        buvid4=cookies.get("buvid4", ""),
    )


async def _fetch_buvid(session: aiohttp.ClientSession) -> dict[str, str]:
    """Device cookies that make Bilibili's 412 anti-bot checks less likely."""
    try:
        async with session.get(_SPI_URL) as resp:
            data = (await resp.json(content_type=None)).get("data") or {}
        return {k: v for k, v in (("buvid3", data.get("b_3", "")), ("buvid4", data.get("b_4", ""))) if v}
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return {}


async def qr_login() -> Credential:
    """QR code login via terminal.

    Displays a QR code in the terminal, polls until login completes,
    then saves and returns the credential.
    """
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=_LOGIN_HEADERS, timeout=timeout) as session:
        async with session.get(_QR_GENERATE_URL) as resp:
            resp.raise_for_status()
            gen = (await resp.json(content_type=None)).get("data") or {}
        qr_link, qr_key = gen.get("url"), gen.get("qrcode_key")
        if not qr_link or not qr_key:
            raise RuntimeError("生成二维码失败")

        print("\n📱 请使用 Bilibili App 扫描以下二维码登录:\n")
        print(_get_qr_terminal_output(qr_link))
        print("\n⭐ 扫码后请在手机上确认登录...")

        announced_scan = False
        while True:
            async with session.get(_QR_POLL_URL, params={"qrcode_key": qr_key}) as resp:
                resp.raise_for_status()
                data = (await resp.json(content_type=None)).get("data") or {}
                set_cookies = {name: morsel.value for name, morsel in resp.cookies.items()}

            code = data.get("code")
            if code == _QR_DONE:
                jar = {c.key: c.value for c in session.cookie_jar}
                cookies = {**jar, **set_cookies, **await _fetch_buvid(session)}
                credential = _credential_from_login(cookies, data.get("url", ""), data.get("refresh_token", ""))
                if not credential.sessdata:
                    raise RuntimeError("登录已确认，但 Bilibili 未返回 SESSDATA，凭证未保存")
                save_credential(credential)
                print("\n✅ 登录成功！凭证已保存")
                return credential
            if code == _QR_EXPIRED:
                raise RuntimeError("二维码已过期，请重试")
            if code == _QR_SCANNED and not announced_scan:
                print("  📲 已扫码，请在手机上确认...")
                announced_scan = True
            elif code not in (_QR_WAITING, _QR_SCANNED):
                raise RuntimeError(f"登录失败: {data.get('message') or code}")

            await asyncio.sleep(2)
