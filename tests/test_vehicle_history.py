"""车辆里程与完整诊断历史：校验、清空、归属、租户隔离、摘要不含原文。"""
from __future__ import annotations

from backend.db.models import Case, Message, Session as ChatSession, User, VehicleProfile


def _owner(db) -> User:
    return db.query(User).filter(User.username == "user001").one()


def _create_vehicle(client, headers, **overrides) -> int:
    body = {
        "brand": "广汽埃安", "model_name": "AION S", "model_year": "2024",
        "power_type": "EV", "vin": "LGAHIST000000001", "plate_no": "桂A·9H001",
        "notes": "历史测试车", "mileage": 32000,
    }
    body.update(overrides)
    r = client.post("/api/vehicles", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _diag_message(db, vehicle_id: int, severity: str, summary: str, stage: str | None = None,
                  with_case: bool = False) -> ChatSession:
    owner = _owner(db)
    session = ChatSession(
        tenant_id=owner.tenant_id, user_id=owner.id, vehicle_id=vehicle_id,
        title=f"历史-{summary}", channel="owner",
        case_notes={"stage": stage} if stage else None,
    )
    db.add(session)
    db.flush()
    db.add(Message(
        tenant_id=owner.tenant_id, session_id=session.id, role="assistant",
        content="诊断正文", diag_json={"severity": severity, "summary": summary,
                                    "hypotheses": [{"title": summary}], "steps": []},
    ))
    if with_case:
        db.add(Case(
            tenant_id=owner.tenant_id, vehicle_id=vehicle_id, session_id=session.id,
            title=summary, symptoms="", diagnosis="", repair_result="",
        ))
    db.commit()
    return session


class TestMileage:
    def test_create_and_update_and_clear(self, client, owner_headers):
        vid = _create_vehicle(client, owner_headers)
        vehicles = client.get("/api/vehicles", headers=owner_headers).json()["vehicles"]
        row = next(v for v in vehicles if v["id"] == vid)
        assert row["mileage"] == 32000
        assert row["history"] == []

        r = client.patch(f"/api/vehicles/{vid}", json={"mileage": 45678}, headers=owner_headers)
        assert r.status_code == 200
        vehicles = client.get("/api/vehicles", headers=owner_headers).json()["vehicles"]
        assert next(v for v in vehicles if v["id"] == vid)["mileage"] == 45678

        r = client.patch(f"/api/vehicles/{vid}", json={"mileage": None}, headers=owner_headers)
        assert r.status_code == 200
        vehicles = client.get("/api/vehicles", headers=owner_headers).json()["vehicles"]
        assert next(v for v in vehicles if v["id"] == vid)["mileage"] is None

        # 未提交 mileage 时不能把已有里程清空（model_fields_set 语义）
        client.patch(f"/api/vehicles/{vid}", json={"mileage": 500}, headers=owner_headers)
        client.patch(f"/api/vehicles/{vid}", json={"notes": "只改备注"}, headers=owner_headers)
        vehicles = client.get("/api/vehicles", headers=owner_headers).json()["vehicles"]
        assert next(v for v in vehicles if v["id"] == vid)["mileage"] == 500

    def test_out_of_range_rejected_with_400(self, client, owner_headers):
        for value in (-1, 2_000_001):
            assert client.post("/api/vehicles", json={
                "brand": "测试", "mileage": value,
            }, headers=owner_headers).status_code == 400
        vid = _create_vehicle(client, owner_headers)
        assert client.patch(f"/api/vehicles/{vid}", json={"mileage": -5},
                            headers=owner_headers).status_code == 400
        assert client.patch(f"/api/vehicles/{vid}", json={"mileage": 1_500_000},
                            headers=owner_headers).status_code == 200


class TestHistory:
    def test_summary_fields_and_pagination(self, client, db_session, owner_headers):
        vid = _create_vehicle(client, owner_headers)
        first = _diag_message(db_session, vid, "yellow", "低温续航衰减", stage="conclusion")
        second = _diag_message(db_session, vid, "red", "电池组故障", stage="verification", with_case=True)
        third = _diag_message(db_session, vid, "green", "胎压偏低", stage="intake")

        body = client.get(f"/api/vehicles/{vid}/history", headers=owner_headers).json()
        assert body["vehicle_id"] == vid
        assert body["total"] == 3
        assert [item["session_id"] for item in body["items"]] == [third.id, second.id, first.id]
        red = next(item for item in body["items"] if item["session_id"] == second.id)
        assert red["severity"] == "red" and red["summary"] == "电池组故障"
        assert red["stage"] == "verification" and red["has_case"] is True
        assert red["session_title"] == "历史-电池组故障"
        assert "content" not in red and "symptoms" not in red

        page = client.get(f"/api/vehicles/{vid}/history", params={"limit": 1, "offset": 1},
                          headers=owner_headers).json()
        assert page["total"] == 3
        assert [item["session_id"] for item in page["items"]] == [second.id]

        assert client.get(f"/api/vehicles/{vid}/history", params={"limit": 0},
                          headers=owner_headers).status_code == 400
        assert client.get(f"/api/vehicles/{vid}/history", params={"offset": -1},
                          headers=owner_headers).status_code == 400

    def test_owner_binding_and_tenant_isolation(self, client, db_session, owner_headers, staff_headers):
        owner = _owner(db_session)
        stranger_vehicle = VehicleProfile(
            tenant_id=owner.tenant_id, brand="未绑定", model_name="X", vin="LGAUNBOUND000001",
        )
        db_session.add(stranger_vehicle)
        db_session.commit()
        _diag_message(db_session, stranger_vehicle.id, "yellow", "未绑定车诊断")

        assert client.get(f"/api/vehicles/{stranger_vehicle.id}/history",
                          headers=owner_headers).status_code == 404
        assert client.patch(f"/api/vehicles/{stranger_vehicle.id}", json={"notes": "x"},
                            headers=owner_headers).status_code == 404
        assert client.delete(f"/api/vehicles/{stranger_vehicle.id}",
                             headers=owner_headers).status_code == 404

        staff_body = client.get(f"/api/vehicles/{stranger_vehicle.id}/history",
                                headers=staff_headers).json()
        assert staff_body["total"] == 1 and staff_body["items"][0]["summary"] == "未绑定车诊断"

        other_tenant = VehicleProfile(
            tenant_id=999, brand="别家店", model_name="Y", vin="LGAOTHER00000001",
        )
        db_session.add(other_tenant)
        db_session.commit()
        assert client.get(f"/api/vehicles/{other_tenant.id}/history",
                          headers=staff_headers).status_code == 404
        assert client.get(f"/api/vehicles/{other_tenant.id}/history",
                          headers=owner_headers).status_code == 404

    def test_staff_search_includes_mileage_and_history(self, client, db_session, owner_headers, staff_headers):
        vid = _create_vehicle(client, owner_headers, vin="LGASEARCH0000001", plate_no="桂A·9S001")
        _diag_message(db_session, vid, "yellow", "检索命中诊断")
        body = client.get("/api/vehicles/search", params={"q": "LGASEARCH"},
                          headers=staff_headers).json()
        row = next(v for v in body["vehicles"] if v["id"] == vid)
        assert row["mileage"] == 32000
        assert row["history"][0]["summary"] == "检索命中诊断"
