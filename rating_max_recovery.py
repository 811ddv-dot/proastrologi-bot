"""Send the already-confirmed Telegram rating to MAX only."""
import base64, json, os, ssl, sys, time, urllib.error, urllib.request
from pathlib import Path

REPO = "811ddv-dot/proastrologi-bot"
STATE_URL = f"https://api.github.com/repos/{REPO}/contents/rating-state.json?ref=main"
STATE_PUT = f"https://api.github.com/repos/{REPO}/contents/rating-state.json"
CHANNEL = -79305594853965
BOT_USERNAME = "id400406889818_bot"


def github_headers():
    token = os.environ.get("RATING_HISTORY_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing GitHub Actions token")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def json_request(url, method="GET", payload=None, headers=None, opener=None, timeout=45):
    head = {"Accept": "application/json", "Content-Type": "application/json"}
    if headers:
        head.update(headers)
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers=head, method=method)
    client = opener or urllib.request.build_opener()
    try:
        with client.open(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while contacting a service") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network/TLS error ({type(exc.reason).__name__})") from None
    except TimeoutError:
        raise RuntimeError("Request timed out") from None


def save_state(state, sha):
    content = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()
    payload = {"message": f"Recover zodiac rating {state.get('pending_number')} in MAX",
               "branch": "main", "content": base64.b64encode(content).decode(), "sha": sha}
    result = json_request(STATE_PUT, "PUT", payload, github_headers())
    new_sha = (result.get("content") or {}).get("sha")
    if not new_sha:
        raise RuntimeError("GitHub did not confirm rating state update")
    return new_sha


def main():
    remote = json_request(STATE_URL, headers=github_headers())
    state = json.loads(base64.b64decode(remote["content"]).decode())
    if (state.get("status") != "telegram_sent" or state.get("pending_number") != 2
            or state.get("pending_file") != "rating-002.jpg" or not state.get("telegram_message_id")):
        raise RuntimeError("Recovery guard failed: expected confirmed Telegram post for rating 002")
    sha = remote["sha"]
    image = Path(".rating-assets/rating-002.jpg")
    if not image.is_file():
        raise RuntimeError("rating-002.jpg missing")

    ca = Path("max-root-ca.pem")
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(ca))
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    token = os.environ.get("MAX_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MAX token missing")
    headers = {"Authorization": token, "Accept": "application/json"}
    me = json_request("https://platform-api2.max.ru/me", headers=headers, opener=opener)
    if me.get("username") != BOT_USERNAME:
        raise RuntimeError("Unexpected MAX bot identity")
    member = json_request(f"https://platform-api2.max.ru/chats/{CHANNEL}/members/me", headers=headers, opener=opener)
    if not member.get("is_admin") or not ({"write", "post_edit_delete_message"} & set(member.get("permissions") or [])):
        raise RuntimeError("MAX bot lacks channel posting permission")

    upload = json_request("https://platform-api2.max.ru/uploads?type=image", "POST", headers=headers, opener=opener)
    upload_url = upload.get("url")
    if not upload_url:
        raise RuntimeError("MAX returned no upload URL")
    boundary = "----proastrologi-rating-max-recovery"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; filename=\"{image.name}\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + image.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(upload_url, data=body, method="POST", headers={
        **headers, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with opener.open(request, timeout=90) as response:
            media = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"MAX media host rejected upload (HTTP {exc.code})") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MAX media host network/TLS error ({type(exc.reason).__name__})") from None
    photo_map = (media.get("photos") or {}).get("photoIds") or {}
    media_token = photo_map.get("token") or media.get("token")
    if not media_token:
        print("MAX photos keys:", sorted(media["photos"].keys()), "photoIds type:", type(media["photos"].get("photoIds")).__name__, "photoIds keys:", sorted(media["photos"]["photoIds"].keys()) if isinstance(media["photos"].get("photoIds"), dict) else "not-dict"); raise RuntimeError("MAX media host did not confirm image upload")
    time.sleep(5)

    state["status"] = "max_pending"
    sha = save_state(state, sha)
    result = json_request(f"https://platform-api2.max.ru/messages?chat_id={CHANNEL}", "POST",
        {"attachments": [{"type": "image", "payload": {"token": media_token}}]}, headers, opener)
    message = result.get("message") or {}
    mid = (message.get("body") or {}).get("mid")
    if not mid or (message.get("recipient") or {}).get("chat_id") != CHANNEL:
        raise RuntimeError("MAX did not confirm the post; state remains max_pending")
    next_state = {"next_number": 3, "status": "ready", "last_post_date": state["pending_date"],
                  "last_number": 2, "telegram_message_id": state["telegram_message_id"], "max_message_id": mid}
    save_state(next_state, sha)
    print("Rating 002 posted to MAX only. Telegram was not contacted.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"MAX-only recovery stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
