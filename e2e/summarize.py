"""Prints the failing cases from e2e/results.json, one block each (run from frontend/)."""
import json
import re

d = json.load(open("e2e/results.json", encoding="utf-8"))
tot = {"passed": 0, "failed": 0, "skipped": 0}


def clean(t):
    return re.sub(r"\x1b\[[0-9;]*m", "", t or "")


def walk(s, path=""):
    for sp in s.get("specs", []):
        for t in sp["tests"]:
            for r in t["results"]:
                key = "passed" if r["status"] == "passed" else ("skipped" if r["status"] == "skipped" else "failed")
                tot[key] += 1
                if key == "failed":
                    print("FAIL", t["projectName"], "|", sp["title"][:70])
                    print("   ", clean(r.get("error", {}).get("message"))[:600].replace("\n", " | "))
    for c in s.get("suites", []):
        walk(c)


for s in d["suites"]:
    walk(s)
print(tot)
