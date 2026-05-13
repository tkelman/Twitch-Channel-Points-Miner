#!/usr/bin/env python3

# usage: ./anonymize_log.py log/filename.log

import json, re, sys
from pathlib import Path
from datetime import datetime

assert len(sys.argv) > 1
with open(sys.argv[1]) as f:
    logdata = f.read()

with open("config.json") as f:
    configjson = json.load(f)
config_streamers = [s.lower() for s in configjson["streamers"]]

for (i, s) in enumerate(config_streamers):
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
