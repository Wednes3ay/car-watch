#!/usr/bin/env python3
"""엔카·당근 새 매물 감시기.

config.json 의 조건으로 엔카·당근을 검색하고,
- 처음 보는 매물만 골라
- 엔카 성능점검·보험이력으로 골격손상/침수/전손/도난 차를 거른 뒤
- 텔레그램으로 알리고 docs/index.html (핸드폰용 목록 페이지)을 만든다.

환경변수:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (없으면 알림 생략)
  PAGE_URL                              (알림에 붙일 목록 페이지 주소, 선택)
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(ROOT, "state")
DOCS_DIR = os.path.join(ROOT, "docs")
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST)
TODAY = NOW.strftime("%Y-%m-%d")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")

ENCAR = requests.Session()
ENCAR.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                      "Referer": "https://www.encar.com/", "Origin": "https://www.encar.com"})
DAANGN = requests.Session()
DAANGN.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                       "Referer": "https://www.daangn.com/kr/cars/"})

FRAME = re.compile("프론트패널|크로스멤버|인사이드패널|사이드멤버|휠하우스|필러|대쉬패널|플로어|리어패널|패키지트레이|트렁크플로어")
SEOUL_AREA = {"서울", "경기", "인천"}


def log(*a):
    print(*a, flush=True)


def get_json(session, url, params=None, tries=3, pause=0.25):
    for t in range(tries):
        try:
            r = session.get(url, params=params, timeout=12)
            if r.status_code == 200 and r.text.strip():
                time.sleep(pause)
                return r.json()
            if r.status_code in (204, 404):
                log(f"  ! {r.status_code} (빈 응답) {url[:70]}")
                return None
            log(f"  ! {r.status_code} {r.text[:80]!r} {url[:70]}")
        except Exception as e:  # 네트워크 오류는 재시도
            log(f"  ! {type(e).__name__} {url[:90]}")
        time.sleep(1.5 * (t + 1))
    return None


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


# ───────────────────────── 엔카 ─────────────────────────

ENCAR_HEADER_SETS = [
    {"Referer": "https://www.encar.com/", "Origin": "https://www.encar.com"},
    {"Referer": "https://www.encar.com/dc/dc_carsearchlist.do", "Origin": None},
    {"Referer": None, "Origin": None},
]
_encar_hdr_ok = None


def pick_encar_headers():
    """엔카가 받아주는 헤더 조합을 찾는다."""
    global _encar_hdr_ok
    if _encar_hdr_ok is not None:
        return _encar_hdr_ok
    probe = {"count": "true", "q": "(And.Hidden.N._.CarType.N.)", "sr": "|PriceAsc|0|1"}
    for i, hs in enumerate(ENCAR_HEADER_SETS):
        for k, v in hs.items():
            if v is None:
                ENCAR.headers.pop(k, None)
            else:
                ENCAR.headers[k] = v
        try:
            r = ENCAR.get("https://api.encar.com/search/car/list/general", params=probe, timeout=20)
            log(f"  엔카 접속 시험 {i + 1}: {r.status_code} {len(r.content)}바이트")
            if r.status_code == 200 and r.content:
                _encar_hdr_ok = True
                return True
        except Exception as e:
            log(f"  엔카 접속 시험 {i + 1}: {type(e).__name__}")
    _encar_hdr_ok = False
    return False


def encar_search(q):
    url = "https://api.encar.com/search/car/list/general"
    if not pick_encar_headers():
        return [], None
    rows, offset, total = [], 0, None
    while True:
        data = get_json(ENCAR, url, {"count": "true", "q": q, "sr": f"|PriceAsc|{offset}|500"})
        if not data:
            break
        total = data.get("Count", 0)
        batch = data.get("SearchResults") or []
        rows += batch
        offset += 500
        if not batch or offset >= total or offset >= 20000:
            break
    return rows, total


def encar_detail(car_id):
    v = get_json(ENCAR, f"https://api.encar.com/v1/readside/vehicle/{car_id}")
    if not v:
        return None
    vid, no = v.get("vehicleId"), v.get("vehicleNo")
    ins = get_json(ENCAR, f"https://api.encar.com/v1/readside/inspection/vehicle/{vid}") if vid else None
    rec = None
    if vid and no:
        rec = get_json(ENCAR, f"https://api.encar.com/v1/readside/record/vehicle/{vid}/open",
                       {"vehicleNo": no})
    outers = []
    for o in (ins or {}).get("outers") or []:
        title = (o.get("type") or {}).get("title", "")
        st = "/".join(s.get("title", "") for s in o.get("statusTypes") or [])
        outers.append((title, st))
    frame = [f"{t}:{s}" for t, s in outers if FRAME.search(t.replace(" ", ""))]
    outer = [f"{t}:{s}".replace("교환(교체)", "교환").replace("판금/용접", "판금")
             for t, s in outers if not FRAME.search(t.replace(" ", ""))]
    detail = (ins or {}).get("master", {}).get("detail", {}) or {}
    rec = rec or {}
    return {
        "trans": (v.get("spec") or {}).get("transmissionName"),
        "ad": (v.get("advertisement") or {}).get("status"),
        "has_ins": bool(ins),
        "frame": frame,
        "outer": outer,
        "tuning": bool(detail.get("tuning")),
        "serious": [s.get("title") for s in detail.get("seriousTypes") or []],
        "has_rec": bool(rec),
        "flood": (rec.get("floodTotalLossCnt") or 0) + (rec.get("floodPartLossCnt") or 0),
        "total_loss": rec.get("totalLossCnt") or 0,
        "theft": rec.get("robberCnt") or 0,
        "owners": rec.get("ownerChangeCnt"),
        "my_acc": rec.get("myAccidentCnt"),
        "my_cost": rec.get("myAccidentCost"),
        "biz": ",".join(x for x, k in (("영업", "business"), ("렌트", "loan"), ("관용", "government"))
                        if rec.get(k)),
    }


def exclusion_reason(d, rules):
    if not d:
        return ""
    r = []
    if rules.get("frame_damage") and d["frame"]:
        r.append("골격손상")
    if rules.get("flood") and d["flood"]:
        r.append("침수")
    if rules.get("total_loss") and d["total_loss"]:
        r.append("전손")
    if rules.get("theft") and d["theft"]:
        r.append("도난")
    if d["serious"]:
        r.append("특별이력")
    if d["ad"] and d["ad"] != "ADVERTISE":
        r.append("판매중 아님")
    return ",".join(r)


# ───────────────────────── 당근 ─────────────────────────

_daangn_ok = None


def daangn_probe():
    """당근이 응답하는지 한 번만 확인 (막혀 있으면 당근은 통째로 건너뜀)."""
    global _daangn_ok
    if _daangn_ok is None:
        try:
            r = DAANGN.get("https://www.daangn.com/kr/search/cars/",
                           params={"q": "레토나", "in": "역삼동-6035", "_data": "routes/kr.search.cars._index"},
                           timeout=15)
            _daangn_ok = r.status_code == 200 and "carPosts" in r.text
            log(f"  당근 접속 시험: {r.status_code} {len(r.content)}바이트 → {'OK' if _daangn_ok else '막힘'}")
        except Exception as e:
            _daangn_ok = False
            log(f"  당근 접속 시험: {type(e).__name__} → 막힘")
    return _daangn_ok


def daangn_search(keyword, region):
    name, rid = region
    data = get_json(DAANGN, "https://www.daangn.com/kr/search/cars/",
                    {"q": keyword, "in": f"{name}-{rid}", "_data": "routes/kr.search.cars._index"},
                    tries=2, pause=0.15)
    return (data or {}).get("carPosts") or []


def daangn_detail(href):
    data = get_json(DAANGN, "https://www.daangn.com" + href,
                    {"_data": "routes/kr.cars.$car_post_id"}, tries=2)
    cp = (data or {}).get("carPost") or {}
    cd = cp.get("carData") or {}
    h = cd.get("carHistorySummary") or {}
    reg = cp.get("region") or {}
    return {
        "gear": cd.get("gear"),
        "my_acc": h.get("mineAccidentCount"),
        "owners": h.get("ownerChangeCount"),
        "total_flood": h.get("totalAndSubmergedAccidentCount") or 0,
        "biz": "" if h.get("businessUsageText") in (None, "없음") else h.get("businessUsageText"),
        "area": " ".join(x for x in (reg.get("name1"), reg.get("name2")) if x),
    }


# ───────────────────────── 메인 ─────────────────────────

def main():
    cfg = load(os.path.join(ROOT, "config.json"), None)
    if not cfg:
        sys.exit("config.json 을 읽을 수 없어요")
    seen = load(os.path.join(STATE_DIR, "seen.json"), {})
    cache = load(os.path.join(STATE_DIR, "details.json"), {})
    first_run = not seen
    rules = cfg.get("exclude_rules", {})
    report = {"run_at": NOW.strftime("%Y-%m-%d %H:%M"), "categories": []}
    new_items = []
    encar_ok = daangn_ok = 0

    for cat in cfg["categories"]:
        key = cat["key"]
        cseen = seen.setdefault(key, {})
        inc = re.compile(cat["include"], re.I)
        exc = re.compile(cat["exclude"], re.I) if cat.get("exclude") else None
        fill = {"max_price": cat["max_price"], "max_km": cat.get("max_km") or 9999999}
        log(f"■ {cat['name']}")

        # ── 엔카
        found = {}
        for q in cat["encar"]:
            rows, total = encar_search(q.format(**fill))
            if total is not None:
                encar_ok += 1
            log(f"  엔카 검색 {len(rows)}/{total}  {q[:70]}")
            for c in rows:
                text = f"{c.get('Model', '')} {c.get('Badge', '')}"
                if not inc.search(text) or (exc and exc.search(text)):
                    continue
                if cat.get("max_km") and (c.get("Mileage") or 0) > cat["max_km"]:
                    continue
                found[str(c["Id"])] = c
        # 같은 차 중복 광고 정리
        uniq, sig = {}, set()
        for cid, c in sorted(found.items(), key=lambda kv: kv[1].get("Price", 0)):
            s = (c.get("Model"), c.get("Badge"), c.get("FormYear"), c.get("Mileage"), c.get("Price"))
            if s in sig:
                continue
            sig.add(s)
            uniq[cid] = c
        log(f"  엔카 후보 {len(uniq)}대")

        items = []
        for i, (cid, c) in enumerate(uniq.items()):
            ck = f"e{cid}"
            if ck not in cache:
                cache[ck] = encar_detail(cid)
            d = cache[ck]
            sid = f"e{cid}"
            is_new = sid not in cseen
            if is_new:
                cseen[sid] = "2000-01-01" if first_run else TODAY
            item = {
                "src": "엔카", "id": cid,
                "name": f"{c.get('Manufacturer', '')} {c.get('Model', '')} {c.get('Badge', '')}".strip(),
                "year": c.get("FormYear") or str(c.get("Year", ""))[:4],
                "km": int(c.get("Mileage") or 0), "price": int(c.get("Price") or 0),
                "area": c.get("OfficeCityState", ""),
                "url": f"https://fem.encar.com/cars/detail/{cid}",
                "first_seen": cseen[sid], "new": is_new and not first_run,
                "detail": d, "excluded": exclusion_reason(d, rules),
            }
            items.append(item)

        # ── 당근
        dk = cat.get("daangn_keywords") or []
        dinc = re.compile(cat.get("daangn_include") or cat["include"], re.I)
        dexc_src = cat.get("daangn_exclude") or cat.get("exclude")
        dexc = re.compile(dexc_src, re.I) if dexc_src else None
        posts = {}
        if not daangn_probe():
            dk = []
        for kw in dk:
            log(f"  당근 '{kw}' 검색 중… (지금까지 {len(posts)}건)")
            for region in cfg["daangn_regions"]:
                res = daangn_search(kw, region)
                if res:
                    daangn_ok += 1
                for p in res:
                    posts.setdefault(p["id"], p)
        log(f"  당근 검색결과 {len(posts)}건")
        encar_pool = [(it["km"], int(it["year"] or 0), it) for it in items if it["year"]]
        for p in posts.values():
            cd = p.get("carData") or {}
            nm = cd.get("carName") or ""
            if p.get("status") != "ON_SALE" or p.get("type") != "SALE":
                continue
            price, km = int(p.get("price") or 0), int(p.get("driveDistance") or 0)
            if price > cat["max_price"] or (cat.get("max_km") and km > cat["max_km"]):
                continue
            if not dinc.search(nm) or (dexc and dexc.search(nm)):
                continue
            year = int(cd.get("modelYear") or 0)
            twin = next((it for k, y, it in encar_pool if abs(k - km) <= 500 and abs(y - year) <= 1), None)
            slug = p["href"].rstrip("/").split("-")[-1]
            sid = f"d{slug}"
            is_new = sid not in cseen
            if is_new:
                cseen[sid] = "2000-01-01" if first_run else TODAY
            if twin:  # 엔카에도 있는 같은 차 → 엔카 쪽만 보여주되 표시
                twin.setdefault("also", []).append("https://www.daangn.com" + p["href"])
                continue
            ck = f"d{slug}"
            if ck not in cache:
                cache[ck] = daangn_detail(p["href"])
            d = cache[ck] or {}
            items.append({
                "src": "당근", "id": slug, "name": nm, "year": str(year or ""),
                "km": km, "price": price, "area": d.get("area") or (p.get("region") or {}).get("name", ""),
                "url": "https://www.daangn.com" + p["href"],
                "first_seen": cseen[sid], "new": is_new and not first_run,
                "detail": d, "excluded": "전손·침수" if d.get("total_flood") else "",
            })

        items.sort(key=lambda x: x["price"])
        report["categories"].append({"key": key, "name": cat["name"], "items": items})
        new_items += [(cat["name"], it) for it in items if it["new"] and not it["excluded"]]
        log(f"  → 표시 {len(items)}대, 새 매물 {sum(1 for it in items if it['new'])}대")

    # 둘 다 아예 응답이 없으면 상태를 덮어쓰지 않는다 (차단 등)
    if encar_ok == 0 and daangn_ok == 0:
        msg = "⚠️ 엔카·당근 모두 응답이 없어요. 접속이 막혔을 수 있어요."
        log(msg)
        notify([msg])
        sys.exit(1)

    live = {f"{'e' if it['src'] == '엔카' else 'd'}{it['id']}" for c in report["categories"] for it in c["items"]}
    cache = {k: v for k, v in cache.items() if k in live}
    save(os.path.join(STATE_DIR, "seen.json"), seen)
    save(os.path.join(STATE_DIR, "details.json"), cache)
    report["warnings"] = [w for w, ok in (("엔카 응답 없음", encar_ok), ("당근 응답 없음", daangn_ok)) if not ok]
    write_page(cfg, report)

    page = os.environ.get("PAGE_URL", "")
    if first_run:
        total = sum(len(c["items"]) for c in report["categories"])
        notify([f"🚗 감시 시작! 지금 매물 {total}대를 저장했어요.\n앞으로는 새로 올라온 차만 알려드릴게요.\n{page}"])
    elif new_items:
        notify(format_new(new_items, page))
    log(f"완료: 새 매물 {len(new_items)}대")


def short(it):
    d = it.get("detail") or {}
    bits = []
    if (d.get("trans") == "수동") or d.get("gear") == "MANUAL":
        bits.append("수동")
    if it["src"] == "엔카":
        if not d.get("has_ins"):
            bits.append("점검표없음")
        if d.get("outer"):
            bits.append(f"외판{len(d['outer'])}")
        if d.get("tuning"):
            bits.append("튜닝")
    if d.get("my_acc") is not None:
        bits.append(f"사고{d['my_acc']}/소유{d.get('owners')}")
    if d.get("biz"):
        bits.append(d["biz"])
    return " · ".join(bits)


def format_new(new_items, page):
    msgs, cur = [], f"🆕 새 매물 {len(new_items)}대\n"
    for cname, it in new_items:
        line = (f"\n[{cname}] {it['name']}\n{it['year']} · {it['km'] / 10000:.1f}만km · "
                f"{it['price']:,}만원 · {it['area']} ({it['src']})\n")
        s = short(it)
        if s:
            line += s + "\n"
        line += it["url"] + "\n"
        if len(cur) + len(line) > 3800:
            msgs.append(cur)
            cur = ""
        cur += line
    if page:
        cur += f"\n전체 목록: {page}"
    msgs.append(cur)
    return msgs


def notify(messages):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        log("(텔레그램 설정 없음 — 알림 생략)")
        for m in messages:
            log(m)
        return
    for m in messages:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": m, "disable_web_page_preview": "true"}, timeout=20)
        except Exception as e:
            log("텔레그램 전송 실패:", e)


def write_page(cfg, report):
    os.makedirs(DOCS_DIR, exist_ok=True)
    report = json.loads(json.dumps(report))  # 원본(알림용)은 건드리지 않기
    for c in report["categories"]:
        for it in c["items"]:
            it["tags"] = short(it)
            d = it.get("detail") or {}
            it["outer_list"] = ", ".join(d.get("outer") or [])
            it.pop("detail", None)
    save(os.path.join(DOCS_DIR, "data.json"), report)
    with open(os.path.join(ROOT, "page_template.html"), encoding="utf-8") as f:
        tpl = f.read()
    data = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    out = tpl.replace("__TITLE__", html.escape(cfg.get("page_title", "새 매물"))).replace("__DATA__", data)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(out)


if __name__ == "__main__":
    main()
