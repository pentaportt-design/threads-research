"""
땡초장 Threads 수집기 - Apify 연동 버전
- Apify Threads Search Scraper 사용
- 매일 오전 7시 GitHub Actions로 자동 실행
- 결과: data.json 저장 → GitHub Pages 대시보드에 표시
"""

import os
import json
import requests
from datetime import datetime

# ── 설정 ──────────────────────────────────────────────
APIFY_API_TOKEN = os.environ["APIFY_API_TOKEN"]
ACTOR_ID = "FP43CZrdHtiSNn4SY"
KEYWORDS = {
    "자영업": ["자영업", "소상공인"],
    "외식업": ["외식업", "식당창업"],
    "음식":   ["밥도둑", "맛집소스"],
    "주부":   ["주부요리", "집밥"],
    "레시피": ["간단레시피", "양념장"],
}

MIN_VIEWS = 10_000
MAX_RESULTS = 20
FOLLOWER_GAIN_MIN = 500


def run_apify_actor(keyword: str, max_results: int = 20) -> list:
    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
    params = {"token": APIFY_API_TOKEN}
    payload = {"searchQuery": keyword, "maxResults": max_results, "sortBy": "top"}
    try:
        res = requests.post(url, params=params, json=payload, timeout=120)
        if res.status_code == 200:
            return res.json()
        else:
            print(f"  Apify 오류 {res.status_code}: {res.text[:200]}")
            return []
    except Exception as e:
        print(f"  요청 실패: {e}")
        return []


def parse_views(item: dict) -> int:
    views = item.get("viewCount") or item.get("views") or item.get("playCount") or 0
    try:
        return int(str(views).replace(",", ""))
    except:
        return 0


def category_color(category: str) -> str:
    colors = {"자영업": "#E67E22", "외식업": "#27AE60", "음식": "#E74C3C", "주부": "#9B59B6", "레시피": "#E8341A"}
    return colors.get(category, "#888888")


def scrape_all() -> dict:
    results = {"updated_at": datetime.now().isoformat(), "viral_posts": [], "growing_accounts": [], "keywords": []}
    account_tracker = {}

    for category, kw_list in KEYWORDS.items():
        category_posts = []
        seen_ids = set()

        for keyword in kw_list:
            print(f"  [{category}] '{keyword}' 수집 중...")
            items = run_apify_actor(keyword, MAX_RESULTS)
            print(f"     {len(items)}개 수집됨")

            for item in items:
                post_id = str(item.get("id") or item.get("postId") or item.get("timestamp", ""))
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                content = (item.get("captionText") or item.get("text") or item.get("content") or "").strip()
                if not content:
                    continue

                username = item.get("username") or item.get("ownerUsername") or "unknown"
                display_name = item.get("displayName") or item.get("fullName") or username
                views = parse_views(item)
                likes = int(item.get("likesCount") or item.get("likes") or 0)
                comments = int(item.get("repliesCount") or item.get("comments") or 0)

                hours_ago = 999
                timestamp = item.get("timestamp") or item.get("createdAt") or ""
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        diff = datetime.now(dt.tzinfo) - dt
                        hours_ago = int(diff.total_seconds() / 3600)
                    except:
                        pass

                post = {
                    "id": len(results["viral_posts"]) + 1,
                    "username": username,
                    "display_name": display_name,
                    "category": category,
                    "views": views if views > 0 else likes * 10,
                    "likes": likes,
                    "comments": comments,
                    "content": content[:200],
                    "hours_ago": hours_ago,
                    "url": item.get("url") or f"https://www.threads.net/@{username}",
                    "avatar_color": category_color(category),
                }

                category_posts.append(post)
                results["viral_posts"].append(post)

                if username not in account_tracker:
                    account_tracker[username] = {
                        "count": 0, "category": category, "display_name": display_name,
                        "followers": int(item.get("followersCount") or item.get("followers") or 0),
                        "avatar_color": category_color(category),
                    }
                account_tracker[username]["count"] += 1

        results["keywords"].append({
            "name": category,
            "emoji": {"자영업":"🏪","외식업":"🍽️","음식":"🥘","주부":"🏠","레시피":"📖"}.get(category, "📌"),
            "post_count": len(category_posts),
            "top_posts": [p["content"][:50] + "..." for p in category_posts[:3]],
        })

    growing = []
    for username, info in account_tracker.items():
        estimated_gain = info["count"] * 400 + min(info["followers"] // 100, 2000)
        if estimated_gain >= FOLLOWER_GAIN_MIN:
            growing.append({
                "username": username, "display_name": info["display_name"],
                "followers_gain": estimated_gain,
                "followers_total": info["followers"] if info["followers"] > 0 else estimated_gain * 10,
                "category": info["category"],
                "growth_rate": round(estimated_gain / max(info["followers"], 1) * 100, 1),
                "avatar_color": info["avatar_color"],
            })

    results["growing_accounts"] = sorted(growing, key=lambda x: -x["followers_gain"])[:10]
    return results


def main():
    print(f"Apify Threads 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    data = scrape_all()
    print(f"완료 - 게시글: {len(data['viral_posts'])}개, 성장 계정: {len(data['growing_accounts'])}개")
    output_path = os.path.join(os.path.dirname(__file__), "data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"data.json 저장 완료")


if __name__ == "__main__":
    main()
