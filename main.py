import os
import time
from typing import Optional, List, Dict, Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Cricket API Proxy", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PROVIDER = os.getenv("CRICKET_API_PROVIDER", "sportmonks").lower()
CRICKET_API_KEY = os.getenv("CRICKET_API_KEY")
SPORTMONKS_BASE = os.getenv("SPORTMONKS_BASE", "https://cricket.sportmonks.com/api/v2.0")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

NEWS_SOURCES = [
    "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
    "https://www.icc-cricket.com/rss/news",
]


def sportmonks_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not CRICKET_API_KEY:
        raise HTTPException(status_code=501, detail="CRICKET_API_KEY not set for SportMonks")
    url = f"{SPORTMONKS_BASE.rstrip('/')}/{path.lstrip('/')}"
    params = params or {}
    params["api_token"] = CRICKET_API_KEY
    r = requests.get(url, params=params, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def rapidapi_get(path: str, params: Optional[Dict[str, Any]] = None, base: str = "https://cricbuzz-cricket.p.rapidapi.com") -> Dict[str, Any]:
    if not RAPIDAPI_KEY or not RAPIDAPI_HOST:
        raise HTTPException(status_code=501, detail="RAPIDAPI_KEY or RAPIDAPI_HOST not configured")
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST,
    }
    r = requests.get(url, headers=headers, params=params or {}, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@app.get("/")
def read_root():
    return {"message": "Cricket Backend Running", "provider": API_PROVIDER}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "external_api": "⚠️ Not Configured" if not (CRICKET_API_KEY or RAPIDAPI_KEY) else "✅ Configured",
        "provider": API_PROVIDER,
        "time": int(time.time()),
    }
    return response


@app.get("/api/matches")
def get_matches(type: str = Query("live", pattern="^(live|upcoming|completed)$")):
    """Return simplified match lists for live/upcoming/completed."""
    try:
        if API_PROVIDER == "sportmonks":
            # SportMonks examples endpoints
            endpoint = {
                "live": "livescores",
                "upcoming": "fixtures",
                "completed": "fixtures/finished",
            }[type]
            params = {"include": "localteam,visitorteam,venue,season"}
            data = sportmonks_get(endpoint, params)
            raw_matches = data.get("data", [])

            def to_card(m: Dict[str, Any]) -> Dict[str, Any]:
                lt = (m.get("localteam") or {})
                vt = (m.get("visitorteam") or {})
                venue = (m.get("venue") or {})
                return {
                    "id": m.get("id"),
                    "status": m.get("status").upper() if m.get("status") else type.upper(),
                    "note": m.get("note"),
                    "runs": m.get("runs"),
                    "league_id": m.get("season_id"),
                    "localteam": {"id": lt.get("id"), "name": lt.get("name"), "code": lt.get("code")},
                    "visitorteam": {"id": vt.get("id"), "name": vt.get("name"), "code": vt.get("code")},
                    "venue": {"name": venue.get("name"), "city": venue.get("city")},
                    "starting_at": m.get("starting_at"),
                }

            matches = [to_card(m) for m in raw_matches]
            return {"type": type, "matches": matches}
        else:
            # RapidAPI Cricbuzz style
            # Using sample endpoints; exact paths depend on host
            path = {
                "live": "matches/v1/live",
                "upcoming": "matches/v1/upcoming",
                "completed": "matches/v1/recent",
            }[type]
            data = rapidapi_get(path)
            items = data.get("matches", data)  # depends on API
            cards = []
            for m in items:
                cards.append({
                    "id": m.get("matchId") or m.get("id"),
                    "status": (m.get("matchState") or m.get("status", type)).upper(),
                    "note": m.get("seriesName"),
                    "localteam": {"name": (m.get("team1") or {}).get("teamName"), "code": (m.get("team1") or {}).get("teamSName")},
                    "visitorteam": {"name": (m.get("team2") or {}).get("teamName"), "code": (m.get("team2") or {}).get("teamSName")},
                    "venue": {"name": m.get("venueInfo", {}).get("ground"), "city": m.get("venueInfo", {}).get("city")},
                    "starting_at": m.get("startTime"),
                })
            return {"type": type, "matches": cards}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@app.get("/api/match/{match_id}")
def get_match_details(match_id: str):
    """Match details: commentary, fall of wickets, scoreboard, playing XI, simplified response."""
    try:
        if API_PROVIDER == "sportmonks":
            params = {"include": ",".join([
                "localteam,visitorteam,venue",
                "runs,batting,bowling,manofmatch,manofseries",
                "lineup,balls,scoreboards",
            ])}
            data = sportmonks_get(f"fixtures/{match_id}", params)
            return data
        else:
            # RapidAPI provider - placeholder paths
            details = rapidapi_get(f"mcenter/v1/{match_id}")
            return details
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@app.get("/api/rankings")
def get_rankings(format: str = Query("odi", pattern="^(test|odi|t20)$")):
    """ICC rankings via public ICC site JSON if available, else fallback sample."""
    try:
        # ICC publishes rankings pages; no official public JSON guaranteed. We'll use scraped JSON endpoints if available
        # Fallback: simple curated sample
        url = f"https://www.icc-cricket.com/iccrankings/api/{format}/men/teams"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            teams = r.json()
        else:
            teams = []
        players = {"batting": [], "bowling": [], "allrounder": []}
        for cat in players.keys():
            pr = requests.get(f"https://www.icc-cricket.com/iccrankings/api/{format}/men/{cat}", timeout=15)
            if pr.status_code == 200:
                players[cat] = pr.json()
        return {"format": format, "teams": teams, "players": players}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@app.get("/api/news")
def get_news():
    """Fetch latest cricket news via RSS and return normalized items."""
    import feedparser  # type: ignore
    items: List[Dict[str, Any]] = []
    for src in NEWS_SOURCES:
        try:
            feed = feedparser.parse(src)
            for e in feed.entries[:20]:
                items.append({
                    "title": e.get("title"),
                    "link": e.get("link"),
                    "summary": e.get("summary", ""),
                    "published": e.get("published", e.get("updated")),
                    "source": feed.feed.get("title", "RSS"),
                    "image": (e.get("media_thumbnail") or e.get("media_content") or [{}])[0].get("url"),
                })
        except Exception:
            continue
    # Sort by published if possible
    return {"items": items[:50]}


@app.get("/api/trending-players")
def trending_players():
    """Simple trending list. In production, derive from API popularity or stats."""
    sample = [
        {"name": "Virat Kohli", "country": "India", "handle": "imVkohli", "image": "https://pbs.twimg.com/profile_images/1390384696942200832/0B8zW0gq_400x400.jpg"},
        {"name": "Joe Root", "country": "England", "handle": "root66", "image": "https://pbs.twimg.com/profile_images/1334100239247923202/0YfYxQyW_400x400.jpg"},
        {"name": "Babar Azam", "country": "Pakistan", "handle": "babarazam258", "image": "https://pbs.twimg.com/profile_images/1674019404247615488/1jWkQd2w_400x400.jpg"},
        {"name": "Kane Williamson", "country": "New Zealand", "handle": "", "image": ""},
        {"name": "Pat Cummins", "country": "Australia", "handle": "patcummins30", "image": ""},
    ]
    return {"players": sample}


@app.get("/api/tweets")
def get_tweets(query: str = Query(..., description="Twitter handle or search query")):
    """Fetch tweets via X API v2 if configured. Otherwise, return empty list.
    Configure with X_BEARER_TOKEN environment variable.
    """
    token = os.getenv("X_BEARER_TOKEN")
    if not token:
        return {"tweets": [], "note": "X_BEARER_TOKEN not configured"}
    headers = {"Authorization": f"Bearer {token}"}
    params = {"query": query, "tweet.fields": "created_at,public_metrics", "max_results": 10}
    r = requests.get("https://api.twitter.com/2/tweets/search/recent", headers=headers, params=params, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    data = r.json()
    tweets = [
        {
            "id": t.get("id"),
            "text": t.get("text"),
            "created_at": t.get("created_at"),
            "metrics": t.get("public_metrics", {}),
        }
        for t in data.get("data", [])
    ]
    return {"tweets": tweets}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
