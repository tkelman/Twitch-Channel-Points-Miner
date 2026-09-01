#!/usr/bin/env python3

# usage: ./check_missed_streaks.py log/filename.log

import re, sys, os, json
from datetime import datetime
from pathlib import Path

assert len(sys.argv) > 1
with open(sys.argv[1]) as f:
    lines = f.readlines()

with open("config.json") as f:
    configjson = json.load(f)

watchstreakcache = "log/watch_streak_cache.{}.json".format(configjson["username"])
channelids = {}
if os.path.isfile(watchstreakcache):
    with open(watchstreakcache) as f:
        cachejson = json.load(f)
    for entry in cachejson["entries"]:
        channelids[entry["streamer_login"].lower()] = entry["channel_id"]

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
streamerorder = {}
mostrecentoffline = {}
shortgaps = 0
with (Path(__file__).parent / "log" / "numonline.csv").open("w") as f:
    numon = 0
    offdecrement = 0
    for (lineno, line) in enumerate(lines):
        off = re.match(r"\[INFO\] (.*): 😴 (.*) \(.* points\) is Offline!", line)
        on  = re.match(r"\[INFO\] (.*): 🥳 (.*) \(.* points\) is Online!",  line)
        streak = re.match(r".* (.*) \(.* points\) .* \| streak length (\d+).*", line)
        slot = re.match(r"SLOT \d: (.*) \(reason.*", line)
        streamer = ""
        order = ""
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
                if offdecrement == 0:
                    channelid = channelids.get(streamer.lower(), streamer)
                    streamerorder[channelid] = lineno - 4
            if offdecrement == 1:
                # save most recent offline time, not including initially-offline streams
                mostrecentoffline[off.group(2)] = offlines[-1]
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
                if offdecrement == 0:
                    channelid = channelids.get(streamer.lower(), streamer)
                    streamerorder[channelid] = lineno - 4
            addtimes = re.match(r".* \| started at (.*) \| streak achievement timestamp (.*)", line)
            if addtimes:
                #print(addtimes)
                onlines[-1]["createdAt"] = isoparse_stripns(addtimes.group(1))
                onlines[-1]["achievementAt"] = isoparse_stripns(addtimes.group(2))
            #print("online:", onlines[-1])

            offline = mostrecentoffline.get(on.group(2))
            if offline and (timestamp - offline["timestamp"]).total_seconds() <= 29 * 60:
                print("ignoring short offline gap for", on.group(2), "from", offline["timestamp"], "to", timestamp)
                onlines.pop()
                offlines.pop(offlines.index(offline))
                shortgaps += 1
        elif slot:
            streamer = slot.group(1)
            channelid = channelids.get(streamer.lower(), streamer)
            if channelid in streamerorder:
                order = streamerorder[channelid]
            else:
                print(streamer, "not found during miner startup")
                streamerorder[channelid] = ""
                order = ""
        else:
            message = re.match(r"\[(INFO|ERROR|DEBUG|DEEP)\] " + timeregex, line)
            if message:
                timestamp = datetime.strptime(message.group(2), timeformat)

        f.write("{},{},{}\n".format(numon, timestamp, order))
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
prevofflines = {}
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

        prevoffline = prevofflines.get(streamer, {})
        if prevoffline.get("lineno", -1) > mostrecentonline["lineno"]:
            # the most recently online stream already ended earlier in the file
            # probably duplicated miner session restarted in same log file
            #print("repeated offline", off)
            continue

        # note: some streamers have started (late june 2026) giving +20 points for a WATCH, not sure why
        pointsregex = r"\[INFO\] (.*): 🚀 \+[12][02] → " + re.escape(streamer) + r" \(.* points\) - Reason: WATCH"
        points = [lines[i] for i in streamrange if re.match(pointsregex, lines[i])]
        #print(points)
        if len(points) == 0:
            if createdAt and achievementAt and achievementAt > createdAt:
                warmstartedstreaksoffline += 1
                #print("warm started streak for", streamer, "stream from",
                #    mostrecentonline["timestamp"], "to", timestamp)
            else:
                maybemissedstreaks += 1
                extra = ""
                if "streaklen" in off and "streaklen" in mostrecentonline:
                    if off["streaklen"] == 0 and mostrecentonline["streaklen"] == 0:
                        extra += "streak len 0 -> 0 "
                    elif off["streaklen"] == mostrecentonline["streaklen"] + 1:
                        extra += "pubsub outage?"
                mostrecentontime = mostrecentonline.get("createdAt", mostrecentonline["timestamp"])
                if (timestamp - mostrecentontime.replace(tzinfo=None)).total_seconds() <= 480:
                    extra += "SHORT"
                print("POSSIBLE MISSED STREAK FOR", streamer, "stream from",
                    mostrecentonline["timestamp"], "to", timestamp, extra)
        else:
            maintainedstreaksoffline += 1
            if "streaklen" in off and "streaklen" in mostrecentonline:
                if off["streaklen"] == 0 and mostrecentonline["streaklen"] == 0:
                    streakregex = r"\[INFO\] (.*): 🚀 \+[34][05]0 → " + re.escape(streamer) + r" \(.* points\) - Reason: WATCH_STREAK"
                    streak = [lines[i] for i in streamrange if re.match(streakregex, lines[i])]
                    if len(streak) == 0:
                        print("accrued points for", streamer, "but streak length = 0", file=sys.stderr)
                    else:
                        print("maintained streak for", streamer, "but streak length = 0", file=sys.stderr)
                elif off["streaklen"] != mostrecentonline["streaklen"] + 1:
                    print("accrued points for", streamer, "but streak length changed by",
                          off["streaklen"] - mostrecentonline["streaklen"])
            #print("maintained streak for", streamer, "stream from",
            #      mostrecentonline["timestamp"], "to", timestamp)
        #if len(points) > 1:
        #    print(points)
    else:
        #print("went online after", timestamp)
        pass

    prevofflines[streamer] = off


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
        # note: some streamers have started (late june 2026) giving +20 points for a WATCH, not sure why
        pointsregex = r"\[INFO\] (.*): 🚀 \+[12][02] → " + re.escape(streamer) + r" \(.* points\) - Reason: WATCH"
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
print(shortgaps, "short offline gaps")
print(notyetextendedstreaks, "streaks not yet extended for now-online streams")
print(warmstartedstreaksonline, "streaks warm started for now-online streams")
print(maintainedstreaksonline, "streaks maintained in now-online streams")
