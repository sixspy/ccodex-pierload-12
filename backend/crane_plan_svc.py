"""岸桥计划空桩（可挂载接口）。

岸桥页与放行页、对账页同源：每行列 `crane_plan_ready`，并单列
“无计划却已出正式放行”的偏航票，使岸桥页不再“空而对账已放行”。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from crane_gate import BAN_CODE, plan_row_valid, release_backed
from db import connect, now_iso, write_audit
from models import StubJobIn

router = APIRouter(tags=["crane_plan"])


class CraneStubIn(StubJobIn):
    ticket_id: int | None = None
    berth_slot: str = "B-07"


def _orphans(conn) -> list[dict]:
    """无岸桥计划支撑却已落正式册的放行——偏航清单。"""
    rows = conn.execute(
        """SELECT g.id, g.ticket_id, g.release_ref, g.crane_job_id,
                  g.crane_berth_slot, t.ticket_code, l.lane_code,
                  j.id AS crane_job_found, j.berth_slot AS release_berth_slot,
                  j.status AS release_job_status
           FROM gate_releases g
           JOIN weigh_tickets t ON t.id=g.ticket_id
           JOIN weigh_lanes l ON l.id=t.lane_id
           LEFT JOIN crane_plan_jobs j ON j.id=g.crane_job_id
           WHERE g.status='已放行' ORDER BY g.id DESC"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if not release_backed(d):
            d["reason"] = "无岸桥计划泊位行却已出正式放行"
            out.append(d)
    return out


@router.get("/api/crane/jobs")
def list_jobs(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT j.*, t.ticket_code, t.status ticket_status
               FROM crane_plan_jobs j
               LEFT JOIN weigh_tickets t ON t.id=j.ticket_id
               ORDER BY j.id DESC LIMIT 100"""
        ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["crane_plan_ready"] = plan_row_valid(r)
            items.append(d)
        orphans = _orphans(conn)
        return {
            "items": items,
            "unplanned_releases": orphans,
            "stub": True,
            "status": "空桩未对接",
            "ban_code": BAN_CODE,
        }


@router.get("/api/crane/plan/{ticket_id}")
def plan_for_ticket(ticket_id: int, authorization: AuthHeader = None):
    """放行页与车道页共用的单票泊位口径。"""
    require_user(authorization)
    with connect() as conn:
        ticket = conn.execute(
            "SELECT ticket_code FROM weigh_tickets WHERE id=?", (ticket_id,)
        ).fetchone()
        if not ticket:
            raise HTTPException(404, "过磅票不存在")
        row = conn.execute(
            """SELECT id, ticket_id, berth_slot, mode, status, detail
               FROM crane_plan_jobs
               WHERE ticket_id=? AND status NOT IN ('已取消','作废')
                 AND TRIM(COALESCE(berth_slot,'')) <> ''
               ORDER BY id DESC LIMIT 1""",
            (ticket_id,),
        ).fetchone()
        ready = plan_row_valid(row)
        return {
            "ticket_id": ticket_id,
            "ticket_code": ticket["ticket_code"],
            "crane_plan_ready": ready,
            "crane_job_id": row["id"] if ready else None,
            "berth_slot": row["berth_slot"] if ready else None,
            "ban_code": BAN_CODE,
        }


@router.post("/api/crane-stub")
def enqueue_stub(body: CraneStubIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        if body.ticket_id:
            ticket = conn.execute(
                "SELECT id FROM weigh_tickets WHERE id=?", (body.ticket_id,)
            ).fetchone()
            if not ticket:
                raise HTTPException(404, "过磅票不存在")
        if not (body.berth_slot or "").strip():
            raise HTTPException(422, "泊位不能为空")
        now = now_iso()
        cur = conn.execute(
            """INSERT INTO crane_plan_jobs(ticket_id,berth_slot,mode,status,detail,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                body.ticket_id,
                body.berth_slot.strip(),
                body.mode,
                "已排程" if body.ticket_id else "已入队",
                body.detail or "岸桥计划空桩预演",
                now,
            ),
        )
        write_audit(
            conn,
            user,
            "crane_stub",
            body.berth_slot,
            {"job_id": cur.lastrowid, "ticket_id": body.ticket_id},
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "status": "已排程" if body.ticket_id else "已入队",
            "crane_plan_ready": bool(body.ticket_id),
            "message": "空桩：未对接岸桥排程",
        }
