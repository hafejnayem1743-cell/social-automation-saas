import base64
import json
import os
import urllib.parse
import urllib.request
import uuid


def request_json(url, method="GET", headers=None, data=None, form=False):
    payload = None
    final_headers = dict(headers or {})

    if data is not None:
        if form:
            payload = urllib.parse.urlencode(data).encode()
            final_headers.setdefault(
                "Content-Type",
                "application/x-www-form-urlencoded"
            )
        else:
            payload = json.dumps(data).encode()
            final_headers.setdefault(
                "Content-Type",
                "application/json"
            )

    req = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers=final_headers
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode(errors="replace")
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = {"raw": raw}
            return r.status, body
    except Exception as e:
        return 0, {"error": str(e)}


def parse_data_uri(value):
    if not value or not isinstance(value, str):
        return None, None

    if not value.startswith("data:"):
        return None, None

    try:
        head, payload = value.split(",", 1)
        mime = head[5:].split(";", 1)[0]

        if ";base64" not in head:
            return None, None

        return mime, base64.b64decode(payload)
    except Exception:
        return None, None


def public_media_url(account):
    return (
        account.get("media_url")
        or account.get("public_media_url")
        or os.getenv("PUBLIC_MEDIA_BASE_URL")
    )


def ok(platform, external_id=None, response=None):
    return {
        "ok": True,
        "platform": platform,
        "external_id": external_id,
        "response": response or {}
    }


def fail(platform, error, response=None, retryable=False):
    return {
        "ok": False,
        "platform": platform,
        "error": error,
        "response": response or {},
        "retryable": retryable
    }


class FacebookPublisher:
    platform = "facebook"

    def publish(self, account, content, media=None):
        token = account.get("access_token")
        target = (
            account.get("platform_target_id")
            or account.get("target_input")
            or account.get("platform_user_id")
        )
        action = account.get("action", "publish")

        if not token:
            return fail("facebook", "missing_access_token")
        if not target:
            return fail("facebook", "missing_page_or_target_id")

        graph_version = os.getenv("META_GRAPH_VERSION", "v23.0")

        if action == "publish":
            media_url = public_media_url(account)

            if media_url:
                url = f"https://graph.facebook.com/{graph_version}/{target}/photos"
                status, result = request_json(
                    url,
                    "POST",
                    data={
                        "url": media_url,
                        "caption": content or "",
                        "access_token": token
                    },
                    form=True
                )
            else:
                url = f"https://graph.facebook.com/{graph_version}/{target}/feed"
                status, result = request_json(
                    url,
                    "POST",
                    data={
                        "message": content or "",
                        "access_token": token
                    },
                    form=True
                )

        elif action in ("comment", "reply"):
            url = f"https://graph.facebook.com/{graph_version}/{target}/comments"
            status, result = request_json(
                url,
                "POST",
                data={
                    "message": content or "",
                    "access_token": token
                },
                form=True
            )
        else:
            return fail("facebook", "unsupported_action")

        if 200 <= status < 300 and result.get("id"):
            return ok("facebook", result.get("id"), result)

        return fail("facebook", "api_request_failed", result, status in (429, 500, 502, 503, 504))


class InstagramPublisher:
    platform = "instagram"

    def publish(self, account, content, media=None):
        token = account.get("access_token")
        ig_user = (
            account.get("platform_target_id")
            or account.get("platform_user_id")
        )

        if not token:
            return fail("instagram", "missing_access_token")
        if not ig_user:
            return fail("instagram", "missing_instagram_user_id")

        version = os.getenv("META_GRAPH_VERSION", "v23.0")
        action = account.get("action", "publish")
        media_url = public_media_url(account)

        if action == "publish":
            if not media_url:
                return fail(
                    "instagram",
                    "instagram_publish_requires_public_media_url"
                )

            create_url = f"https://graph.facebook.com/{version}/{ig_user}/media"
            status, container = request_json(
                create_url,
                "POST",
                data={
                    "image_url": media_url,
                    "caption": content or "",
                    "access_token": token
                },
                form=True
            )

            creation_id = container.get("id")
            if not creation_id:
                return fail("instagram", "container_creation_failed", container)

            publish_url = f"https://graph.facebook.com/{version}/{ig_user}/media_publish"
            status2, result = request_json(
                publish_url,
                "POST",
                data={
                    "creation_id": creation_id,
                    "access_token": token
                },
                form=True
            )

            if 200 <= status2 < 300 and result.get("id"):
                return ok("instagram", result.get("id"), result)

            return fail(
                "instagram",
                "media_publish_failed",
                result,
                status2 in (429, 500, 502, 503, 504)
            )

        if action == "comment":
            target = account.get("platform_target_id")
            if not target:
                return fail("instagram", "missing_media_id")

            url = f"https://graph.facebook.com/{version}/{target}/comments"
            status, result = request_json(
                url,
                "POST",
                data={
                    "message": content or "",
                    "access_token": token
                },
                form=True
            )

            if 200 <= status < 300 and result.get("id"):
                return ok("instagram", result.get("id"), result)

            return fail("instagram", "comment_failed", result, status == 429)

        if action == "reply":
            target = account.get("platform_target_id")
            if not target:
                return fail("instagram", "missing_comment_id")

            url = f"https://graph.facebook.com/{version}/{target}/replies"
            status, result = request_json(
                url,
                "POST",
                data={
                    "message": content or "",
                    "access_token": token
                },
                form=True
            )

            if 200 <= status < 300 and result.get("id"):
                return ok("instagram", result.get("id"), result)

            return fail("instagram", "reply_failed", result, status == 429)

        return fail("instagram", "unsupported_action")


class TelegramPublisher:
    platform = "telegram"

    def publish(self, account, content, media=None):
        token = account.get("access_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = (
            account.get("platform_target_id")
            or account.get("target_input")
            or account.get("platform_user_id")
        )

        if not token:
            return fail("telegram", "telegram_bot_token_not_configured")
        if not chat_id:
            return fail("telegram", "missing_chat_id_or_channel")

        action = account.get("action", "publish")
        base = f"https://api.telegram.org/bot{token}/"

        reply_to = account.get("reply_to_message_id")

        if media and str(media).startswith("data:image/"):
            mime, raw = parse_data_uri(media)

            if raw:
                boundary = "----NBSA-" + uuid.uuid4().hex
                parts = []

                def add_field(name, value):
                    parts.append(
                        (
                            f'--{boundary}\r\n'
                            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                            f'{value}\r\n'
                        ).encode()
                    )

                add_field("chat_id", chat_id)
                add_field("caption", content or "")

                if reply_to:
                    add_field(
                        "reply_parameters",
                        json.dumps({"message_id": int(reply_to)})
                    )

                parts.append(
                    (
                        f'--{boundary}\r\n'
                        f'Content-Disposition: form-data; name="photo"; '
                        f'filename="nbsa.jpg"\r\n'
                        f'Content-Type: {mime or "image/jpeg"}\r\n\r\n'
                    ).encode()
                )
                parts.append(raw)
                parts.append(f"\r\n--{boundary}--\r\n".encode())

                payload = b"".join(parts)

                req = urllib.request.Request(
                    base + "sendPhoto",
                    data=payload,
                    method="POST",
                    headers={
                        "Content-Type": f"multipart/form-data; boundary={boundary}"
                    }
                )

                try:
                    with urllib.request.urlopen(req, timeout=45) as r:
                        result=json.loads(
                            r.read().decode(errors="replace")
                        )
                        status=r.status
                except Exception as e:
                    return fail("telegram", str(e), retryable=True)

                if status == 200 and result.get("ok"):
                    msg=result.get("result") or {}
                    return ok(
                        "telegram",
                        str(msg.get("message_id")),
                        result
                    )

                return fail("telegram", "send_photo_failed", result)

        data={
            "chat_id": chat_id,
            "text": content or ""
        }

        if reply_to:
            data["reply_parameters"]={"message_id": int(reply_to)}

        status, result=request_json(
            base + "sendMessage",
            "POST",
            data=data
        )

        if status == 200 and result.get("ok"):
            msg=result.get("result") or {}
            return ok(
                "telegram",
                str(msg.get("message_id")),
                result
            )

        return fail(
            "telegram",
            "send_message_failed",
            result,
            status in (429,500,502,503,504)
        )


class XPublisher:
    platform = "x"

    def publish(self, account, content, media=None):
        token=account.get("access_token")
        target=account.get("platform_target_id")
        action=account.get("action","publish")

        if not token:
            return fail("x","missing_access_token")

        data={"text":content or ""}

        if action in ("comment","reply"):
            if not target:
                return fail("x","missing_post_id")
            data["reply"]={"in_reply_to_tweet_id":str(target)}

        status,result=request_json(
            "https://api.x.com/2/tweets",
            "POST",
            {"Authorization":"Bearer "+token},
            data
        )

        tweet_id=(result.get("data") or {}).get("id")

        if 200 <= status < 300 and tweet_id:
            return ok("x",tweet_id,result)

        return fail(
            "x",
            "x_api_request_failed",
            result,
            status in (429,500,502,503,504)
        )


class YouTubePublisher:
    platform = "youtube"

    def publish(self, account, content, media=None):
        token=account.get("access_token")
        action=account.get("action","publish")

        if not token:
            return fail("youtube","missing_access_token")

        if action in ("comment","reply"):
            video_id=account.get("platform_target_id")

            if not video_id:
                return fail("youtube","missing_video_id")

            body={
                "snippet":{
                    "videoId":str(video_id),
                    "topLevelComment":{
                        "snippet":{
                            "textOriginal":content or ""
                        }
                    }
                }
            }

            status,result=request_json(
                "https://www.googleapis.com/youtube/v3/commentThreads"
                "?part=snippet",
                "POST",
                {"Authorization":"Bearer "+token},
                body
            )

            item=(result.get("snippet") or {}).get("topLevelComment") or {}
            external_id=item.get("id")

            if 200 <= status < 300 and external_id:
                return ok("youtube",external_id,result)

            return fail("youtube","youtube_comment_failed",result,status==429)

        # YouTube Data API video publishing needs actual video bytes.
        if not media or not str(media).startswith("data:video/"):
            return fail(
                "youtube",
                "youtube_publish_requires_video_media"
            )

        return fail(
            "youtube",
            "youtube_video_upload_adapter_requires_multipart_media"
        )


class TikTokPublisher:
    platform = "tiktok"

    def publish(self, account, content, media=None):
        token=account.get("access_token")
        action=account.get("action","publish")

        if not token:
            return fail("tiktok","missing_access_token")

        if action != "publish":
            return fail(
                "tiktok",
                "tiktok_comment_reply_not_supported_by_this_adapter"
            )

        media_url=public_media_url(account)

        if not media_url:
            return fail(
                "tiktok",
                "tiktok_photo_publish_requires_public_verified_media_url"
            )

        creator_status,creator=request_json(
            "https://open.tiktokapis.com/v2/post/publish/"
            "creator_info/query/",
            "POST",
            {
                "Authorization":"Bearer "+token,
                "Content-Type":"application/json; charset=UTF-8"
            },
            {}
        )

        if creator_status != 200:
            return fail("tiktok","creator_info_failed",creator)

        options=(creator.get("data") or {}).get(
            "privacy_level_options"
        ) or []

        privacy=account.get("privacy_level")

        if privacy not in options:
            privacy="PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else (
                options[0] if options else None
            )

        if not privacy:
            return fail("tiktok","no_valid_privacy_option")

        body={
            "post_info":{
                "title":(content or "")[:90],
                "description":content or "",
                "privacy_level":privacy,
                "disable_comment":False,
                "auto_add_music":False
            },
            "source_info":{
                "source":"PULL_FROM_URL",
                "photo_cover_index":0,
                "photo_images":[media_url]
            },
            "post_mode":"DIRECT_POST",
            "media_type":"PHOTO"
        }

        status,result=request_json(
            "https://open.tiktokapis.com/v2/post/publish/content/init/",
            "POST",
            {
                "Authorization":"Bearer "+token,
                "Content-Type":"application/json"
            },
            body
        )

        publish_id=(result.get("data") or {}).get("publish_id")

        if status == 200 and publish_id:
            return ok("tiktok",publish_id,result)

        return fail(
            "tiktok",
            "tiktok_publish_failed",
            result,
            status in (429,500,502,503,504)
        )


class PinterestPublisher:
    platform = "pinterest"

    def publish(self, account, content, media=None):
        token=account.get("access_token")
        board_id=(
            account.get("platform_target_id")
            or account.get("target_input")
        )

        if not token:
            return fail("pinterest","missing_access_token")
        if not board_id:
            return fail("pinterest","missing_board_id")

        media_url=public_media_url(account)

        if not media_url:
            return fail(
                "pinterest",
                "pinterest_pin_requires_public_media_url"
            )

        body={
            "board_id":str(board_id),
            "description":content or "",
            "media_source":{
                "source_type":"image_url",
                "url":media_url
            }
        }

        status,result=request_json(
            "https://api.pinterest.com/v5/pins",
            "POST",
            {"Authorization":"Bearer "+token},
            body
        )

        pin_id=result.get("id")

        if status == 201 and pin_id:
            return ok("pinterest",pin_id,result)

        return fail(
            "pinterest",
            "pinterest_create_pin_failed",
            result,
            status in (429,500,502,503,504)
        )


class RedditPublisher:
    platform = "reddit"

    def publish(self, account, content, media=None):
        token=account.get("access_token")
        action=account.get("action","publish")
        target=(
            account.get("platform_target_id")
            or account.get("target_input")
        )

        if not token:
            return fail("reddit","missing_access_token")
        if not target:
            return fail("reddit","missing_subreddit_or_parent_id")

        headers={
            "Authorization":"Bearer "+token,
            "User-Agent":os.getenv(
                "REDDIT_USER_AGENT",
                "NAYEM-BOSS-SOCIAL-AUTOMATION/1.0"
            )
        }

        if action == "publish":
            subreddit=str(target).replace("r/","").lstrip("/")
            body={
                "sr":subreddit,
                "kind":"self",
                "title":(content or "")[:300],
                "text":content or "",
                "api_type":"json"
            }

            status,result=request_json(
                "https://oauth.reddit.com/api/submit",
                "POST",
                headers,
                body,
                form=True
            )

        else:
            body={
                "api_type":"json",
                "thing_id":str(target),
                "text":content or ""
            }

            status,result=request_json(
                "https://oauth.reddit.com/api/comment",
                "POST",
                headers,
                body,
                form=True
            )

        errors=result.get("json",{}).get("errors") or []

        if 200 <= status < 300 and not errors:
            data=result.get("json",{}).get("data",{})
            external_id=data.get("id") or data.get("name")
            return ok("reddit",external_id,result)

        return fail(
            "reddit",
            "reddit_api_request_failed",
            result,
            status in (429,500,502,503,504)
        )


OFFICIAL_PUBLISHERS={
    "facebook":FacebookPublisher(),
    "instagram":InstagramPublisher(),
    "telegram":TelegramPublisher(),
    "x":XPublisher(),
    "youtube":YouTubePublisher(),
    "tiktok":TikTokPublisher(),
    "pinterest":PinterestPublisher(),
    "reddit":RedditPublisher()
}

print("REAL 8-PLATFORM OFFICIAL PUBLISHERS LOADED")
