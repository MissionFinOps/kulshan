from kulshan.reckoner.contracts import PeriodSpec, QuerySpec
from kulshan.reckoner.investigations import built_in_investigations
from kulshan.reckoner.sessions import InvestigationSession, load_session, save_session


def test_investigation_modules_and_session_round_trip(tmp_path):
    assert [item.module_id for item in built_in_investigations()] == [
        "compute-cost",
        "storage-cost",
        "data-transfer-cost",
    ]
    session = InvestigationSession("s-1")
    query = QuerySpec(metric="unblended-cost", period=PeriodSpec("last-7-days"))
    session.add(query, breadcrumb=("service",), note="review")
    path = tmp_path / "session.json"
    save_session(session, path)
    loaded = load_session(path)
    assert loaded.entries[0].query.to_dict() == query.to_dict()
    loaded.close()
