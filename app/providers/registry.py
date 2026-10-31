import importlib
import logging

from ..config import get_settings
from .archive import ArchiveProvider
from .base import AvailabilityProvider, FreeContentProvider, MetadataProvider
from .tmdb import TMDBProvider
from .youtube import YouTubeProvider
from .watchmode import WatchmodeProvider

log = logging.getLogger("ott.providers")


class Registry:
    def __init__(self):
        self.metadata: list[MetadataProvider] = []
        self.availability: list[AvailabilityProvider] = []
        self.free: list[FreeContentProvider] = []
        self.youtube: YouTubeProvider | None = None

    def register(self, adapter) -> None:
        if isinstance(adapter, MetadataProvider):
            self.metadata.append(adapter)
        if isinstance(adapter, AvailabilityProvider) and adapter not in self.availability:
            self.availability.append(adapter)
        if isinstance(adapter, FreeContentProvider):
            self.free.append(adapter)

    @property
    def primary_metadata(self) -> MetadataProvider | None:
        return next((p for p in self.metadata if p.configured()), None)

    def status(self) -> dict[str, bool]:
        names = {p.name: p.configured() for p in [*self.metadata, *self.availability, *self.free]}
        if self.youtube:
            names["youtube"] = self.youtube.configured()
        return names


def build_registry() -> Registry:
    reg = Registry()
    tmdb = TMDBProvider()
    reg.register(WatchmodeProvider())  # preferred availability source (deep links)
    reg.register(tmdb)  # metadata + fallback availability
    reg.register(ArchiveProvider())
    reg.youtube = YouTubeProvider()
    for spec in get_settings().extra_providers:
        try:
            mod, cls = spec.split(":")
            reg.register(getattr(importlib.import_module(mod), cls)())
        except Exception:
            log.exception("could not load extra provider %s", spec)
    return reg


_registry: Registry | None = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry


def set_registry(reg: Registry | None) -> None:
    global _registry
    _registry = reg
