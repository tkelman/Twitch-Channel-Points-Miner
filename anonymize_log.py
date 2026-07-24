#!/usr/bin/env python3

# usage: ./anonymize_log.py log/filename.log

import json, os, re, sys
from pathlib import Path
from datetime import datetime

assert len(sys.argv) > 1
with open(sys.argv[1]) as f:
    logdata = f.read()

with open("config.json") as f:
    configjson = json.load(f)
streamers = [s.lower() for s in configjson["streamers"]]

# iterate through watch streak cache file to detect duplicate channel ids
# append old/removed streamer names for anonymizing older files
newnames = {}
oldnames = []
watchstreakcache = "log/watch_streak_cache.{}.json".format(configjson["username"])
if os.path.isfile(watchstreakcache):
    with open(watchstreakcache) as f:
        cachejson = json.load(f)
    for entry in cachejson["entries"]:
        if entry["channel_id"] in newnames:
            if entry["checked_at"] <= newnames[entry["channel_id"]]["checked_at"]:
                # this entry is older than what's saved in newnames for same channel id
                oldnames.append(entry)
                continue
            else: # this entry is newer than what's saved in newnames for same channel id
                # so before overwriting the entry in newnames, back up the older entry
                # from newnames to oldnames
                oldnames.append(newnames[entry["channel_id"]])
        newnames[entry["channel_id"]] = entry

    for oldentry in sorted(oldnames, key=lambda e: e["checked_at"]):
        oldname = oldentry["streamer_login"].lower()
        newname = newnames[oldentry["channel_id"]]["streamer_login"].lower()
        print("rename detected from", oldname, "to", newname)
        streamers.append(oldname)

already_anonymized = True
for s in streamers:
    if " {} ".format(s) in logdata or " {} ".format(s.capitalize()) in logdata:
        already_anonymized = False
        break

if already_anonymized:
    maxnum = len(streamers) + 5000
    streamers = []
    for i in range(1, maxnum):
        if (" streamer{} ".format(i) in logdata or
            " Streamer{} ".format(i) in logdata or
            " streamer{}:".format(i) in logdata or
            " Streamer{}:".format(i) in logdata or
            " streamer{}\n".format(i) in logdata):
            streamers.append("streamer{}".format(i))

for (i, s) in enumerate(streamers):
    logdata = logdata.replace(" {} ".format(s), " streamer{} ".format(i + 1))
    logdata = logdata.replace(" {} ".format(s.capitalize()), " Streamer{} ".format(i + 1))
    logdata = logdata.replace(" {}:".format(s), " streamer{}:".format(i + 1))
    logdata = logdata.replace(" {}:".format(s.capitalize()), " Streamer{}:".format(i + 1))
    logdata = logdata.replace(" {}\n".format(s), " streamer{}\n".format(i + 1))

lines = logdata.splitlines()
raidtargets = []
for line in lines:
    raid = re.match(r".* Joining raid from (.*) to (.*)", line)
    if raid:
        #if not re.match(r"streamer\d+", raid.group(1)):
        #   print(line)
        assert re.match(r"streamer\d+", raid.group(1))
        if not re.match(r"streamer\d+", raid.group(2)) and raid.group(2) not in raidtargets:
            raidtargets.append(raid.group(2))

for (i, s) in enumerate(raidtargets):
    logdata = logdata.replace(" {}\n".format(s), " raidtarget{}\n".format(i + 1))

anonfile = Path(__file__).parent / "log" / ("miner" + datetime.now().strftime("%Y-%m-%dT%H-%M-%S") + ".log")
with anonfile.open("w") as f:
    f.write(logdata)
