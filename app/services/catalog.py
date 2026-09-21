"""Presentation metadata and existing camera resources, independent of user notes."""

import csv

from .spot_repo import SPOTS_CSV

with open(SPOTS_CSV, encoding="utf-8") as source:
    GUIDES = {row["id"]: row["notes"] for row in csv.DictReader(source)}

CAMERAS = {
    "north-pier-two-rivers": {
        "kind": "image",
        "embed": "/camera/two-rivers",
        "url": "http://harborcam.two-rivers.org/camera/index.html#/video",
        "name": "Two Rivers Harbor",
    },
    "port-washington": {
        "kind": "image",
        "embed": "/camera/port-washington",
        "url": "http://24.106.61.2:8081/camera/index.html#/video",
        "name": "Port Washington Harbor",
    },
    "kewaunee": {
        "kind": "image",
        "embed": "/camera/kewaunee",
        "url": "http://172.220.111.253/aca/index.html#view",
        "name": "Kewaunee Harbor",
    },
    "sheboygan-elbow": {
        "kind": "iframe",
        "embed": "https://www.youtube.com/embed/13j5iZkMpbE",
        "url": "https://www.youtube.com/watch?v=13j5iZkMpbE",
        "name": "Sheboygan Elbow",
    },
    "sheboygan-blue-harbor": {
        "kind": "iframe",
        "embed": "https://www.youtube.com/embed/ABRrwDe5Hho",
        "url": "https://www.youtube.com/watch?v=ABRrwDe5Hho",
        "name": "Blue Harbor",
    },
}
STREAMS = {
    "two-rivers": "http://harborcam.two-rivers.org/mjpg/video.mjpg?camera=1&resolution=1280x720",
    "port-washington": "http://24.106.61.2:8081/mjpg/video.mjpg?camera=1&resolution=1280x720",
    "kewaunee": "http://172.220.111.253/mjpg/video.mjpg",
}
WINDFINDER = {
    "north-pier-two-rivers": "https://www.windfinder.com/forecast/two_rivers_coast_guard",
    "sheboygan-elbow": "https://www.windfinder.com/forecast/sheboygan",
    "sheboygan-blue-harbor": "https://www.windfinder.com/forecast/sheboygan",
}
