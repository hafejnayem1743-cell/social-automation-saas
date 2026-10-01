import json, sqlite3, hashlib, secrets, hmac, os, threading, time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote


def _load_local_env():
    path=os.path.join(os.path.dirname(__file__), '..', '.env')
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line=line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k,v=line.split('=',1)
                k=k.strip()
                v=v.strip().strip('"').strip("'")
                if k and v:
                    os.environ.setdefault(k,v)
    except Exception:
        pass


_load_local_env()

from publishing_engine import publish
from oauth_engine import (
    ensure_oauth_schema,
    provider_info,
    create_oauth_start,
    complete_oauth,
    telegram_connect,
    redirect_uri,
)

DB="social_automation.db"
HOST="127.0.0.1"
PORT=8000
SESSION_DAYS=30
WORKER_INTERVAL=10

def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row

    try:
        exists=c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='posts'"
        ).fetchone()

        if exists:
            cols=[r[1] for r in c.execute("PRAGMA table_info(posts)").fetchall()]
            if "media_data" not in cols:
                c.execute("ALTER TABLE posts ADD COLUMN media_data TEXT")

        c.execute("""
        CREATE TABLE IF NOT EXISTS password_resets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        c.commit()
    except sqlite3.OperationalError:
        pass

    ensure_automation_schema(c)
    return c

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

def reset_token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

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
                o.webhook_url,
                o.status AS connector_status,
                p.content AS post_content,
                j.target_id AS target_id,
                j.action AS action,
                j.automation_id AS automation_id,
                p.media_data AS post_media
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
                        "webhook_url": j["webhook_url"],
                    }

                    if not j["post_content"]:
                        raise ValueError("post_content_missing")

                    target_id=j["target_id"]

                    if target_id:
                        target=c.execute("""
                        SELECT *
                        FROM automation_targets
                        WHERE id=? AND tenant_id=? AND status='active'
                        """,(target_id,j["tenant_id"])).fetchone()

                        if not target:
                            raise ValueError("target_not_found")

                        account=dict(account)
                        account["target_id"]=target["id"]
                        account["target_type"]=target["target_type"]
                        account["target_input"]=target["target_input"]
                        account["target_name"]=target["target_name"]
                        account["platform_target_id"]=target["platform_target_id"]
                        account["action"]=j["action"] or "publish"
                        account["target_metadata"]=target["metadata_json"]

                    result=publish(
                        j["platform"],
                        account,
                        j["post_content"],
                        j["post_media"]
                    )

                    if isinstance(result, dict):
                        result_ok = bool(result.get("ok"))
                        result_retryable = bool(result.get("retryable", False))
                        result_error = result.get("error")
                    else:
                        result_ok = bool(result.ok)
                        result_retryable = bool(result.retryable)
                        result_error = getattr(result, 'error', None)

                    if result_ok:
                        c.execute("""
                        UPDATE scheduled_jobs
                        SET status='published',last_error=NULL,updated_at=?
                        WHERE id=?
                        """,(now(),j["id"]))
                    else:
                        if result_retryable and j["attempts"] < 3:
                            delay = 30 * (2 ** (j["attempts"] - 1))
                            retry_at = (datetime.utcnow() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                            c.execute("""
                            UPDATE scheduled_jobs
                            SET status='pending',scheduled_at=?,last_error=?,updated_at=?
                            WHERE id=?
                            """,(retry_at,result_error or "publish_retry",now(),j["id"]))
                        else:
                            c.execute("""
                            UPDATE scheduled_jobs
                            SET status='failed',last_error=?,updated_at=?
                            WHERE id=?
                            """,(result_error or "publish_failed",now(),j["id"]))

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

try:
    from app.automation_engine import (
        PLATFORMS,
        ACTIONS,
        ensure_automation_schema,
        list_targets,
        create_target,
        delete_target,
        list_automations,
        create_automation,
        delete_automation,
    )
except ModuleNotFoundError:
    from automation_engine import (
        PLATFORMS,
        ACTIONS,
        ensure_automation_schema,
        list_targets,
        create_target,
        delete_target,
        list_automations,
        create_automation,
        delete_automation,
    )

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

        if p=="/api/targets":
            u=require(self)
            if not u:return
            c=db()
            data=list_targets(c,u["tenant_id"])
            c.close()
            return response(self,200,{"targets":data})

        if p=="/api/automations":
            u=require(self)
            if not u:return
            c=db()
            data=list_automations(c,u["tenant_id"])
            c.close()
            return response(self,200,{"automations":data})

        if p=="/health":
            return response(self,200,{"status":"ok","version":"0.5.0"})

        # OAuth callback is intentionally public: provider redirects here.
        if p.startswith("/oauth/callback/"):
            platform=p.rsplit("/",1)[-1].strip().lower()
            params=parse_qs(urlparse(self.path).query)
            c=db()
            owner,result=complete_oauth(c,platform,params)
            c.close()

            frontend=os.getenv("NBSA_FRONTEND_URL","http://127.0.0.1:5173").rstrip("/")
            if result.get("ok"):
                location=frontend+"/dashboard.html?oauth=success&platform="+quote(platform)
            else:
                location=frontend+"/dashboard.html?oauth=error&platform="+quote(platform)+"&reason="+quote(str(result.get("error") or result.get("provider_error") or "oauth_failed"))

            self.send_response(302)
            self.send_header("Location",location)
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            return

        u=require(self)
        if not u:return

        if p=="/api/oauth/providers":
            return response(self,200,{"providers":provider_info()})

        if p.startswith("/api/oauth/start/"):
            platform=p.rsplit("/",1)[-1].strip().lower()
            c=db()
            url,error=create_oauth_start(c,u,platform)
            c.close()
            if error:
                return response(self,400,{"detail":error,"platform":platform})
            return response(self,200,{"platform":platform,"url":url})

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
            SELECT id,tenant_id,content,status,scheduled_at,created_at,media_data
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
            SELECT id,post_id,connector_id,target_id,action,automation_id,
                   scheduled_at,status,attempts,last_error,created_at,updated_at
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

        if p.startswith("/api/targets/"):
            u=require(self)
            if not u:return

            try:
                target_id=int(p.rsplit("/",1)[1])
            except ValueError:
                return response(self,400,{"detail":"Invalid target id"})

            c=db()
            ok=delete_target(c,u["tenant_id"],target_id)
            c.close()

            if not ok:
                return response(self,404,{"detail":"Target not found"})

            return response(self,200,{
                "message":"Target deleted",
                "id":target_id
            })

        if p.startswith("/api/automations/"):
            u=require(self)
            if not u:return

            try:
                automation_id=int(p.rsplit("/",1)[1])
            except ValueError:
                return response(self,400,{"detail":"Invalid automation id"})

            c=db()
            ok=delete_automation(c,u["tenant_id"],automation_id)
            c.close()

            if not ok:
                return response(self,404,{"detail":"Automation not found"})

            return response(self,200,{
                "message":"Automation deleted",
                "id":automation_id
            })
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
            exp=(datetime.now()+timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                      (token,u["id"],now(),exp))
            c.commit()
            c.close()

            with LOGIN_LOCK:
                LOGIN_ATTEMPTS.pop(client_ip,None)

            return response(self,200,{"message":"Login successful","token":token,"expires_at":exp,
                "user":{"id":u["id"],"email":u["email"],"role":u["role"],"tenant_id":u["tenant_id"]}})

        if p=="/api/auth/forgot-password":
            d=body(self)
            email=str(d.get("email","")).strip().lower()

            # Always return the same public message to avoid account enumeration.
            message="If that email exists, a password reset link has been generated."

            token=secrets.token_urlsafe(32)
            token_hash=reset_token_hash(token)
            exp=(datetime.now()+timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

            c=db()
            u=c.execute(
                "SELECT id FROM users WHERE email=? AND is_active=1",
                (email,)
            ).fetchone()

            if u:
                c.execute(
                    "DELETE FROM password_resets WHERE user_id=? OR expires_at<=datetime('now')",
                    (u["id"],)
                )
                c.execute("""
                INSERT INTO password_resets(user_id,token_hash,expires_at,created_at)
                VALUES(?,?,?,?)
                """,(u["id"],token_hash,exp,now()))
                c.commit()

            c.close()

            # Free-first/local mode: provide a usable local reset link.
            # Set NBSA_DEV_RESET_LINK=0 in production and deliver this link by email instead.
            dev_reset=os.getenv("NBSA_DEV_RESET_LINK","1")!="0"

            out={"message":message,"expires_in_minutes":30}
            if dev_reset:
                frontend=os.getenv(
                    "NBSA_FRONTEND_URL",
                    "http://127.0.0.1:5173"
                ).rstrip("/")
                out["reset_link"]=f"{frontend}/reset.html?token={token}"

            return response(self,200,out)

        if p=="/api/auth/reset-password":
            d=body(self)
            token=str(d.get("token","")).strip()
            password=str(d.get("password",""))

            if not token:
                return response(self,400,{"detail":"Reset token is required"})

            if len(password)<8:
                return response(self,400,{"detail":"Password must be at least 8 characters"})

            token_hash=reset_token_hash(token)
            c=db()

            row=c.execute("""
            SELECT id,user_id
            FROM password_resets
            WHERE token_hash=?
              AND used_at IS NULL
              AND expires_at>datetime('now')
            """,(token_hash,)).fetchone()

            if not row:
                c.close()
                return response(self,400,{"detail":"Reset link is invalid or expired"})

            c.execute(
                "UPDATE users SET password_hash=? WHERE id=? AND is_active=1",
                (hash_password(password),row["user_id"])
            )
            c.execute(
                "UPDATE password_resets SET used_at=? WHERE id=?",
                (now(),row["id"])
            )
            c.execute(
                "DELETE FROM password_resets WHERE user_id=? AND id!=?",
                (row["user_id"],row["id"])
            )
            c.execute(
                "DELETE FROM sessions WHERE user_id=?",
                (row["user_id"],)
            )
            c.commit()
            c.close()

            return response(self,200,{"message":"Password reset successful. Please login again."})

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
            media_data=str(d.get("media") or "").strip()

            if media_data:
                if not media_data.startswith("data:image/"):
                    c.close()
                    return response(self,400,{"detail":"Only image uploads are supported"})
                if len(media_data) > 7000000:
                    c.close()
                    return response(self,400,{"detail":"Image is too large; maximum is about 5 MB"})

            if not content and not media_data:
                c.close()
                return response(self,400,{"detail":"content is required"})

            if status not in {"draft","ready"}:
                c.close()
                return response(self,400,{"detail":"Invalid post status"})

            t=now()
            cur=c.execute("""
            INSERT INTO posts(tenant_id,content,status,scheduled_at,created_at,media_data)
            VALUES(?,?,?,?,?,?)
            """,(u["tenant_id"],content,status,scheduled_at,t,media_data or None))
            c.commit()
            pid=cur.lastrowid
            c.close()
            return response(self,201,{"message":"Post created","id":pid})

        if p=="/api/telegram/connect":
            if not has_permission(u,"connectors_manage"):
                c.close()
                return response(self,403,{"detail":"Insufficient permissions"})

            ok,result=telegram_connect(c,u)
            c.close()

            if not ok:
                return response(self,400,result)

            return response(self,200,{
                "message":"Telegram Bot connected",
                **result
            })

        if p=="/api/oauth/connectors":
            c.close()
            return response(self,405,{
                "detail":"Manual token connectors are disabled. Use official Connect OAuth or Telegram Bot Connect."
            })

        if p=="/api/oauth/connectors":
            if not has_permission(u,"connectors_manage"):
                c.close()
                return response(self,403,{"detail":"Insufficient permissions"})

            platform=str(d.get("platform","")).strip().lower()
            account=str(d.get("account_name","")).strip()

            if not platform or not account:
                c.close()
                return response(self,400,{"detail":"platform and account_name are required"})

            allowed_platforms={"facebook","instagram","telegram","x","youtube","tiktok","pinterest","reddit"}
            if platform not in allowed_platforms:
                c.close()
                return response(self,400,{"detail":"Unsupported platform"})

            t=now()
            cur=c.execute("""
            INSERT INTO oauth_connectors
            (tenant_id,user_id,platform,account_name,platform_user_id,
             access_token,refresh_token,token_expires_at,webhook_url,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,(
                u["tenant_id"],u["id"],platform,account,
                d.get("platform_user_id"),
                d.get("access_token"),
                d.get("refresh_token"),
                d.get("token_expires_at"),
                d.get("webhook_url"),
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

            post_id=d.get("post_id")
            connector_id=d.get("connector_id")

            if post_id is None or connector_id is None:
                c.close()
                return response(
                    self,400,
                    {"detail":"post_id and connector_id are required"}
                )

            scheduled=str(d.get("scheduled_at","")).strip()
            if not scheduled:
                c.close()
                return response(self,400,{"detail":"scheduled_at is required"})

            if not isinstance(post_id,int):
                try: post_id=int(post_id)
                except (TypeError,ValueError):
                    c.close()
                    return response(self,400,{"detail":"Invalid post id"})

                r=c.execute("""
                SELECT id FROM posts
                WHERE id=? AND tenant_id=?
                """,(post_id,u["tenant_id"])).fetchone()
                if not r:
                    c.close()
                    return response(self,400,{"detail":"Invalid post"})

            if not isinstance(connector_id,int):
                try: connector_id=int(connector_id)
                except (TypeError,ValueError):
                    c.close()
                    return response(self,400,{"detail":"Invalid connector id"})

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


# ==================== OFFICIAL OAUTH RUNTIME ====================
print("FULL 8-PLATFORM OAUTH RUNTIME LOADED")


# ==================== UNIVERSAL CONNECTOR RUNTIME ====================
try:
    from app.universal_connectors import PLATFORMS, platform_status, CONNECTOR_REGISTRY
    from app.publishing_engine import publish, get_publisher, PUBLISHERS
    from app.official_publishers import OFFICIAL_PUBLISHERS
except ModuleNotFoundError:
    from universal_connectors import PLATFORMS, platform_status, CONNECTOR_REGISTRY
    from publishing_engine import publish, get_publisher, PUBLISHERS
    from official_publishers import OFFICIAL_PUBLISHERS
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
