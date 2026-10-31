from conftest import PASSWORD, Browser
from helpers import mk_title


def second_device(email="user@example.com"):
    b = Browser()
    r = b.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    b.csrf = r.json()["csrf_token"]
    return b


def lock(u, pin="1234", password=PASSWORD):
    return u.put(f"/profiles/{u.profile}/pin", json={"pin": pin, "password": password})


def test_set_pin_needs_password_and_valid_digits(make_user):
    u = make_user()
    assert lock(u, password="wrong password").status_code == 403
    assert lock(u, pin="12").status_code == 422 and lock(u, pin="abcd").status_code == 422
    r = lock(u)
    assert r.status_code == 200 and r.json()["has_pin"] is True
    assert "pin" not in r.text.replace("has_pin", "")  # the hash never leaves the server


def test_locked_profile_blocks_other_devices_until_unlocked(make_user, db):
    u = make_user()
    t = mk_title(db)
    lock(u)
    assert u.get("/watchlist").status_code == 200  # the device that set it is already open
    d2 = second_device()
    d2.profile = u.profile
    r = d2.get("/watchlist")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "profile_locked"
    assert d2.put(f"/watchlist/{t.id}").status_code == 403
    assert d2.get("/profiles").json()[0]["has_pin"] is True  # listing profiles is still allowed
    assert d2.post(f"/profiles/{u.profile}/unlock", json={"pin": "0000"}).status_code == 403
    assert d2.post(f"/profiles/{u.profile}/unlock", json={"pin": "1234"}).status_code == 200
    assert d2.get("/watchlist").status_code == 200


def test_only_one_profile_stays_open_per_session(make_user):
    u = make_user()
    first = u.profile
    second = u.post("/profiles", json={"name": "Second"}).json()["id"]
    lock(u)
    u.profile = second
    assert lock(u, "5678").status_code == 200  # opens `second`, closes `first`
    u.profile = first
    assert u.get("/watchlist").status_code == 403
    assert u.post(f"/profiles/{first}/unlock", json={"pin": "1234"}).status_code == 200
    assert u.get("/watchlist").status_code == 200
    u.profile = second
    assert u.get("/watchlist").status_code == 403


def test_five_wrong_pins_lock_the_profile_then_password_resets(make_user):
    u = make_user()
    lock(u)
    d2 = second_device()
    for _ in range(5):
        assert d2.post(f"/profiles/{u.profile}/unlock", json={"pin": "9999"}).status_code == 403
    assert d2.post(f"/profiles/{u.profile}/unlock", json={"pin": "1234"}).status_code == 429  # even the right PIN waits
    assert lock(u, "4321").status_code == 200  # the owner resets it with the password
    assert d2.post(f"/profiles/{u.profile}/unlock", json={"pin": "4321"}).status_code == 200


def test_changing_pin_closes_it_on_other_devices(make_user):
    u = make_user()
    lock(u)
    d2 = second_device()
    assert d2.post(f"/profiles/{u.profile}/unlock", json={"pin": "1234"}).status_code == 200
    d2.profile = u.profile
    assert d2.get("/watchlist").status_code == 200
    lock(u, "4321")
    assert d2.get("/watchlist").status_code == 403


def test_clear_pin(make_user):
    u = make_user()
    lock(u)
    r = u.put(f"/profiles/{u.profile}/pin", json={"pin": None, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["has_pin"] is False
    d2 = second_device()
    d2.profile = u.profile
    assert d2.get("/watchlist").status_code == 200


def test_editing_or_deleting_a_locked_profile_needs_it_open(make_user):
    u = make_user()
    extra = u.post("/profiles", json={"name": "Second"}).json()["id"]
    lock(u)
    d2 = second_device()
    assert d2.patch(f"/profiles/{u.profile}", json={"name": "Renamed"}).status_code == 403
    assert d2.delete(f"/profiles/{u.profile}").status_code == 403
    d2.post(f"/profiles/{u.profile}/unlock", json={"pin": "1234"})
    assert d2.patch(f"/profiles/{u.profile}", json={"name": "Renamed"}).status_code == 200
    assert d2.patch(f"/profiles/{extra}", json={"name": "Other"}).status_code == 200  # unlocked profiles are unaffected


def test_cannot_touch_another_users_pin(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    assert b.put(f"/profiles/{a.profile}/pin", json={"pin": "1234", "password": PASSWORD}).status_code == 404
    assert b.post(f"/profiles/{a.profile}/unlock", json={"pin": "1234"}).status_code == 404
