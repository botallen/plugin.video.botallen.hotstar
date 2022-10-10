from functools import wraps, reduce
from codequick import Script
from codequick.script import Settings
from codequick.storage import PersistentDict
from .contants import url_constructor
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import urlquick
import json
from uuid import uuid4
import time
import hashlib
import hmac

from xbmc import executebuiltin


def deep_get(dictionary, keys, default=None):
    return reduce(lambda d, key: d.get(key, default) if isinstance(d, dict) else default, keys.split("."), dictionary)


def isLoggedIn(func):
    """
    Decorator to ensure that a valid login is present when calling a method
    """
    @wraps(func)
    def login_wrapper(*args, **kwargs):
        with PersistentDict("userdata.pickle") as db:
            if db.get("token"):
                return func(*args, **kwargs)
            elif db.get("isGuest") is None:
                db["token"] = guestToken()
                db["isGuest"] = True
                db.flush()
                return func(*args, **kwargs)
            else:
                # login require
                Script.notify(
                    "Login Error", "You need valid subscription to watch this content")
                # executebuiltin(
                #    "RunPlugin(plugin://plugin.video.botallen.hotstar/resources/lib/main/login/)")
                return False
    return login_wrapper
    
    
def getAuth(includeST=False, persona=False, includeUM=False):
    _AKAMAI_ENCRYPTION_KEY = b'\x05\xfc\x1a\x01\xca\xc9\x4b\xc4\x12\xfc\x53\x12\x07\x75\xf9\xee'
    if persona:
        _AKAMAI_ENCRYPTION_KEY = b"\xa0\xaa\x8b\xcf\x9d\xd5\x8e\xc6\xe3\xb5\x7d\x9b\x4e\x5a\x00\x80\xb1\x45\x0d\xf7\x43\x6c\xfa\x22\xdd\x5c\xff\xdf\xea\x8e\x12\x52"
    st = int(time.time())
    
    um = '/um/v3' if includeUM else ''
    exp = st + 6000
    auth = 'st=%d~exp=%d~acl=%s/*' % (st, exp, um) if includeST else 'exp=%d~acl=/*' % exp
    auth += '~hmac=' + hmac.new(_AKAMAI_ENCRYPTION_KEY,
                                auth.encode(), hashlib.sha256).hexdigest()
    return auth
    
    
def guestToken():
    hdr = {
                'hotstarauth': getAuth(includeST=True, persona=False, includeUM=True),
                'X-HS-Platform': 'PCTV',
                'X-Request-Id': str(uuid4()),
                'Content-Type': 'application/json',
            }

    data = json.dumps({"device_ids": [{"id": str(uuid4()), "type": "device_id"}]}).encode('utf-8')
    resp = urlquick.post(url_constructor("/um/v3/users"), data=data, headers=hdr).json()

    return deep_get(resp, "user_identity")


def updateQueryParams(url, params):
    url_parts = list(urlparse(url))
    query = dict(parse_qsl(url_parts[4]))
    query.update(params)
    url_parts[4] = urlencode(query)
    return urlunparse(url_parts)


def qualityFilter(config):
    return (
        config.get("resolution", "hd") == ["4k", "hd", "sd"][Settings.get_int("resolution")] and
        config.get("video_codec", "h265") == ["dvh265", "h265", "vp9", "h264"][Settings.get_int("video_codec")] and
        config.get("dynamic_range", "sdr") == ["dv", "hdr10", "sdr"][Settings.get_int("dynamic_range")] and
        config.get("audio_channel", "stereo") == ["stereo", "dolby51"][Settings.get_int("audio_channel")] and
        config.get("audio_codec", "aac") == [
            "ec3", "aac"][Settings.get_int("audio_codec")]
    )
