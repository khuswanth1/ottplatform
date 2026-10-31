from conftest import PASSWORD, Browser

NEW = "a brand new passphrase"


def login(email, password):
    b = Browser()
    r = b.post("/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        b.csrf = r.json()["csrf_token"]
    return b, r


def test_change_password_keeps_this_device_and_signs_out_the_others(make_user):
    u = make_user("pw@example.com")
    other, r = login("pw@example.com", PASSWORD)
    assert r.status_code == 200 and other.get("/auth/me").status_code == 200
    r = u.post("/account/change-password", json={"current_password": PASSWORD, "new_password": NEW})
    assert r.status_code == 200, r.text
    assert u.get("/auth/me").status_code == 200            # this device stays signed in
    assert other.get("/auth/me").status_code == 401        # the other one does not
    assert login("pw@example.com", PASSWORD)[1].status_code == 401   # old password no longer works
    assert login("pw@example.com", NEW)[1].status_code == 200


def test_wrong_current_password_changes_nothing(make_user):
    u = make_user("pw2@example.com")
    assert u.post("/account/change-password", json={"current_password": "not it at all", "new_password": NEW}).status_code == 403
    assert login("pw2@example.com", PASSWORD)[1].status_code == 200


def test_weak_or_unchanged_new_password_is_refused(make_user):
    u = make_user("pw3@example.com")
    assert u.post("/account/change-password", json={"current_password": PASSWORD, "new_password": "short"}).status_code == 422
    assert u.post("/account/change-password", json={"current_password": PASSWORD, "new_password": PASSWORD}).status_code == 422
    assert login("pw3@example.com", PASSWORD)[1].status_code == 200


def test_requires_login():
    assert Browser().post("/account/change-password", json={"current_password": "x", "new_password": NEW}).status_code == 401
