from polymarket_btc_bot.audit import AuditLog


def test_audit_log_appends_and_tails_jsonl(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(path)

    audit.append({"event_type": "paper_decision", "id": 1})
    audit.append({"event_type": "paper_decision", "id": 2})

    assert audit.tail(1) == [{"event_type": "paper_decision", "id": 2}]
    assert len(audit.tail(5)) == 2
