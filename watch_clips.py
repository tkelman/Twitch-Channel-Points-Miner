#!/usr/bin/env python3

# watch most recent clip for every streamer that hasn't incremented
# weekly rewards for the day/week, or has an expiring streak

import json, os, requests, datetime, random, string, time, collections
from base64 import b64encode

with open("config.json") as f:
    configjson = json.load(f)
username = configjson["username"]
configstreamers = [s.lower() for s in configjson["streamers"]]

extrastreamers = []
for filename in ("raid_targets.txt", "/mnt/e/Dropbox/twitch_channels.txt"):
    if os.path.isfile(filename):
        with open(filename) as f:
            extrastreamers += [s.lower() for s in f.read().splitlines()]
extrastreamers = list(set(extrastreamers) - set(configstreamers)) # remove duplicates
chunksize = 5000
streamers = configstreamers.copy()
while len(extrastreamers) > chunksize:
    # repeat initial list of streamers every chunksize extras
    streamers += extrastreamers[:chunksize]
    streamers += configstreamers
    extrastreamers = extrastreamers[chunksize:]
streamers += extrastreamers

with open("cookies/{}.json".format(username)) as f:
    cookiejson = json.load(f)

# populate a map of streamer name -> channel ids from the watch streak cache file
channelids = {}
watchstreakcache = "log/watch_streak_cache.{}.json".format(username)
if os.path.isfile(watchstreakcache):
    with open(watchstreakcache) as f:
        cachejson = json.load(f)
    #for entry in cachejson["entries"]:
    #    channelids[entry["streamer_login"].lower()] = entry["channel_id"]
    # skipping for now to avoid caching pre-rename usernames
    # for streamers that change names, the channelid does not change
    # so we get sometimes confusing results where api calls using
    # channel id work fine but calls using screen name do not

def gql_payload(operationName, sha256Hash):
    return [
        {
            "operationName": operationName,
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": sha256Hash
                }
            },
            "variables": {}
        }
    ]

def gql_post(payload):
    gql_headers = {
        #"Client-ID": "kimne78kx3ncx6brgo4mv6wki5h1ko",
        "Client-ID": "ue6666qo983tsx6so1t0vnawi233wa",
        "Authorization": "OAuth {}".format(cookiejson["auth-token"]["value"])
    }
    response = requests.post("https://gql.twitch.tv/gql", json=payload, headers=gql_headers)
    if response.status_code == 200:
        return response.json()
    else:
        return [{"errors": "Failed to fetch data: {} - {}".format(response.status_code, response.text)}]

def safeindex(data, indices):
    # index into a gql return dict with some robustness for malformed data
    assert len(data) == 1
    out = data[0]
    for i in indices:
        if out is None:
            return out
        out = out.get(i, {})
    return out

def gql_post_with_retries(payload, retries=15):
    attempts = 0
    data = gql_post(payload)
    errors = safeindex(data, ["errors"])
    if len(errors) == 1 and safeindex(errors, ["message"]) == 'graphql: got nil for non-null "WeeklyVisitRewardTier"':
        return data
    while errors and attempts < retries:
        print("gql error", data)
        time.sleep(1.2 ** attempts)
        data = gql_post(payload)
        errors = safeindex(data, ["errors"])
        attempts += 1
    return data

def get_id(streamer):
    payload = gql_payload("GetIDFromLogin", "94e82a7b1e3c21e186daa73ee2afc4b8f23bade1fbbff6fe8ac133f50a2f58ca")
    payload[0]["variables"] = {
        "login": streamer
    }
    data = gql_post_with_retries(payload)
    user = safeindex(data, ["data", "user"])
    if user:
        return user.get("id")
    else:
        return None

def channelid(streamer):
    # use cached channel id if we've saved it before, otherwise query api
    channel_id = channelids.get(streamer)
    if not channel_id:
        channel_id = get_id(streamer)
        if channel_id:
            channelids[streamer] = channel_id
    return channel_id

def weekly_visit_rewards(streamer):
    payload = gql_payload("WeeklyVisitRewardsQuery", "ce98e9db55db7e4abcc1f5ac65c933b73c58fa9c4c8afe3c5098a8ed79737a3c")
    payload[0]["variables"] = {
        "channelID": channelid(streamer)
    }
    return gql_post_with_retries(payload)

def reward_list(streamer):
    payload = gql_payload("RewardList", "0b1471876d7647993731b9e3c6a13bf304c67fb31d07f06a945d42286ee377c4")
    payload[0]["variables"] = {
        "channelID": channelid(streamer)
    }
    return gql_post_with_retries(payload)

def utctolocal(ts):
    # parse iso string to a datetime object and convert from utc to local tz
    if '.' in ts:
        timeformat = "%Y-%m-%dT%H:%M:%S.%fZ"
    else:
        timeformat = "%Y-%m-%dT%H:%M:%SZ"
    return datetime.datetime.strptime(ts, timeformat).replace(
        tzinfo=datetime.timezone.utc).astimezone()

def streak_expiresat(rewardlist, s):
    watchstreakmilestone = safeindex(rewardlist, ["data", "channel", "self", "watchStreakMilestone"])
    if watchstreakmilestone is None or ("expiresAt" not in watchstreakmilestone):
        print(s, "malformed reward list", rewardlist)
        return None
    expiresat = watchstreakmilestone["expiresAt"]
    if expiresat:
        expiresat = utctolocal(expiresat)
    return expiresat

def get_twitch_clips(streamer, limit=20, filter="ALL_TIME"):
    payload = gql_payload("ClipsCards__User", "1cd671bfa12cec480499c087319f26d21925e9695d1f80225aae6a4354f23088")
    payload[0]["variables"] = {
        "login": streamer,
        "limit": limit,
        "criteria": {
            "filter": filter # Options: 'LAST_DAY', 'LAST_WEEK', 'LAST_MONTH', 'ALL_TIME'
        }
    }
    # todo: proper pagination
    return gql_post_with_retries(payload)

def get_recent_template(data, minlength, mode, sortkey, lengthkey):
    edges = safeindex(data, ["data", "user", mode, "edges"])
    if edges is None:
        print("malformed", mode, "output", data)
        return {}
    for edge in sorted(edges, key=lambda x: x["node"][sortkey], reverse=True):
        if edge["node"][lengthkey] > minlength:
            return edge
    return {}

def get_recent_clip(data, minlength=5):
    return get_recent_template(data, minlength, "clips", "createdAt", "durationSeconds")

def get_twitch_vods(streamer, limit=20):
    payload = gql_payload("FilterableVideoTower_Videos", "67004f7881e65c297936f32c75246470629557a393788fb5a69d6d9a25a8fd5f")
    payload[0]["variables"] = {
        "channelOwnerLogin": streamer,
        "limit": limit,
        "videoSort": "TIME"
    }
    # todo: proper pagination
    return gql_post_with_retries(payload)

def get_recent_vod(data, minlength=300):
    return get_recent_template(data, minlength, "videos", "publishedAt", "lengthSeconds")

def is_live(streamer):
    payload = gql_payload("WithIsStreamLiveQuery", "04e46329a6786ff3a81c01c50bfa5d725902507a0deb83b0edbf7abe7a3716ea")
    payload[0]["variables"] = {
        "id": channelid(streamer)
    }
    data = gql_post_with_retries(payload)
    user = safeindex(data, ["data", "user"])
    if user is None or "stream" not in user:
        print(streamer, "malformed is_live data", data)
        return False
    return user["stream"] is not None

def create_random_alphanumeric_id(length):
    return "".join(
        random.choice(string.ascii_lowercase + string.digits)
        for _ in range(length)
    )

def spade_post(payload):
    encoded_payload = {"data": (b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))).decode("utf-8")}
    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:85.0) Gecko/20100101 Firefox/85.0"
    return requests.post(
        "https://spade.twitch.tv/track",
        data=encoded_payload,
        headers={"User-Agent": user_agent},
        timeout=20,
    )

def send_clip_video_play(clipnode, play_session_id):
    properties = {
        "location": "vod",
        "url": clipnode["url"],
        "channel_id": clipnode["broadcaster"]["id"],
        "vod_type": "clip",
        "vod_id": clipnode["id"],
        "content_mode": "clip",
        "live": False,
        "minutes_logged": 0,
        "play_session_id": play_session_id,
        "player": "site",
        "user_id": channelid(username),
        "vod_timestamp": 0,
        "clip_slug": clipnode["slug"],
    }
    return spade_post([
        {"event": "video-play", "properties": properties}
    ])

def send_clip_second_watched(clipnode, play_session_id, seconds_watched):
    properties = {
        "location": "vod",
        "platform": "web",
        "url": clipnode["url"],
        "channel_id": clipnode["broadcaster"]["id"],
        "vod_type": "clip",
        "vod_id": clipnode["id"],
        "live": False,
        "minutes_logged": 0,
        "play_session_id": play_session_id,
        "player": "site",
        "seconds_after_play": seconds_watched,
        "vod_timestamp": seconds_watched - 0.1,
        "clip_slug": clipnode["slug"],
        "user_id": channelid(username),
    }
    return spade_post([
        {"event": "n_second_play", "properties": properties}
    ])

def send_vod_minute_watched(vodnode):
    properties = {
        "channel_id": vodnode["owner"]["id"],
        "broadcast_id": None,
        "player": "site",
        "user_id": channelid(username),
        "live": False,
        "channel": vodnode["owner"]["login"],
        "vod_id": vodnode["id"],
        "content_mode": "vod",
    }
    return spade_post([
        {"event": "minute-watched", "properties": properties}
    ])

def increment_vod(vod, queuelength):
    s = vod["node"]["owner"]["login"]
    data = weekly_visit_rewards(s)
    weeklyVisitRewards = safeindex(data, ["data", "channel", "self", "weeklyVisitRewards"])
    if weeklyVisitRewards:
        visited = weeklyVisitRewards["hasEarnedWeeklyRewardThisWeek"] or weeklyVisitRewards["hasVisitedToday"]
    else: # weekly rewards disabled
        visited = True
    if visited and not streak_expiresat(reward_list(s), s):
        print(s, "visited for weekly rewards and streak not expiring, finished with vod watching")
        vod["watchtime"] = 3600
        return

    lastwatched = vod.get("lastwatched", time.monotonic())
    if ("watchtime" not in vod) or time.monotonic() - lastwatched > 60:
        print(s, "watching vod from", utctolocal(vod["node"]["publishedAt"]),
              "vod queue length", queuelength)
        send_vod_minute_watched(vod["node"])
        vod["lastwatched"] = time.monotonic()
        vod["watchtime"] = vod.get("watchtime", 0) + vod["lastwatched"] - lastwatched

vodqueue = collections.deque()
vodwatching = None

for (i, s) in enumerate(streamers):
    if not channelid(s):
        print(s, "channel not found, streamer", i, "of", len(streamers))
        continue

    data = weekly_visit_rewards(s)
    data_channel_self = safeindex(data, ["data", "channel", "self"])
    if data_channel_self is None or ("weeklyVisitRewards" not in data_channel_self):
        print(s, "malformed weekly rewards output", data)
        continue
    weeklyVisitRewards = data_channel_self["weeklyVisitRewards"]
    hasEarnedWeeklyRewardThisWeek = safeindex(data, ["data", "channel", "self", "weeklyVisitRewards", "hasEarnedWeeklyRewardThisWeek"])
    hasVisitedToday = safeindex(data, ["data", "channel", "self", "weeklyVisitRewards", "hasVisitedToday"])
    if not weeklyVisitRewards:
        print(s, "weekly rewards disabled, streamer", i, "of", len(streamers))
        visited = True
    else:
        visited = hasEarnedWeeklyRewardThisWeek or hasVisitedToday

    rewardlist = reward_list(s)
    expiresat = streak_expiresat(rewardlist, s)
    if i % (len(configstreamers) + chunksize) >= len(configstreamers):
        streaklength = safeindex(rewardlist, ["data", "channel", "self", "watchStreakMilestone", "watchStreakMilestone", "value"])
        if not streaklength or not streaklength.isdecimal():
            print(s, "malformed reward list", rewardlist)
        elif int(streaklength) > 0:
            print(s, "unexpectedly nonzero streak length", streaklength)
    if visited and not expiresat:
        continue
    if expiresat:
        print(s, "need to watch recent clip/vod because streak expires at", expiresat)
    missedstreamids = []
    for stream in safeindex(rewardlist, ["data", "channel", "self", "watchStreakMilestone", "missedStreams"]) or []:
        for id in stream["broadcastIdentifiers"]:
            missedstreamids.append(id["id"])

    daysVisitedThisWeek = safeindex(data, ["data", "channel", "self", "weeklyVisitRewards", "daysVisitedThisWeek"])
    accumulatedWeeks = safeindex(data, ["data", "channel", "self", "weeklyVisitRewards", "accumulatedWeeks"])
    if hasEarnedWeeklyRewardThisWeek:
        print(s, "done for week, daysVisitedThisWeek:", daysVisitedThisWeek,
              "accumulatedWeeks:", accumulatedWeeks,
              "streamer", i, "of", len(streamers))
    elif hasVisitedToday:
        print(s, "visited for today, daysVisitedThisWeek:", daysVisitedThisWeek,
              "accumulatedWeeks:", accumulatedWeeks,
              "streamer", i, "of", len(streamers))
    elif not visited:
        print(s, "need to watch any clip/vod for weekly rewards, daysVisitedThisWeek:",
              daysVisitedThisWeek, "accumulatedWeeks:", accumulatedWeeks,
              "streamer", i, "of", len(streamers))

    need_vod = False
    clip = {}
    extraclips = []
    if expiresat:
        recentclips = get_twitch_clips(s, limit=20, filter="LAST_DAY")
        clip = get_recent_clip(recentclips, minlength=5)
        need_vod = True # always watch a vod for expiring streaks, in case the
        # most recent clip is from an older stream than the most recent vod
        if not clip:
            clip = get_recent_clip(recentclips, minlength=0)
            if clip:
                print(s, "recent clips are all short but streak expires at", expiresat)
            else:
                print(s, "no recent clip but streak expires at", expiresat)
        if clip and clip["node"]["broadcastIdentifier"]["id"] not in missedstreamids:
            print(s, "found recent clip but broadcast id does not match missed streams")
            for extraclip in safeindex(recentclips, ["data", "user", "clips", "edges"]):
                if extraclip["node"]["broadcastIdentifier"]["id"] in missedstreamids:
                    extraclips.append(extraclip)
    if not clip:
        if expiresat:
            lastweekclips = get_twitch_clips(s, limit=20, filter="LAST_WEEK")
            for extraclip in safeindex(lastweekclips, ["data", "user", "clips", "edges"]) or []:
                if extraclip["node"]["broadcastIdentifier"]["id"] in missedstreamids:
                    extraclips.append(extraclip)
        oldclips = get_twitch_clips(s, limit=20, filter="ALL_TIME")
        clip = get_recent_clip(oldclips, minlength=5)
        if not clip:
            need_vod = True
            clip = get_recent_clip(oldclips, minlength=0)
            if clip:
                print(s, "only has short clips, no clips over 5 seconds")
            #else: # check for vods below
            #    print(s, "no clips available")

    if clip:
        play_session_id = create_random_alphanumeric_id(32)
        send_clip_video_play(clip["node"], play_session_id)
        time.sleep(5)
        send_clip_second_watched(clip["node"], play_session_id, seconds_watched=5)

    if len(extraclips) > 0:
        print(s, "watching", len(extraclips), "extra clips to get correct broadcast id from missed streams")
    for (j, extraclip) in enumerate(extraclips):
        play_session_id = create_random_alphanumeric_id(32)
        send_clip_video_play(extraclip["node"], play_session_id)
        time.sleep(5)
        send_clip_second_watched(extraclip["node"], play_session_id, seconds_watched=5)
        if not streak_expiresat(reward_list(s), s):
            print(s, "finishing early after", j + 1, "extra clips")
            break

    if need_vod:
        vods = get_twitch_vods(s, limit=20)
        latestvod = get_recent_vod(vods, minlength=0)
        if not clip:
            if latestvod:
                print(s, "no clips available but vod found")
            elif is_live(s):
                print(s, "no clips or vods available but channel is live right now")
            else:
                print(s, "no clips or vods available")
        if latestvod:
            vodqueue.append(latestvod)
            if latestvod["node"]["lengthSeconds"] < 300:
                # if latest vod is short, also try adding an older long vod to the queue
                longervod = get_recent_vod(vods, minlength=300)
                if longervod:
                    vodqueue.append(longervod)
            if len(missedstreamids) > 0 and latestvod["node"]["broadcastIdentifier"]["id"] not in missedstreamids:
                print(s, "most recent vod broadcast id does not match missed streams")
                for vod in safeindex(vods, ["data", "user", "videos", "edges"]):
                    if vod["node"]["broadcastIdentifier"]["id"] in missedstreamids:
                        vodqueue.append(vod)

    if not vodwatching and len(vodqueue) > 0:
        vodwatching = vodqueue.popleft()

    if vodwatching:
        increment_vod(vodwatching, len(vodqueue))

        if vodwatching["watchtime"] > 300 and len(vodqueue) > 0:
            vodwatching = vodqueue.popleft()
        elif vodwatching["watchtime"] > 600 and len(vodqueue) == 0:
            # stop watching after 10 minutes if queue is empty
            vodwatching = None

# clean up remaining vod queue after processing all streamers' clips
while (vodwatching is not None and vodwatching.get("watchtime", 0) <= 300) or len(vodqueue) > 0:
    time.sleep(31)
    increment_vod(vodwatching, len(vodqueue))

    if vodwatching["watchtime"] > 300 and len(vodqueue) > 0:
        vodwatching = vodqueue.popleft()
