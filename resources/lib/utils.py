from functools import wraps, reduce
from codequick import Script
from codequick.script import Settings
from codequick.storage import PersistentDict
from .contants import url_constructor
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import urlquick
from uuid import uuid4

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
                token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOiJ1bV9hY2Nlc3MiLCJleHAiOjE2NjQ4NjI3MzIsImlhdCI6MTY2NDI1NzkzMiwiaXNzIjoiVFMiLCJqdGkiOiIxMzc5MTIzN2QxNTg0YjJiOGE5ZGNjMTFiMzg4YTcyZCIsInN1YiI6IntcImhJZFwiOlwiMDg0ZjE4NjdmODVlNGYxMDkwODdlODc2YWI4ZWIyYWVcIixcInBJZFwiOlwiZGIxYzFlN2Q2NmFhNDg1ZDg4MzdiOGRhNzAzZWUwOWFcIixcIm5hbWVcIjpcIkd1ZXN0IFVzZXJcIixcImlwXCI6XCIxMDMuMTcyLjg2LjExNFwiLFwiY291bnRyeUNvZGVcIjpcImluXCIsXCJjdXN0b21lclR5cGVcIjpcIm51XCIsXCJ0eXBlXCI6XCJndWVzdFwiLFwiaXNFbWFpbFZlcmlmaWVkXCI6ZmFsc2UsXCJpc1Bob25lVmVyaWZpZWRcIjpmYWxzZSxcImRldmljZUlkXCI6XCI5NTE5OWEwYi1jODVhLTQwNTUtYmE4MS1hZDcyNGUwNTk5MTNcIixcInByb2ZpbGVcIjpcIkFEVUxUXCIsXCJ2ZXJzaW9uXCI6XCJ2MlwiLFwic3Vic2NyaXB0aW9uc1wiOntcImluXCI6e319LFwiaXNzdWVkQXRcIjoxNjY0MjU3OTMyMDU1fSIsInZlcnNpb24iOiIxXzAifQ.MfG9sAeXaBRkQgqz_TpQDAEt5jvIm6mlrzuA3fgvngk'
                db["token"] = token               
                # db["token"] = guestToken()
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


def guestToken():
    resp = urlquick.post(url_constructor("/in/aadhar/v2/firetv/in/user/guest-signup"), json={
        "idType": "device",
        "id": str(uuid4()),
    }).json()
    return deep_get(resp, "description.userIdentity")


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
