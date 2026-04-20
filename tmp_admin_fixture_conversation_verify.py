from __future__ import annotations

from tmp_admin_fixture_family_verify import FixtureAdminClient


def main() -> None:
    grouped_client = FixtureAdminClient()
    answer, _ = grouped_client.send("branch wise risk")
    assert "branch-wise breakdown" in answer.lower()
    answer, _ = grouped_client.send("only CSE")
    assert "matching students" in answer.lower()
    answer, _ = grouped_client.send("continue")
    assert "action list" in answer.lower() or "operational" in answer.lower() or "governance move" in answer.lower()

    deep_client = FixtureAdminClient()
    answer, _ = deep_client.send("which branch has good attendance but high risk")
    assert "hidden risk" in answer.lower() or "attendance" in answer.lower()
    answer, _ = deep_client.send("ok")
    assert "action list" in answer.lower() or "operational" in answer.lower()
    answer, _ = deep_client.send("why is that happening")
    assert "attendance" in answer.lower() or "risk" in answer.lower() or "driver" in answer.lower()
    answer, _ = deep_client.send("what is main cause")
    assert "factor" in answer.lower() or "driver" in answer.lower() or "pressure" in answer.lower()
    answer, _ = deep_client.send("how to fix it")
    assert "action" in answer.lower() or "priority" in answer.lower() or "governance" in answer.lower()
    answer, _ = deep_client.send("give full solution plan")
    assert "action list" in answer.lower() or "governance" in answer.lower() or "plan" in answer.lower()

    print("Admin fixture conversation verification passed.")


if __name__ == "__main__":
    main()
