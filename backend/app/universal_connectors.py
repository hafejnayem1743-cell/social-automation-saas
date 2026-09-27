import os, json, urllib.request, urllib.parse

PLATFORMS = {
    "facebook": {
        "type": "meta",
        "enabled": bool(os.getenv("META_CLIENT_ID")),
        "oauth": True
    },
    "instagram": {
        "type": "meta",
        "enabled": bool(os.getenv("META_CLIENT_ID")),
        "oauth": True
    },
    "telegram": {
        "type": "telegram",
        "enabled": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "oauth": False
    },
    "x": {
        "type": "x",
        "enabled": bool(os.getenv("X_CLIENT_ID")),
        "oauth": True
    },
    "linkedin": {
        "type": "linkedin",
        "enabled": bool(os.getenv("LINKEDIN_CLIENT_ID")),
        "oauth": True
    },
    "youtube": {
        "type": "google",
        "enabled": bool(os.getenv("GOOGLE_CLIENT_ID")),
        "oauth": True
    },
    "tiktok": {
        "type": "tiktok",
        "enabled": bool(os.getenv("TIKTOK_CLIENT_KEY")),
        "oauth": True
    },
    "pinterest": {
        "type": "pinterest",
        "enabled": bool(os.getenv("PINTEREST_APP_ID")),
        "oauth": True
    },
    "reddit": {
        "type": "reddit",
        "enabled": bool(os.getenv("REDDIT_CLIENT_ID")),
        "oauth": True
    },
    "discord": {
        "type": "discord",
        "enabled": bool(os.getenv("DISCORD_CLIENT_ID")),
        "oauth": True
    },
    "threads": {
        "type": "meta_threads",
        "enabled": bool(os.getenv("THREADS_CLIENT_ID")),
        "oauth": True
    },
    "wordpress": {
        "type": "wordpress",
        "enabled": bool(os.getenv("WORDPRESS_URL")),
        "oauth": False
    },
    "website": {
        "type": "webhook",
        "enabled": bool(os.getenv("WEBSITE_WEBHOOK_URL")),
        "oauth": False
    }
}

def platform_status():
    return {
        name: {
            "type": cfg["type"],
            "oauth": cfg["oauth"],
            "configured": cfg["enabled"]
        }
        for name, cfg in PLATFORMS.items()
    }

def get_platform(name):
    return PLATFORMS.get(name)

class Connector:
    platform = "unknown"

    def publish(self, token, content, media_url=None):
        raise NotImplementedError

class GenericOfficialConnector(Connector):
    def __init__(self, platform):
        self.platform = platform

    def publish(self, token, content, media_url=None):
        if not token:
            return {
                "ok": False,
                "platform": self.platform,
                "error": "missing_access_token"
            }
        return {
            "ok": False,
            "platform": self.platform,
            "error": "official_connector_requires_platform_api_adapter"
        }

CONNECTOR_REGISTRY = {
    platform: GenericOfficialConnector(platform)
    for platform in PLATFORMS
}
