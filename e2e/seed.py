"""Seed data for the end-to-end run. Titles are made up; nothing here comes from a provider."""
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, "D:/ottplatform/backend")
from app.db import SessionLocal  # noqa: E402
from app.models import Episode, Genre, MediaAsset, Profile, Season, Title, TitleGenre, TitleRight, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.catalog import norm_name, slugify  # noqa: E402

db = SessionLocal()
drama = Genre(name="Drama", slug=slugify("Drama"))
db.add(drama)
db.flush()


def title(name, type_="movie", year=2020, popularity=50, release=None, playable=True, kids=False):
    t = Title(type=type_, name=name, norm_name=norm_name(name), status="published", year=year, popularity=popularity, source="admin",
              synopsis=f"A made-up synopsis for {name}.", age_rating="PG", is_kids_safe=kids, release_date=release)
    db.add(t)
    db.flush()
    db.add(TitleGenre(title_id=t.id, genre_id=drama.id))
    if playable:
        db.add(TitleRight(title_id=t.id, license_type="public_domain", status="verified", territories=["*"], entitlement="registered",
                          evidence_url="https://proof.example/seed"))
    return t


def movie_asset(t):
    db.add(MediaAsset(title_id=t.id, kind="mp4", url=f"https://cdn.example.com/{t.norm_name}.mp4"))


for name, pop in (("Open Film", 90), ("Second Film", 80)):
    movie_asset(title(name, popularity=pop))
title("Locked Film", popularity=70, playable=False)  # no verified right: shows "where to watch", not Play
title("Coming Soon Film", popularity=60, release=date.today() + timedelta(days=20), playable=False)

serial = title("Serial", type_="series", popularity=95)
season = Season(title_id=serial.id, number=1)
db.add(season)
db.flush()
for n in range(1, 6):
    e = Episode(season_id=season.id, title_id=serial.id, number=n, name=f"Part {n}", air_date=date.today() - timedelta(days=60 - n))
    db.add(e)
    db.flush()
    db.add(MediaAsset(title_id=serial.id, episode_id=e.id, kind="mp4", url=f"https://cdn.example.com/serial-{n}.mp4"))

admin = User(email="admin@example.com", password_hash=hash_password("correct horse battery"), role="admin",
             email_verified_at=datetime.now(timezone.utc))
db.add(admin)
db.flush()
db.add(Profile(user_id=admin.id, name="Admin"))
db.commit()
print("seeded", db.query(Title).count(), "titles")
