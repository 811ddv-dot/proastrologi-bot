"""Publish one pre-rendered zodiac rating to the existing TG and MAX channels."""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPOSITORY = "811ddv-dot/proastrologi-bot"
STATE_PATH = "rating-state.json"
STATE_FILE = Path("rating-state.json")
TG_CHANNEL = "@proastrologi"
MAX_CHANNEL_ID = -79305594853965
MAX_BOT_USERNAME = "id400406889818_bot"
RELEASE_TAG = "ratings-v1"
MOSCOW = ZoneInfo("Europe/Moscow")


def json_request(url, method="GET", payload=None, headers=None, timeout=45):
    request_headers = {"Accept": "application/json", "User-Agent": "proastrologi-ratings/1"}
    if headers:
        request_headers.update(headers)
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        # Avoid logging response bodies, which may echo request details.
        raise RuntimeError(f"HTTP {exc.code} while contacting a publishing service") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Network error while contacting a publishing service") from None


def gh_headers():
    token = os.environ.get("RATING_HISTORY_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing GitHub Actions token for rating state")
    return {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}


def read_remote_state():
    url = f"https://api.github.com/repos/{REPOSITORY}/contents/{STATE_PATH}?ref=main"
    try:
        remote = json_request(url, headers=gh_headers())
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return {"next_number": 2, "status": "ready", "last_post_date": None}, None
        raise
    if remote.get("encoding") != "base64" or not remote.get("sha"):
        raise RuntimeError("GitHub rating state is malformed")
    content = base64.b64decode(remote["content"]).decode("utf-8")
    state = json.loads(content)
    if not isinstance(state, dict) or not isinstance(state.get("next_number"), int):
        raise RuntimeError("GitHub rating cursor is malformed")
    return state, remote["sha"]


def save_remote_state(state, sha):
    raw = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    payload = {
        "message": f"Update zodiac rating publication state ({state.get('status')})",
        "branch": "main",
        "content": base64.b64encode(raw.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    url = f"https://api.github.com/repos/{REPOSITORY}/contents/{STATE_PATH}"
    result = json_request(url, method="PUT", payload=payload, headers=gh_headers())
    new_sha = (result.get("content") or {}).get("sha")
    if not new_sha:
        raise RuntimeError("GitHub did not confirm the rating state update")
    state["_sha"] = new_sha
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return new_sha


def telegram_request(method, fields):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Telegram bot token is missing")
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "proastrologi-ratings/1"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram rejected the request (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Telegram connection failed") from None


def telegram_photo(path):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Telegram bot token is missing")
    boundary = "----proastrologi-rating-boundary"
    photo = Path(path)
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{TG_CHANNEL}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{photo.name}\"\r\nContent-Type: image/jpeg\r\n\r\n".encode(),
        photo.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto", data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "proastrologi-ratings/1"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram rejected the request (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Telegram connection failed") from None


def max_request(path, payload=None):
    import ssl
    from pathlib import Path as FilePath

    token = os.environ.get("MAX_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MAX bot token is missing")
    ca_path = FilePath(__file__).with_name("max-root-ca.pem")
    context = ssl.create_default_context(cafile=str(ca_path))
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://platform-api2.max.ru" + path, data=data,
        headers={"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with opener.open(request, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"MAX rejected the request (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("MAX connection failed") from None


def max_upload_image(path):
    import ssl

    token = os.environ.get("MAX_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MAX bot token is missing")
    context = ssl.create_default_context(cafile=str(Path(__file__).with_name("max-root-ca.pem")))
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(
        "https://platform-api2.max.ru/uploads?type=image", method="POST",
        headers={"Authorization": token, "Accept": "application/json"})
    try:
        with opener.open(request, timeout=45) as response:
            upload = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        raise RuntimeError("MAX upload URL request failed") from None
    upload_url = upload.get("url")
    if not upload_url:
        raise RuntimeError("MAX did not return a media upload URL")

    boundary = "----proastrologi-max-rating-boundary"
    photo = Path(path)
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; filename=\"{photo.name}\"\r\nContent-Type: image/jpeg\r\n\r\n".encode(),
        photo.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        upload_url, data=body,
        headers={"Authorization": token, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    try:
        with opener.open(request, timeout=90) as response:
            result = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        raise RuntimeError("MAX image upload failed") from None
    # Image upload responses place the reusable media token in a nested photos map.
    uploaded = result.get("photos") or {}
    token_record = uploaded.get("0") or uploaded.get("photoIds") or {}
    confirmed_token = token_record.get("token")
    if not confirmed_token:
        raise RuntimeError("MAX image upload was not confirmed")
    time.sleep(3)  # MAX processes images asynchronously before they can be attached.
    return confirmed_token


def verify_destinations():
    me = telegram_request("getMe", {})
    if not me.get("ok") or not (me.get("result") or {}).get("id"):
        raise RuntimeError("Telegram bot identity could not be verified")
    tg_member = telegram_request("getChatMember", {
        "chat_id": TG_CHANNEL, "user_id": me["result"]["id"]})
    member = tg_member.get("result") or {}
    if not tg_member.get("ok") or member.get("status") not in ("creator", "administrator"):
        raise RuntimeError("Telegram bot cannot publish in @proastrologi")
    if member.get("status") == "administrator" and not member.get("can_post_messages", False):
        raise RuntimeError("Telegram bot has no post permission in @proastrologi")

    max_me = max_request("/me")
    if max_me.get("username") != MAX_BOT_USERNAME:
        raise RuntimeError("MAX bot identity did not match the existing horoscope bot")
    max_member = max_request(f"/chats/{MAX_CHANNEL_ID}/members/me")
    permissions = set(max_member.get("permissions") or [])
    if not max_member.get("is_admin") or not ({"write", "post_edit_delete_message"} & permissions):
        raise RuntimeError("MAX bot cannot publish in the existing horoscope channel")


def release_url(number):
    return (f"https://github.com/{REPOSITORY}/releases/download/{RELEASE_TAG}/"
            f"rating-{number:03d}.jpg")


def main():
    state, sha = read_remote_state()
    if state.get("_sha"):
        sha = state.pop("_sha")
    status = state.get("status", "ready")
    if status != "ready":
        raise RuntimeError("Previous post has an uncertain result; inspect both channels before resuming")
    number = state.get("next_number", 2)
    if number > 365:
        print("All 365 rating cards have been published.")
        return

    today = datetime.now(MOSCOW).date().isoformat()
    if state.get("last_post_date") == today:
        print("A rating was already published today; duplicate dispatch skipped.")
        return

    verify_destinations()
    image_path = Path(".rating-assets") / f"rating-{number:03d}.jpg"
    if not image_path.is_file():
        raise RuntimeError(f"Rating image is missing from the restored asset bundle: {image_path.name}")
    state.update({"status": "pending", "pending_number": number,
                  "pending_date": today, "pending_file": image_path.name})
    sha = save_remote_state(state, sha)

    tg = telegram_photo(image_path)
    if not tg.get("ok") or not (tg.get("result") or {}).get("message_id"):
        raise RuntimeError("Telegram did not confirm the photo post; cursor remains pending")
    state["telegram_message_id"] = tg["result"]["message_id"]
    state["status"] = "telegram_sent"
    sha = save_remote_state(state, sha)

    media_token = max_upload_image(image_path)
    result = max_request(f"/messages?chat_id={MAX_CHANNEL_ID}", {
        "attachments": [{"type": "image", "payload": {"token": media_token}}]})
    message = result.get("message") or {}
    mid = ((message.get("body") or {}).get("mid"))
    if not mid or (message.get("recipient") or {}).get("chat_id") != MAX_CHANNEL_ID:
        raise RuntimeError("MAX did not confirm the image post; cursor remains pending")

    state = {"next_number": number + 1, "status": "ready", "last_post_date": today,
             "last_number": number, "telegram_message_id": tg["result"]["message_id"],
             "max_message_id": mid}
    save_remote_state(state, sha)
    print(f"Rating {number:03d} posted to Telegram and MAX.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Rating publication stopped: {exc}", file=sys.stderr)
        sys.exit(1)
