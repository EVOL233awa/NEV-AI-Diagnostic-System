"""阶段 4 离线测试：成员管理、预约闭环状态机、车辆双通道、统计与审计。

权限矩阵 + 业务流全部走 TestClient + 临时库，无任何云端调用。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.db.models import Appointment, Message, Session as ChatSession, User


# ---------- 成员管理（仅 admin，密码=账号名） ----------


def test_users_admin_only(client, owner_headers, staff_headers, admin_headers) -> None:
    assert client.get("/api/admin/users", headers=owner_headers).status_code == 403
    assert client.get("/api/admin/users", headers=staff_headers).status_code == 403
    assert client.get("/api/admin/users", headers=admin_headers).status_code == 200


def test_create_user_with_password_equals_username(client, admin_headers) -> None:
    r = client.post("/api/admin/users", headers=admin_headers, json={
        "username": "owner042", "display_name": "测试车主", "role": "owner",
        "vehicle_brand": "比亚迪", "vehicle_model": "海豹", "vehicle_plate": "桂A·T042",
    })
    assert r.status_code == 201, r.text
    # 新账号直接用账号名登录 + 拿到默认车辆
    login = client.post("/api/auth/login", json={"username": "owner042", "password": "owner042"})
    assert login.status_code == 200
    h = {"Authorization": f"Bearer {login.json()['token']}"}
    my = client.get("/api/vehicles", headers=h).json()["vehicles"]
    assert len(my) == 1 and my[0]["model_name"] == "海豹" and my[0]["is_default"]


def test_create_user_duplicates_and_invalid(client, admin_headers) -> None:
    assert client.post(
        "/api/admin/users", headers=admin_headers, json={"username": "user001", "role": "owner"}
    ).status_code == 409
    assert client.post(
        "/api/admin/users", headers=admin_headers, json={"username": "ab", "role": "owner"}
    ).status_code in (400, 422)  # Pydantic 长度校验先挡（422），正则兜底（400）
    assert client.post(
        "/api/admin/users", headers=admin_headers, json={"username": "newbie9", "role": "boss"}
    ).status_code == 400


def test_disable_and_self_lock_guard(client, admin_headers) -> None:
    r = client.post("/api/admin/users", headers=admin_headers, json={"username": "staff043", "role": "staff"})
    uid = r.json()["id"]
    # 停用后登录 403
    assert client.patch(f"/api/admin/users/{uid}", headers=admin_headers, json={"disabled": True}).status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": "staff043", "password": "staff043"}
    ).status_code == 403
    # 启用 + 重置密码（=账号名）
    assert client.patch(f"/api/admin/users/{uid}", headers=admin_headers, json={"disabled": False}).status_code == 200
    assert client.post(f"/api/admin/users/{uid}/reset-password", headers=admin_headers).status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": "staff043", "password": "staff043"}
    ).status_code == 200
    # 自停守卫：admin 不能停用/降级自己
    me = client.get("/api/auth/me", headers=admin_headers).json()["user"]["id"]
    assert client.patch(f"/api/admin/users/{me}", headers=admin_headers, json={"disabled": True}).status_code == 400
    assert client.patch(f"/api/admin/users/{me}", headers=admin_headers, json={"role": "staff"}).status_code == 400


def test_admin_set_password(client, admin_headers, staff_headers) -> None:
    r = client.post("/api/admin/users", headers=admin_headers, json={"username": "staff044", "role": "staff"})
    uid = r.json()["id"]
    url = f"/api/admin/users/{uid}/password"
    # 弱密码：过短 / 纯字母 / 含账号名
    assert client.post(url, headers=admin_headers, json={"new_password": "ab1"}).status_code == 400
    assert client.post(url, headers=admin_headers, json={"new_password": "abcdefgh"}).status_code == 400
    assert client.post(url, headers=admin_headers, json={"new_password": "Xstaff044Y9"}).status_code == 400
    # 店员无权设置他人密码
    assert client.post(url, headers=staff_headers, json={"new_password": "SafePass9"}).status_code == 403
    # 设置成功后旧密码（=账号名）失效、新密码可登录
    assert client.post(url, headers=admin_headers, json={"new_password": "SafePass9"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "staff044", "password": "staff044"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "staff044", "password": "SafePass9"}).status_code == 200
    # 管理员可给自己改密码，再重置回演示口径（密码=账号名，重置无强度校验）
    # 注意：账号名 admin 使一切含 "admin" 子串的密码都被规则拒绝，测试密码须避开
    me = client.get("/api/auth/me", headers=admin_headers).json()["user"]["id"]
    assert client.post(
        f"/api/admin/users/{me}/password", headers=admin_headers, json={"new_password": "Strong8Pass"}
    ).status_code == 200
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 401
    assert client.post(f"/api/admin/users/{me}/reset-password", headers=admin_headers).status_code == 200
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 200


# ---------- 预约闭环 ----------


def _mk_owner_with_diag(client, admin_headers, db, tag: str, privacy: bool = True) -> dict:
    """建一个车主账号 + 带诊断结论的会话，返回 {headers, session_id, owner_id}。"""
    username = f"owner{tag}"
    r = client.post("/api/admin/users", headers=admin_headers, json={"username": username, "role": "owner"})
    user_id = r.json()["id"]
    db.get(User, user_id).privacy_share_dialog = privacy
    db.commit()
    session = ChatSession(tenant_id=1, user_id=user_id, title=f"诊断-{tag}", channel="owner")
    db.add(session)
    db.flush()
    db.add(Message(tenant_id=1, session_id=session.id, role="user", content=f"车主{tag}的故障描述"))
    db.add(Message(
        tenant_id=1, session_id=session.id, role="assistant", content="结论",
        diag_json={
            "severity": "yellow", "summary": f"故障{tag}", "hypotheses": [{"title": "假设A"}],
            "steps": ["步骤1"], "pending_checks": ["检查1"],
        },
    ))
    db.commit()
    login = client.post("/api/auth/login", json={"username": username, "password": username})
    return {"headers": {"Authorization": f"Bearer {login.json()['token']}"},
            "session_id": session.id, "owner_id": user_id}


def test_appointment_full_lifecycle(client, staff_headers, admin_headers, db_session) -> None:
    owner = _mk_owner_with_diag(client, admin_headers, db_session, "701")
    future = (datetime.now() + timedelta(days=2)).replace(microsecond=0)

    # 车主一键预约（带会话 → 生成摘要卡）
    r = client.post("/api/appointments", headers=owner["headers"], json={
        "session_id": owner["session_id"], "appointment_time": future.isoformat(),
    })
    assert r.status_code == 201, r.text
    appt_id = r.json()["id"]

    # 店员队列可见，摘要卡在（决策 #15：摘要卡不受隐私开关影响）
    queue = client.get("/api/appointments", headers=staff_headers).json()["appointments"]
    row = next(a for a in queue if a["id"] == appt_id)
    assert row["status"] == "pending" and row["summary_card"]["summary"] == "故障701"

    # 隐私开启 → 店员可看对话原文
    dialog = client.get(f"/api/appointments/{appt_id}/dialog", headers=staff_headers)
    assert dialog.status_code == 200
    assert any("故障描述" in m["content"] for m in dialog.json()["messages"])

    # 接单（可改约时间）
    new_time = (datetime.now() + timedelta(days=3)).replace(microsecond=0)
    r = client.post(f"/api/appointments/{appt_id}/accept", headers=staff_headers,
                    json={"appointment_time": new_time.isoformat(), "shop_note": "备件已备"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    # pending → complete 直跳非法
    appt2 = client.post("/api/appointments", headers=owner["headers"],
                        json={"appointment_time": future.isoformat()})
    assert client.post(
        f"/api/appointments/{appt2.json()['id']}/complete", headers=staff_headers,
        json={"repair_result": "x"},
    ).status_code == 409
    # 回填 → completed
    r = client.post(f"/api/appointments/{appt_id}/complete", headers=staff_headers,
                    json={"repair_result": "更换模块后恢复正常"})
    assert r.status_code == 200 and r.json()["status"] == "completed"

    # 车主视角只看到自己的预约
    mine = client.get("/api/appointments", headers=owner["headers"]).json()["appointments"]
    assert {a["id"] for a in mine} == {appt_id, appt2.json()["id"]}


def test_appointment_privacy_blocks_dialog(client, staff_headers, admin_headers, db_session) -> None:
    owner = _mk_owner_with_diag(client, admin_headers, db_session, "702", privacy=False)
    future = (datetime.now() + timedelta(days=1)).isoformat()
    appt_id = client.post("/api/appointments", headers=owner["headers"],
                          json={"session_id": owner["session_id"], "appointment_time": future}).json()["id"]
    # 隐私关闭 → 原文 403，但摘要卡仍在队列行里
    assert client.get(f"/api/appointments/{appt_id}/dialog", headers=staff_headers).status_code == 403
    row = next(a for a in client.get("/api/appointments", headers=staff_headers).json()["appointments"]
               if a["id"] == appt_id)
    assert row["summary_card"]["summary"] == "故障702"
    # 车主打开开关后立即生效
    client.patch("/api/auth/privacy", headers=owner["headers"], json={"privacy_share_dialog": True})
    assert client.get(f"/api/appointments/{appt_id}/dialog", headers=staff_headers).status_code == 200


def test_appointment_owner_cancel_and_staff_cancel(client, staff_headers, admin_headers, db_session) -> None:
    owner = _mk_owner_with_diag(client, admin_headers, db_session, "703")
    future = (datetime.now() + timedelta(days=1)).isoformat()
    a1 = client.post("/api/appointments", headers=owner["headers"],
                     json={"appointment_time": future}).json()["id"]
    # 车主取消自己的 pending
    assert client.post(f"/api/appointments/{a1}/cancel", headers=owner["headers"],
                       json={"reason": "临时有事"}).status_code == 200
    # 店员取消 accepted 单
    a2 = client.post("/api/appointments", headers=owner["headers"],
                     json={"session_id": owner["session_id"], "appointment_time": future}).json()["id"]
    client.post(f"/api/appointments/{a2}/accept", headers=staff_headers, json={})
    assert client.post(f"/api/appointments/{a2}/cancel", headers=staff_headers,
                       json={"reason": "备件缺货"}).status_code == 200
    # 取消后再取消 → 409
    assert client.post(f"/api/appointments/{a2}/cancel", headers=staff_headers, json={}).status_code == 409
    # 车主不能看别人的预约
    other = _mk_owner_with_diag(client, admin_headers, db_session, "704")
    a3 = client.post("/api/appointments", headers=other["headers"],
                     json={"appointment_time": future}).json()["id"]
    assert client.get(f"/api/appointments/{a3}/dialog", headers=owner["headers"]).status_code in (401, 403, 404)
    assert client.post(f"/api/appointments/{a3}/cancel", headers=owner["headers"], json={}).status_code == 404


def test_appointment_time_in_past_rejected(client, db_session, admin_headers) -> None:
    owner = _mk_owner_with_diag(client, admin_headers, db_session, "705")
    past = (datetime.now() - timedelta(days=1)).isoformat()
    assert client.post("/api/appointments", headers=owner["headers"],
                       json={"appointment_time": past}).status_code == 400


# ---------- 车辆双通道 + 店员档案检索 ----------


def test_owner_adds_vehicle_and_sets_default(client, admin_headers) -> None:
    client.post("/api/admin/users", headers=admin_headers, json={"username": "owner706", "role": "owner"})
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'owner706', 'password': 'owner706'}).json()['token']}"}
    r = client.post("/api/vehicles", headers=h, json={
        "brand": "特斯拉", "model_name": "Model 3", "power_type": "EV", "plate_no": "桂B·706",
    })
    assert r.status_code == 201
    vehicles = client.get("/api/vehicles", headers=h).json()["vehicles"]
    assert len(vehicles) == 1 and vehicles[0]["is_default"] is True
    # 非法能源类型 / 空档案
    assert client.post("/api/vehicles", headers=h, json={"power_type": "SOLAR"}).status_code == 400
    assert client.post("/api/vehicles", headers=h, json={"power_type": "EV", "brand": ""}).status_code == 400


def test_staff_vehicle_search_no_dialog(client, staff_headers, admin_headers, db_session) -> None:
    owner = _mk_owner_with_diag(client, admin_headers, db_session, "707")
    # 给车主绑一辆车（admin 代填路径在 test_create_user_with_password_equals_username 覆盖；这里走 PATCH 数据准备）
    owner_user = db_session.get(User, owner["owner_id"])
    from backend.db.models import OwnerVehicle, VehicleProfile
    v = VehicleProfile(tenant_id=1, plate_no="桂A·707", brand="蔚来", model_name="ET5", power_type="EV")
    db_session.add(v)
    db_session.flush()
    db_session.add(OwnerVehicle(owner_id=owner_user.id, vehicle_id=v.id, is_default=True))
    # 把该车主已有诊断会话挂到这辆车上（生产中由 create_session 自动绑默认车）
    for s in db_session.query(ChatSession).filter_by(user_id=owner_user.id).all():
        s.vehicle_id = v.id
    db_session.commit()
    # 店员检索到档案 + 历史诊断摘要
    r = client.get("/api/vehicles/search", headers=staff_headers, params={"q": "桂A·707"})
    assert r.status_code == 200
    rows = r.json()["vehicles"]
    assert len(rows) == 1 and rows[0]["model_name"] == "ET5"
    assert rows[0]["history"] and rows[0]["history"][0]["summary"] == "故障707"
    # 检索结果不包含对话原文（结构上没有 messages 字段）
    assert "messages" not in rows[0]
    # 车主角色不能调店员检索
    assert client.get("/api/vehicles/search", headers=owner["headers"], params={"q": "x"}).status_code == 403
    assert client.get("/api/vehicles/search", headers=staff_headers, params={"q": "  "}).status_code == 400


def test_owner_deletes_vehicle_and_default_promotes(client, admin_headers, staff_headers) -> None:
    client.post("/api/admin/users", headers=admin_headers, json={"username": "owner708", "role": "owner"})
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'owner708', 'password': 'owner708'}).json()['token']}"}
    id1 = client.post("/api/vehicles", headers=h, json={"brand": "比亚迪", "plate_no": "桂B·801"}).json()["id"]
    id2 = client.post("/api/vehicles", headers=h, json={"brand": "蔚来", "plate_no": "桂B·802"}).json()["id"]
    # 首辆是默认车；删默认车 → 剩余首辆自动补位
    assert client.delete(f"/api/vehicles/{id1}", headers=staff_headers).status_code == 403
    assert client.delete(f"/api/vehicles/{id1}", headers=h).status_code == 200
    assert client.delete(f"/api/vehicles/{id1}", headers=h).status_code == 404
    vehicles = client.get("/api/vehicles", headers=h).json()["vehicles"]
    assert len(vehicles) == 1 and vehicles[0]["id"] == id2 and vehicles[0]["is_default"] is True
    # 店员检索不再返回已删档案
    rows = client.get("/api/vehicles/search", headers=staff_headers, params={"q": "桂B·801"}).json()["vehicles"]
    assert rows == []


# ---------- 统计与审计 ----------


def test_stats_and_audit_admin_only(client, owner_headers, staff_headers, admin_headers) -> None:
    assert client.get("/api/admin/stats", headers=staff_headers).status_code == 403
    stats = client.get("/api/admin/stats", headers=admin_headers).json()
    assert set(stats["usage"]) == {"today", "week", "month"}
    assert set(stats["appointments"]) >= {"completed", "cancelled"}  # 前面用例产生过流转
    logs = client.get("/api/admin/audit-logs", headers=admin_headers).json()["logs"]
    actions = {row["action"] for row in logs}
    assert {"user_create", "appointment_create", "appointment_accept", "appointment_complete"} <= actions
