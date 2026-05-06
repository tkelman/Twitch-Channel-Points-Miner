#!/usr/bin/env python3

# usage: ./flag_missed_streaks.py log/logfile1.log log/logfile2.log
# go through the streak lengths in the initial "Loading data" section
# for the two files and flag any streaks that are expiring or decreased

# this won't say anything about streamers who went online during a log file
# and were missed by the miner, but started and ended with streak length of 0

import re, sys

assert len(sys.argv) > 2
streaks = [{}, {}]
for i in [0, 1]:
    with open(sys.argv[i + 1]) as f:
        lines = f.readlines()

    for line in lines:
        if "expires at" in line:
            print(line.strip())
        data = re.match(r".* (.*) \(.* points\) .* \| streak length (\d+).*", line)
        if data:
            streamer = data.group(1)
            streaklen = int(data.group(2))
            if streamer in streaks[i]:
                print(streamer, "repeated multiple times in", sys.argv[i + 1])
                assert streaks[i][streamer] == streaklen
            streaks[i][streamer] = streaklen

        if re.match(r"\[INFO\] (.*): ✅ \d+ Streamer loaded! \(.*\)", line):
            break

totaldecrease = 0
totalincrease = 0
for streamer, streaklen in streaks[0].items():
    if streamer in streaks[1]:
        streaklen2 = streaks[1][streamer]
        if streaklen2 < streaklen:
            totaldecrease += streaklen - streaklen2
            print(streamer, "streak length decreased from", streaklen, "to", streaklen2)
        elif streaklen2 > streaklen:
            totalincrease += streaklen2 - streaklen
        #    print(streamer, "streak length increased from", streaklen, "to", streaklen2)
    else:
        print(streamer, "in", sys.argv[1], "but not in", sys.argv[2])

for streamer in streaks[1]:
    if streamer not in streaks[0]:
        print(streamer, "in", sys.argv[2], "but not in", sys.argv[1])

print("total missed streak lengths decreased by", totaldecrease)
print("total extended streak lengths increased by", totalincrease)
