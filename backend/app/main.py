import json, sqlite3, hashlib, secrets, hmac, os, threading, time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DB="social_automation.db"
HOST="127.0.0.1"
PORT=8000
SESSION_DAYS=30
WORKER_INTERVAL=10

def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    return c

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS oauth_connectors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        account_name TEXT NOT NULL,
        platform_user_id TEXT,
        access_token TEXT,
        refresh_token TEXT,
        token_expires_at TEXT,
        status TEXT NOT NULL DEFAULT 'connected',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS scheduled_jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        post_id INTEGER,
        connector_id INTEGER,
        scheduled_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)
    c.close()

def response(handler,status,data):
    b=json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type","application/json")
    handler.send_header("Content-Length",str(len(b)))
    handler.send_header("Access-Control-Allow-Origin","http://127.0.0.1:5173")
    handler.end_headers()
    handler.wfile.write(b)

def body(handler):
    n=int(handler.headers.get("Content-Length","0"))
    try:return json.loads(handler.rfile.read(n).decode()) if n else {}
    except:return {}

def hash_password(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    dk=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,200000)
    return salt.hex()+"$"+dk.hex()

LOGIN_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = 300
LOGIN_BLOCK = 600

ROLE_PERMISSIONS = {
    "owner": {"connectors_manage", "scheduler_manage"},
    "admin": {"connectors_manage", "scheduler_manage"},
    "member": {"scheduler_manage"},
}

def has_permission(user, permission):
    return permission in ROLE_PERMISSIONS.get(user["role"], set())

def verify(password,stored):
    try:
        s,h=stored.split("$",1)
        salt=bytes.fromhex(s)
        dk=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,200000)
        return hmac.compare_digest(dk.hex(),h)
    except:return False

def auth(handler):
    a=handler.headers.get("Authorization","")
    if not a.startswith("Bearer "): return None
    token=a[7:]
    c=db()
    r=c.execute("""
    SELECT u.*,s.token
    FROM sessions s JOIN users u ON u.id=s.user_id
    WHERE s.token=? AND datetime(s.expires_at)>datetime('now') AND u.is_active=1
    """,(token,)).fetchone()
    c.close()
    return dict(r) if r else None

def require(handler,roles=None):
    u=auth(handler)
    if not u:
        response(handler,401,{"detail":"Authentication required"})
        return None
    if roles and u["role"] not in roles:
        response(handler,403,{"detail":"Insufficient permissions"})
        return None
    return u

def worker():
    while True:
        try:
            c=db()
            jobs=c.execute("""
            SELECT
                j.*,
                o.platform,
                o.account_name,
                o.platform_user_id,
                o.access_token,
                o.refresh_token,
                o.token_expires_at,
                o.status AS connector_status,
                p.content AS post_content
            FROM scheduled_jobs j
            JOIN oauth_connectors o ON o.id=j.connector_id
                AND o.tenant_id=j.tenant_id
            LEFT JOIN posts p ON p.id=j.post_id
                AND p.tenant_id=j.tenant_id
            WHERE j.status='pending'
            AND datetime(j.scheduled_at)<=datetime('now')
            AND o.status='connected'
            ORDER BY j.id
            LIMIT 20
            """).fetchall()

            for j in jobs:
                claimed=c.execute("""
                UPDATE scheduled_jobs
                SET status='processing',attempts=attempts+1,updated_at=?
                WHERE id=? AND status='pending'
                """,(now(),j["id"]))

                if claimed.rowcount != 1:
                    continue

                try:
                    account={
                        "id": j["connector_id"],
                        "platform": j["platform"],
                        "account_name": j["account_name"],
                        "platform_user_id": j["platform_user_id"],
                        "access_token": j["access_token"],
                        "refresh_token": j["refresh_token"],
                        "token_expires_at": j["token_expires_at"],
                    }

                    if not j["post_content"]:
                        raise ValueError("post_content_missing")

                    result=publish(
                        j["platform"],
                        account,
                        j["post_content"]
                    )

                    if result.ok:
                        c.execute("""
                        UPDATE scheduled_jobs
                        SET status='published',last_error=NULL,updated_at=?
                        WHERE id=?
                        """,(now(),j["id"]))
                    else:
                        if result.retryable and j["attempts"] < 3:
                            delay = 30 * (2 ** (j["attempts"] - 1))
                            retry_at = (datetime.utcnow() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                            c.execute("""
                            UPDATE scheduled_jobs
                            SET status='pending',scheduled_at=?,last_error=?,updated_at=?
                            WHERE id=?
                            """,(retry_at,result.error or "publish_retry",now(),j["id"]))
                        else:
                            c.execute("""
                            UPDATE scheduled_jobs
                            SET status='failed',last_error=?,updated_at=?
                            WHERE id=?
                            """,(result.error or "publish_failed",now(),j["id"]))

                except Exception as e:
                    c.execute("""
                    UPDATE scheduled_jobs
                    SET status='failed',last_error=?,updated_at=?
                    WHERE id=?
                    """,(str(e)[:500],now(),j["id"]))

            c.commit()
            c.close()

        except Exception:
            pass

        time.sleep(WORKER_INTERVAL)

class API(BaseHTTPRequestHandler):

    def log_message(self,*args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Headers","Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods","GET,POST,PUT,DELETE,OPTIONS")
        self.end_headers()

    def do_GET(self):
        p=urlparse(self.path).path

        if p=="/health":
            return response(self,200,{"status":"ok","version":"0.5.0"})

        u=require(self)
        if not u:return

        c=db()

        if p=="/api/me":
            data={k:u[k] for k in ["id","email","role","tenant_id","is_active"]}
            c.close()
            return response(self,200,{"user":data})

        if p=="/api/admin/users":
            if not has_permission(u,"connectors_manage"):
                c.close()
                return response(self,403,{"detail":"Insufficient permissions"})

            rows=c.execute("""
            SELECT id,email,role,is_active,created_at
            FROM users
            WHERE tenant_id=?
            ORDER BY id DESC
            """,(u["tenant_id"],)).fetchall()
            c.close()
            return response(self,200,{"users":[dict(x) for x in rows]})

        if p=="/api/posts":
            rows=c.execute("""
            SELECT id,tenant_id,content,status,scheduled_at,created_at
            FROM posts WHERE tenant_id=? ORDER BY id DESC
            """,(u["tenant_id"],)).fetchall()
            c.close()
            return response(self,200,{"posts":[dict(x) for x in rows]})

        if p=="/api/campaigns":
            c=db()
            rows=c.execute(
                "SELECT id,tenant_id,name,status,created_at FROM campaigns "
                "WHERE tenant_id=? ORDER BY id DESC",
                (u["tenant_id"],)
            ).fetchall()
            c.close()
            return response(self,200,{"campaigns":[dict(r) for r in rows]})

        if p=="/api/oauth/connectors":
            rows=c.execute("""
            SELECT id,platform,account_name,platform_user_id,
                   token_expires_at,status,created_at,updated_at
            FROM oauth_connectors
            WHERE tenant_id=?
            ORDER BY id DESC
            """,(u["tenant_id"],)).fetchall()
            c.close()
            return response(self,200,{"connectors":[dict(x) for x in rows]})

        if p=="/api/scheduler/jobs":
            rows=c.execute("""
            SELECT id,post_id,connector_id,scheduled_at,status,
                   attempts,last_error,created_at,updated_at
            FROM scheduled_jobs
            WHERE tenant_id=?
            ORDER BY id DESC
            """,(u["tenant_id"],)).fetchall()
            c.close()
            return response(self,200,{"jobs":[dict(x) for x in rows]})

        if p=="/api/campaigns":
            c=db()
            rows=c.execute(
                "SELECT id,tenant_id,name,status,created_at FROM campaigns "
                "WHERE tenant_id=? ORDER BY id DESC",
                (u["tenant_id"],)
            ).fetchall()
            c.close()
            return response(self,200,{"campaigns":[dict(r) for r in rows]})

        if p=="/api/status":
            count=c.execute(
                "SELECT COUNT(*) n FROM scheduled_jobs WHERE tenant_id=? AND status='pending'",
                (u["tenant_id"],)).fetchone()["n"]
            c.close()
            return response(self,200,{
                "version":"0.5.0",
                "worker":"running",
                "pending_jobs":count
            })

        c.close()
        return response(self,404,{"detail":"Not found"})

    def do_PUT(self):
        p=urlparse(self.path).path
        u=require(self)
        if not u:return

        if p.startswith("/api/campaigns/"):
            try:
                cid=int(p.rsplit("/",1)[1])
            except ValueError:
                return response(self,400,{"detail":"Invalid campaign id"})

            d=body(self)
            c=db()
            campaign=c.execute(
                "SELECT * FROM campaigns WHERE id=? AND tenant_id=?",
                (cid,u["tenant_id"])
            ).fetchone()

            if not campaign:
                c.close()
                return response(self,404,{"detail":"Campaign not found"})

            name=str(d.get("name",campaign["name"])).strip()
            status=str(d.get("status",campaign["status"])).strip().lower()

            if not name:
                c.close()
                return response(self,400,{"detail":"name is required"})

            if status not in {"draft","active","paused"}:
                c.close()
                return response(self,400,{"detail":"Invalid campaign status"})

            c.execute(
                "UPDATE campaigns SET name=?,status=? WHERE id=? AND tenant_id=?",
                (name,status,cid,u["tenant_id"])
            )
            c.commit()
            c.close()
            return response(self,200,{"message":"Campaign updated","id":cid})

        if p.startswith("/api/posts/"):
            try:
                pid=int(p.rsplit("/",1)[1])
            except ValueError:
                return response(self,400,{"detail":"Invalid post id"})

            d=body(self)
            c=db()
            post=c.execute(
                "SELECT * FROM posts WHERE id=? AND tenant_id=?",
                (pid,u["tenant_id"])
            ).fetchone()

            if not post:
                c.close()
                return response(self,404,{"detail":"Post not found"})

            content=d.get("content",post["content"])
            status=str(d.get("status",post["status"])).strip().lower()
            scheduled_at=d.get("scheduled_at",post["scheduled_at"])

            if not str(content).strip():
                c.close()
                return response(self,400,{"detail":"content is required"})

            if status not in {"draft","ready"}:
                c.close()
                return response(self,400,{"detail":"Invalid post status"})

            c.execute("""
            UPDATE posts
            SET content=?,status=?,scheduled_at=?
            WHERE id=? AND tenant_id=?
            """,(str(content).strip(),status,scheduled_at,pid,u["tenant_id"]))
            c.commit()
            c.close()
            return response(self,200,{"message":"Post updated","id":pid})


        if not p.startswith("/api/admin/users/"):
            return response(self,404,{"detail":"Not found"})

        if not has_permission(u,"connectors_manage"):
            return response(self,403,{"detail":"Insufficient permissions"})

        try:
            user_id=int(p.rsplit("/",1)[1])
        except ValueError:
            return response(self,400,{"detail":"Invalid user id"})

        d=body(self)
        c=db()

        target=c.execute("""
        SELECT id,tenant_id,email,role,is_active
        FROM users WHERE id=? AND tenant_id=?
        """,(user_id,u["tenant_id"])).fetchone()

        if not target:
            c.close()
            return response(self,404,{"detail":"User not found"})

        if target["id"]==u["id"]:
            c.close()
            return response(self,400,{"detail":"Cannot modify yourself"})

        active=d.get("is_active")
        role=d.get("role")

        if active is not None and not isinstance(active,bool):
            c.close()
            return response(self,400,{"detail":"is_active must be boolean"})

        if role is not None and role not in ("admin","member"):
            c.close()
            return response(self,400,{"detail":"Invalid role"})

        sets=[]
        values=[]

        if active is not None:
            sets.append("is_active=?")
            values.append(1 if active else 0)

        if role is not None:
            sets.append("role=?")
            values.append(role)

        if not sets:
            c.close()
            return response(self,400,{"detail":"Nothing to update"})

        values.append(user_id)
        values.append(u["tenant_id"])

        c.execute(
            f"UPDATE users SET {','.join(sets)} WHERE id=? AND tenant_id=?",
            values
        )
        c.commit()
        c.close()

        return response(self,200,{"message":"User updated","id":user_id})

    def do_DELETE(self):
        p=urlparse(self.path).path
        u=require(self)
        if not u:return

        if p.startswith("/api/campaigns/"):
            try:
                cid=int(p.rsplit("/",1)[1])
            except ValueError:
                return response(self,400,{"detail":"Invalid campaign id"})

            c=db()
            cur=c.execute(
                "DELETE FROM campaigns WHERE id=? AND tenant_id=?",
                (cid,u["tenant_id"])
            )
            c.commit()
            deleted=cur.rowcount
            c.close()

            if not deleted:
                return response(self,404,{"detail":"Campaign not found"})

            return response(self,200,{"message":"Campaign deleted","id":cid})

        if p.startswith("/api/posts/"):
            try:
                pid=int(p.rsplit("/",1)[1])
            except ValueError:
                return response(self,400,{"detail":"Invalid post id"})

            c=db()
            cur=c.execute(
                "DELETE FROM posts WHERE id=? AND tenant_id=?",
                (pid,u["tenant_id"])
            )
            c.commit()
            deleted=cur.rowcount
            c.close()

            if not deleted:
                return response(self,404,{"detail":"Post not found"})

            return response(self,200,{"message":"Post deleted","id":pid})

        return response(self,404,{"detail":"Not found"})

    def do_POST(self):
        p=urlparse(self.path).path

        if p=="/api/auth/register":
            d=body(self)
            email=str(d.get("email","")).strip().lower()
            password=str(d.get("password",""))

            if not email or "@" not in email:
                return response(self,400,{"detail":"Valid email is required"})

            if len(password)<8:
                return response(self,400,{"detail":"Password must be at least 8 characters"})

            c=db()

            if c.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone():
                c.close()
                return response(self,409,{"detail":"Email already registered"})

            t=now()
            cur=c.execute(
                "INSERT INTO tenants(name,created_at) VALUES(?,?)",
                (email,t)
            )
            tenant_id=cur.lastrowid

            cur=c.execute("""
            INSERT INTO users
            (tenant_id,email,password_hash,role,created_at,is_active)
            VALUES(?,?,?,?,?,1)
            """,(
                tenant_id,email,hash_password(password),"owner",t
            ))
            user_id=cur.lastrowid
            c.commit()
            c.close()

            return response(self,201,{
                "message":"Registration successful",
                "user":{
                    "id":user_id,
                    "email":email,
                    "role":"owner",
                    "tenant_id":tenant_id
                }
            })

        if p=="/api/auth/login":
            d=body(self)
            client_ip=self.client_address[0]
            now_ts=time.time()

            with LOGIN_LOCK:
                record=LOGIN_ATTEMPTS.get(client_ip)
                if record and record.get("blocked_until",0)>now_ts:
                    return response(self,429,{"detail":"Too many login attempts. Try again later."})

            c=db()
            u=c.execute("SELECT * FROM users WHERE email=?",(d.get("email",""),)).fetchone()
            valid=bool(u and u["is_active"] and verify(d.get("password",""),u["password_hash"]))

            if not valid:
                c.close()
                with LOGIN_LOCK:
                    record=LOGIN_ATTEMPTS.get(client_ip,{"count":0,"first":now_ts,"blocked_until":0})
                    if now_ts-record["first"]>LOGIN_WINDOW:
                        record={"count":0,"first":now_ts,"blocked_until":0}
                    record["count"]+=1
                    if record["count"]>=MAX_LOGIN_ATTEMPTS:
                        record["blocked_until"]=now_ts+LOGIN_BLOCK
                    LOGIN_ATTEMPTS[client_ip]=record
                return response(self,401,{"detail":"Invalid credentials"})

            c.execute("DELETE FROM sessions WHERE user_id=? AND expires_at<=datetime('now')",(u["id"],))
            token=secrets.token_urlsafe(32)

            token=secrets.token_urlsafe(32)
            exp=(datetime.utcnow()+timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                      (token,u["id"],now(),exp))
            c.commit()
            c.close()

            with LOGIN_LOCK:
                LOGIN_ATTEMPTS.pop(client_ip,None)

            return response(self,200,{"message":"Login successful","token":token,"expires_at":exp,
                "user":{"id":u["id"],"email":u["email"],"role":u["role"],"tenant_id":u["tenant_id"]}})

        if p=="/api/auth/logout":
            u=require(self)
            if not u:return
            token=self.headers["Authorization"][7:]
            c=db()
            c.execute("DELETE FROM sessions WHERE token=?",(token,))
            c.commit()
            c.close()
            return response(self,200,{"message":"Logged out"})

        u=require(self)
        if not u:return

        d=body(self)
        c=db()

        if p=="/api/campaigns":
            name=str(d.get("name","")).strip()
            status=str(d.get("status","draft")).strip().lower()

            if not name:
                c.close()
                return response(self,400,{"detail":"name is required"})

            if status not in {"draft","active","paused"}:
                c.close()
                return response(self,400,{"detail":"Invalid campaign status"})

            cur=c.execute(
                "INSERT INTO campaigns (tenant_id,name,status) VALUES (?,?,?)",
                (u["tenant_id"],name,status)
            )
            c.commit()
            cid=cur.lastrowid
            c.close()

            return response(self,201,{"message":"Campaign created","id":cid})

        if p=="/api/posts":
            content=str(d.get("content","")).strip()
            status=str(d.get("status","draft")).strip().lower()
            scheduled_at=d.get("scheduled_at")

            if not content:
                c.close()
                return response(self,400,{"detail":"content is required"})

            if status not in {"draft","ready"}:
                c.close()
                return response(self,400,{"detail":"Invalid post status"})

            t=now()
            cur=c.execute("""
            INSERT INTO posts(tenant_id,content,status,scheduled_at,created_at)
            VALUES(?,?,?,?,?)
            """,(u["tenant_id"],content,status,scheduled_at,t))
            c.commit()
            pid=cur.lastrowid
            c.close()
            return response(self,201,{"message":"Post created","id":pid})

        if p=="/api/oauth/connectors":
            if not has_permission(u,"connectors_manage"):
                c.close()
                return response(self,403,{"detail":"Insufficient permissions"})

            platform=str(d.get("platform","")).strip().lower()
            account=str(d.get("account_name","")).strip()

            if not platform or not account:
                c.close()
                return response(self,400,{"detail":"platform and account_name are required"})

            allowed_platforms={"telegram","wordpress","website"}
            if platform not in allowed_platforms:
                c.close()
                return response(self,400,{"detail":"Unsupported platform"})

            t=now()
            cur=c.execute("""
            INSERT INTO oauth_connectors
            (tenant_id,user_id,platform,account_name,platform_user_id,
             access_token,refresh_token,token_expires_at,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,(
                u["tenant_id"],u["id"],platform,account,
                d.get("platform_user_id"),
                d.get("access_token"),
                d.get("refresh_token"),
                d.get("token_expires_at"),
                "connected",t,t
            ))
            c.commit()
            cid=cur.lastrowid
            c.close()
            return response(self,201,{"message":"OAuth connector saved","id":cid})

        if p=="/api/scheduler/jobs":
            if not has_permission(u,"scheduler_manage"):
                c.close()
                return response(self,403,{"detail":"Insufficient permissions"})

            scheduled=str(d.get("scheduled_at","")).strip()
            if not scheduled:
                c.close()
                return response(self,400,{"detail":"scheduled_at is required"})

            post_id=d.get("post_id")
            if post_id is not None:
                r=c.execute("""
                SELECT id FROM posts
                WHERE id=? AND tenant_id=?
                """,(post_id,u["tenant_id"])).fetchone()
                if not r:
                    c.close()
                    return response(self,400,{"detail":"Invalid post"})

            connector_id=d.get("connector_id")
            if connector_id is not None:
                r=c.execute("""
                SELECT id FROM oauth_connectors
                WHERE id=? AND tenant_id=?
                """,(connector_id,u["tenant_id"])).fetchone()
                if not r:
                    c.close()
                    return response(self,400,{"detail":"Invalid connector"})

            t=now()
            cur=c.execute("""
            INSERT INTO scheduled_jobs
            (tenant_id,user_id,post_id,connector_id,scheduled_at,status,created_at,updated_at)
            VALUES(?,?,?,?,?,'pending',?,?)
            """,(
                u["tenant_id"],u["id"],post_id,
                connector_id,scheduled,t,t
            ))
            c.commit()
            jid=cur.lastrowid
            c.close()
            return response(self,201,{"message":"Scheduled job created","id":jid})

        c.close()
        return response(self,404,{"detail":"Not found"})


# ==================== V0.7 OFFICIAL OAUTH ====================

OAUTH_CONFIG = {
    "facebook": {
        "authorize_url": "https://www.facebook.com/v23.0/dialog/oauth",
        "scopes": ["pages_manage_posts", "pages_read_engagement"]
    },
    "instagram": {
        "authorize_url": "https://www.facebook.com/v23.0/dialog/oauth",
        "scopes": ["instagram_basic", "instagram_content_publish"]
    }
}

def oauth_config(platform):
    return OAUTH_CONFIG.get(platform)

def build_oauth_url(platform, client_id, redirect_uri, state):
    from urllib.parse import urlencode
    cfg = oauth_config(platform)
    if not cfg:
        return None

    return cfg["authorize_url"] + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": ",".join(cfg["scopes"]),
        "response_type": "code"
    })

print("V0.7 OFFICIAL OAUTH FOUNDATION LOADED")


# ==================== UNIVERSAL CONNECTOR RUNTIME ====================
try:
    from app.universal_connectors import PLATFORMS, platform_status, CONNECTOR_REGISTRY
    from app.publishing_engine import publish, get_publisher, PUBLISHERS
    from app.official_publishers import OFFICIAL_PUBLISHERS
    PUBLISHERS.update(OFFICIAL_PUBLISHERS)
    print("UNIVERSAL CONNECTOR RUNTIME: LOADED")
except Exception as e:
    print("UNIVERSAL CONNECTOR RUNTIME ERROR:", e)


def main():
    init_db()
    threading.Thread(target=worker,daemon=True).start()
    print("""
==============================================
 NAYEM BOSS SOCIAL AUTOMATION API
 Version: 0.5.0
 OAUTH CONNECTOR + SCHEDULER FOUNDATION
 Worker interval: 10 seconds
 Running on http://127.0.0.1:8000
==============================================
""")
    ThreadingHTTPServer((HOST,PORT),API).serve_forever()

print("V0.6.1 CONNECTOR LAYER LOADED")

if __name__=="__main__":
    main()
