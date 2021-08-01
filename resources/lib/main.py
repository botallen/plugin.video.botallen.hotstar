# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from codequick import Route, run, Script, Resolver

import resources.lib.utils as U
from xbmcgui import DialogProgress
from xbmc import executebuiltin
from xbmcplugin import SORT_METHOD_EPISODE, SORT_METHOD_DATE
import time
import urlquick
from .api import HotstarAPI
from .builder import Builder
from .contants import BASE_HEADERS, CONTENT_TYPE


@Route.register
def root(plugin):
    yield builder.buildSearch(Route.ref("/resources/lib/main:tray_list"))
    menuItmes = api.getMenu()
    yield from builder.buildMenu(menuItmes)
    yield builder.buildSettings()


@Route.register
def menu_list(plugin, url):
    items, nextPageUrl = api.getPage(url)
    yield from builder.buildPage(items, nextPageUrl)


@Route.register
def tray_list(plugin, url, search_query=False):

    items, nextPageUrl, allResultsPageUrl = api.getTray(
        url, search_query=search_query)

    if not items or len(items) == 0:
        yield False
        Script.notify("No Result Found", "No items to show")
        raise StopIteration()

    plugin.content_type = items and CONTENT_TYPE.get(items[0].get("assetType"))
    if plugin.content_type == "episodes":
        plugin.add_sort_methods(SORT_METHOD_EPISODE)
    yield from builder.buildTray(items, nextPageUrl, allResultsPageUrl)


@Resolver.register
@U.isLoggedIn
def play_vod(plugin, contentId, subtag, label, drm=False, lang=None, partner=None, ask=False):
    playbackUrl, licenceUrl, playbackProto = api.getPlay(
        contentId, subtag, drm=drm, lang=lang, partner=partner, ask=ask)
    if playbackUrl:
        return builder.buildPlay(playbackUrl, licenceUrl, playbackProto, label, drm)
    return False


@Resolver.register
@U.isLoggedIn
def play_ext(plugin, contentId, partner=None):
    drm, subtag, label = api.getExtItem(contentId)
    if drm is not None:
        playbackUrl, licenceUrl, playbackProto = api.getPlay(
            contentId, subtag, drm=drm, partner=partner)
        if playbackUrl:
            return builder.buildPlay(playbackUrl, licenceUrl, playbackProto, label, drm)
    return False


@Script.register
def login(plugin):
    msg = "1. Go to [B]https://tv.hotstar.com[/B]\n2. Login with your hotstar account[CR]3. Enter the 4 digit code : "
    pdialog = DialogProgress()
    pdialog.create("Login", msg+"Loading...")
    for code, i in api.doLogin():
        if pdialog.iscanceled() or i == 100:
            break
        else:
            time.sleep(1)
        pdialog.update(i, msg+"[B][UPPERCASE]%s[/UPPERCASE][/B]" % code)
    pdialog.close()


@Script.register
def logout(plugin):
    api.doLogout()


@Script.register
def settings(plugin):
    executebuiltin("Addon.OpenSettings({0})".format(plugin.get_info("id")))
    return False


api = HotstarAPI()
builder = Builder()
