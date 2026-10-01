import time
from dataclasses import dataclass

@dataclass
class PublishResult:
    ok: bool
    platform: str
    external_id: str | None = None
    error: str | None = None
    retryable: bool = False

class BasePublisher:
    platform = "unknown"

    def publish(self, account, content, media=None):
        raise NotImplementedError

class OfficialPublisher(BasePublisher):
    def __init__(self, platform):
        self.platform = platform

    def publish(self, account, content, media=None):
        token = account.get("access_token")
        if not token:
            return PublishResult(
                False, self.platform,
                error="missing_access_token",
                retryable=False
            )

        # Real platform API implementation is attached per platform.
        return PublishResult(
            False, self.platform,
            error="platform_api_not_configured",
            retryable=False
        )

PUBLISHERS = {
    name: OfficialPublisher(name)
    for name in (
        "facebook",
        "instagram",
        "telegram",
        "x",
        "linkedin",
        "youtube",
        "tiktok",
        "pinterest",
        "reddit",
        "discord",
        "threads",
        "wordpress",
        "website"
    )
}

def get_publisher(platform):
    return PUBLISHERS.get(platform)

def publish(platform, account, content, media=None):
    publisher = get_publisher(platform)

    if not publisher:
        return PublishResult(
            False, platform,
            error="unsupported_platform",
            retryable=False
        )

    return publisher.publish(account, content, media)

try:
    from app.official_publishers import OFFICIAL_PUBLISHERS
except ModuleNotFoundError:
    from official_publishers import OFFICIAL_PUBLISHERS

PUBLISHERS.update(OFFICIAL_PUBLISHERS)
print("OFFICIAL PUBLISHERS CONNECTED")
