#!/usr/bin/env python3

# usage: ./flag_missed_streaks.py log/logfile1.log log/logfile2.log
# go through the streak lengths in the initial "Loading data" section
# for the two files and flag any streaks that are expiring or decreased

# this won't say anything about streamers who went online during a log file
# and were missed by the miner, but started and ended with streak length of 0

import re, sys

assert len(sys.argv) > 2
streaks = [{}, {}]
onlines = [set(), set()] # set of streamers that are online at the end of first file, start of second
initialized = [False, False]
for i in [0, 1]:
    with open(sys.argv[i + 1]) as f:
        lines = f.readlines()

    for line in lines:
        if "expires at" in line: # and not initialized[i]: # decide whether to gate this print
            print(line.strip())
        data = re.match(r".* (.*) \(.* points\) (.*) \| streak length (-?\d+).*", line)
        if data:
            streamer = data.group(1)
            if "is Online!" in data.group(2):
                if streamer in onlines[i]:
                    print("unexpectedly double online at", line.strip())
                onlines[i].add(streamer)
            if "is Offline!" in data.group(2):
                assert "is Online!" not in data.group(2)
                if initialized[i]:
                    if streamer not in onlines[i]:
                        print("unexpectedly double offline at", line.strip())
                    onlines[i].discard(streamer)
                else:
                    assert streamer not in onlines[i]
            streaklen = int(data.group(3))
            if not initialized[i]:
                if streamer in streaks[i]:
                    print(streamer, "repeated multiple times in", sys.argv[i + 1])
                    assert streaks[i][streamer] == streaklen
                streaks[i][streamer] = streaklen

        if re.match(r"\[INFO\] (.*): ✅ \d+ Streamer loaded! \(.*\)", line):
            initialized[i] = True
            if i == 1:
                break # don't need to read past initialization of second file

totaldecrease = 0
totalincrease = 0
totalposbefore = 0
totalposafter = 0
for streamer, streaklen in streaks[0].items():
    totalposbefore += max(streaklen, 0)
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

for streamer, streaklen in streaks[1].items():
    totalposafter += max(streaklen, 0)
    if streamer not in streaks[0]:
        print(streamer, "in", sys.argv[2], "but not in", sys.argv[1])

print("total missed streak lengths decreased by", totaldecrease)
print("total extended streak lengths increased by", totalincrease)
print("total positive streak lengths", totalposbefore, "->", totalposafter)

print("streamers that went offline between end of first file and start of second:", onlines[0] - onlines[1])
print("streamers that went online between end of first file and start of second:", onlines[1] - onlines[0])
print("total streamers online at both end of first file and start of second:", len(onlines[0] & onlines[1]))
