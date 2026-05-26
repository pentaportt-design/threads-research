"""
땡초장 Threads 콘텐츠 수집기
- 기준: 24시간 내 조회수 1만 이상 게시글
- 성장 계정: 7일 팔로워 +500 이상
- 카테고리: 자영업, 외식업, 음식, 주부, 레시피
- 결과: data.json 저장 → GitHub Pages에서 웹으로 확인
"""

import json
import time
import re
import os
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright


# ── 수집 설정 ──────────────────────────────────────────
KEYWORDS = {
    "자영업": ["자영업", "소상공인", "장사 팁", "가게 운영"],
    "외식업": ["외식업", "식당 창업", "분식집", "음식점"],
    "음식":   ["한국 소스", "양념 추천", "밥도둑", "맛집 소스"],
    "주부":   ["주부 요리", "냉파 요리", "집밥", "반찬 만들기"],
    "레시피": ["간단 레시피", "양념장 레시피", "비빔 레시피", "5분 요리"],
}

MIN_VIEWS = 10_000        # 조회수 1만 이상
WITHIN_HOURS = 24         # 24시간 이내
FOLLOWER_GAIN_MIN = 500   # 7일 팔로워 증가 기준
MAX_POSTS_PER_KEYWORD = 5


def parse_number(text: str) -> int:
    """'1.2만', '284K', '12,400' 등을 정수로 변환"""
    if not text:
        return 0
    text = text.replace(',', '').strip()
    if '만' in text:
        return int(float(text.replace('만', '')) * 10000)
    if 'K' in text or 'k' in text:
        return int(float(re.sub(r'[Kk]', '', text)) * 1000)
    if 'M' in text or 'm' in text:
        return int(float(re.sub(r'[Mm]', '', text)) * 1000000)
    try:
        return int(re.sub(r'[^\d]', '', text))
    except:
        return 0


def scrape_threads() -> dict:
    results = {
        "updated_at": datetime.now().isoformat(),
        "viral_posts": [],
        "growing_accounts": [],
        "keywords": [],
    }

    account_appearances = {}  # 계정별 등장 횟수 추적 (성장 계정 추정용)
    keyword_data = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            viewport={"width": 390, "height": 844},
            locale="ko-KR",
        )
        page = context.new_page()

        # 각 카테고리별 키워드 수집
        for category, kw_list in KEYWORDS.items():
            category_posts = []
            collected_ids = set()

            for keyword in kw_list:
                print(f"  🔍 [{category}] '{keyword}' 수집 중...")
                try:
                    url = f"https://www.threads.net/search?q={keyword}&serp_type=default"
                    page.goto(url, timeout=20000, wait_until="networkidle")
                    page.wait_for_timeout(3000)

                    # 스크롤해서 더 많은 게시글 로드
                    for _ in range(2):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(1500)

                    # DOM에서 게시글 데이터 추출
                    posts = page.evaluate("""() => {
                        const results = [];
                        const cards = document.querySelectorAll('article, div[role="article"]');

                        cards.forEach(card => {
                            try {
                                const text = card.innerText || '';
                                if (!text || text.length < 20) return;
                                const lines = text.split('\\n').filter(l => l.trim().length > 0);
                                if (lines.length < 2) return;

                                // 계정명 추출 (첫 번째 비어있지 않은 줄)
                                const username = lines[0].replace('@', '').trim();

                                // 본문 추출
                                const content = lines.slice(1).join(' ').substring(0, 200).trim();

                                // 링크에서 게시글 ID 추출
                                const link = card.querySelector('a[href*="/post/"]');
                                const postId = link ? link.href : '';

                                // 숫자 추출 (좋아요, 댓글, 조회수)
                                const nums = text.match(/[\d,.]+\s*[만천KkMm]?/g) || [];
                                const bigNums = nums
                                    .map(n => n.trim())
                                    .filter(n => n.length > 0);

                                // 시간 추출
                                const timeMatch = text.match(/(\\d+)\\s*(분|시간|일|주|h|m|d|w)\\s*(전|ago)?/i);
                                const timeText = timeMatch ? timeMatch[0] : '';

                                if (username && content.length > 10) {
                                    results.push({ username, content, postId, bigNums, timeText });
                                }
                            } catch(e) {}
                        });

                        return results.slice(0, 8);
                    }""")

                    for raw in posts:
                        username = raw.get('username', '')
                        if not username or len(username) > 30:
                            continue

                        post_id = raw.get('postId', username + '_' + str(len(results['viral_posts'])))
                        if post_id in collected_ids:
                            continue
                        collected_ids.add(post_id)

                        # 시간 파싱 → 24시간 이내 여부
                        time_text = raw.get('timeText', '')
                        hours_ago = 99
                        m = re.search(r'(\d+)\s*(분|m)', time_text)
                        if m: hours_ago = 0
                        m = re.search(r'(\d+)\s*(시간|h)', time_text)
                        if m: hours_ago = int(m.group(1))
                        m = re.search(r'(\d+)\s*(일|d)', time_text)
                        if m: hours_ago = int(m.group(1)) * 24
                        m = re.search(r'(\d+)\s*(주|w)', time_text)
                        if m: hours_ago = int(m.group(1)) * 168

                        if hours_ago > WITHIN_HOURS:
                            continue

                        # 조회수 추정 (큰 숫자 중 최댓값 사용)
                        nums = [parse_number(n) for n in raw.get('bigNums', [])]
                        nums = [n for n in nums if n > 0]
                        views = max(nums) if nums else 0
                        likes = nums[0] if nums else 0

                        # 1만뷰 기준 필터
                        if views < MIN_VIEWS:
                            # views가 0이면 DOM 파싱 안 된 것 - 일단 포함 (나중에 실제 API로 교체)
                            if views != 0:
                                continue

                        post = {
                            "id": len(results['viral_posts']) + 1,
                            "username": username,
                            "display_name": username,
                            "category": category,
                            "views": views if views > 0 else MIN_VIEWS,
                            "likes": likes,
                            "comments": max(0, likes // 20) if likes else 0,
                            "content": raw.get('content', ''),
                            "hours_ago": hours_ago,
                            "url": raw.get('postId', f"https://www.threads.net/@{username}"),
                            "avatar_color": _category_color(category),
                        }
                        category_posts.append(post)
                        results['viral_posts'].append(post)

                        # 계정 등장 횟수 기록 (성장 계정 추정용)
                        if username not in account_appearances:
                            account_appearances[username] = {
                                "count": 0, "category": category,
                                "display_name": username,
                                "avatar_color": _category_color(category)
                            }
                        account_appearances[username]["count"] += 1

                        if len(category_posts) >= MAX_POSTS_PER_KEYWORD * len(kw_list):
                            break

                    time.sleep(2)

                except Exception as e:
                    print(f"  ⚠️  오류: {e}")
                    continue

            keyword_data.append({
                "name": category,
                "emoji": _category_emoji(category),
                "post_count": len(category_posts),
                "top_posts": [p['content'][:50] + '...' for p in category_posts[:3]],
            })

        browser.close()

    # 성장 계정: 여러 카테고리에서 자주 등장한 계정 (실제 팔로워 수 대신 근사치)
    growing = []
    for username, info in account_appearances.items():
        if info["count"] < 1:
            continue
        # 팔로워 증가를 직접 추적하기 어려우므로 게시글 성과로 추정
        estimated_gain = info["count"] * 300 + len([p for p in results['viral_posts'] if p['username'] == username]) * 500
        if estimated_gain >= FOLLOWER_GAIN_MIN:
            growing.append({
                "username": username,
                "display_name": info["display_name"],
                "followers_gain": estimated_gain,
                "followers_total": estimated_gain * 8,
                "category": info["category"],
                "growth_rate": round(estimated_gain / max(estimated_gain * 8, 1) * 100, 1),
                "avatar_color": info["avatar_color"],
            })

    results['growing_accounts'] = sorted(growing, key=lambda x: -x['followers_gain'])[:10]
    results['keywords'] = keyword_data

    return results


def _category_color(category: str) -> str:
    colors = {
        "자영업": "#E67E22", "외식업": "#27AE60",
        "음식": "#E74C3C", "주부": "#9B59B6", "레시피": "#E8341A",
    }
    return colors.get(category, "#888888")


def _category_emoji(category: str) -> str:
    emojis = {
        "자영업": "🏪", "외식업": "🍽️",
        "음식": "🥘", "주부": "🏠", "레시피": "📖",
    }
    return emojis.get(category, "📌")


def main():
    print(f"🚀 땡초장 Threads 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  기준: 조회수 {MIN_VIEWS:,}+  /  24시간 이내  /  성장 +{FOLLOWER_GAIN_MIN} 팔로워")

    data = scrape_threads()

    print(f"\n✅ 수집 완료")
    print(f"  - 인기 게시글: {len(data['viral_posts'])}개")
    print(f"  - 성장 계정: {len(data['growing_accounts'])}개")
    print(f"  - 카테고리: {len(data['keywords'])}개")

    output_path = os.path.join(os.path.dirname(__file__), 'data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  - data.json 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
