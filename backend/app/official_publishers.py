import json
import urllib.request
import urllib.parse

def request_json(url, method="GET", headers=None, data=None):
    body = None
    if data is not None:
        body = json.dumps(data).encode()

    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=headers or {}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else {}
    except Exception as e:
        return 0, {"error": str(e)}

class TelegramPublisher:
    platform = "telegram"

    def publish(self, account, content, media=None):
        token = account.get("access_token")
        chat_id = account.get("platform_user_id")

        if not token or not chat_id:
            return {
                "ok": False,
                "platform": "telegram",
                "error": "missing_bot_token_or_chat_id"
            }

        url = f"https://api.telegram.org/bot{token}/sendMessage"

        status, result = request_json(
            url,
            "POST",
            {"Content-Type": "application/json"},
            {
                "chat_id": chat_id,
                "text": content
            }
        )

        return {
            "ok": status == 200 and result.get("ok") is True,
            "platform": "telegram",
            "response": result
        }

class WordPressPublisher:
    platform = "wordpress"

    def publish(self, account, content, media=None):
        base = (account.get("base_url") or "").rstrip("/")
        username = account.get("username")
        app_password = account.get("app_password")

        if not base or not username or not app_password:
            return {
                "ok": False,
                "platform": "wordpress",
                "error": "missing_wordpress_credentials"
            }

        import base64
        auth = base64.b64encode(
            f"{username}:{app_password}".encode()
        ).decode()

        status, result = request_json(
            base + "/wp-json/wp/v2/posts",
            "POST",
            {
                "Content-Type": "application/json",
                "Authorization": "Basic " + auth
            },
            {
                "title": content[:80],
                "content": content,
                "status": "publish"
            }
        )

        return {
            "ok": status in (200, 201),
            "platform": "wordpress",
            "response": result
        }

class WebhookPublisher:
    platform = "website"

    def publish(self, account, content, media=None):
        url = account.get("webhook_url")

        if not url:
            return {
                "ok": False,
                "platform": "website",
                "error": "missing_webhook_url"
            }

        status, result = request_json(
            url,
            "POST",
            {"Content-Type": "application/json"},
            {
                "content": content,
                "media": media
            }
        )

        return {
            "ok": 200 <= status < 300,
            "platform": "website",
            "response": result
        }

OFFICIAL_PUBLISHERS = {
    "telegram": TelegramPublisher(),
    "wordpress": WordPressPublisher(),
    "website": WebhookPublisher()
}

print("OFFICIAL PUBLISHERS LOADED")
