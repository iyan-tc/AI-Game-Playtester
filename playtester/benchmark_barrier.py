"""Release a short matrix benchmark together after every hosted runner is ready."""
import json
import os
import time
from datetime import datetime
from urllib.request import Request, urlopen


def main():
    expected=len(json.loads(os.environ["SHARDS"]))
    job_url=f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}/attempts/{os.environ['GITHUB_RUN_ATTEMPT']}/jobs"
    request=Request(job_url,headers={"Authorization":"Bearer "+os.environ["GH_TOKEN"],
                                     "Accept":"application/vnd.github+json"})
    deadline=time.monotonic()+100
    while time.monotonic()<deadline:
        with urlopen(request,timeout=10) as r:
            jobs=json.load(r)["jobs"]
        ready=[step["started_at"] for job in jobs for step in job["steps"]
               if step["name"]=="Coordinate browser benchmark" and step["status"] in {"in_progress","completed"}
               and step.get("started_at")]
        if len(ready)==expected:
            last=max(datetime.fromisoformat(t).timestamp() for t in ready)
            time.sleep(max(0,last+12-time.time()))
            return
        time.sleep(3)
    raise SystemExit("Timed out waiting for hosted benchmark peers")


if __name__=="__main__":
    main()

