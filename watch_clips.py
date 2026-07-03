#!/usr/bin/env python3

# watch most recent clip for every streamer that hasn't incremented
# weekly rewards for the day/week, or has an expiring streak

import json, os, requests, datetime, random, string, time
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
chunksize = 4000
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
        raise Exception("Failed to fetch data: {} - {}".format(response.status_code, response.text))

def get_id(streamer):
    payload = gql_payload("GetIDFromLogin", "94e82a7b1e3c21e186daa73ee2afc4b8f23bade1fbbff6fe8ac133f50a2f58ca")
    payload[0]["variables"] = {
        "login": streamer
    }
    data = gql_post(payload)
    assert len(data) == 1
    user = data[0]["data"]["user"]
    if user:
        return user["id"]
    else:
        return None

def channelid(streamer):
    # use channel id from watch streak cache file if it's there, otherwise query api
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
    return gql_post(payload)

def reward_list(streamer):
    payload = gql_payload("RewardList", "0b1471876d7647993731b9e3c6a13bf304c67fb31d07f06a945d42286ee377c4")
    payload[0]["variables"] = {
        "channelID": channelid(streamer)
    }
    return gql_post(payload)

def streak_expiresat(streamer):
    rewardlist = reward_list(streamer)
    assert len(rewardlist) == 1
    expiresat = rewardlist[0]["data"]["channel"]["self"]["watchStreakMilestone"]["expiresAt"]
    if expiresat: # parse to a datetime object and convert from utc to local tz
        expiresat = datetime.datetime.strptime(expiresat, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=datetime.timezone.utc).astimezone()
    return expiresat

def get_twitch_clips(streamer, limit=5, filter="ALL_TIME"):
    payload = gql_payload("ClipsCards__User", "90c33f5e6465122fba8f9371e2a97076f9ed06c6fed3788d002ab9eba8f91d88")
    payload[0]["variables"] = {
        "login": streamer,
        "limit": limit,
        "criteria": {
            "filter": filter # Options: 'LAST_DAY', 'LAST_WEEK', 'LAST_MONTH', 'ALL_TIME'
        }
    }    
    return gql_post(payload)

def get_recent_clip(streamer, filter="LAST_DAY", minlength=5):
    data = get_twitch_clips(streamer, limit=100, filter=filter)
    assert len(data) == 1
    if data[0] is None or data[0]["data"]["user"] is None:
        print(streamer, "malformed clips output for filter", filter)
        return {}
    clips = sorted(data[0]["data"]["user"]["clips"]["edges"], key=lambda c: c["node"]["createdAt"], reverse=True)
    for c in clips:
        if c["node"]["durationSeconds"] > minlength:
            return c
    return {}

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

for (i, s) in enumerate(streamers):
    if not channelid(s):
        print(s, "channel not found, streamer", i, "of", len(streamers))
        continue

    data = weekly_visit_rewards(s)
    assert len(data) == 1
    weeklyVisitRewards = data[0]["data"]["channel"]["self"]["weeklyVisitRewards"]    
    if not weeklyVisitRewards:
        print(s, "channel points disabled, streamer", i, "of", len(streamers))
        continue
    
    expiresat = None
    weekly_visited = weeklyVisitRewards["hasEarnedWeeklyRewardThisWeek"] or weeklyVisitRewards["hasVisitedToday"]
    if weekly_visited:
        expiresat = streak_expiresat(s)
        if not expiresat:
            continue
        print(s, "need to watch recent clip/vod because streak expires at", expiresat)
    
    if weeklyVisitRewards["hasEarnedWeeklyRewardThisWeek"]:
        print(s, "done for week, daysVisitedThisWeek:", weeklyVisitRewards["daysVisitedThisWeek"],
              "accumulatedWeeks:", weeklyVisitRewards["accumulatedWeeks"],
              "streamer", i, "of", len(streamers))
    elif weeklyVisitRewards["hasVisitedToday"]:
        print(s, "visited for today, daysVisitedThisWeek:", weeklyVisitRewards["daysVisitedThisWeek"],
              "accumulatedWeeks:", weeklyVisitRewards["accumulatedWeeks"],
              "streamer", i, "of", len(streamers))
    else:
        print(s, "need to watch any clip/vod for weekly rewards, daysVisitedThisWeek:",
              weeklyVisitRewards["daysVisitedThisWeek"],
              "accumulatedWeeks:", weeklyVisitRewards["accumulatedWeeks"],
              "streamer", i, "of", len(streamers))
    
    clip = get_recent_clip(s, filter="LAST_DAY", minlength=5)
    if not clip:
        # no clip from last day, warn if streak is expiring
        if not weekly_visited:
            expiresat = streak_expiresat(s)
        if expiresat:
            clip = get_recent_clip(s, filter="LAST_DAY", minlength=0)
            if clip:
                print(s, "recent clips are all short but streak expires at", expiresat)
            else:
                print(s, "no recent clip but streak expires at", expiresat)
        clip = get_recent_clip(s, filter="ALL_TIME", minlength=5)
        if not clip:
            clip = get_recent_clip(s, filter="ALL_TIME", minlength=0)
            if clip:
                print(s, "only has short clips, no clips over 5 seconds")
            else:
                # todo: check for vods
                print(s, "no clips available")
                continue
    
    play_session_id = create_random_alphanumeric_id(32)
    send_clip_video_play(clip["node"], play_session_id)
    time.sleep(5)
    send_clip_second_watched(clip["node"], play_session_id, seconds_watched=5)
    
