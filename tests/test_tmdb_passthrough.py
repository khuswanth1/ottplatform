import pytest

from conftest import Browser


@pytest.mark.parametrize("path", [
    "/catalog/keyword/abc",
    "/catalog/person/12abc/credits",
    "/catalog/person/..%2Fx/translations",
    "/titles/collection/x1/translations",
    "/titles/guest-session/bad%20id/rated/movies",
])
def test_tmdb_ids_are_validated_before_upstream_call(upstream, path):
    n = len(upstream.calls)
    assert Browser().get(path).status_code in (404, 422)
    assert len(upstream.calls) == n


def test_guest_session_rated_accepts_tv_episodes(upstream):
    r = Browser().get("/titles/guest-session/abc123/rated/tv/episodes")
    assert r.status_code == 200
    r = Browser().get("/titles/guest-session/abc123/rated/other")
    assert r.status_code == 422
