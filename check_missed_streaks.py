#!/usr/bin/env python3

# usage: ./check_missed_streaks.py log/filename.log

import re, sys
from datetime import datetime
from pathlib import Path

assert len(sys.argv) > 1
with open(sys.argv[1]) as f:
    lines = f.readlines()

timeregex = r"(\d\d:\d\d \d\d\/\d\d\/\d\d): "
if re.match(r"\[INFO\] " + timeregex + r"Twitch Channel Points Miner", lines[0]):
    timeformat = "%H:%M %d/%m/%y"
else:
    # TODO: verify if this works when show_seconds is true
    timeformat = "%H:%M:%S %d/%m/%y"
    timeregex = r"(\d\d:\d\d:\d\d \d\d\/\d\d\/\d\d): "

def isoparse_stripns(timestamp):
    # strip nanoseconds before parsing iso timestamp with strptime
    if '.' in timestamp:
        sections = re.match(r"(.*\.)(\d+)( .*)", timestamp)
        #print(sections)
        predecimal = sections.group(1)
        microseconds = sections.group(2)
        timezone = sections.group(3)
        if len(microseconds) > 6:
            microseconds = microseconds[0:6]
        return datetime.strptime(predecimal + microseconds + timezone, "%Y-%m-%d %H:%M:%S.%f %z %Z")
    else:
        return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S %z %Z")

offlines = []
onlines = []
numonline = []
with (Path(__file__).parent / "log" / "numonline.csv").open("w") as f:
    numon = 0
    offdecrement = 0
    for (lineno, line) in enumerate(lines):
        off = re.match(r"\[INFO\] (.*): 😴 (.*) \(.* points\) is Offline!", line)
        on  = re.match(r"\[INFO\] (.*): 🥳 (.*) \(.* points\) is Online!",  line)
        streak = re.match(r".* (.*) \(.* points\) .* \| streak length (\d+).*", line)
        streamer = ""
        if streak:
            streamer = streak.group(1)
            streaklen = int(streak.group(2))
        loaded = re.match(r"\[INFO\] (.*): ✅ \d+ Streamer loaded! \(.*\)", line)
        timestamp = ""
        if loaded:
            # only decrement count for offline streams after finished loading streamer list
            offdecrement = 1
            timestamp = datetime.strptime(loaded.group(1), timeformat)
        elif off:
            numon -= offdecrement
            timestamp = datetime.strptime(off.group(1), timeformat)
            offlines.append({
                "timestamp": timestamp,
                "streamer": off.group(2),
                "lineno": lineno
                })
            if streak:
                assert streamer == off.group(2)
                offlines[-1]["streaklen"] = streaklen
            #print("offline:", offlines[-1])
        elif on:
            numon += 1
            timestamp = datetime.strptime(on.group(1), timeformat)
            onlines.append({
                "timestamp": timestamp,
                "streamer": on.group(2),
                "lineno": lineno
                })
            if streak:
                assert streamer == on.group(2)
                onlines[-1]["streaklen"] = streaklen
            addtimes = re.match(r".* \| started at (.*) \| streak achievement timestamp (.*)", line)
            if addtimes:
                #print(addtimes)
                onlines[-1]["createdAt"] = isoparse_stripns(addtimes.group(1))
                onlines[-1]["achievementAt"] = isoparse_stripns(addtimes.group(2))
            #print("online:", onlines[-1])
        else:
            message = re.match(r"\[(INFO|ERROR|DEBUG|DEEP)\] " + timeregex, line)
            if message:
                timestamp = datetime.strptime(message.group(2), timeformat)

        f.write("{},{}\n".format(numon, timestamp))
        numonline.append(numon)

#print(numonline)

# check for finished streams that may have been missed before ending:
# (candidates for manually saving streaks with clips or vods)
# go through streams that have ended within the log file
# look for Reason: WATCH channel point earn events between
# the most recent stream start time and this stream end time
maybemissedstreaks = 0
maintainedstreaksoffline = 0
warmstartedstreaksoffline = 0
for off in offlines:
    timestamp = off["timestamp"]
    streamer = off["streamer"]
    lineno = off["lineno"]
    #print(streamer, "offline at", timestamp)
    wasonline = False
    mostrecentonline = {}
    for on in onlines:
        if on["streamer"] == streamer:
            wasonline = True
            if on["lineno"] < lineno:
                mostrecentonline = on
            #print("online at", on)
    if not wasonline:
        #print("was not online during log file")
        pass
    elif mostrecentonline:
        #print("most recent online", mostrecentonline)
        createdAt = mostrecentonline.get("createdAt", None)
        achievementAt = mostrecentonline.get("achievementAt", None)
        streamrange = range(mostrecentonline["lineno"], lineno)
        pointsregex = r"\[INFO\] (.*): 🚀 \+1[02] → " + re.escape(streamer) + r" \(.* points\) - Reason: WATCH"
        points = [lines[i] for i in streamrange if re.match(pointsregex, lines[i])]
        #print(points)
        if len(points) == 0:
            if createdAt and achievementAt and achievementAt > createdAt:
                warmstartedstreaksoffline += 1
                #print("warm started streak for", streamer, "stream from",
                #    mostrecentonline["timestamp"], "to", timestamp)
            else:
                maybemissedstreaks += 1
                zerozero = ""
                if "streaklen" in off and "streaklen" in mostrecentonline:
                    if off["streaklen"] == 0 and mostrecentonline["streaklen"] == 0:
                        zerozero = "streak len 0 -> 0"
                print("POSSIBLE MISSED STREAK FOR", streamer, "stream from",
                    mostrecentonline["timestamp"], "to", timestamp, zerozero)
        else:
            maintainedstreaksoffline += 1
            #print("maintained streak for", streamer, "stream from",
            #      mostrecentonline["timestamp"], "to", timestamp)
        #if len(points) > 1:
        #    print(points)
    else:
        #print("went online after", timestamp)
        pass


# check for streams that are still online as of the end of the log file
# to see if watch points have not yet been earned since the stream went online
notyetextendedstreaks = 0
maintainedstreaksonline = 0
warmstartedstreaksonline = 0
for on in onlines:
    timestamp = on["timestamp"]
    streamer = on["streamer"]
    lineno = on["lineno"]
    createdAt = on.get("createdAt", None)
    achievementAt = on.get("achievementAt", None)
    #print(streamer, "online at", timestamp)
    nextoffline = {}
    for off in reversed(offlines):
        if off["streamer"] == streamer:
            if off["lineno"] > lineno:
                nextoffline = off
            #print("offline at", off)
    if nextoffline == {}:
        streamrange = range(lineno, len(lines))
        pointsregex = r"\[INFO\] (.*): 🚀 \+1[02] → " + re.escape(streamer) + r" \(.* points\) - Reason: WATCH"
        points = [lines[i] for i in streamrange if re.match(pointsregex, lines[i])]
        #print(points)
        if len(points) == 0:
            if createdAt and achievementAt and achievementAt > createdAt:
                warmstartedstreaksonline += 1
                #print("warm started streak for", streamer, "stream started at", timestamp)
            else:
                notyetextendedstreaks += 1
                print("NOT YET EXTENDED STREAK FOR", streamer, "stream started at", timestamp)
        else:
            maintainedstreaksonline += 1
            #print("maintained streak for", streamer, "stream started at", timestamp)
    else:
        #print("went offline at", nextoffline["timestamp"])
        pass
            
print(maybemissedstreaks, "streaks possibly missed")
print(warmstartedstreaksoffline, "streaks warm started in finished streams")
print(maintainedstreaksoffline, "streaks maintained in finished streams")
print(notyetextendedstreaks, "streaks not yet extended for now-online streams")
print(warmstartedstreaksonline, "streaks warm started for now-online streams")
print(maintainedstreaksonline, "streaks maintained in now-online streams")
