"""Run independent account configurations concurrently with a shared batch ceiling."""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import yaml


def allocate(total, count):
    if not 1 <= count <= 5 or not Decimal(0) < total <= 1:
        raise ValueError("Expected one to five accounts and a batch budget in (0,1]")
    amount=(total/count).quantize(Decimal(".00000001"),rounding=ROUND_DOWN)
    if not amount:
        raise ValueError("Budget too small to split")
    return str(amount)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--budget",type=Decimal,default=Decimal("1"))
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    jobs=yaml.safe_load(args.manifest.read_text(encoding="utf-8"))["players"]
    budget=allocate(args.budget,len(jobs))
    accounts=[os.environ[j["username_env"]] for j in jobs]
    if len(set(accounts))!=len(accounts):
        raise ValueError("Each browser needs its own test account")
    def run(pair):
        index,job=pair
        env=dict(os.environ,PLAYTEST_USERNAME=accounts[index],PLAYTEST_PASSWORD=os.environ[job["password_env"]])
        argv=[sys.executable,"-m","playtester.cli","run","--game",job["game"],"--persona",job["persona"],
              "--output",str(args.output),"--run-id",f"player-{index+1}","--max-budget-usd",budget]
        return subprocess.run(argv,env=env,check=False).returncode
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return int(any(list(pool.map(run,enumerate(jobs)))))


if __name__=="__main__":
    raise SystemExit(main())

