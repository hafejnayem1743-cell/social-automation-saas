import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta


PLATFORMS = (
    "facebook",
    "instagram",
    "telegram",
    "x",
    "youtube",
    "tiktok",
    "pinterest",
    "reddit",
)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_env():
    path=os.path.join(os.path.dirname(__file__),"..",".env")
    path=os.path.abspath(path)

    if not os.path.exists(path):
        return

    try:
        for line in open(path,"r",encoding="utf-8"):
            line=line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k,v=line.split("=",1)
            k=k.strip()
            v=v.strip().strip('"').strip("'")
            if k and v:
                os.environ.setdefault(k,v)
    except Exception:
        pass


_load_env()


def env(name,default=""):
    return os.getenv(name,default)


def ensure_oauth_schema(c):
    c.execute("""
    CREATE TABLE IF NOT EXISTS oauth_states(
        state TEXT PRIMARY KEY,
        tenant_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        code_verifier TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """)
    c.commit()


def provider_info():
    meta=bool(env("META_CLIENT_ID") and env("META_CLIENT_SECRET"))
    return {
        "facebook":{
            "oauth":True,
            "configured":meta,
            "env":"META_CLIENT_ID / META_CLIENT_SECRET",
        },
        "instagram":{
            "oauth":True,
            "configured":meta,
            "env":"META_CLIENT_ID / META_CLIENT_SECRET",
        },
        "telegram":{
            "oauth":False,
            "configured":bool(env("TELEGRAM_BOT_TOKEN")),
            "env":"TELEGRAM_BOT_TOKEN",
        },
        "x":{
            "oauth":True,
            "configured":bool(env("X_CLIENT_ID") and env("X_CLIENT_SECRET")),
            "env":"X_CLIENT_ID / X_CLIENT_SECRET",
        },
        "youtube":{
            "oauth":True,
            "configured":bool(env("GOOGLE_CLIENT_ID") and env("GOOGLE_CLIENT_SECRET")),
            "env":"GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET",
        },
        "tiktok":{
            "oauth":True,
            "configured":bool(env("TIKTOK_CLIENT_KEY") and env("TIKTOK_CLIENT_SECRET")),
            "env":"TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET",
        },
        "pinterest":{
            "oauth":True,
            "configured":bool(env("PINTEREST_APP_ID") and env("PINTEREST_APP_SECRET")),
            "env":"PINTEREST_APP_ID / PINTEREST_APP_SECRET",
        },
        "reddit":{
            "oauth":True,
            "configured":bool(env("REDDIT_CLIENT_ID") and env("REDDIT_CLIENT_SECRET")),
            "env":"REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET",
        },
    }


def redirect_uri(platform):
    configured=env(f"{platform.upper()}_REDIRECT_URI")

    if platform=="facebook" or platform=="instagram":
        configured=env("META_REDIRECT_URI") or configured

    if configured:
        return configured

    base=env("NBSA_PUBLIC_API_URL","http://127.0.0.1:8000").rstrip("/")
    return f"{base}/oauth/callback/{platform}"


def _pkce_verifier():
    return secrets.token_urlsafe(64)


def _pkce_challenge(verifier):
    digest=hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def create_oauth_start(c,user,platform):
    _load_env()
    ensure_oauth_schema(c)

    if platform not in PLATFORMS or platform=="telegram":
        return None, "oauth_not_available_for_platform"

    info=provider_info().get(platform)
    if not info or not info["configured"]:
        return None, "platform_app_credentials_not_configured"

    state=secrets.token_urlsafe(40)
    verifier=None

    if platform=="x":
        verifier=_pkce_verifier()

    expires=(datetime.now()+timedelta(minutes=10)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    c.execute(
        """
        INSERT INTO oauth_states
        (state,tenant_id,user_id,platform,code_verifier,created_at,expires_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            state,
            user["tenant_id"],
            user["id"],
            platform,
            verifier,
            _now(),
            expires
        )
    )
    c.commit()

    uri=redirect_uri(platform)

    if platform in ("facebook","instagram"):
        graph_version=env("META_GRAPH_VERSION","v23.0")

        scopes=(
            "pages_show_list,"
            "pages_read_engagement,"
            "pages_manage_posts,"
            "instagram_basic,"
            "instagram_content_publish"
        )

        url=(
            f"https://www.facebook.com/{graph_version}/dialog/oauth?"
            +urllib.parse.urlencode({
                "client_id":env("META_CLIENT_ID"),
                "redirect_uri":uri,
                "state":state,
                "scope":scopes,
                "response_type":"code"
            })
        )

    elif platform=="x":
        scopes="tweet.read tweet.write users.read offline.access"

        url=(
            "https://twitter.com/i/oauth2/authorize?"
            +urllib.parse.urlencode({
                "response_type":"code",
                "client_id":env("X_CLIENT_ID"),
                "redirect_uri":uri,
                "scope":scopes,
                "state":state,
                "code_challenge":_pkce_challenge(verifier),
                "code_challenge_method":"S256"
            })
        )

    elif platform=="youtube":
        scopes=(
            "https://www.googleapis.com/auth/youtube.upload "
            "https://www.googleapis.com/auth/youtube.force-ssl"
        )

        url=(
            "https://accounts.google.com/o/oauth2/v2/auth?"
            +urllib.parse.urlencode({
                "client_id":env("GOOGLE_CLIENT_ID"),
                "redirect_uri":uri,
                "response_type":"code",
                "scope":scopes,
                "access_type":"offline",
                "include_granted_scopes":"true",
                "prompt":"consent",
                "state":state
            })
        )

    elif platform=="tiktok":
        scopes="user.info.basic,video.publish"

        url=(
            "https://www.tiktok.com/v2/auth/authorize/?"
            +urllib.parse.urlencode({
                "client_key":env("TIKTOK_CLIENT_KEY"),
                "response_type":"code",
                "scope":scopes,
                "redirect_uri":uri,
                "state":state
            })
        )

    elif platform=="pinterest":
        scopes="user_accounts:read,boards:read,boards:write,pins:read,pins:write"

        url=(
            "https://www.pinterest.com/oauth/?"
            +urllib.parse.urlencode({
                "client_id":env("PINTEREST_APP_ID"),
                "redirect_uri":uri,
                "response_type":"code",
                "scope":scopes,
                "state":state
            })
        )

    elif platform=="reddit":
        scopes="identity read submit comment"

        url=(
            "https://www.reddit.com/api/v1/authorize?"
            +urllib.parse.urlencode({
                "client_id":env("REDDIT_CLIENT_ID"),
                "response_type":"code",
                "state":state,
                "redirect_uri":uri,
                "duration":"permanent",
                "scope":scopes
            })
        )

    else:
        return None,"unsupported_platform"

    return url,None


def _request(url,method="GET",headers=None,data=None,form=False):
    h=dict(headers or {})
    payload=None

    if data is not None:
        if form:
            payload=urllib.parse.urlencode(data).encode()
            h.setdefault(
                "Content-Type",
                "application/x-www-form-urlencoded"
            )
        else:
            payload=json.dumps(data).encode()
            h.setdefault("Content-Type","application/json")

    req=urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers=h
    )

    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read().decode(errors="replace")
            try:
                body=json.loads(raw) if raw else {}
            except Exception:
                body={"raw":raw}
            return r.status,body
    except Exception as e:
        return 0,{"error":str(e)}


def _save(c,user,platform,name,platform_user_id,access_token,
          refresh_token="",expires_at="",metadata=None):

    t=_now()

    old=c.execute(
        """
        SELECT id FROM oauth_connectors
        WHERE tenant_id=? AND platform=? AND platform_user_id=?
        """,
        (
            user["tenant_id"],
            platform,
            str(platform_user_id or "")
        )
    ).fetchone()

    if old:
        c.execute(
            """
            UPDATE oauth_connectors
            SET account_name=?,access_token=?,refresh_token=?,
                token_expires_at=?,status='connected',
                updated_at=?
            WHERE id=?
            """,
            (
                name,
                access_token,
                refresh_token or None,
                expires_at or None,
                t,
                old["id"]
            )
        )
        cid=old["id"]
    else:
        cur=c.execute(
            """
            INSERT INTO oauth_connectors
            (tenant_id,user_id,platform,account_name,platform_user_id,
             access_token,refresh_token,token_expires_at,webhook_url,
             status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                user["tenant_id"],
                user["id"],
                platform,
                name,
                str(platform_user_id or ""),
                access_token,
                refresh_token or None,
                expires_at or None,
                None,
                "connected",
                t,
                t
            )
        )
        cid=cur.lastrowid

    c.commit()
    return cid


def _meta_complete(c,user,code):
    version=env("META_GRAPH_VERSION","v23.0")
    uri=redirect_uri("facebook")

    status,tok=_request(
        f"https://graph.facebook.com/{version}/oauth/access_token",
        "GET",
        data={
            "client_id":env("META_CLIENT_ID"),
            "client_secret":env("META_CLIENT_SECRET"),
            "redirect_uri":uri,
            "code":code
        }
    )

    access=tok.get("access_token")
    if not access:
        return False,"meta_token_exchange_failed",tok,[]

    status,pages=_request(
        f"https://graph.facebook.com/{version}/me/accounts",
        "GET",
        data={
            "fields":"id,name,access_token,instagram_business_account",
            "access_token":access
        }
    )

    page_rows=pages.get("data") or []

    saved=[]

    for page in page_rows:
        page_id=page.get("id")
        page_name=page.get("name") or ("Facebook "+str(page_id))

        if page_id:
            cid=_save(
                c,user,"facebook",page_name,page_id,
                page.get("access_token") or access,
                metadata=page
            )
            saved.append(cid)

        if page.get("instagram_business_account"):
            ig=page["instagram_business_account"]
            ig_id=ig.get("id")

            if ig_id:
                cid=_save(
                    c,
                    user,
                    "instagram",
                    page_name+" · Instagram",
                    ig_id,
                    page.get("access_token") or access,
                    metadata=ig
                )
                saved.append(cid)

    if not saved:
        status,me=_request(
            f"https://graph.facebook.com/{version}/me",
            "GET",
            data={
                "fields":"id,name",
                "access_token":access
            }
        )

        if me.get("id"):
            cid=_save(
                c,user,"facebook",
                me.get("name") or "Facebook",
                me.get("id"),
                access
            )
            saved.append(cid)

    return True,"meta_connected",{},saved


def _x_complete(c,user,code,state_row):
    uri=redirect_uri("x")

    basic=base64.b64encode(
        (
            env("X_CLIENT_ID")+":"+env("X_CLIENT_SECRET")
        ).encode()
    ).decode()

    status,tok=_request(
        "https://api.x.com/2/oauth2/token",
        "POST",
        {
            "Authorization":"Basic "+basic
        },
        {
            "code":code,
            "grant_type":"authorization_code",
            "redirect_uri":uri,
            "code_verifier":state_row["code_verifier"]
        },
        form=True
    )

    access=tok.get("access_token")
    if not access:
        return False,"x_token_exchange_failed",tok,[]

    status,me=_request(
        "https://api.x.com/2/users/me",
        "GET",
        {"Authorization":"Bearer "+access}
    )

    user_data=me.get("data") or {}
    if not user_data.get("id"):
        return False,"x_identity_failed",me,[]

    cid=_save(
        c,
        user,
        "x",
        user_data.get("name") or "@"+user_data.get("username","X"),
        user_data.get("id"),
        access,
        tok.get("refresh_token"),
        metadata=user_data
    )

    return True,"x_connected",{},[cid]


def _google_complete(c,user,code):
    uri=redirect_uri("youtube")

    status,tok=_request(
        "https://oauth2.googleapis.com/token",
        "POST",
        None,
        {
            "code":code,
            "client_id":env("GOOGLE_CLIENT_ID"),
            "client_secret":env("GOOGLE_CLIENT_SECRET"),
            "redirect_uri":uri,
            "grant_type":"authorization_code"
        },
        form=True
    )

    access=tok.get("access_token")
    if not access:
        return False,"google_token_exchange_failed",tok,[]

    status,channels=_request(
        "https://www.googleapis.com/youtube/v3/channels",
        "GET",
        {
            "Authorization":"Bearer "+access
        },
        {
            "part":"snippet",
            "mine":"true"
        }
    )

    rows=channels.get("items") or []
    saved=[]

    for item in rows:
        cid_data=item.get("id")
        title=(
            item.get("snippet",{}).get("title")
            or "YouTube Channel"
        )

        if cid_data:
            cid=_save(
                c,
                user,
                "youtube",
                title,
                cid_data,
                access,
                tok.get("refresh_token"),
                metadata=item
            )
            saved.append(cid)

    if not saved:
        return False,"youtube_channel_not_found",channels,[]

    return True,"youtube_connected",{},saved


def _tiktok_complete(c,user,code):
    uri=redirect_uri("tiktok")

    status,tok=_request(
        "https://open.tiktokapis.com/v2/oauth/token/",
        "POST",
        None,
        {
            "client_key":env("TIKTOK_CLIENT_KEY"),
            "client_secret":env("TIKTOK_CLIENT_SECRET"),
            "code":code,
            "grant_type":"authorization_code",
            "redirect_uri":uri
        },
        form=True
    )

    access=tok.get("access_token")
    if not access:
        return False,"tiktok_token_exchange_failed",tok,[]

    status,me=_request(
        "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,username",
        "GET",
        {
            "Authorization":"Bearer "+access
        }
    )

    data=me.get("data",{}).get("user",{}) or {}

    open_id=data.get("open_id")
    if not open_id:
        return False,"tiktok_identity_failed",me,[]

    name=(
        data.get("display_name")
        or data.get("username")
        or "TikTok"
    )

    cid=_save(
        c,
        user,
        "tiktok",
        name,
        open_id,
        access,
        tok.get("refresh_token"),
        metadata=data
    )

    return True,"tiktok_connected",{},[cid]


def _pinterest_complete(c,user,code):
    uri=redirect_uri("pinterest")

    basic=base64.b64encode(
        (
            env("PINTEREST_APP_ID")+":"+env("PINTEREST_APP_SECRET")
        ).encode()
    ).decode()

    status,tok=_request(
        "https://api.pinterest.com/v5/oauth/token",
        "POST",
        {
            "Authorization":"Basic "+basic
        },
        {
            "grant_type":"authorization_code",
            "code":code,
            "redirect_uri":uri
        },
        form=True
    )

    access=tok.get("access_token")
    if not access:
        return False,"pinterest_token_exchange_failed",tok,[]

    status,me=_request(
        "https://api.pinterest.com/v5/user_account",
        "GET",
        {
            "Authorization":"Bearer "+access
        }
    )

    user_id=me.get("username") or me.get("account_type")
    name=me.get("username") or "Pinterest"

    if not user_id:
        return False,"pinterest_identity_failed",me,[]

    cid=_save(
        c,
        user,
        "pinterest",
        name,
        user_id,
        access,
        tok.get("refresh_token"),
        metadata=me
    )

    return True,"pinterest_connected",{},[cid]


def _reddit_complete(c,user,code):
    uri=redirect_uri("reddit")

    basic=base64.b64encode(
        (
            env("REDDIT_CLIENT_ID")+":"+env("REDDIT_CLIENT_SECRET")
        ).encode()
    ).decode()

    status,tok=_request(
        "https://www.reddit.com/api/v1/access_token",
        "POST",
        {
            "Authorization":"Basic "+basic,
            "User-Agent":env(
                "REDDIT_USER_AGENT",
                "NAYEM-BOSS-SOCIAL-AUTOMATION/1.0"
            )
        },
        {
            "grant_type":"authorization_code",
            "code":code,
            "redirect_uri":uri
        },
        form=True
    )

    access=tok.get("access_token")
    if not access:
        return False,"reddit_token_exchange_failed",tok,[]

    status,me=_request(
        "https://oauth.reddit.com/api/v1/me",
        "GET",
        {
            "Authorization":"Bearer "+access,
            "User-Agent":env(
                "REDDIT_USER_AGENT",
                "NAYEM-BOSS-SOCIAL-AUTOMATION/1.0"
            )
        }
    )

    name=me.get("name")
    user_id=me.get("id")

    if not user_id:
        return False,"reddit_identity_failed",me,[]

    cid=_save(
        c,
        user,
        "reddit",
        name or "Reddit",
        user_id,
        access,
        tok.get("refresh_token"),
        metadata=me
    )

    return True,"reddit_connected",{},[cid]


def complete_oauth(c,platform,query):
    _load_env()
    ensure_oauth_schema(c)

    state=(query.get("state") or [""])[0]
    code=(query.get("code") or [""])[0]
    error=(query.get("error") or [""])[0]

    if not state:
        return None,{"ok":False,"error":"missing_oauth_state"}

    row=c.execute(
        """
        SELECT * FROM oauth_states
        WHERE state=? AND expires_at>datetime('now')
        """,
        (state,)
    ).fetchone()

    if not row:
        return None,{"ok":False,"error":"oauth_state_invalid_or_expired"}

    if row["platform"]!=platform:
        c.execute("DELETE FROM oauth_states WHERE state=?",(state,))
        c.commit()
        return None,{"ok":False,"error":"oauth_platform_mismatch"}

    if error:
        c.execute("DELETE FROM oauth_states WHERE state=?",(state,))
        c.commit()
        return {
            "user_id":row["user_id"],
            "tenant_id":row["tenant_id"]
        },{
            "ok":False,
            "error":"provider_denied",
            "provider_error":error
        }

    if not code:
        c.execute("DELETE FROM oauth_states WHERE state=?",(state,))
        c.commit()
        return {
            "user_id":row["user_id"],
            "tenant_id":row["tenant_id"]
        },{
            "ok":False,
            "error":"missing_authorization_code"
        }

    user=c.execute(
        """
        SELECT id,email,role,tenant_id,is_active
        FROM users WHERE id=? AND tenant_id=? AND is_active=1
        """,
        (row["user_id"],row["tenant_id"])
    ).fetchone()

    if not user:
        c.execute("DELETE FROM oauth_states WHERE state=?",(state,))
        c.commit()
        return None,{"ok":False,"error":"oauth_user_invalid"}

    try:
        if platform in ("facebook","instagram"):
            ok,status,error_data,saved=_meta_complete(c,user,code)
        elif platform=="x":
            ok,status,error_data,saved=_x_complete(c,user,code,row)
        elif platform=="youtube":
            ok,status,error_data,saved=_google_complete(c,user,code)
        elif platform=="tiktok":
            ok,status,error_data,saved=_tiktok_complete(c,user,code)
        elif platform=="pinterest":
            ok,status,error_data,saved=_pinterest_complete(c,user,code)
        elif platform=="reddit":
            ok,status,error_data,saved=_reddit_complete(c,user,code)
        else:
            ok,status,error_data,saved=False,"unsupported_platform",{},[]
    except Exception as e:
        ok,status,error_data,saved=False,"oauth_callback_exception",{"error":str(e)},[]

    c.execute("DELETE FROM oauth_states WHERE state=?",(state,))
    c.commit()

    return {
        "user_id":row["user_id"],
        "tenant_id":row["tenant_id"]
    },{
        "ok":ok,
        "status":status,
        "saved_connector_ids":saved,
        "error":error_data if not ok else None
    }


def telegram_connect(c,user):
    _load_env()
    token=env("TELEGRAM_BOT_TOKEN")

    if not token:
        return False,{"error":"TELEGRAM_BOT_TOKEN_NOT_CONFIGURED"}

    status,result=_request(
        f"https://api.telegram.org/bot{token}/getMe",
        "GET"
    )

    if status!=200 or result.get("ok") is not True:
        return False,{
            "error":"telegram_bot_authentication_failed",
            "response":result
        }

    bot=result.get("result") or {}
    bot_id=bot.get("id")
    username=bot.get("username")
    name=bot.get("first_name") or username or "Telegram Bot"

    if not bot_id:
        return False,{"error":"telegram_bot_identity_not_found"}

    cid=_save(
        c,
        user,
        "telegram",
        "@"+username if username else name,
        str(bot_id),
        token,
        metadata=bot
    )

    return True,{
        "connector_id":cid,
        "account_name":"@"+username if username else name,
        "bot_id":str(bot_id),
        "username":username
    }
