from __future__ import annotations

from neverplayalone_backend.utils.time import utc_now_ts

from .conftest import build_agent_tarball


def test_round_submission_and_publication_flow(client) -> None:
    now = utc_now_ts()
    response = client.post("/admin/bootstrap", json={"first_round_start_at": now + 60})
    assert response.status_code == 200
    round_id = response.json()["round_id"]

    current = client.get("/miner/rounds/current")
    assert current.status_code == 200
    assert current.json()["submission_round"]["round_id"] == round_id

    slot = client.post("/miner/submissions/slot", json={"miner_uid": 7, "filename": "agent.tar.gz"})
    assert slot.status_code == 200
    slot_body = slot.json()

    upload = client.put(slot_body["upload_url"], content=build_agent_tarball())
    assert upload.status_code == 200

    finalized = client.post("/miner/submissions/finalize", json={"submission_id": slot_body["submission_id"]})
    assert finalized.status_code == 200
    assert finalized.json()["accepted"] is True

    frozen = client.post(f"/admin/rounds/{round_id}/freeze", json={"freeze_block_hash": "0x1234"})
    assert frozen.status_code == 200
    next_round_id = frozen.json()["next_round_id"]
    assert next_round_id == round_id + 1

    rounds = client.get("/validator/rounds/current")
    assert rounds.status_code == 200
    payload = rounds.json()
    assert payload["submission_round"]["round_id"] == next_round_id
    assert payload["evaluating_round"]["round_id"] == round_id

    roster = client.get(f"/validator/rounds/{round_id}/roster")
    assert roster.status_code == 200
    roster_body = roster.json()
    assert roster_body["freeze_block_hash"] == "0x1234"
    assert len(roster_body["entries"]) == 1

    report_slot = client.post(
        "/validator/artifacts/slot",
        json={
            "round_id": round_id,
            "validator_uid": 3,
            "miner_uid": 7,
            "miner_hotkey": "auth-disabled",
            "artifact_kind": "report_json",
        },
    )
    assert report_slot.status_code == 200
    report_slot_body = report_slot.json()
    report_upload = client.put(report_slot_body["upload_url"], content=b'{"score":1}')
    assert report_upload.status_code == 200

    recording_slot = client.post(
        "/validator/artifacts/slot",
        json={
            "round_id": round_id,
            "validator_uid": 3,
            "miner_uid": 7,
            "miner_hotkey": "auth-disabled",
            "artifact_kind": "recording_mcpr",
        },
    )
    assert recording_slot.status_code == 200
    recording_slot_body = recording_slot.json()
    recording_upload = client.put(recording_slot_body["upload_url"], content=b"mcpr")
    assert recording_upload.status_code == 200

    scoreboard = client.post(
        "/validator/scoreboards",
        json={
            "round_id": round_id,
            "validator_uid": 3,
            "stake_weight": 9.5,
            "rows": [
                {
                    "miner_uid": 7,
                    "miner_hotkey": "auth-disabled",
                    "score": 1.0,
                    "status": "ok",
                    "report_s3_key": report_slot_body["storage_key"],
                    "recording_s3_key": recording_slot_body["storage_key"],
                }
            ],
        },
    )
    assert scoreboard.status_code == 200

    listed = client.get(f"/validator/rounds/{round_id}/scoreboards")
    assert listed.status_code == 200
    listed_body = listed.json()
    assert len(listed_body) == 1
    assert listed_body[0]["rows"][0]["score"] == 1.0

    consensus = client.post(
        "/validator/consensus-results",
        json={
            "round_id": round_id,
            "validator_uid": 3,
            "top_miner_uid": 7,
            "top_miner_hotkey": "auth-disabled",
        },
    )
    assert consensus.status_code == 200


def test_public_endpoints_gate_before_round_end(client) -> None:
    now = utc_now_ts()
    response = client.post("/admin/bootstrap", json={"first_round_start_at": now + 10})
    round_id = response.json()["round_id"]
    blocked = client.get(f"/public/rounds/{round_id}")
    assert blocked.status_code == 403
