# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import urlquick
from xbmc import executebuiltin
from xbmcgui import Dialog
from functools import reduce
from resources.lib.contants import API_BASE_URL, BASE_HEADERS, url_constructor
from resources.lib.utils import deep_get, updateQueryParams, qualityFilter
from codequick import Script
from codequick.script import Settings
from codequick.storage import PersistentDict
from urllib.parse import quote_plus, urlparse, parse_qsl
from urllib.request import urlopen, Request
import time
import hashlib
import hmac
import json
import re
from uuid import uuid4
from base64 import b64decode


class HotstarAPI:

    def __init__(self):
        self.session = urlquick.Session()
        self.session.headers.update(BASE_HEADERS)

    def getMenu(self):
        url = url_constructor("/o/v2/menu")
        resp = self.get(
            url, headers={"x-country-code": "in", "x-platform-code": "ANDROID_TV"})
        return deep_get(resp, "body.results.menuItems")

    def getPage(self, url):
        results = deep_get(self.get(url), "body.results")
        itmes = deep_get(results, "trays.items", []) or results.get(
            "items", [])
        nextPageUrl = results.get("nextOffsetURL") or deep_get(
            results, "trays.nextOffsetURL")
        return itmes, nextPageUrl

    def getTray(self, url, search_query=None):
        if search_query:
            url = url_constructor("/s/v1/scout?q=%s&size=30" %
                                  quote_plus(search_query))
        if "persona" in url:
            with PersistentDict("userdata.pickle") as db:
                pid = db.get("udata", {}).get("pId")
            results = self.get(url.format(pid=pid), headers={
                               "hotstarauth": self._getAuth(includeST=True, persona=True)})
            # ids = ",".join(map(lambda x: x.get("item_id"),
            #                deep_get(results, "data.items")))
            # url = url_constructor("/o/v1/multi/get/content?ids=" + ids)
        else:
            results = self.get(url)

        if "data" in results:
            results = results.get("data")
            if "progress_meta" in results and type(results.get("items")) is dict:
                for cID, data in results.get("progress_meta").items():
                    results["items"][cID].update(data)
        else:
            results = deep_get(results, "body.results")

        if results:
            items = results.get("items") or deep_get(results, "assets.items") or (results.get(
                "map") and list(results.get("map").values())) or deep_get(results, "trays.items") or []
            if type(items) is dict:
                items = list(items.values())
            nextPageUrl = deep_get(
                results, "assets.nextOffsetURL") or results.get("nextOffsetURL")

            totalResults = deep_get(
                results, "assets.totalResults") or results.get("totalResults")
            offset = deep_get(
                results, "assets.offset") or results.get("offset")
            allResultsPageUrl = None
            if len(items) > 0 and nextPageUrl is not None and ("/season/" in nextPageUrl or items[0].get("assetType") == "EPISODE") and totalResults is not None:
                allResultsPageUrl = updateQueryParams(nextPageUrl, {"size": str(
                    totalResults), "tas": str(totalResults), "offset": "0"})

            if deep_get(results, "channelClip.clipType", "") == "LIVE":
                items.insert(0, deep_get(results, "channelClip", {}))

            return items, nextPageUrl, allResultsPageUrl
        return [], None, None

    def getPlay(self, contentId, subtag, drm=False, lang=None, partner=None, ask=False):
        url = url_constructor("/play/v1/playback/%scontent/%s" %
                              ('partner/' if partner is not None else '', contentId))
        encryption = "widevine" if drm else "plain"
        if partner:
            resp = self.post(url, headers=self._getPlayHeaders(extra={"X-HS-Platform": "android"}), params=self._getPlayParams(
                subtag, encryption), max_age=-1, json={"user_id": "", "partner_data": "x", "data": {"third_party_bundle": partner}})
        else:
            resp = self.get(url, headers=self._getPlayHeaders(
            ), params=self._getPlayParams(subtag, encryption), max_age=-1)
        playBackSets = deep_get(resp, "data.playBackSets")
        if playBackSets is None:
            return None, None, None
        playbackUrl, licenceUrl, playbackProto = HotstarAPI._findPlayback(
            playBackSets, lang, ask)
        return playbackUrl, licenceUrl, playbackProto

    def getExtItem(self, contentId):
        url = url_constructor(
            "/o/v1/multi/get/content?ids={0}".format(contentId))
        resp = self.get(url)
        url = deep_get(resp, "body.results.map.{0}.uri".format(contentId))
        if url is None:
            return None, None, None
        resp = self.get(url)
        item = deep_get(resp, "body.results.item")
        if item.get("clipType") == "LIVE":
            item["encrypted"] = True
        return "com.widevine.alpha" if item.get("encrypted") else False, item.get("isSubTagged") and "subs-tag:%s|" % item.get("features")[0].get("subType"), item.get("title")

    def doLogin(self):
        url = url_constructor(
            "/in/aadhar/v2/firetv/in/users/logincode/")
        resp = self.post(url, headers={"Content-Length": "0"})
        code = deep_get(resp, "description.code")
        yield (code, 1)
        for i in range(2, 101):
            resp = self.get(url+code, max_age=-1)
            Script.log(resp, lvl=Script.INFO)
            token = deep_get(resp, "description.userIdentity")
            if token:
                with PersistentDict("userdata.pickle") as db:
                    db["token"] = token
                    db["deviceId"] = str(uuid4())
                    db["udata"] = json.loads(json.loads(
                        b64decode(token.split(".")[1]+"========")).get("sub"))
                    if db.get("isGuest"):
                        del db["isGuest"]
                    db.flush()
                yield code, 100
                break
            yield code, i

    def doLogout(self):
        with PersistentDict("userdata.pickle") as db:
            db.clear()
            db.flush()
        Script.notify("Logout Success", "You are logged out")

    def get(self, url, **kwargs):
        try:
            response = self.session.get(url, **kwargs)
            return response.json()
        except Exception as e:
            return self._handleError(e, url, "get", **kwargs)

    def post(self, url, **kwargs):
        try:
            response = self.session.post(url, **kwargs)
            return response.json()
        except Exception as e:
            return self._handleError(e, url, "post", **kwargs)

    def _handleError(self, e, url, _rtype, **kwargs):
        if e.__class__.__name__ == "ValueError":
            Script.log("Can not parse response of request url %s" %
                       url, lvl=Script.DEBUG)
            Script.notify("Internal Error", "")
        elif e.__class__.__name__ == "HTTPError":
            if e.response.status_code == 402 or e.response.status_code == 403:
                with PersistentDict("userdata.pickle") as db:
                    if db.get("isGuest"):
                        Script.notify(
                            "Login Error", "Please login to watch this content")
                        executebuiltin(
                            "RunPlugin(plugin://plugin.video.botallen.hotstar/resources/lib/main/login/)")
                    else:
                        Script.notify(
                            "Subscription Error", "You don't have valid subscription to watch this content", display_time=2000)
            elif e.response.status_code == 401:
                new_token = self._refreshToken()
                if new_token:
                    kwargs.get("headers") and kwargs['headers'].update(
                        {"X-HS-UserToken": new_token})
                    if _rtype == "get":
                        return self.get(url, **kwargs)
                    else:
                        return self.post(url, **kwargs)
                else:
                    Script.notify("Token Error", "Token not found")

            elif e.response.status_code == 474 or e.response.status_code == 475:
                Script.notify(
                    "VPN Error", "Your VPN provider does not support Hotstar")
            elif e.response.status_code == 404 and e.response.headers.get("Content-Type") == "application/json":
                if e.response.json().get("errorCode") == "ERR_PB_1412":
                    Script.notify("Network Error",
                                  "Use Jio network to play this content")
            else:
                Script.notify("Invalid Response", "{0}: Invalid response from server".format(
                    e.response.status_code))
            return False
        else:
            Script.log("{0}: Got unexpected response for request url {1}".format(
                e.__class__.__name__, url), lvl=Script.DEBUG)
            Script.notify(
                "API Error", "Raise issue if you are continuously facing this error")
            raise e

    def _refreshToken(self):
        try:
            with PersistentDict("userdata.pickle") as db:
                oldToken = db.get("token")
                if oldToken:
                    resp = self.session.get(url_constructor("/in/aadhar/v2/firetv/in/users/refresh-token"),
                                            headers={"userIdentity": oldToken, "deviceId": db.get("deviceId", str(uuid4()))}, raise_for_status=False, max_age=-1).json()
                    if resp.get("errorCode"):
                        return resp.get("message")
                    new_token = deep_get(resp, "description.userIdentity")
                    db['token'] = new_token
                    db.flush()
                    return new_token
            return False
        except Exception as e:
            return e

    @staticmethod
    def _getPlayHeaders(includeST=False, playbackUrl=None, extra={}):
        with PersistentDict("userdata.pickle") as db:
            token = db.get("token")
        auth = HotstarAPI._getAuth(includeST)
        headers = {
            "hotstarauth": auth,
            "X-Country-Code": "in",
            "X-HS-AppVersion": "3.3.0",
            "X-HS-Platform": "firetv",
            "X-HS-UserToken": token,
            "User-Agent": "Hotstar;in.startv.hotstar/3.3.0 (Android/8.1.0)",
            **extra,
        }
        if playbackUrl:
            r = Request(playbackUrl)
            r.add_header("User-Agent", headers.get("User-Agent"))
            cookie = urlopen(r).headers.get("Set-Cookie", "").split(";")[0]
            if cookie:
                headers["Cookie"] = cookie
        return headers

    @staticmethod
    def _getAuth(includeST=False, persona=False):
        _AKAMAI_ENCRYPTION_KEY = b'\x05\xfc\x1a\x01\xca\xc9\x4b\xc4\x12\xfc\x53\x12\x07\x75\xf9\xee'
        if persona:
            _AKAMAI_ENCRYPTION_KEY = b"\xa0\xaa\x8b\xcf\x9d\xd5\x8e\xc6\xe3\xb5\x7d\x9b\x4e\x5a\x00\x80\xb1\x45\x0d\xf7\x43\x6c\xfa\x22\xdd\x5c\xff\xdf\xea\x8e\x12\x52"
        st = int(time.time())
        exp = st + 6000
        auth = 'st=%d~exp=%d~acl=/*' % (st,
                                        exp) if includeST else 'exp=%d~acl=/*' % exp
        auth += '~hmac=' + hmac.new(_AKAMAI_ENCRYPTION_KEY,
                                    auth.encode(), hashlib.sha256).hexdigest()
        return auth

    @staticmethod
    def _getPlayParams(subTag="", encryption="widevine"):
        with PersistentDict("userdata.pickle") as db:
            deviceId = db.get("deviceId", str(uuid4()))
        return {
            "os-name": "firetv",
            "desired-config": "audio_channel:stereo|encryption:%s|ladder:tv|package:dash|%svideo_codec:h264" % (encryption, subTag or ""),
            "device-id": deviceId,
            "os-version": "8.1.0"
        }

    @staticmethod
    def _findPlayback(playBackSets, lang=None, ask=False):
        selected = None
        index = -1
        options = []
        quality = {"4k": 0, "hd": 1, "sd": 2}
        for each in playBackSets:
            config = {k: v for d in map(lambda x: dict([x.split(":")]), each.get(
                "tagsCombination", "a:b").split(";")) for k, v in d.items()}
            Script.log(
                f"Checking combination {config} with language {lang}", lvl=Script.DEBUG)
            if config.get("encryption", "") in ["plain", "widevine"] and config.get("package", "") in ["hls", "dash"]:
                if lang and config.get("language") and config.get("language", "") != lang:
                    continue
                config["playback"] = (each.get("playbackUrl"), each.get(
                    "licenceUrl"), "mpd" if config.get("package") == "dash" else "hls")
                if selected is None:
                    selected = config["playback"]
                if config.get("ladder"):
                    del config["ladder"]
                if config not in options:
                    options.append(config)
        options.sort(key=lambda x: str(
            quality.get(x.get("resolution", "sd")) or ""))
        if len(options) > 0:
            if Settings.get_string("playback_select") == "Ask" or ask:
                index = Dialog().select("Playback Quality", list(map(lambda x: "Video: {0} - {1} - {2} - {3} | Audio: {4} - {5} | {6}".format(x.get("resolution", "").upper(), x.get(
                    "dynamic_range", "").upper(), x.get("video_codec", "").upper(), x.get("container", "").upper(), x.get("audio_channel", "").upper(), x.get("audio_codec", "").upper(), "Non-DRM" if x.get("encryption", "plain") == "plain" else "DRM"), options)))
                if index == -1:
                    return (None, None, None)
            else:
                options = list(filter(qualityFilter, options))
                if len(options) > 0:
                    index = 0
        if len(options) > 0:
            Script.log("Selected Config {0}".format(options[index]))
            selected = options[index].get("playback")
        if selected is None:
            selected = (playBackSets[0].get("playbackUrl"), playBackSets[0].get(
                "licenceUrl"), "hls" if ".m3u8" in playBackSets[0].get("playbackUrl") else "mpd")
            Script.log("No stream found for desired config. Using %s" %
                       playBackSets[0].get("playbackUrl"), lvl=Script.INFO)
        return selected
