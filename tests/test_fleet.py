import json
from decimal import Decimal

import pytest

from playtester.fleet import run_batch, seats


def test_matrix_preserves_batch_budget_and_scopes_credentials(monkeypatch,tmp_path):
    values=[dict(game="demo",persona="explorer",username=f"ai_{i}",password="private",url="https://example.invalid/") for i in range(5)]
    monkeypatch.setenv("PLAYTEST_SEATS_JSON",json.dumps(values))
    seen=[]
    def run(args,env,check):
        assert "PLAYTEST_SEATS_JSON" not in env
        seen.append((args[-1],env["PLAYTEST_USERNAME"]))
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("playtester.fleet.subprocess.run",run)
    roles=seats(json.dumps(values),5)
    for index in range(5):
        assert run_batch(roles,[index],Decimal(1),tmp_path,2)==0
    assert sum(Decimal(cost) for cost,_ in seen)==1 and len({s for _,s in seen})==5
    values[4]["username"]=values[0]["username"]
    with pytest.raises(ValueError):
        seats(json.dumps(values),5)

