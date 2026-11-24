"""岸桥禁放（第12号）：放行资格与放行状态的唯一口径。

正确性口径只有一条：岸桥计划 `crane_plan_jobs` 的匹配泊位行。
本仓裁决走甲路径：无匹配泊位行时，放行写口原子拒收，正式册零增。
乙路径（影子意图后晋升）不采用；第三路（只改页面/双口径/对账兜底）禁止。

正式册 `gate_releases` 行以写入时钉住的 `crane_job_id` 为晋升凭证；
无凭证的行一律记偏航，不得以“已放行”呈现给对账、证明、车道、放行、空桩任一页。
裁决见 `docs/岸桥禁放纪要.md`，自 2026-11-24 当日封死。
"""
from __future__ import annotations

BAN_CODE = "岸桥禁放第12号"
BAN_MEMO = "docs/岸桥禁放纪要.md"
BAN_SEALED_AT = "2026-11-24"
DEAD_JOB_STATUS = ("已取消", "作废")

STATE_RELEASED = "已放行"
STATE_UNPROMOTED = "偏航未晋升"
STATE_WAITING = "待放行"
STATE_BANNED = "禁放"


def _get(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def plan_row_valid(row) -> bool:
    """泊位行有效：有票、泊位非空、未取消。"""
    return bool(
        row is not None
        and (row["status"] or "") not in DEAD_JOB_STATUS
        and (row["berth_slot"] or "").strip()
    )


def _plan_query() -> str:
    return """SELECT id, ticket_id, berth_slot, mode, status, detail, created_at
              FROM crane_plan_jobs
              WHERE ticket_id=? AND status NOT IN ('已取消','作废')
                AND TRIM(COALESCE(berth_slot,'')) <> ''
              ORDER BY id DESC LIMIT 1"""


def crane_plan_for_ticket(conn, ticket_id: int):
    return conn.execute(_plan_query(), (ticket_id,)).fetchone()


def crane_plan_ready(conn, ticket_id: int) -> dict:
    row = crane_plan_for_ticket(conn, ticket_id)
    ready = plan_row_valid(row)
    return {
        "ready": ready,
        "job_id": row["id"] if ready else None,
        "berth_slot": row["berth_slot"] if ready else None,
        "job_status": row["status"] if ready else None,
        "reason": None if ready else "无岸桥计划泊位行",
        "ban_code": BAN_CODE,
        "ban_memo": BAN_MEMO,
    }


def _plans_by_ticket(conn, ticket_ids: list[int]) -> dict:
    if not ticket_ids:
        return {}
    marks = ",".join("?" for _ in ticket_ids)
    rows = conn.execute(
        f"""SELECT id, ticket_id, berth_slot, status FROM crane_plan_jobs
            WHERE ticket_id IN ({marks}) AND status NOT IN ('已取消','作废')
              AND TRIM(COALESCE(berth_slot,'')) <> ''
            ORDER BY id DESC""",
        ticket_ids,
    ).fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(int(r["ticket_id"]), r)
    return out


_RELEASE_JOIN = """
SELECT g.*, j.id AS crane_job_found, j.berth_slot AS release_berth_slot,
       j.status AS release_job_status
FROM gate_releases g
LEFT JOIN crane_plan_jobs j ON j.id = g.crane_job_id
WHERE g.status='已放行'"""


def _releases_by_ticket(conn, ticket_ids: list[int]) -> dict:
    if not ticket_ids:
        return {}
    marks = ",".join("?" for _ in ticket_ids)
    rows = conn.execute(
        _RELEASE_JOIN + f" AND g.ticket_id IN ({marks}) ORDER BY g.id DESC",
        ticket_ids,
    ).fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(int(r["ticket_id"]), r)
    return out


def release_backed(row) -> bool:
    """正式行是否有晋升凭证：写时钉住的岸桥泊位行仍然有效。"""
    if row is None:
        return False
    if _get(row, "crane_job_id") is None:
        return False
    if _get(row, "crane_job_found") is None:
        return False
    return bool(
        (_get(row, "release_job_status") or "") not in DEAD_JOB_STATUS
        and (_get(row, "release_berth_slot") or "").strip()
    )


def state_for(plan, release) -> dict:
    """由“当前泊位计划 + 正式册行”合成唯一放行口径。"""
    plan_ready = plan_row_valid(plan)
    berth = plan["berth_slot"] if plan_ready else _get(release, "release_berth_slot")
    if release is not None:
        backed = release_backed(release)
        state = STATE_RELEASED if backed else STATE_UNPROMOTED
        released = backed
        register = "正式" if backed else "偏航"
    elif plan_ready:
        state = STATE_WAITING
        released = False
        register = None
    else:
        state = STATE_BANNED
        released = False
        register = None
    return {
        "release_state": state,
        "released": released,
        "release_register": register,
        "release_ref": _get(release, "release_ref"),
        "crane_plan_ready": plan_ready,
        "crane_job_id": plan["id"] if plan_ready else _get(release, "crane_job_id"),
        "crane_berth_slot": berth,
        "ban_code": BAN_CODE,
    }


def _open_overload_ids(conn, ticket_ids: list[int]) -> set:
    if not ticket_ids:
        return set()
    marks = ",".join("?" for _ in ticket_ids)
    rows = conn.execute(
        f"""SELECT DISTINCT ticket_id FROM overload_holds
            WHERE status='开放' AND ticket_id IN ({marks})""",
        ticket_ids,
    ).fetchall()
    return {int(r["ticket_id"]) for r in rows}


def annotate_tickets(conn, items: list[dict]) -> list[dict]:
    """过磅页/车道页/放行页共用的票级口径。"""
    if not items:
        return items
    ids = [int(x["id"]) for x in items]
    plans = _plans_by_ticket(conn, ids)
    releases = _releases_by_ticket(conn, ids)
    open_holds = _open_overload_ids(conn, ids)
    for x in items:
        tid = int(x["id"])
        x.update(state_for(plans.get(tid), releases.get(tid)))
        x["open_overload"] = tid in open_holds
        x["releasable"] = bool(
            x.get("status") == "已裁定"
            and not x["open_overload"]
            and x["crane_plan_ready"]
            and not x["released"]
        )
        # 单一展示口径：无凭证的“已放行”票不得以“已放行”呈现。
        x["display_status"] = (
            STATE_UNPROMOTED
            if x["release_state"] == STATE_UNPROMOTED
            else x.get("status")
        )
    return items


def annotate_releases(conn, items: list[dict]) -> list[dict]:
    """放行页：正式册行逐条标注是否晋升、所钉泊位与唯一口径。"""
    if not items:
        return items
    ids = sorted({int(x["ticket_id"]) for x in items})
    plans = _plans_by_ticket(conn, ids)
    for x in items:
        tid = int(x["ticket_id"])
        backed = release_backed(x)
        x["release_backed"] = backed
        x["release_state"] = STATE_RELEASED if backed else STATE_UNPROMOTED
        x["released"] = backed
        x["release_register"] = "正式" if backed else "偏航"
        x["crane_plan_ready"] = plan_row_valid(plans.get(tid))
        x["crane_berth_slot"] = x.get("crane_berth_slot") or (
            x.get("release_berth_slot") if backed else None
        )
        x["ban_code"] = BAN_CODE
    return items


def lane_release_summary(conn) -> dict:
    """车道页：每条车道的“有据已放行 / 偏航”计数，与放行页同源。"""
    rows = conn.execute(
        """SELECT t.lane_id, g.crane_job_id, j.id AS crane_job_found,
                  j.berth_slot AS release_berth_slot, j.status AS release_job_status
           FROM gate_releases g
           JOIN weigh_tickets t ON t.id=g.ticket_id
           LEFT JOIN crane_plan_jobs j ON j.id=g.crane_job_id
           WHERE g.status='已放行'"""
    ).fetchall()
    out: dict = {}
    for r in rows:
        lane = int(r["lane_id"])
        slot = out.setdefault(lane, {"released_backed": 0, "released_unbacked": 0})
        if release_backed(r):
            slot["released_backed"] += 1
        else:
            slot["released_unbacked"] += 1
    return out


def state_for_ticket(conn, ticket_id: int) -> dict:
    """单票口径：对账页、证明页、放行页共用同一函数，不得另立判断。"""
    return state_for(
        crane_plan_for_ticket(conn, ticket_id),
        conn.execute(
            _RELEASE_JOIN + " AND g.ticket_id=? ORDER BY g.id DESC LIMIT 1",
            (ticket_id,),
        ).fetchone(),
    )
