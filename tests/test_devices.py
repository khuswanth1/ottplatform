from conftest import PASSWORD, Browser
from app.useragent import describe

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
EDGE_WIN = CHROME_WIN + " Edg/126.0"
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0"


def sign_in(email="user@example.com", ua=None):
    b = Browser()
    r = b.post("/auth/login", json={"email": email, "password": PASSWORD}, headers={"User-Agent": ua} if ua else None)
    assert r.status_code == 200
    b.csrf = r.json()["csrf_token"]
    return b


def test_user_agent_labels():
    assert describe(CHROME_WIN) == "Chrome on Windows"
    assert describe(EDGE_WIN) == "Edge on Windows"            # Edge also says Chrome and Safari
    assert describe(SAFARI_IPHONE) == "Safari on iPhone"
    assert describe(FIREFOX_LINUX) == "Firefox on Linux"
    assert describe("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36") == "Chrome on Android"
    assert describe("") == "Unknown device" and describe(None) == "Unknown device"
    assert describe("weird/1.0") == "Unknown device"


def test_lists_signed_in_devices_and_marks_this_one(make_user):
    u = make_user()
    other = sign_in(ua=SAFARI_IPHONE)
    rows = u.get("/account/devices").json()
    assert len(rows) == 2 and sum(r["current"] for r in rows) == 1
    assert "Safari on iPhone" in [r["label"] for r in rows]
    assert [r["current"] for r in other.get("/account/devices").json()].count(True) == 1
    assert {"id", "label", "ip", "created_at", "last_seen_at", "current"} == set(rows[0])


def test_sign_out_one_device(make_user):
    u = make_user()
    other = sign_in(ua=EDGE_WIN)
    target = next(r for r in u.get("/account/devices").json() if r["label"] == "Edge on Windows")
    assert u.delete(f"/account/devices/{target['id']}").status_code == 200
    assert other.get("/auth/me").status_code == 401           # that device is signed out at once
    assert u.get("/auth/me").status_code == 200
    assert len(u.get("/account/devices").json()) == 1
    assert u.delete(f"/account/devices/{target['id']}").status_code == 404   # already gone


def test_cannot_sign_out_this_device_here(make_user):
    u = make_user()
    me = next(r for r in u.get("/account/devices").json() if r["current"])
    assert u.delete(f"/account/devices/{me['id']}").status_code == 400
    assert u.get("/auth/me").status_code == 200


def test_sign_out_all_others_keeps_this_device(make_user):
    u = make_user()
    others = [sign_in(), sign_in(ua=SAFARI_IPHONE)]
    r = u.post("/account/sign-out-others")
    assert r.status_code == 200 and "2 other devices" in r.json()["message"]
    assert all(o.get("/auth/me").status_code == 401 for o in others)
    assert u.get("/auth/me").status_code == 200
    assert u.post("/account/sign-out-others").json()["message"] == "Signed out of 0 other devices."


def test_devices_are_private_to_the_account(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    a_dev = a.get("/account/devices").json()[0]
    assert [r["id"] for r in b.get("/account/devices").json()] == [r["id"] for r in b.get("/account/devices").json()]
    assert a_dev["id"] not in [r["id"] for r in b.get("/account/devices").json()]
    assert b.delete(f"/account/devices/{a_dev['id']}").status_code == 404
    assert a.get("/auth/me").status_code == 200
    b.post("/account/sign-out-others")
    assert a.get("/auth/me").status_code == 200                 # B's sweep does not touch A


def test_requires_login():
    assert Browser().get("/account/devices").status_code == 401
    assert Browser().post("/account/sign-out-others").status_code == 401
