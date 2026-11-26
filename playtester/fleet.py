"""Private workflow entry. Allocate the whole batch before sharding it."""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr

from .parallel import allocate


class Seat(BaseModel):
    game: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    persona: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    username: SecretStr
    password: SecretStr
    url: SecretStr


def seats(value, count):
    rows=[Seat.model_validate(r) for r in json.loads(value)[:count]]
    accounts={r.username.get_secret_value() for r in rows}
    if len(rows)!=count or len(accounts)!=count or "" in accounts:
        raise ValueError("Missing independent test accounts")
    return rows


def run_batch(rows, indexes, budget, output, steps):
    share=allocate(budget,len(rows))
    def run(i):
        seat=rows[i]
        env=dict(os.environ,PLAYTEST_USERNAME=seat.username.get_secret_value(),
                 PLAYTEST_PASSWORD=seat.password.get_secret_value(),PLAYTEST_GAME_URL=seat.url.get_secret_value())
        env.pop("PLAYTEST_SEATS_JSON",None)
        return subprocess.run([sys.executable,"-m","playtester.cli","run","--game",seat.game,"--persona",seat.persona,
            "--run-id",f"seat-{i+1}","--steps",str(steps),"--output",str(output),"--max-budget-usd",share],
            env=env,check=False).returncode
    with ThreadPoolExecutor(max_workers=len(indexes)) as pool:
        return int(any(list(pool.map(run,indexes))))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--count",type=int,choices=(1,2,5),required=True)
    p.add_argument("--shard",type=int,default=-1)
    p.add_argument("--budget",type=Decimal,default=Decimal(1))
    p.add_argument("--steps",type=int,choices=range(1,51),default=50)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if not -1 <= args.shard < args.count:
        p.error("Invalid shard")
    try:
        rows=seats(os.environ["PLAYTEST_SEATS_JSON"],args.count)
    except Exception:
        p.exit(2,"Invalid private seat configuration\n")
    indexes=list(range(args.count)) if args.shard<0 else [args.shard]
    return run_batch(rows,indexes,args.budget,args.output,args.steps)


if __name__=="__main__":
    raise SystemExit(main())

