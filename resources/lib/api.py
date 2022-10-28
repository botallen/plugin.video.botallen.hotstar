# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import urlquick
from xbmcgui import Dialog
import xbmc
from resources.lib.contants import BASE_HEADERS, url_constructor
from resources.lib.utils import deep_get, updateQueryParams, qualityFilter, getAuth
from codequick import Script
from codequick.script import Settings
from codequick.storage import PersistentDict
from urllib.parse import quote_plus
from urllib.request import urlopen, Request
import json
from uuid import uuid4
from base64 import b64decode

class HotstarAPI:
    device_id = str(uuid4())

    def __init__(self):
        self.session = urlquick.Session()
        self.session.headers.update(BASE_HEADERS)

    def getMenu(self):
        url = url_constructor("/o/v2/menu")
        resp = self.get(
            url, headers={"x-country-code": "in", "x-platform-code": "firetv"})
        return deep_get(resp, "body.results.menuItems")         # deep_get(resp["body"]["results"]["menuItems"][0]["subItem"][1], "subItem")

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
                               "hotstarauth": getAuth(includeST=True, persona=True)})
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
            allResultsPageUrl = None
            if len(items) > 0 and nextPageUrl is not None and ("/season/" in nextPageUrl or items[0].get("assetType") == "EPISODE") and totalResults is not None:
                allResultsPageUrl = updateQueryParams(nextPageUrl, {"size": str(
                    totalResults), "tas": str(totalResults), "offset": "0"})

            if deep_get(results, "channelClip.clipType", "") == "LIVE":
                items.insert(0, deep_get(results, "channelClip", {}))

            return items, nextPageUrl, allResultsPageUrl
        return [], None, None

    def getPlay(self, contentId, subtag, drm=False, lang=None, partner=None, ask=False):
        # 'partner/' if partner is not None else '',
        url = url_constructor("/play/v4/playback/content/%s" % (contentId))
        encryption = "widevine"     # if drm else "plain"

        """
        if partner:
            resp = self.post(url, headers=self._getPlayHeaders(extra={"X-HS-Platform": "android"}), params=self._getPlayParams(
                subtag, encryption), max_age=-1, json={"user_id": "", "partner_data": "x", "data": {"third_party_bundle": partner}})
        else:
            resp = self.get(url, headers=self._getPlayHeaders(
            ), params=self._getPlayParams(subtag, encryption), max_age=-1)
        """

        data = '{"os_name":"Windows","os_version":"10","app_name":"web","app_version":"7.41.0","platform":"Chrome","platform_version":"106.0.0.0","client_capabilities":{"ads":["non_ssai"],"audio_channel":["stereo"],"dvr":["short"],"package":["dash","hls"],"dynamic_range":["sdr"],"video_codec":["h264"],"encryption":["widevine"],"ladder":["tv"],"container":["fmp4"],"resolution":["hd"]},"drm_parameters":{"widevine_security_level":["SW_SECURE_DECODE","SW_SECURE_CRYPTO"],"hdcp_version":["HDCP_NO_DIGITAL_OUTPUT"]},"resolution":"auto"}'
        resp = self.post(url, headers=self._getPlayHeaders(includeST=True), params=self._getPlayParams(
            subtag, encryption), max_age=-1, data=data)
        playBackSets = deep_get(resp, "data.playback_sets")
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
        with PersistentDict("userdata.pickle") as db:
            if db.get("token"):
                self._refreshToken()
            else:
                token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOiJ1bV9hY2Nlc3MiLCJleHAiOjE2Njc0NDk0MDAsImlhdCI6MTY2Njg0NDYwMCwiaXNzIjoiVFMiLCJqdGkiOiI0OGQ1MTY1YThlZTU0MDU5YTJmODc1NzU1YzMwMDcwZiIsInN1YiI6IntcImhJZFwiOlwiMDg0ZjE4NjdmODVlNGYxMDkwODdlODc2YWI4ZWIyYWVcIixcInBJZFwiOlwiZGIxYzFlN2Q2NmFhNDg1ZDg4MzdiOGRhNzAzZWUwOWFcIixcIm5hbWVcIjpcIkd1ZXN0IFVzZXJcIixcImlwXCI6XCIxMDMuMTc3LjEzLjE0NlwiLFwiY291bnRyeUNvZGVcIjpcImluXCIsXCJjdXN0b21lclR5cGVcIjpcIm51XCIsXCJ0eXBlXCI6XCJndWVzdFwiLFwiaXNFbWFpbFZlcmlmaWVkXCI6ZmFsc2UsXCJpc1Bob25lVmVyaWZpZWRcIjpmYWxzZSxcImRldmljZUlkXCI6XCI5NTE5OWEwYi1jODVhLTQwNTUtYmE4MS1hZDcyNGUwNTk5MTNcIixcInByb2ZpbGVcIjpcIkFEVUxUXCIsXCJ2ZXJzaW9uXCI6XCJ2MlwiLFwic3Vic2NyaXB0aW9uc1wiOntcImluXCI6e319LFwiaXNzdWVkQXRcIjoxNjY2ODQ0NjAwMjA4fSIsInZlcnNpb24iOiIxXzAifQ.aCCvR7Il0NCsg6181y5NDBCwiTACrYg3wxdAusKfmuY'
                db.clear()
                db["token"] = token
                db.flush()
        mobile = Dialog().numeric(0, "Enter 10 Digit mobile number")
        url = url_constructor("/um/v3/users/084f1867f85e4f109087e876ab8eb2ae/register?register-by=phone_otp")
        data = {
            "phone_number": mobile,
            "country_prefix": "91",
            "device_meta": {"device_name": "Chrome Browser on Windows"}
        }
        data = json.dumps(data)
        resp = self.put(url, headers=self._getPlayHeaders(includeST=True, includeUM=True, extra={"x-hs-device-id": self.device_id, "x-request-id": self.device_id}), data=data)
        if deep_get(resp, "message") == 'User verification initiated':
            OTP = Dialog().numeric(0, "Enter 4 Digit OTP")
            url = url_constructor(
                "/um/v3/users/login?login-by=phone_otp")

            data = {
                "phone_number": mobile,
                "verification_code": OTP,
                "device_meta": {"device_name": "Chrome Browser on Windows"}
            }
            data = json.dumps(data)
            resp = self.put(url, headers=self._getPlayHeaders(
                includeST=True, includeUM=False, extra={"x-hs-device-id": self.device_id}), data=data)
            token = deep_get(resp, "user_identity")
            if token:
                with PersistentDict("userdata.pickle") as db:
                    db["token"] = token
                    db["deviceId"] = self.device_id
                    db["udata"] = json.loads(json.loads(
                        b64decode(token.split(".")[1] + "========")).get("sub"))
                    db.flush()
                    Script.notify("Login Success", "You are logged in")

    def doLogout(self):
        with PersistentDict("userdata.pickle") as db:
            db.clear()
            db.flush()

        Script.notify("Logout Success", "You are logged out")
        return

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

    def put(self, url, **kwargs):
        try:
            response = self.session.put(url, **kwargs)
            xbmc.log(json.dumps(response.json()))
            return response.json()
        except Exception as e:
            return self._handleError(e, url, "put", **kwargs)

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
                            "Subscription Error", "Please subscribe to watch this content")
                        # executebuiltin(
                        #    "RunPlugin(plugin://plugin.video.botallen.hotstar/resources/lib/main/login/)")
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
                    resp = self.session.get(url_constructor("/um/v3/users/refresh"),
                                            headers=self._getPlayHeaders(includeST=True, includeUM=False, extra={"x-hs-device-id": self.device_id, "x-request-id": self.device_id}), raise_for_status=False, max_age=-1).json()
                    if resp.get("errorCode"):
                        return resp.get("message")
                    new_token = deep_get(resp, "user_identity")
                    db['token'] = new_token
                    db.flush()
                    return new_token
            return False
        except Exception as e:
            return e

    @staticmethod
    def _getPlayHeaders(includeST=False, includeUM=False, playbackUrl=None, extra={}):
        with PersistentDict("userdata.pickle") as db:
            token = db.get("token")

        auth = getAuth(includeST, False, includeUM)
        headers = {
            "hotstarauth": auth,
            "x-hs-platform": "web",
            "x-hs-appversion": "7.41.0",
            "content-type": "application/json",
            "x-country-code": "IN",
            "x-platform-code": "firetv",
            "x-hs-usertoken": token,
            "x-hs-request-id": HotstarAPI.device_id,
            "user-agent": "Hotstar;in.startv.hotstar/3.3.0 (Android/8.1.0)",
            **extra,
        }
        if playbackUrl:
            r = Request(playbackUrl)
            r.add_header("user-agent", headers.get("user-agent"))
            cookie = urlopen(r).headers.get("Set-Cookie", "").split(";")[0]
            if cookie:
                headers["Cookie"] = cookie
        return headers

    @staticmethod
    def _getPlayParams(subTag="", encryption="widevine"):
        with PersistentDict("userdata.pickle") as db:
            deviceId = db.get("deviceId", HotstarAPI.device_id)
        return {
            "desired-config": "audio_channel:stereo|container:fmp4|dynamic_range:sdr|encryption:%s|ladder:tv|package:dash|resolution:fhd|%svideo_codec:h264" % (encryption, subTag or ""),
            "device-id": deviceId
        }

    @staticmethod
    def _findPlayback(playBackSets, lang=None, ask=False):
        selected = None
        index = -1
        options = []
        quality = {"4k": 0, "hd": 1, "sd": 2}
        for each in playBackSets:
            config = {k: v for d in map(lambda x: dict([x.split(":")]), each.get(
                "tags_combination", "a:b").split(";")) for k, v in d.items()}
            Script.log(
                f"Checking combination {config} with language {lang}", lvl=Script.DEBUG)
            if config.get("encryption", "") in ["plain", "widevine"] and config.get("package", "") in ["hls", "dash"]:
                if lang and config.get("language") and config.get("language", "") != lang:
                    continue
                config["playback"] = (each.get("playback_url"), each.get(
                    "licence_url"), "mpd" if config.get("package") == "dash" else "hls")
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
