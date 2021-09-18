# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import datetime
from codequick import Listitem, Script, Resolver, Route
from codequick.storage import PersistentDict
from urlquick import MAX_AGE
import inputstreamhelper
from .contants import url_constructor, IMG_THUMB_H_URL, IMG_POSTER_V_URL, IMG_FANART_H_URL, MEDIA_TYPE, BASE_HEADERS, TRAY_IDENTIFIERS, PERSONA_BASE_URL, NAME
from .api import deep_get, HotstarAPI
from .utils import updateQueryParams
from urllib.parse import urlencode
from pickle import dumps
from binascii import hexlify
import urlquick
import re
import json


class Builder:

    def buildMenu(self, menuItems):
        for each in menuItems:
            if not each.get("pageUri"):
                continue
            item = Listitem()
            item.label = each.get("name")
            item.art['fanart'] = "https://secure-media.hotstar.com/static/firetv/v1/poster_%s_in.jpg" % each.get(
                "name").lower() if not each.get("name").lower() == "genres" else "https://secure-media.hotstar.com/static/firetv/v1/poster_genre_in.jpg"
            item.set_callback(Route.ref("/resources/lib/main:menu_list") if each.get("pageType") else Route.ref(
                "/resources/lib/main:tray_list"), url=updateQueryParams(each.get("pageUri"), {"tas": "15"}))
            item.art.local_thumb(each.get("name").lower() + ".png")
            yield item

    def buildSearch(self, callback):
        return Listitem().search(callback, url="")

    def buildSettings(self):
        return Listitem.from_dict(Route.ref("/resources/lib/main:settings"), "Settings")

    def buildPage(self, items, nextPageUrl=None):
        for each in items:
            if each.get("traySource", "") in ["THIRD_PARTY"]:
                continue
            tray_url = ""
            if each.get("uri"):
                tray_url = updateQueryParams(each.get("uri"), {"tas": "15"})
            if each.get("traySource") == "GRAVITY":
                path = TRAY_IDENTIFIERS.get(each.get("addIdentifier"))
                if path:
                    tray_url = PERSONA_BASE_URL + path
                else:
                    continue
            art = info = None
            aItems = deep_get(each, "assets.items")
            if aItems and len(aItems) > 0:
                info = {
                    "plot": "Contains : " + " | ".join([x.get("title") for x in aItems])
                }
                art = {
                    "thumb": IMG_THUMB_H_URL % deep_get(aItems[0], "images.h"),
                    "icon": IMG_THUMB_H_URL % deep_get(aItems[0], "images.h"),
                    "poster": IMG_POSTER_V_URL % (deep_get(aItems[0], "images.v") or deep_get(aItems[0], "images.h")),
                    "fanart": IMG_FANART_H_URL % deep_get(aItems[0], "images.h"),
                }
            yield Listitem().from_dict(**{
                "label": "Carousel" if each.get("layoutType", "") == "MASTHEAD" else each.get("title"),
                "art": art,
                "info": info,
                "callback": Route.ref("/resources/lib/main:tray_list"),
                "properties": {
                    "IsPlayable": False
                },
                "params": {
                    "url": tray_url,
                }
            })
        if nextPageUrl:
            yield Listitem().next_page(url=nextPageUrl)

    def buildTray(self, items, nextPageUrl=None, allResultsPageUrl=None):
        for eachItem in items:
            yield Listitem().from_dict(**self._buildItem(eachItem))
        if nextPageUrl:
            yield Listitem().next_page(url=nextPageUrl)
        if allResultsPageUrl:
            item = Listitem()
            item.label = "All Episodes"
            item.art.global_thumb("playlist.png")
            item.set_callback(
                Route.ref("/resources/lib/main:tray_list"), url=allResultsPageUrl)
            yield item

    def buildPlay(self, playbackUrl, licenceUrl=None, playbackProto="mpd", label="", drm=False):
        is_helper = inputstreamhelper.Helper("mpd", drm=drm)
        if is_helper.check_inputstream():
            stream_headers = HotstarAPI._getPlayHeaders(
                playbackUrl=playbackUrl)
            subtitleUrl = re.sub(
                "(.*)(master[\w+\_\-]*?\.[\w+]{3})([\w\/\?=~\*\-]*)", "\g<1>subtitle/lang_en/subtitle.vtt\g<3>", playbackUrl) + "|User-Agent=Hotstar%3Bin.startv.hotstar%2F3.3.0+%28Android%2F8.1.0%29"
            Script.log(subtitleUrl, lvl=Script.DEBUG)
            if licenceUrl and "/hms/wv/" in licenceUrl:
                drm = "com.widevine.alpha"
            return Listitem().from_dict(**{
                "label": label,
                "callback": playbackUrl,
                "properties": {
                    "IsPlayable": True,
                    "inputstream": is_helper.inputstream_addon,
                    "inputstream.adaptive.manifest_type": playbackProto,
                    "inputstream.adaptive.license_type": drm,
                    "inputstream.adaptive.stream_headers": urlencode(stream_headers),
                    "inputstream.adaptive.license_key": licenceUrl and licenceUrl + '|%s&Content-Type=application/octet-stream|R{SSM}|' % urlencode(stream_headers)
                },
                "subtitles": [subtitleUrl]
            })
        return False

    def _buildItem(self, item):
        context = []
        if item.get("assetType") in ["CHANNEL", "GENRE", "GAME", "LANGUAGE", "SHOW", "SEASON"]:
            if item.get("assetType", "") in ["SHOW"] or item.get("pageType") in ["HERO_LANDING_PAGE", "NAVIGATION_LANDING_PAGE"]:
                callback = Route.ref("/resources/lib/main:menu_list")
            else:
                callback = Route.ref("/resources/lib/main:tray_list")
            params = {"url": item.get("uri")}
        else:
            if item.get("isSubTagged"):
                with PersistentDict("userdata.pickle") as db:
                    subtag = deep_get(dict(db), "udata.subscriptions.in")
                if subtag:
                    subtag = list(subtag.keys())[0]
                    Script.log("Using subtag from subscription: %s" %
                               subtag, lvl=Script.DEBUG)
                else:
                    resp = urlquick.get(
                        item.get("uri"), headers=BASE_HEADERS).json()
                    item = deep_get(resp, "body.results.item")
                    if item.get("features", [{}])[0].get("subType"):
                        subtag = item.get("features", [{}])[
                            0].get("subType")
                        Script.log("Using subtag %s" %
                                   subtag, lvl=Script.DEBUG)
                    else:
                        subtag = "HotstarPremium"
                        Script.log("No subType found.Using subtag %s as default" %
                                   subtag, lvl=Script.DEBUG)
            callback = Resolver.ref("/resources/lib/main:play_vod")
            params = {
                "contentId": item.get("contentId"),
                "subtag": item.get("isSubTagged") and "subs-tag:%s|" % subtag,
                "label": item.get("title"),
                "drm": "com.widevine.alpha" if item.get("encrypted") or item.get("clipType", "") == "LIVE" else False,
                "partner": "com.jio.jioplay.tv" if item.get("clipType", "") == "LIVE" else None
            }
            context.extend([("Select Playback", "PlayMedia(plugin://plugin.video.botallen.hotstar/resources/lib/main/play_vod/?_pickle_=%s)" %
                             hexlify(dumps(dict({"ask": True}, **params))).decode("ascii"))])
            if len(item.get("langObjs", [])) > 1:
                context.extend(map(lambda x: ("Play in %s" % x.get("name"), "PlayMedia(plugin://plugin.video.botallen.hotstar/resources/lib/main/play_vod/?_pickle_=%s)" %
                                              hexlify(dumps(dict({"lang": x.get("iso3code")}, **params))).decode("ascii")), item.get("langObjs", [])))

        label = item.get("title")
        if item.get("clipType", "") == "LIVE":
            label += "  -  [COLOR red]LIVE[/COLOR]"
        elif item.get("assetType") == "SEASON":
            label = "Season {0} ({1})".format(
                item.get("seasonNo"), item.get("episodeCnt"))

        props = {"IsPlayable": False}
        if item.get("watched"):
            props["ResumeTime"] = item.get(
                "watched", 0) * item.get("duration", 0)
            props["TotalTime"] = item.get("duration", 0)
        return {
            "label": label,
            "art": {
                "icon": IMG_THUMB_H_URL % deep_get(item, "images.h"),
                "thumb": IMG_THUMB_H_URL % deep_get(item, "images.h"),
                "fanart": IMG_FANART_H_URL % deep_get(item, "images.h"),
                "poster": IMG_POSTER_V_URL % ((deep_get(item, "images.v") or deep_get(item, "imageSets.DARK_THEME.v") or deep_get(item, "images.h")))
            },
            "info": {
                "genre": item.get("genre"),
                "year": item.get("year"),
                "episode": item.get("episodeNo") or item.get("episodeCnt"),
                "season": item.get("seasonNo") or item.get("seasonCnt"),
                "mpaa": item.get("parentalRatingName"),
                "plot": item.get("description"),
                "title": label,
                "sorttitle": item.get("shortTitle"),
                "duration": item.get("duration"),
                "studio": item.get("cpDisplayName"),
                "premiered": item.get("broadCastDate") and datetime.fromtimestamp(item.get("broadCastDate")).strftime("%Y-%m-%d"),
                "path": "",
                "trailer": "",
                "dateadded": item.get("broadCastDate") and datetime.fromtimestamp(item.get("broadCastDate")).strftime("%Y-%m-%d %H:%M:%S"),
                "mediatype": MEDIA_TYPE.get(item.get("assetType"))
            },
            "properties": props,
            # TODO: Get Stream Info
            # "stream": {
            #     # "video_codec": "h264",
            #     "width": "1920",
            #     "height": "1080",
            #     # "audio_codec": "aac"
            # },
            "callback": callback,
            "context": context,
            "params": params
        }
