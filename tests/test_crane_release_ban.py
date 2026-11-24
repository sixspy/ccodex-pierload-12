"""岸桥禁放第12号（岸桥案丑）—— 三红基线。

唯一正确性口径：岸桥计划（crane_plan_jobs 的匹配泊位行）。
本文件在改任何业务代码之前先落三个失败测，并用测试器见红：

    甲  test_12jia_*   无岸桥计划仍能放行，正式册（gate_releases）被增量
    乙  test_12yi_*    对账/证明把未晋升的放行意图误标为已放行
    丙  test_12bing_*  双人同票抢放行不占闸口锁，败方不记争用痕

`no_crane_plan_release_fixture` 就是“无岸桥计划却能出正式放行”的造假绿夹具：
它绕过写口直接落一条正式放行，复现“岸桥页空而对账已放行”。
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db, now_iso

BAN_CODE = "岸桥禁放第12号"
FAKE_RELEASE_OFFICER = "造假夹具"


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db()
    yield


def _auth(c: TestClient, user: str = "admin", password: str = "admin123") -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": password}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _make_ticket(c: TestClient, h: dict, code: str, gross: float = 11.5) -> dict:
    lanes = c.get("/api/lanes", headers=h).json()["items"]
    lane = next(x for x in lanes if x["lane_code"] == "LN-S-01-OUT")
    res = c.post(
        "/api/tickets",
        headers=h,
        json={
            "lane_id": lane["id"],
            "bl_ref": "BL-2026-0102",
            "vehicle_plate": "测岸·12",
            "axle_weights": [
                {"axle": 1, "w": 6.0},
                {"axle": 2, "w": round(gross - 6.0, 3)},
            ],
            "ticket_code": code,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "已裁定", body
    return body


def _add_crane_plan(
    c: TestClient, h: dict, ticket_id: int, berth: str = "CR-L12"
) -> dict:
    res = c.post(
        "/api/crane-stub",
        headers=h,
        json={"ticket_id": ticket_id, "berth_slot": berth},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _official_release_count(c: TestClient, h: dict) -> int:
    return c.get("/api/dashboard", headers=h).json()["gate_releases"]


def _release(c: TestClient, h: dict, ticket_id: int, officer: str = "闸口值班"):
    return c.post(
        "/api/gate/release",
        headers=h,
        json={"ticket_id": ticket_id, "officer": officer},
    )


def _seed_unbacked_formal_release(c: TestClient, h: dict, code: str) -> dict:
    """造假绿：绕过放行写口，直接落一条没有岸桥计划支撑的正式放行。"""
    ticket = _make_ticket(c, h, code)
    with connect() as conn:
        lane_id = conn.execute(
            "SELECT lane_id FROM weigh_tickets WHERE id=?", (ticket["id"],)
        ).fetchone()["lane_id"]
        conn.execute(
            """INSERT INTO gate_releases(ticket_id,lane_id,release_ref,status,officer,released_at)
               VALUES (?,?,?,?,?,?)""",
            (
                ticket["id"],
                lane_id,
                f"PL-{code}",
                "已放行",
                FAKE_RELEASE_OFFICER,
                now_iso(),
            ),
        )
        conn.execute(
            "UPDATE weigh_tickets SET status='已放行' WHERE id=?", (ticket["id"],)
        )
        conn.commit()
    return ticket


@pytest.fixture
def no_crane_plan_release_fixture():
    """夹具：无岸桥计划、岸桥页空，却已有正式放行 PL-*（目前为造假绿）。"""
    c = TestClient(app)
    h = _auth(c)
    ticket = _seed_unbacked_formal_release(c, h, "WT-CR12-YI")
    return c, h, ticket


def test_12jia_no_plan_release_atomically_rejected_official_zero_increment():
    """甲：无岸桥计划时放行写口原子拒收，正式册零增。"""
    c = TestClient(app)
    h = _auth(c)
    ticket = _make_ticket(c, h, "WT-CR12-JIA")
    before = _official_release_count(c, h)

    res = _release(c, h, ticket["id"])
    assert res.status_code == 409, res.text
    assert "岸桥" in res.text

    # 正式册零增
    assert _official_release_count(c, h) == before
    detail = c.get(f"/api/tickets/{ticket['id']}", headers=h).json()
    assert detail["ticket"]["status"] == "已裁定"
    assert detail["gate_releases"] == []
    jobs = c.get("/api/crane/jobs", headers=h).json()["items"]
    assert all(j["ticket_id"] != ticket["id"] for j in jobs)

    # 偏离纪要：记岸桥禁放偏航并拒写
    audit = c.get("/api/audit?limit=50", headers=h).json()["items"]
    assert any(a["action"] == "crane_release_deviation" for a in audit), audit


def test_12yi_reconcile_does_not_mark_unpromoted_release_as_released(
    no_crane_plan_release_fixture,
):
    """乙：对账/证明不得把无岸桥计划支撑的放行意图标为已放行。"""
    c, h, ticket = no_crane_plan_release_fixture

    proof = c.get(f"/api/proof/ticket/{ticket['ticket_code']}", headers=h).json()
    assert proof.get("crane_plan_ready") is False, proof
    assert proof.get("released") is False, proof
    assert proof.get("release_state") != "已放行", proof

    recon = c.get("/api/reconcile/BL-2026-0102", headers=h).json()
    row = next(
        x for x in recon["tickets"] if x["ticket_code"] == ticket["ticket_code"]
    )
    assert row.get("crane_plan_ready") is False, row
    assert row.get("released") is False, row
    assert row.get("release_state") != "已放行", row


def test_12bing_two_sessions_same_ticket_one_release_contention_logged():
    """丙：两路会话并发打同票放行，占闸口锁；败方只记争用痕不增放行。"""
    c = TestClient(app)
    h_admin = _auth(c, "admin", "admin123")
    h_writer = _auth(c, "writer", "writer123")
    ticket = _make_ticket(c, h_admin, "WT-CR12-BING")
    _add_crane_plan(c, h_admin, ticket["id"], "CR-L12")
    before = _official_release_count(c, h_admin)

    barrier = threading.Barrier(2)
    results: list[tuple[str, int, str]] = []
    results_lock = threading.Lock()

    def _strike(headers: dict, officer: str) -> None:
        client = TestClient(app)
        barrier.wait()
        res = _release(client, headers, ticket["id"], officer)
        with results_lock:
            results.append((officer, res.status_code, res.text))

    threads = [
        threading.Thread(target=_strike, args=(h_admin, "甲班")),
        threading.Thread(target=_strike, args=(h_writer, "乙班")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    codes = sorted(code for _, code, _ in results)
    assert codes == [200, 409], results
    assert _official_release_count(c, h_admin) == before + 1

    releases = c.get("/api/gate/releases", headers=h_admin).json()["items"]
    same = [x for x in releases if x["ticket_code"] == ticket["ticket_code"]]
    assert len(same) == 1, same

    cont = c.get("/api/contention", headers=h_admin).json()["items"]
    gate_rows = [x for x in cont if x["lock_key"] == f"gate:{ticket['id']}"]
    assert len(gate_rows) == 1, cont
    loser = next(r for r in results if r[1] == 409)
    assert "争用" in loser[2], loser

    # 闸口占用锁在正式落册后不释放：第三方再来仍只落争用痕，不增放行。
    third = _release(c, h_admin, ticket["id"], "丙班")
    assert third.status_code == 409
    assert _official_release_count(c, h_admin) == before + 1
    cont2 = c.get("/api/contention", headers=h_admin).json()["items"]
    assert len([x for x in cont2 if x["lock_key"] == f"gate:{ticket['id']}"]) == 2


def test_12jia_ban_memo_sealed_and_path_declared():
    """裁决写入纪要当日封死：纪要存在、甲路径与禁第三路须明写。"""
    from pathlib import Path

    from crane_gate import BAN_CODE, BAN_MEMO, BAN_SEALED_AT

    memo = Path(__file__).resolve().parents[1] / BAN_MEMO
    assert memo.exists(), BAN_MEMO
    text = memo.read_text(encoding="utf-8")
    assert BAN_CODE in text
    assert BAN_SEALED_AT in text
    assert "甲" in text and "原子拒收" in text
    assert "第三路" in text and "禁止" in text
    assert "两边不得混用" in text

