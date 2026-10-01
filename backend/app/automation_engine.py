import json
from datetime import datetime

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

ACTIONS = ("publish", "comment", "reply")

def now_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def ensure_automation_schema(c):
    c.execute("""
    CREATE TABLE IF NOT EXISTS automation_targets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        connector_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        target_type TEXT NOT NULL DEFAULT 'destination',
        target_input TEXT NOT NULL,
        target_name TEXT,
        platform_target_id TEXT,
        metadata_json TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(tenant_id) REFERENCES tenants(id),
        FOREIGN KEY(connector_id) REFERENCES oauth_connectors(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS automations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        action TEXT NOT NULL,
        scheduled_at TEXT NOT NULL,
        recurring_rule TEXT,
        status TEXT NOT NULL DEFAULT 'scheduled',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(tenant_id) REFERENCES tenants(id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(post_id) REFERENCES posts(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS automation_target_map(
        automation_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        PRIMARY KEY(automation_id,target_id),
        FOREIGN KEY(automation_id) REFERENCES automations(id),
        FOREIGN KEY(target_id) REFERENCES automation_targets(id)
    )
    """)

    cols={r[1] for r in c.execute("PRAGMA table_info(scheduled_jobs)").fetchall()}

    if "target_id" not in cols:
        c.execute("ALTER TABLE scheduled_jobs ADD COLUMN target_id INTEGER")
    if "action" not in cols:
        c.execute("ALTER TABLE scheduled_jobs ADD COLUMN action TEXT DEFAULT 'publish'")
    if "automation_id" not in cols:
        c.execute("ALTER TABLE scheduled_jobs ADD COLUMN automation_id INTEGER")

    c.commit()

def list_targets(c, tenant_id):
    rows=c.execute("""
    SELECT
        t.id,t.tenant_id,t.connector_id,t.platform,t.target_type,
        t.target_input,t.target_name,t.platform_target_id,
        t.metadata_json,t.status,t.created_at,t.updated_at,
        o.account_name,o.status AS connector_status
    FROM automation_targets t
    JOIN oauth_connectors o
      ON o.id=t.connector_id
     AND o.tenant_id=t.tenant_id
    WHERE t.tenant_id=?
    ORDER BY t.id DESC
    """,(tenant_id,)).fetchall()
    return [dict(x) for x in rows]

def create_target(c, tenant_id, payload):
    connector_id=int(payload.get("connector_id") or 0)
    platform=str(payload.get("platform","")).strip().lower()

    target_type=str(
        payload.get("target_type") or "destination"
    ).strip().lower()

    target_input=str(
        payload.get("target_input")
        or payload.get("handle")
        or payload.get("username")
        or payload.get("target_name")
        or payload.get("name")
        or payload.get("id")
        or ""
    ).strip()

    target_name=str(payload.get("target_name") or "").strip() or None
    platform_target_id=str(
        payload.get("platform_target_id") or ""
    ).strip() or None

    if platform not in PLATFORMS:
        raise ValueError("Unsupported platform")

    if not connector_id:
        raise ValueError("connector_id is required")

    if not target_input:
        raise ValueError("target_input is required")

    if target_type not in {
        "destination",
        "post",
        "video",
        "comment",
        "channel",
        "page",
        "group",
        "account",
        "subreddit"
    }:
        raise ValueError("Invalid target_type")

    row=c.execute("""
    SELECT id,platform,status
    FROM oauth_connectors
    WHERE id=? AND tenant_id=?
    """,(connector_id,tenant_id)).fetchone()

    if not row:
        raise ValueError("Connector not found")

    if str(row["platform"]).lower()!=platform:
        raise ValueError("Target platform does not match connector")

    if row["status"]!="connected":
        raise ValueError("Connector is not connected")

    metadata=payload.get("metadata") or {}
    try:
        metadata_json=json.dumps(metadata,ensure_ascii=False)
    except Exception:
        raise ValueError("metadata must be JSON-compatible")

    t=now_string()

    cur=c.execute("""
    INSERT INTO automation_targets(
        tenant_id,connector_id,platform,target_type,target_input,
        target_name,platform_target_id,metadata_json,status,created_at,updated_at
    )
    VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """,(
        tenant_id,connector_id,platform,target_type,target_input,
        target_name,platform_target_id,metadata_json,"active",t,t
    ))

    c.commit()

    row=c.execute("""
    SELECT
        t.id,t.tenant_id,t.connector_id,t.platform,t.target_type,
        t.target_input,t.target_name,t.platform_target_id,
        t.metadata_json,t.status,t.created_at,t.updated_at,
        o.account_name
    FROM automation_targets t
    JOIN oauth_connectors o
      ON o.id=t.connector_id
     AND o.tenant_id=t.tenant_id
    WHERE t.id=? AND t.tenant_id=?
    """,(cur.lastrowid,tenant_id)).fetchone()

    return dict(row)

def delete_target(c, tenant_id, target_id):
    row=c.execute("""
    SELECT id FROM automation_targets
    WHERE id=? AND tenant_id=?
    """,(target_id,tenant_id)).fetchone()

    if not row:
        return False

    c.execute("""
    UPDATE scheduled_jobs
    SET status='cancelled',updated_at=?
    WHERE tenant_id=?
      AND target_id=?
      AND status IN ('pending','processing')
    """,(now_string(),tenant_id,target_id))

    c.execute(
        "DELETE FROM automation_target_map WHERE target_id=?",
        (target_id,)
    )
    c.execute("""
    DELETE FROM automation_targets
    WHERE id=? AND tenant_id=?
    """,(target_id,tenant_id))

    c.commit()
    return True

def list_automations(c, tenant_id):
    rows=c.execute("""
    SELECT
        a.id,a.tenant_id,a.user_id,a.post_id,a.name,a.action,
        a.scheduled_at,a.recurring_rule,a.status,a.created_at,a.updated_at,
        COUNT(m.target_id) AS target_count
    FROM automations a
    LEFT JOIN automation_target_map m
      ON m.automation_id=a.id
    WHERE a.tenant_id=?
    GROUP BY a.id
    ORDER BY a.id DESC
    """,(tenant_id,)).fetchall()

    return [dict(x) for x in rows]

def create_automation(c, tenant_id, user_id, payload):
    post_id=int(payload.get("post_id") or 0)
    name=str(payload.get("name","")).strip()
    action=str(payload.get("action","publish")).strip().lower()
    scheduled_at=str(payload.get("scheduled_at","")).strip()
    recurring_rule=str(payload.get("recurring_rule") or "").strip() or None
    target_ids=payload.get("target_ids") or []

    if not post_id:
        raise ValueError("post_id is required")
    if not name:
        raise ValueError("name is required")
    if action not in ACTIONS:
        raise ValueError("Invalid automation action")
    if not scheduled_at:
        raise ValueError("scheduled_at is required")
    if not isinstance(target_ids,list) or not target_ids:
        raise ValueError("At least one target is required")

    ids=[]
    for value in target_ids:
        try:
            value=int(value)
        except Exception:
            raise ValueError("Invalid target id")
        if value not in ids:
            ids.append(value)

    post=c.execute("""
    SELECT id FROM posts
    WHERE id=? AND tenant_id=?
    """,(post_id,tenant_id)).fetchone()

    if not post:
        raise ValueError("Post not found")

    placeholders=",".join("?" for _ in ids)

    targets=c.execute(f"""
    SELECT id,connector_id,platform
    FROM automation_targets
    WHERE tenant_id=?
      AND status='active'
      AND id IN ({placeholders})
    """,[tenant_id,*ids]).fetchall()

    found={r["id"]:dict(r) for r in targets}

    if any(x not in found for x in ids):
        raise ValueError("One or more targets are invalid")

    t=now_string()

    cur=c.execute("""
    INSERT INTO automations(
        tenant_id,user_id,post_id,name,action,
        scheduled_at,recurring_rule,status,created_at,updated_at
    )
    VALUES(?,?,?,?,?,?,?,?,?,?)
    """,(
        tenant_id,user_id,post_id,name,action,
        scheduled_at,recurring_rule,"scheduled",t,t
    ))

    automation_id=cur.lastrowid

    for target_id in ids:
        target=found[target_id]

        c.execute("""
        INSERT INTO automation_target_map(automation_id,target_id)
        VALUES(?,?)
        """,(automation_id,target_id))

        c.execute("""
        INSERT INTO scheduled_jobs(
            tenant_id,user_id,post_id,connector_id,
            scheduled_at,status,attempts,last_error,
            created_at,updated_at,target_id,action,automation_id
        )
        VALUES(?,?,?,?,?,'pending',0,NULL,?,?,?,?,?)
        """,(
            tenant_id,user_id,post_id,target["connector_id"],
            scheduled_at,t,t,target_id,action,automation_id
        ))

    c.commit()

    return {
        "message":"Automation created",
        "id":automation_id,
        "targets_created":len(ids),
        "action":action,
        "scheduled_at":scheduled_at
    }

def delete_automation(c, tenant_id, automation_id):
    row=c.execute("""
    SELECT id FROM automations
    WHERE id=? AND tenant_id=?
    """,(automation_id,tenant_id)).fetchone()

    if not row:
        return False

    c.execute("""
    UPDATE scheduled_jobs
    SET status='cancelled',updated_at=?
    WHERE tenant_id=?
      AND automation_id=?
      AND status IN ('pending','processing')
    """,(now_string(),tenant_id,automation_id))

    c.execute(
        "DELETE FROM automation_target_map WHERE automation_id=?",
        (automation_id,)
    )
    c.execute("""
    DELETE FROM automations
    WHERE id=? AND tenant_id=?
    """,(automation_id,tenant_id))

    c.commit()
    return True
