# Acro Optical Marketing Studio — 프로그램 본체
# 이 파일을 실행하면 내 맥북 안에서만 열리는 작은 웹사이트가 켜져요.

import calendar as pycal  # 파이썬에 들어 있는 달력 계산 도구
import json
import re
import socket
import sys
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (Flask, abort, g, redirect, render_template, request,
                   send_from_directory, url_for)

# 이 프로젝트 폴더의 위치
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"      # 데이터(JSON 파일)를 저장하는 폴더
PHOTOS_DIR = BASE_DIR / "photos"  # 안경테 사진 원본을 저장하는 폴더

# 폴더가 없으면 자동으로 만들어요
DATA_DIR.mkdir(exist_ok=True)
PHOTOS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)


# ------------------------------------------------------------
# 파일 읽기/쓰기 도우미
# ------------------------------------------------------------
def load_json(filename, default):
    """data 폴더에서 JSON 파일을 읽어요. 파일이 없으면 default를 돌려줘요."""
    path = DATA_DIR / filename
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(filename, data):
    """data 폴더에 JSON 파일로 저장해요.
    임시 파일에 먼저 쓰고 바꿔치기해서, 저장 중에 꺼져도 원래 파일이 망가지지 않아요."""
    path = DATA_DIR / filename
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ------------------------------------------------------------
# ① 매장 기본 정보 — 반드시 여기 한 곳(data/store.json)에만 저장해요
# ------------------------------------------------------------
STORE_FILE = "store.json"

# 매장 정보 항목: (저장 이름, 화면에 보이는 이름, 여러 줄 입력인지)
STORE_FIELDS = [
    ("address", "주소", False),
    ("hours", "영업시간", True),
    ("phone", "전화번호", False),
    ("directions", "찾아오는 길", True),
]


def load_store():
    """매장 정보 전체(확인 안 된 것 포함)를 읽어요. 매장 정보 화면에서만 써요."""
    data = load_json(STORE_FILE, {})
    fields = data.get("fields", {})
    for key, _label, _multi in STORE_FIELDS:
        fields.setdefault(key, {"value": "", "confirmed": False})
    return {"fields": fields, "updated_at": data.get("updated_at", "")}


def get_confirmed_store():
    """'확인됨'으로 표시된 매장 정보만 돌려줘요.
    다른 기능(캡션 프롬프트 등)은 매장 정보를 꼭 이 함수로만 가져와야 해요."""
    fields = load_store()["fields"]
    return {
        key: fields[key]["value"]
        for key, _label, _multi in STORE_FIELDS
        if fields[key]["confirmed"] and fields[key]["value"].strip()
    }


# ------------------------------------------------------------
# 화면(페이지)들
# ------------------------------------------------------------
@app.route("/")
def home():
    """첫 화면"""
    return render_template("home.html")


@app.route("/store", methods=["GET", "POST"])
def store():
    """매장 기본 정보 화면 — 보기(GET)와 저장(POST)"""
    if request.method == "POST":
        fields = {}
        for key, _label, _multi in STORE_FIELDS:
            value = request.form.get(key, "").strip()
            # 내용이 비어 있으면 '확인됨'으로 저장하지 않아요
            confirmed = request.form.get(f"{key}_confirmed") == "on" and bool(value)
            fields[key] = {"value": value, "confirmed": confirmed}
        save_json(STORE_FILE, {
            "fields": fields,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        return redirect(url_for("store", saved=1))

    return render_template(
        "store.html",
        store=load_store(),
        store_fields=STORE_FIELDS,
        confirmed=get_confirmed_store(),
        saved=request.args.get("saved") == "1",
    )


# ------------------------------------------------------------
# ② 안경테 관리 — data/frames.json 에 저장, 사진 원본은 photos/ 폴더에 보관
# ------------------------------------------------------------
FRAMES_FILE = "frames.json"
TRASH_DIR = PHOTOS_DIR / "_trash"  # 지운 사진은 바로 없애지 않고 여기로 옮겨요

STYLE_TAGS = ["캐주얼", "클래식", "미니멀"]
CHANNELS = [("instagram", "인스타"), ("daangn", "당근")]
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif"}

# 입력할 때 고를 수 있는 '추천 단어' (목록에 없으면 직접 써도 돼요)
SUGGEST = {
    "material": ["메탈", "티타늄", "아세테이트(뿔테)", "TR", "콤비(메탈+뿔테)"],
    "shape": ["원형", "사각", "오벌", "보잉", "웰링턴", "하금테", "무테"],
}


def load_frames():
    return load_json(FRAMES_FILE, {"frames": []})["frames"]


def save_frames(frames):
    save_json(FRAMES_FILE, {"frames": frames})


def find_frame(frames, frame_id):
    for frame in frames:
        if frame["id"] == frame_id:
            return frame
    abort(404)


def frame_name(frame):
    """화면에 보여줄 이름: '브랜드 모델명'"""
    parts = [frame["brand"]["value"], frame["model"]]
    return " ".join(p for p in parts if p) or "(이름 없음)"


def only_digits(text):
    """'120,000원' → '120000' 처럼 숫자만 남겨요"""
    return re.sub(r"[^0-9]", "", text or "")


def checked_value(form, key, value):
    """'확인됨' 칸: 체크했고 내용이 있을 때만 확인됨으로 저장해요"""
    return {"value": value, "confirmed": form.get(f"{key}_confirmed") == "on" and bool(value)}


def frame_from_form(form, frame):
    """입력 칸에 적힌 내용을 안경테 정보에 옮겨 담아요"""
    frame["brand"] = checked_value(form, "brand", form.get("brand", "").strip())
    frame["model"] = form.get("model", "").strip()
    frame["material"] = form.get("material", "").strip()
    frame["shape"] = form.get("shape", "").strip()
    frame["color"] = form.get("color", "").strip()

    tags = [t for t in STYLE_TAGS if form.get(f"tag_{t}") == "on"]
    for extra in form.get("extra_tags", "").split(","):
        extra = extra.strip()
        if extra and extra not in tags:
            tags.append(extra)
    frame["tags"] = tags

    frame["price"] = checked_value(form, "price", only_digits(form.get("price")))
    frame["stock"] = checked_value(form, "stock", only_digits(form.get("stock")))

    frame["shot"] = form.get("shot") == "on"
    frame["posted"] = {key: form.get(f"posted_{key}") == "on" for key, _ in CHANNELS}
    frame["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def save_uploaded_photos(frame, files):
    """올린 사진을 photos 폴더에 원본 그대로(크기·화질 변경 없이)저장해요"""
    for f in files:
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in PHOTO_EXTS:
            continue
        filename = f"{frame['id']}_{uuid.uuid4().hex[:6]}{ext}"
        f.save(PHOTOS_DIR / filename)
        frame["photos"].append({"file": filename, "original_name": f.filename})


def move_photo_to_trash(filename):
    """사진을 photos/_trash 폴더로 옮겨요 (실수로 지워도 다시 꺼낼 수 있게)"""
    src = PHOTOS_DIR / filename
    if src.exists():
        TRASH_DIR.mkdir(exist_ok=True)
        src.replace(TRASH_DIR / filename)


def is_unposted(frame):
    """아직 어느 채널에도 안 올린 안경테인지"""
    return not any(frame["posted"].values())


@app.route("/photos/<path:filename>")
def photo(filename):
    """photos 폴더의 사진을 화면에 보여줘요"""
    return send_from_directory(PHOTOS_DIR, filename)


@app.route("/frames")
def frames():
    """안경테 목록"""
    all_frames = load_frames()
    only_unposted = request.args.get("filter") == "unposted"
    shown = [f for f in all_frames if is_unposted(f)] if only_unposted else all_frames
    return render_template(
        "frames.html",
        frames=shown,
        total=len(all_frames),
        unposted_count=sum(1 for f in all_frames if is_unposted(f)),
        only_unposted=only_unposted,
        channels=CHANNELS,
        frame_name=frame_name,
        saved=request.args.get("saved"),
    )


@app.route("/frames/new", methods=["GET", "POST"])
def frame_new():
    """안경테 새로 등록"""
    if request.method == "POST":
        frames_list = load_frames()
        frame = {
            "id": uuid.uuid4().hex[:8],
            "photos": [],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        frame_from_form(request.form, frame)
        save_uploaded_photos(frame, request.files.getlist("photos"))
        frames_list.append(frame)
        save_frames(frames_list)
        return redirect(url_for("frames", saved="new"))

    empty = {
        "id": None, "photos": [], "brand": {"value": "", "confirmed": False},
        "model": "", "material": "", "shape": "", "color": "", "tags": [],
        "price": {"value": "", "confirmed": False},
        "stock": {"value": "", "confirmed": False},
        "shot": False, "posted": {key: False for key, _ in CHANNELS},
    }
    return render_frame_form(empty)


@app.route("/frames/<frame_id>", methods=["GET", "POST"])
def frame_edit(frame_id):
    """안경테 수정"""
    frames_list = load_frames()
    frame = find_frame(frames_list, frame_id)
    if request.method == "POST":
        # 체크한 사진은 휴지통(_trash) 폴더로 옮겨요
        remove = set(request.form.getlist("remove_photo"))
        for p in frame["photos"]:
            if p["file"] in remove:
                move_photo_to_trash(p["file"])
        frame["photos"] = [p for p in frame["photos"] if p["file"] not in remove]

        # 고른 대표 사진을 맨 앞으로 옮겨요 (맨 앞 사진 = 대표 사진)
        main = request.form.get("main_photo")
        frame["photos"].sort(key=lambda p: p["file"] != main)

        frame_from_form(request.form, frame)
        save_uploaded_photos(frame, request.files.getlist("photos"))
        save_frames(frames_list)
        return redirect(url_for("frames", saved="edit"))
    return render_frame_form(frame)


@app.route("/frames/<frame_id>/delete", methods=["POST"])
def frame_delete(frame_id):
    """안경테 삭제 (사진은 photos/_trash 로 옮겨 둬요)"""
    frames_list = load_frames()
    frame = find_frame(frames_list, frame_id)
    for p in frame["photos"]:
        move_photo_to_trash(p["file"])
    save_frames([f for f in frames_list if f["id"] != frame_id])
    return redirect(url_for("frames", saved="delete"))


def render_frame_form(frame):
    custom_tags = [t for t in frame["tags"] if t not in STYLE_TAGS]
    return render_template(
        "frame_form.html",
        frame=frame,
        style_tags=STYLE_TAGS,
        extra_tags=", ".join(custom_tags),
        channels=CHANNELS,
        suggest=SUGGEST,
    )


# ------------------------------------------------------------
# ③ 콘텐츠 캘린더 — data/contents.json 에 저장
# ------------------------------------------------------------
CONTENTS_FILE = "contents.json"

# 종류: (저장 이름, 보이는 이름, 채널)
CONTENT_TYPES = [
    ("ig_post", "인스타 게시물", "instagram"),
    ("ig_reels", "인스타 릴스", "instagram"),
    ("ig_story", "인스타 스토리", "instagram"),
    ("daangn_news", "당근 소식", "daangn"),
]
DIRECTIONS = [
    ("product", "제품 소개"),
    ("style", "스타일 추천"),
    ("info", "안경 정보"),
    ("visit", "매장 방문 안내"),
]
STATUSES = [
    ("idea", "아이디어"),
    ("draft", "초안"),
    ("shot", "촬영 완료"),
    ("posted", "게시 완료"),
]
# 성과 기록칸: (저장 이름, 보이는 이름, 어느 채널 콘텐츠에 보일지)
METRICS = [
    ("saves", "저장 수", "instagram"),
    ("profile_visits", "프로필 방문 수", "instagram"),
    ("daangn_regulars", "당근 단골 수", "daangn"),
    ("visitors", "\"보고 왔어요\" 손님 수", "both"),
]
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

TYPE_LABEL = {k: label for k, label, _ in CONTENT_TYPES}
TYPE_CHANNEL = {k: ch for k, _, ch in CONTENT_TYPES}
DIRECTION_LABEL = dict(DIRECTIONS)
STATUS_LABEL = dict(STATUSES)


def load_contents():
    return load_json(CONTENTS_FILE, {"contents": []})["contents"]


def save_contents(contents):
    save_json(CONTENTS_FILE, {"contents": contents})


def find_content(contents, content_id):
    for c in contents:
        if c["id"] == content_id:
            return c
    abort(404)


def parse_date(text, fallback):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return fallback


def content_from_form(form, content):
    content["date"] = parse_date(form.get("date"), date.today()).isoformat()
    content["type"] = form.get("type") if form.get("type") in TYPE_LABEL else CONTENT_TYPES[0][0]
    content["direction"] = form.get("direction") if form.get("direction") in DIRECTION_LABEL else DIRECTIONS[0][0]
    content["status"] = form.get("status") if form.get("status") in STATUS_LABEL else STATUSES[0][0]
    content["memo"] = form.get("memo", "").strip()
    content["frame_ids"] = form.getlist("frame_ids")
    content["metrics"] = {key: only_digits(form.get(f"metric_{key}")) for key, _l, _c in METRICS}
    content["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def calendar_helpers():
    """화면에서 이름표를 쓸 수 있게 넘겨주는 것들"""
    return dict(
        content_types=CONTENT_TYPES, directions=DIRECTIONS, statuses=STATUSES,
        metrics=METRICS, type_label=TYPE_LABEL, type_channel=TYPE_CHANNEL,
        direction_label=DIRECTION_LABEL, status_label=STATUS_LABEL,
        frame_name=frame_name,
    )


@app.route("/calendar")
def calendar():
    """한 주 보기 (월요일 ~ 일요일)"""
    picked = parse_date(request.args.get("week"), date.today())
    monday = picked - timedelta(days=picked.weekday())
    days = [monday + timedelta(days=i) for i in range(7)]

    contents = load_contents()
    week_items = [c for c in contents if monday.isoformat() <= c["date"] <= days[-1].isoformat()]
    by_day = {d.isoformat(): [] for d in days}
    for c in sorted(week_items, key=lambda c: c.get("created_at", "")):
        by_day[c["date"]].append(c)

    frames_by_id = {f["id"]: f for f in load_frames()}
    status_counts = {key: sum(1 for c in week_items if c["status"] == key) for key, _ in STATUSES}

    return render_template(
        "calendar.html",
        days=days, by_day=by_day, weekdays=WEEKDAYS, today=date.today(),
        monday=monday,
        prev_week=(monday - timedelta(days=7)).isoformat(),
        next_week=(monday + timedelta(days=7)).isoformat(),
        frames_of=lambda c: [frames_by_id[i] for i in c["frame_ids"] if i in frames_by_id],
        status_counts=status_counts,
        week_total=len(week_items), saved=request.args.get("saved"),
        **calendar_helpers(),
    )


def week_of(date_text):
    d = parse_date(date_text, date.today())
    return (d - timedelta(days=d.weekday())).isoformat()


@app.route("/contents/new", methods=["GET", "POST"])
def content_new():
    """콘텐츠 추가"""
    if request.method == "POST":
        contents = load_contents()
        content = {"id": uuid.uuid4().hex[:8], "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        content_from_form(request.form, content)
        contents.append(content)
        save_contents(contents)
        return redirect(url_for("calendar", week=week_of(content["date"]), saved="new"))

    empty = {
        "id": None,
        "date": parse_date(request.args.get("date"), date.today()).isoformat(),
        "type": CONTENT_TYPES[0][0], "direction": DIRECTIONS[0][0], "status": STATUSES[0][0],
        "memo": "", "frame_ids": [], "metrics": {},
    }
    return render_content_form(empty)


@app.route("/contents/<content_id>", methods=["GET", "POST"])
def content_edit(content_id):
    """콘텐츠 수정"""
    contents = load_contents()
    content = find_content(contents, content_id)
    if request.method == "POST":
        content_from_form(request.form, content)
        save_contents(contents)
        return redirect(url_for("calendar", week=week_of(content["date"]), saved="edit"))
    return render_content_form(content)


@app.route("/contents/<content_id>/delete", methods=["POST"])
def content_delete(content_id):
    """콘텐츠 삭제 — 지운 뒤 원래 보던 화면(주/월/년)으로 돌아가요"""
    contents = load_contents()
    content = find_content(contents, content_id)
    save_contents([c for c in contents if c["id"] != content_id])
    back = request.form.get("next", "")
    if back.startswith("/") and not back.startswith("//"):
        sep = "&" if "?" in back else "?"
        return redirect(f"{back}{sep}saved=delete")
    return redirect(url_for("calendar", week=week_of(content["date"]), saved="delete"))


@app.template_global()
def here():
    """지금 보고 있는 화면 주소 (안내 메시지 표시용 saved 는 빼고)"""
    args = {k: v for k, v in request.args.items() if k != "saved"}
    return url_for(request.endpoint, **args)


def contents_by_date():
    """날짜별로 콘텐츠를 묶어요: {'2026-11-17': [콘텐츠, ...]}"""
    grouped = {}
    for c in sorted(load_contents(), key=lambda c: c.get("created_at", "")):
        grouped.setdefault(c["date"], []).append(c)
    return grouped


@app.route("/calendar/month")
def calendar_month():
    """한 달 보기 — 한 줄(한 주)을 누르면 그 주 보기로 넘어가요"""
    today = date.today()
    try:
        y, m = map(int, request.args.get("month", "").split("-"))
        first = date(y, m, 1)
    except ValueError:
        first = today.replace(day=1)
    weeks = pycal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    grouped = contents_by_date()
    month_items = [c for d, items in grouped.items() if d.startswith(first.strftime("%Y-%m")) for c in items]
    return render_template(
        "calendar_month.html", first=first, weeks=weeks, by_date=grouped,
        today=today, weekdays=WEEKDAYS,
        prev_month=prev_month.strftime("%Y-%m"), next_month=next_month.strftime("%Y-%m"),
        month_total=len(month_items),
        status_counts={k: sum(1 for c in month_items if c["status"] == k) for k, _ in STATUSES},
        saved=request.args.get("saved"), **calendar_helpers(),
    )


@app.route("/calendar/year")
def calendar_year():
    """1년(12개월) 보기 — 달을 누르면 그 달 보기로 넘어가요"""
    today = date.today()
    try:
        year = int(request.args.get("year", ""))
        date(year, 1, 1)
    except ValueError:
        year = today.year
    cal = pycal.Calendar(firstweekday=0)
    months = [(date(year, m, 1), cal.monthdatescalendar(year, m)) for m in range(1, 13)]
    grouped = contents_by_date()
    year_total = sum(len(v) for d, v in grouped.items() if d.startswith(str(year)))
    return render_template(
        "calendar_year.html", year=year, months=months, by_date=grouped,
        today=today, weekdays=WEEKDAYS, year_total=year_total,
        month_count={m: sum(len(v) for d, v in grouped.items() if d.startswith(f"{year}-{m:02d}")) for m in range(1, 13)},
        saved=request.args.get("saved"), **calendar_helpers(),
    )


def render_content_form(content):
    return render_template(
        "content_form.html", content=content, frames=load_frames(),
        week=week_of(content["date"]), **calendar_helpers(),
    )


# ------------------------------------------------------------
# ④ 캡션 프롬프트 만들기 — '확인됨' 정보만 담아서 Claude 채팅에 붙여넣을 문장을 만들어요
#    (앱 안에서 AI를 부르지 않아요. 문장만 만들어서 복사해요.)
# ------------------------------------------------------------
STORE_NAME = "아크로안경점"
STORE_LABEL = {key: label for key, label, _m in STORE_FIELDS}

DIRECTION_GUIDE = {
    "product": "안경테의 소재, 형태, 색상 같은 특징이 잘 보이도록 제품을 소개해 주세요.",
    "style": "이 안경테가 어떤 스타일, 어떤 날, 어떤 옷차림에 어울리는지 추천하는 느낌으로 써 주세요.",
    "info": "안경에 관한 쉽고 유용한 일반 정보를 알려 주는 글로 써 주세요. 확실하지 않은 의학적·기술적 주장은 넣지 마세요.",
    "visit": "매장에 직접 찾아오고 싶어지도록 안내해 주세요. 매장이 건물 안쪽 깊은 곳에 있어서, 찾아오는 길이 잘 전달되는 게 중요해요.",
}

TYPE_GUIDE = {
    "ig_post": [
        "인스타그램 게시물 캡션을 써 주세요.",
        "스타일과 제품이 돋보이는 짧고 세련된 캡션 (3~5줄 정도).",
        "마지막에 어울리는 해시태그 10~15개.",
    ],
    "ig_reels": [
        "인스타그램 릴스(짧은 영상) 캡션을 써 주세요.",
        "스타일과 제품이 돋보이는 짧은 캡션 (2~4줄 정도).",
        "영상 첫 화면에 크게 넣을 짧은 문구 1개도 따로 제안해 주세요.",
        "마지막에 어울리는 해시태그 10~15개.",
    ],
    "ig_story": [
        "인스타그램 스토리에 넣을 아주 짧은 문구를 써 주세요.",
        "스타일과 제품이 돋보이게, 1~2줄로 짧게.",
        "해시태그는 2~3개만.",
    ],
    "daangn_news": [
        "당근 비즈프로필 '소식' 글을 써 주세요.",
        "동네 이웃에게 말하듯 친근하고 따뜻한 말투로.",
        "매장이 건물 안쪽에 있어서 처음 오는 분은 찾기 어려울 수 있어요. 찾아오는 길이 잘 드러나게 써 주세요.",
        "해시태그는 쓰지 않아도 돼요.",
    ],
}


def build_caption_prompt(content):
    """콘텐츠 하나로 캡션 프롬프트를 만들어요.
    돌려주는 것: (프롬프트 문장, 확인 안 돼서 뺀 정보 목록, 경고 목록)"""
    excluded, warnings = [], []
    channel = TYPE_CHANNEL[content["type"]]

    # 매장 정보: 반드시 get_confirmed_store() 로만 가져와요
    store_info = get_confirmed_store()
    for key, label, _m in STORE_FIELDS:
        if key not in store_info:
            excluded.append(f"매장 {label}")

    # 연결된 안경테
    frames_by_id = {f["id"]: f for f in load_frames()}
    linked = [frames_by_id[i] for i in content["frame_ids"] if i in frames_by_id]
    frame_blocks = []
    for n, f in enumerate(linked, 1):
        name = f["model"] or f"안경테 {n}"
        lines = []
        if f["brand"]["confirmed"]:
            lines.append(f"- 브랜드: {f['brand']['value']}")
        elif f["brand"]["value"]:
            excluded.append(f"{name}의 브랜드")
        if f["model"]:
            lines.append(f"- 모델명: {f['model']}")
        for key, label in [("material", "소재"), ("shape", "형태"), ("color", "색상")]:
            if f[key]:
                lines.append(f"- {label}: {f[key]}")
        if f["tags"]:
            lines.append(f"- 스타일: {', '.join(f['tags'])}")
        if f["price"]["confirmed"]:
            lines.append(f"- 가격: {int(f['price']['value']):,}원")
        elif f["price"]["value"]:
            excluded.append(f"{name}의 가격")
        if f["stock"]["confirmed"]:
            lines.append(f"- 재고: {f['stock']['value']}개")
        elif f["stock"]["value"]:
            excluded.append(f"{name}의 재고")
        frame_blocks.append(f"[안경테 {n}]\n" + ("\n".join(lines) if lines else "- (입력된 정보 없음)"))

    if not linked and content["direction"] in ("product", "style"):
        warnings.append("연결된 안경테가 없어요. 제품 소개·스타일 추천 글이라면 안경테를 연결해 주세요.")
    if channel == "daangn" and "directions" not in store_info:
        warnings.append("당근 글인데 '찾아오는 길'이 확인되지 않았어요. 매장 정보에서 확인해 주세요.")

    # 프롬프트 문장 조립
    parts = [
        f"안녕하세요. 저는 '{STORE_NAME}'의 온라인 홍보를 맡고 있어요. "
        "매장이 건물 안쪽 깊은 곳에 있어서, 온라인 글을 보고 손님이 일부러 찾아오게 만드는 게 목표예요.",
        "",
        "## 써 줄 글",
        *[f"- {line}" for line in TYPE_GUIDE[content["type"]]],
        f"- 글 방향: {DIRECTION_LABEL[content['direction']]} — {DIRECTION_GUIDE[content['direction']]}",
    ]
    if content.get("memo"):
        parts.append(f"- 이번 글 주제 메모: {content['memo']}")

    parts += ["", "## 매장 정보 (확인된 정보만)", f"- 매장 이름: {STORE_NAME}"]
    for key, label, _m in STORE_FIELDS:
        if key in store_info:
            # 여러 줄로 적은 정보(영업시간 등)는 줄마다 들여써서 보기 좋게 넣어요
            lines = [ln.strip() for ln in store_info[key].splitlines() if ln.strip()]
            if len(lines) == 1:
                parts.append(f"- {label}: {lines[0]}")
            else:
                parts.append(f"- {label}:")
                parts += [f"  {ln}" for ln in lines]

    if frame_blocks:
        parts += ["", "## 소개할 안경테 (확인된 정보만)", *frame_blocks]

    parts += [
        "",
        "## 꼭 지켜 주세요",
        "- 위에 적힌 정보만 사용하세요.",
        "- 가격, 할인, 쿠폰, 이벤트, 재고, 브랜드, 영업시간, 주소, 전화번호처럼 사실 정보는 위에 없으면 절대 지어내지 마세요.",
        "- 꼭 필요한데 위에 없는 정보는 [여기에 ○○ 입력]처럼 빈칸으로 남겨 주세요.",
        "- 지역 해시태그를 쓴다면 위 주소에 나온 지역 이름만 사용하세요.",
        "- 과장된 표현(최고, 최저가, 1등 등)은 쓰지 마세요.",
        "",
        "초안 2개를 서로 다른 느낌으로 써 주세요.",
    ]
    return "\n".join(parts), excluded, warnings


@app.route("/contents/<content_id>/prompt")
def content_prompt(content_id):
    """캡션 프롬프트 화면"""
    content = find_content(load_contents(), content_id)
    prompt, excluded, warnings = build_caption_prompt(content)
    return render_template(
        "prompt.html", content=content, prompt=prompt, excluded=excluded,
        warnings=warnings, week=week_of(content["date"]), **calendar_helpers(),
    )


# ------------------------------------------------------------
# 가족과 같이 쓸 때: 두 사람이 동시에 저장해도 내용이 덮어써지지 않게
# 저장(POST)은 한 번에 하나씩 차례대로 처리해요.
# ------------------------------------------------------------
SAVE_LOCK = threading.Lock()


@app.before_request
def wait_my_turn():
    if request.method == "POST":
        SAVE_LOCK.acquire()
        g.has_lock = True


@app.teardown_request
def done_my_turn(_error=None):
    if g.pop("has_lock", False):
        SAVE_LOCK.release()


def my_wifi_address():
    """같은 와이파이의 다른 기기가 이 맥북을 찾아올 주소(192.168.x.x)를 알아내요"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # 실제로 보내지는 않고 주소만 확인해요
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


if __name__ == "__main__":
    PORT = 5050  # 5000번은 맥의 AirPlay가 쓰고 있어서 5050번을 써요

    if "--share" in sys.argv:
        # 공유 모드: 같은 와이파이의 가족 기기에서도 들어올 수 있어요.
        # 안전을 위해 개발자용 디버그 기능은 꺼요.
        ip = my_wifi_address()
        print("\n=== 가족 공유 모드 ===")
        print(f"이 맥북에서:      http://127.0.0.1:{PORT}")
        print(f"가족 폰·아이패드: http://{ip}:{PORT}" if ip else "와이파이 주소를 찾지 못했어요. 와이파이 연결을 확인해 주세요.")
        print("끝내려면 control + C\n")
        app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
    else:
        # 혼자 쓰는 모드: 이 맥북에서만 열려요
        app.run(host="127.0.0.1", port=PORT, debug=True)
