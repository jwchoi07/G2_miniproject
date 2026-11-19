"""Daily Words (G2) — Streamlit version.

The original app screen (daily_words.html) is shown inside Streamlit as it is.
Python does the data work on the server:
  1) reads the word library voca_3000.csv
     (번호, 단어, 뜻, 수준, 함께 알아둘 파생어 (뜻), 예문),
  2) turns 수준 into Level 1/2/3 (초등 → 1, 중·고 공통 → 2, 고교 선택 → 3),
  3) builds a fill-in-the-blank question and step-by-step hints for every word,
  4) puts the data into the page and shows it with st.components.v1.html.

Files in the repository:
  app.py, voca_3000.csv, requirements.txt   (required — the app screen is inside this file)
  audio.json   (optional: recorded pronunciation clips)
"""
import csv
import json
import math
import random
import re
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

BASE = Path(__file__).parent
APP_HEIGHT = 920  # height of the app screen inside Streamlit (px)
LEVEL_MAP = {"초등": 1, "중·고 공통": 2, "고교 선택": 3}

st.set_page_config(page_title="Daily Words", page_icon="📘", layout="centered")

# Hide Streamlit's own header/footer so only the app screen is visible.
st.markdown(
    """<style>
    .stApp{background:#edf1fa}
    header[data-testid="stHeader"],footer,#MainMenu{display:none}
    .block-container{padding:.6rem .4rem 0;max-width:720px}
    iframe{display:block;border:0}
    </style>""",
    unsafe_allow_html=True,
)


def find_file(name):
    """Find a file next to app.py, ignoring upper/lower case (Voca_3000.csv also works)."""
    exact = BASE / name
    if exact.exists():
        return exact
    for path in BASE.iterdir():
        if path.name.lower() == name.lower():
            return path
    return None


def read_json(name, default):
    path = find_file(name)
    if path is None:
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------
# Word library (CSV)
# ------------------------------------------------------------------
def split_top_level(text):
    """Split 'a (x, y), b (z)' on commas that are not inside brackets."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def parse_family(text):
    """'disabled (장애가 있는)' -> [{'w': 'disabled', 'pos': '장애가 있는'}]"""
    family = []
    for part in split_top_level(text or ""):
        m = re.match(r"^(.*?)\s*\((.*)\)\s*$", part)
        word, meaning = (m.group(1), m.group(2)) if m else (part, "")
        family.append({"w": word.strip(), "pos": meaning.strip()})
    return family


def find_in_sentence(sentence, forms):
    """Return the exact text of the first form that appears as a whole word."""
    for form in forms:
        m = re.search(r"(?<![A-Za-z])" + re.escape(form) + r"(?![A-Za-z])", sentence, re.I)
        if m:
            return m.group(0)
    return None


def load_library():
    path = find_file("voca_3000.csv")
    if path is None:
        st.error("단어 라이브러리 파일(voca_3000.csv)을 찾을 수 없어요. app.py와 같은 폴더에 올려 주세요.")
        st.stop()
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in ("단어", "뜻", "수준", "예문") if not rows or c not in rows[0]]
    if missing:
        st.error(f"{path.name}에 필요한 열이 없어요: {', '.join(missing)}. 새 voca_3000.csv로 교체해 주세요.")
        st.stop()
    family_col = next((c for c in rows[0] if c.startswith("함께 알아둘")), None)

    words = []
    for row in rows:
        forms = [x.strip() for x in row["단어"].split("/") if x.strip()]  # advertize / advertise
        sentence = (row.get("예문") or "").strip()
        words.append({
            "word": forms[0],
            "level": LEVEL_MAP.get(row["수준"].strip(), 2),
            "pos": "",
            "meaning": row["뜻"].strip(),
            "family": parse_family(row.get(family_col, "")) if family_col else [],
            "variation": forms[1:],
            "ex": sentence,
            "exForm": find_in_sentence(sentence, forms) or forms[0],
            "exampleSource": "library",
        })
    return words


# ------------------------------------------------------------------
# Fill-in-the-blank questions and hints
# ------------------------------------------------------------------
def scramble(answer):
    """Shuffle the letters of the answer (always different from the answer)."""
    letters = list(answer.replace(" ", ""))
    rng = random.Random(answer)  # same word -> same scramble
    for _ in range(10):
        rng.shuffle(letters)
        if "".join(letters) != answer.replace(" ", ""):
            break
    return letters


def make_hints(w, answer, is_original):
    """Hints from weakest to strongest. Only hints that exist for the word are added."""
    word = w["word"]
    n = len(answer)
    hints = []

    # The answer is a changed form of the headword (preparing ← prepare, decision ← decide)
    if is_original and answer.lower() != word.lower():
        hints.append(dict(id="base", icon="🌱", label="기본 단어",
                          text=f"기본 단어는 {word}({w['meaning']})예요. 문장에 맞는 형태로 바꿔 써 보세요."))

    hints.append(dict(id="length", icon="📏", label="글자 수", text=f"{n}글자 단어예요."))
    hints.append(dict(id="first", icon="🔤", label="첫 글자", text=f"‘{answer[0]}’(으)로 시작해요."))

    related = [f["w"] + (f" ({f['pos']})" if f.get("pos") else "")
               for f in w.get("family", []) if f["w"].lower() != answer.lower()]
    if related:
        hints.append(dict(id="related", icon="🔗", label="관련 단어",
                          text="함께 알아 두면 좋은 단어: " + ", ".join(related)))

    hints.append(dict(id="sound", icon="🔊", label="발음 듣기",
                      text="소리를 듣고 철자를 떠올려 보세요.", say=answer))

    if n >= 4:
        hints.append(dict(id="last", icon="🔚", label="끝 글자", text=f"‘{answer[-1]}’(으)로 끝나요."))
    if n >= 3:
        hints.append(dict(id="scramble", icon="🧩", label="철자 섞기",
                          text="이 글자들을 바르게 배열해 보세요.", tiles=scramble(answer)))
    if n >= 4:
        shown = math.ceil(n / 2)
        hints.append(dict(id="half", icon="👀", label="절반 공개",
                          text=f"앞의 {shown}글자를 빈칸에 보여 줄게요."))
    return hints


def make_blank(w, is_original):
    """Question + hints for one word (shown on the quiz screen)."""
    if is_original:
        # The 20 original items keep their own sentence, translation and grammar note.
        q = dict(w["quiz"], kind="sentence")
    else:
        forms = [w["word"], *w["variation"]]
        found = find_in_sentence(w["ex"], forms)
        if found:
            pattern = re.compile(r"(?<![A-Za-z])" + re.escape(found) + r"(?![A-Za-z])")
            answers = [found] + [f for f in forms if f.lower() != found.lower()]
            q = dict(s=pattern.sub("___", w["ex"], count=1), tr=f"뜻: {w['meaning']}",
                     a=answers, kind="sentence",
                     note="예문 속 쓰임과 철자를 함께 기억해 보세요.")
        else:
            # No example sentence: write the word from its meaning.
            q = dict(s="영어로 쓰세요: ___", tr=w["meaning"], a=forms, kind="meaning",
                     note="기본형 철자를 확인해 보세요.")
    q["hints"] = make_hints(w, q["a"][0], is_original)
    return q


@st.cache_data
def build_page():
    words = load_library()
    original = read_json("original_words.json", ORIGINAL_WORDS)
    audio = read_json("audio.json", {})

    # Same rule as the app: original items overwrite the list, but level/meaning stay from the list.
    original_by_word = {o["word"].lower(): o for o in original}
    merged = []
    for w in words:
        old = original_by_word.get(w["word"].lower())
        if old:
            w = {**w, **old, "level": w["level"], "meaning": w["meaning"], "variation": w["variation"]}
        w["blank"] = make_blank(w, old is not None)
        merged.append(w)

    def js(data):
        # "</" is escaped so the data can never close the <script> tag early.
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = APP_HTML
    html = html.replace("/*__AUDIO_JSON__*/{}", js(audio))
    html = html.replace("/*__ORIGINAL_WORDS_JSON__*/[]", js(original))
    html = html.replace("/*__WORDS_JSON__*/[]", js(merged))
    return html




# ------------------------------------------------------------------
# Data and app screen (kept at the bottom so the Python code stays easy to read)
# ------------------------------------------------------------------

# The 20 original items: their own sentence, translation and grammar note.
ORIGINAL_WORDS = [
 {
  "word": "relax",
  "level": 2,
  "pos": "동사",
  "meaning": "휴식을 취하다, 긴장을 풀다",
  "family": [],
  "variation": [],
  "ex": "I relax by listening to music after school.",
  "exForm": "relax",
  "quiz": {
   "s": "Take a deep breath and try to ___.",
   "tr": "심호흡을 하고 긴장을 풀어 보세요.",
   "a": [
    "relax"
   ],
   "note": "try to 뒤에는 동사원형이 와서 relax를 그대로 씀."
  }
 },
 {
  "word": "prepare",
  "level": 2,
  "pos": "동사",
  "meaning": "준비하다",
  "family": [],
  "variation": [],
  "ex": "My mom is preparing dinner in the kitchen.",
  "exForm": "preparing",
  "quiz": {
   "s": "I am ___ for the English test this week.",
   "tr": "나는 이번 주 영어 시험을 준비하고 있다.",
   "a": [
    "preparing"
   ],
   "note": "am + 동사-ing 진행형. prepare는 e를 빼고 -ing를 붙여 preparing이 됨."
  }
 },
 {
  "word": "exercise",
  "level": 1,
  "pos": "동사·명사",
  "meaning": "운동하다, 운동",
  "family": [],
  "variation": [],
  "ex": "I exercise in the park every morning.",
  "exForm": "exercise",
  "quiz": {
   "s": "My dad ___ every evening to stay healthy.",
   "tr": "우리 아빠는 건강을 유지하려고 매일 저녁 운동하신다.",
   "a": [
    "exercises"
   ],
   "note": "주어 My dad가 3인칭 단수이고 현재의 습관이라 exercises."
  }
 },
 {
  "word": "communicate",
  "level": 2,
  "pos": "동사",
  "meaning": "의사소통하다",
  "family": [
   {
    "w": "communication",
    "pos": "명사"
   }
  ],
  "variation": [],
  "ex": "We communicate with our friends by text message.",
  "exForm": "communicate",
  "quiz": {
   "s": "Good ___ is important between friends.",
   "tr": "친구 사이에는 좋은 의사소통이 중요하다.",
   "a": [
    "communication"
   ],
   "note": "Good(형용사) 뒤 주어 자리라 명사형 communication이 필요함."
  }
 },
 {
  "word": "borrow",
  "level": 1,
  "pos": "동사",
  "meaning": "빌리다",
  "family": [],
  "variation": [],
  "ex": "Can I borrow your pen?",
  "exForm": "borrow",
  "quiz": {
   "s": "I ___ a book from the library yesterday.",
   "tr": "나는 어제 도서관에서 책을 빌렸다.",
   "a": [
    "borrowed"
   ],
   "note": "yesterday가 있어 과거형 borrowed."
  }
 },
 {
  "word": "health",
  "level": 2,
  "pos": "명사",
  "meaning": "건강",
  "family": [
   {
    "w": "healthy",
    "pos": "형용사"
   }
  ],
  "variation": [],
  "ex": "Sleep is important for your health.",
  "exForm": "health",
  "quiz": {
   "s": "Eating vegetables keeps you ___.",
   "tr": "채소를 먹으면 건강을 유지할 수 있다.",
   "a": [
    "healthy"
   ],
   "note": "keep + 사람 + 형용사(~한 상태로 유지하다) 구조라 형용사형 healthy."
  }
 },
 {
  "word": "neighbor",
  "level": 2,
  "pos": "명사",
  "meaning": "이웃",
  "family": [],
  "variation": [
   "neighbour"
  ],
  "ex": "My neighbor has a cute dog.",
  "exForm": "neighbor",
  "quiz": {
   "s": "Our new ___ moved in next door yesterday.",
   "tr": "새 이웃이 어제 옆집으로 이사 왔다.",
   "a": [
    "neighbor",
    "neighbour"
   ],
   "note": "미국식 neighbor, 영국식 neighbour 모두 정답."
  }
 },
 {
  "word": "recipe",
  "level": 2,
  "pos": "명사",
  "meaning": "조리법",
  "family": [],
  "variation": [],
  "ex": "This recipe is easy to follow.",
  "exForm": "recipe",
  "quiz": {
   "s": "Grandma gave me her ___ for kimchi stew.",
   "tr": "할머니께서 김치찌개 조리법을 알려 주셨다.",
   "a": [
    "recipe"
   ],
   "note": "her 뒤 명사 자리. 음식을 만드는 방법을 나타냄."
  }
 },
 {
  "word": "schedule",
  "level": 2,
  "pos": "명사",
  "meaning": "일정",
  "family": [],
  "variation": [],
  "ex": "I check my schedule every night.",
  "exForm": "schedule",
  "quiz": {
   "s": "Let me check my ___ for this weekend.",
   "tr": "이번 주말 일정을 확인해 볼게.",
   "a": [
    "schedule"
   ],
   "note": "my 뒤 명사 자리. 주말 계획을 확인하는 상황."
  }
 },
 {
  "word": "hunger",
  "level": 2,
  "pos": "명사",
  "meaning": "배고픔",
  "family": [
   {
    "w": "hungry",
    "pos": "형용사"
   }
  ],
  "variation": [],
  "ex": "The baby cried from hunger.",
  "exForm": "hunger",
  "quiz": {
   "s": "I skipped lunch, so I'm very ___ now.",
   "tr": "점심을 걸러서 지금 무척 배가 고프다.",
   "a": [
    "hungry"
   ],
   "note": "be동사(am) 뒤 상태를 나타내는 형용사 hungry. hunger는 명사라 이 자리에 못 씀."
  }
 },
 {
  "word": "recommend",
  "level": 2,
  "pos": "동사",
  "meaning": "추천하다",
  "family": [],
  "variation": [],
  "ex": "Can you recommend a good book?",
  "exForm": "recommend",
  "quiz": {
   "s": "Our teacher ___ this movie to us last week.",
   "tr": "선생님께서 지난주에 우리에게 이 영화를 추천해 주셨다.",
   "a": [
    "recommended"
   ],
   "note": "last week가 있어 과거형 recommended. m이 두 개라는 점에 주의."
  }
 },
 {
  "word": "manage",
  "level": 2,
  "pos": "동사",
  "meaning": "관리하다, 해내다",
  "family": [],
  "variation": [],
  "ex": "I manage my time well during exams.",
  "exForm": "manage",
  "quiz": {
   "s": "She ___ to finish her homework before dinner yesterday.",
   "tr": "그녀는 어제 저녁 먹기 전에 숙제를 끝내 냈다.",
   "a": [
    "managed"
   ],
   "note": "manage to + 동사원형 = (어려운 일을) 해내다. yesterday가 있어 과거형 managed."
  }
 },
 {
  "word": "believe",
  "level": 1,
  "pos": "동사",
  "meaning": "믿다",
  "family": [],
  "variation": [],
  "ex": "I believe you can do it.",
  "exForm": "believe",
  "quiz": {
   "s": "Do you ___ in ghosts?",
   "tr": "너는 귀신이 있다고 믿니?",
   "a": [
    "believe"
   ],
   "note": "Do you 뒤에는 동사원형. believe in은 '~의 존재를 믿다'. ie 순서에 주의."
  }
 },
 {
  "word": "catch",
  "level": 1,
  "pos": "동사",
  "meaning": "잡다",
  "family": [],
  "variation": [],
  "ex": "I ran to catch the bus.",
  "exForm": "catch",
  "quiz": {
   "s": "Yesterday, he ___ the ball with one hand.",
   "tr": "어제 그는 한 손으로 공을 잡았다.",
   "a": [
    "caught"
   ],
   "note": "catch의 과거형은 불규칙형 caught."
  }
 },
 {
  "word": "add",
  "level": 1,
  "pos": "동사",
  "meaning": "더하다, 추가하다",
  "family": [],
  "variation": [],
  "ex": "Add some salt to the soup.",
  "exForm": "Add",
  "quiz": {
   "s": "Can you ___ my name to the list?",
   "tr": "내 이름을 명단에 추가해 줄래?",
   "a": [
    "add"
   ],
   "note": "Can you 뒤 동사원형. add A to B = A를 B에 추가하다."
  }
 },
 {
  "word": "adopt",
  "level": 2,
  "pos": "동사",
  "meaning": "입양하다, 채택하다",
  "family": [],
  "variation": [],
  "ex": "We adopted a puppy from the animal shelter.",
  "exForm": "adopted",
  "quiz": {
   "s": "Many families ___ pets from animal shelters.",
   "tr": "많은 가족이 동물 보호소에서 반려동물을 입양한다.",
   "a": [
    "adopt"
   ],
   "note": "주어가 복수(Many families)이고 현재의 일반적인 사실이라 adopt 그대로."
  }
 },
 {
  "word": "apply",
  "level": 2,
  "pos": "동사",
  "meaning": "지원하다, 적용하다",
  "family": [
   {
    "w": "applicant",
    "pos": "명사"
   }
  ],
  "variation": [],
  "ex": "I applied for the school's English camp.",
  "exForm": "applied",
  "quiz": {
   "s": "Each ___ must write a short essay.",
   "tr": "지원자는 각자 짧은 글을 써야 한다.",
   "a": [
    "applicant"
   ],
   "note": "Each 뒤 사람을 나타내는 명사 자리라 applicant."
  }
 },
 {
  "word": "decide",
  "level": 1,
  "pos": "동사",
  "meaning": "결정하다",
  "family": [
   {
    "w": "decision",
    "pos": "명사"
   }
  ],
  "variation": [],
  "ex": "I decided to join the soccer club.",
  "exForm": "decided",
  "quiz": {
   "s": "It was a hard ___ to make.",
   "tr": "내리기 어려운 결정이었다.",
   "a": [
    "decision"
   ],
   "note": "a hard(형용사) 뒤 명사 자리라 decision. make a decision = 결정을 내리다."
  }
 },
 {
  "word": "suggest",
  "level": 2,
  "pos": "동사",
  "meaning": "제안하다",
  "family": [],
  "variation": [],
  "ex": "My friend suggested watching a movie.",
  "exForm": "suggested",
  "quiz": {
   "s": "Who ___ this restaurant last time?",
   "tr": "지난번에 누가 이 식당을 제안했지?",
   "a": [
    "suggested"
   ],
   "note": "last time이 있어 과거형 suggested. gg 철자에 주의."
  }
 },
 {
  "word": "improve",
  "level": 2,
  "pos": "동사",
  "meaning": "향상시키다",
  "family": [],
  "variation": [],
  "ex": "I want to improve my English.",
  "exForm": "improve",
  "quiz": {
   "s": "Your English is ___ every day!",
   "tr": "네 영어 실력이 날마다 늘고 있어!",
   "a": [
    "improving"
   ],
   "note": "is + 동사-ing 진행형. e를 빼고 improving."
  }
 }
]

# The original app screen (HTML/CSS/JavaScript). Data is filled in by build_page().
APP_HTML = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#313338">
<title>Daily Words</title>
<style>
:root{
  --bg:#313338; --bg-deep:#1e1f22; --panel:#2b2d31; --raised:#383a40;
  --line:rgba(255,255,255,.08); --line-2:rgba(255,255,255,.14);
  --text:#f2f3f5; --text-2:#dbdee1; --muted:#949ba4; --faint:#6d6f78;
  --good:#23a55a; --bad:#f23f43;
  --r-device:48px; --pad:16px; --r-card:28px; --face-pad:20px; --r-inner:12px;
  --ease:cubic-bezier(.2,.8,.2,1); --spring:cubic-bezier(.34,1.56,.64,1);
  --font:-apple-system,"SF Pro Text","SF Pro","Segoe UI","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;
  color-scheme:dark;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font-family:var(--font);color:var(--text-2);background:var(--bg);display:flex;align-items:center;justify-content:center;min-height:100dvh;-webkit-font-smoothing:antialiased}
button{font:inherit;color:inherit;border:0;background:none;padding:0;cursor:pointer;-webkit-tap-highlight-color:transparent}
:focus-visible{outline:2px solid rgba(255,255,255,.7);outline-offset:3px}

/* ---------- device frame ---------- */
.device{position:relative;width:100%;height:100dvh;overflow:hidden;display:flex;flex-direction:column;
  background:
    radial-gradient(70% 40% at 15% 0%,rgba(255,255,255,.06),transparent 70%),
    radial-gradient(60% 40% at 90% 100%,rgba(255,255,255,.04),transparent 70%),
    var(--bg);}
@media (min-width:520px){
  body{background:#111214}
  .device{width:390px;height:min(844px,calc(100dvh - 48px));border-radius:var(--r-device);
    box-shadow:0 0 0 10px #000,0 0 0 11px #2b2d31,0 40px 90px rgba(0,0,0,.6)}
}

/* ---------- glass & light ---------- */
.glass{position:relative;
  background:linear-gradient(140deg,rgba(255,255,255,.10),rgba(255,255,255,.035));
  -webkit-backdrop-filter:blur(20px) saturate(140%);backdrop-filter:blur(20px) saturate(140%);
  border:1px solid var(--line);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.14),0 10px 30px rgba(0,0,0,.35),0 2px 6px rgba(0,0,0,.25)}
.surface{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);
  box-shadow:0 12px 32px rgba(0,0,0,.28)}
.glow{position:relative;isolation:isolate}
.glow::before,.glow::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity .35s var(--ease);z-index:2}
.glow::before{background:radial-gradient(150px circle at var(--mx,50%) var(--my,50%),rgba(255,255,255,.12),rgba(255,255,255,0) 65%)}
.glow::after{padding:1px;
  background:radial-gradient(110px circle at var(--mx,50%) var(--my,50%),rgba(255,255,255,.75),rgba(255,255,255,0) 70%);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;
  mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);mask-composite:exclude}
.glow.hot::before,.glow.hot::after{opacity:1}
.press{transition:transform .35s var(--spring),filter .2s}
.press:active{transform:scale(.95);filter:brightness(1.12)}

/* ---------- panes ---------- */
.viewport{flex:1;position:relative;overflow:hidden;touch-action:pan-y}
.track{display:flex;width:300%;height:100%;transition:transform .45s var(--ease);will-change:transform}
.track.dragging{transition:none}
.pane{width:calc(100%/3);height:100%;overflow-y:auto;padding:calc(18px + env(safe-area-inset-top)) var(--pad) 130px;user-select:none;-webkit-user-select:none;scrollbar-width:none}
.pane::-webkit-scrollbar{display:none}
.sec-title{font-size:13px;font-weight:700;color:var(--muted);margin:4px 6px 12px}
.icon-btn{width:44px;height:44px;border-radius:999px;display:grid;place-items:center;color:var(--text-2);flex:none}
.icon-btn svg{width:20px;height:20px}
.btn{height:50px;padding:0 20px;border-radius:999px;font-weight:800;font-size:15px;display:inline-flex;align-items:center;justify-content:center;gap:8px;color:var(--text-2)}
.btn.primary{color:var(--bg-deep);background:var(--text);box-shadow:inset 0 1px 0 #fff,0 8px 22px rgba(0,0,0,.35)}
.btn:disabled{opacity:.35;pointer-events:none}
.btn.full{width:100%}
.duo{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.stack{display:grid;gap:10px}
.link{display:block;margin:16px auto 0;font-size:13px;color:var(--muted);font-weight:700;text-decoration:underline;text-underline-offset:3px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:6px 12px;border-radius:999px;font-size:13px;font-weight:700;background:var(--bg-deep);color:var(--text-2);border:1px solid var(--line)}
.chip small{font-weight:600;color:var(--muted);font-size:11px}
.chip.ghost{color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.stars{color:var(--text);letter-spacing:1px;margin-right:5px}

/* ---------- set list ---------- */
.set-list{display:grid;gap:12px}
.set-item{display:block;width:100%;text-align:left;padding:18px 20px;border-radius:24px}
.set-head{display:flex;justify-content:space-between;align-items:baseline}
.set-head b{font-size:20px;color:var(--text);font-weight:800;letter-spacing:-.01em}
.set-head span{font-size:13px;color:var(--muted);font-weight:700}
.set-words{margin-top:6px;font-size:14px;color:var(--muted);line-height:1.5}
.mini-bar{margin-top:14px;height:6px;border-radius:999px;background:var(--bg-deep);overflow:hidden}
.mini-bar i{display:block;height:100%;border-radius:999px;background:var(--text-2);transition:width .5s var(--ease)}

/* ---------- study ---------- */
.study-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.study-title{text-align:center}
.study-title b{display:block;font-size:17px;color:var(--text);font-weight:800}
.study-title span{font-size:12px;color:var(--muted);font-weight:700}
.icon-spacer{width:44px}
.dots{display:flex;justify-content:center;gap:6px;margin:0 0 14px}
.dots i{width:7px;height:7px;border-radius:999px;background:var(--raised);transition:width .3s var(--ease),background .3s}
.dots i.know{background:var(--muted)}
.dots i.dont{background:rgba(242,63,67,.6)}
.dots i.on{width:22px;background:var(--text)}
.stage-wrap{position:relative;padding:0 18px}
.edge{position:absolute;top:50%;width:18px;display:grid;place-items:center;color:var(--faint);pointer-events:none;transform:translateY(-50%);transition:opacity .3s}
.edge svg{width:16px;height:16px}
.edge.left{left:0;animation:nudgeL 2.4s ease-in-out infinite}
.edge.right{right:0;animation:nudgeR 2.4s ease-in-out infinite}
.edge.off{opacity:0}
@keyframes nudgeL{0%,70%,100%{transform:translate(0,-50%)}85%{transform:translate(-3px,-50%)}}
@keyframes nudgeR{0%,70%,100%{transform:translate(0,-50%)}85%{transform:translate(3px,-50%)}}
.stage{perspective:1400px;touch-action:pan-y;transition:transform .35s var(--spring),opacity .25s}
.stage.dragging{transition:none}
.flashcard{position:relative;height:380px;transform-style:preserve-3d;transition:transform .6s var(--ease);cursor:pointer;border-radius:var(--r-card)}
.flashcard.flipped{transform:rotateY(180deg)}
.face{position:absolute;inset:0;backface-visibility:hidden;-webkit-backface-visibility:hidden;padding:var(--face-pad);display:flex;flex-direction:column;overflow:hidden}
.face.back{transform:rotateY(180deg)}
.badge{align-self:flex-start;font-size:12px;font-weight:700;padding:6px 11px;border-radius:999px;background:var(--bg-deep);color:var(--text-2);border:1px solid var(--line)}
.word{font-size:44px;font-weight:800;letter-spacing:-.03em;margin:auto 0 4px;text-align:center;color:var(--text)}
.pos{text-align:center;color:var(--muted);font-size:14px}
.front-tags{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:14px}
.speak{margin:16px auto 0;width:46px;height:46px;border-radius:999px;display:grid;place-items:center;background:var(--bg-deep);border:1px solid var(--line);color:var(--text-2)}
.speak svg{width:20px;height:20px}
.hint{margin-top:auto;text-align:center;font-size:12px;color:var(--faint)}
.meaning{font-size:25px;font-weight:800;margin:12px 0 2px;letter-spacing:-.02em;color:var(--text)}
.sub{font-size:13px;color:var(--muted)}
.label{font-size:12px;color:var(--muted);font-weight:700;margin:14px 0 7px}
.ex{font-size:16px;line-height:1.55;margin:0;padding:12px 14px;background:var(--bg-deep);border-radius:var(--r-inner);color:var(--text-2)}
mark{background:linear-gradient(transparent 60%,rgba(255,255,255,.2) 60%);color:var(--text);font-weight:800;padding:0 1px}
.none{font-size:13px;color:var(--faint)}
.study-actions{margin-top:16px}

/* ---------- set done ---------- */
.done{padding:24px var(--face-pad)}
.done-score{text-align:center}
.done-score b{font-size:54px;font-weight:800;color:var(--text);letter-spacing:-.03em}
.done-score span{font-size:22px;color:var(--muted);font-weight:700}
.done-score p{margin:2px 0 18px;color:var(--muted);font-size:14px}
.rows{display:grid;gap:8px;margin-bottom:20px}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:11px 14px;border-radius:14px;background:var(--bg-deep)}
.row .w{font-weight:800;color:var(--text)}
.row .m{font-size:12px;color:var(--muted);margin-top:1px}
.tag{flex:none;font-size:12px;font-weight:800;padding:4px 10px;border-radius:999px}
.tag.know{background:rgba(35,165,90,.15);color:#57d38a}
.tag.dont{background:rgba(242,63,67,.15);color:#ff7b7e}
.tag.none{background:var(--raised);color:var(--muted)}

/* ---------- quiz ---------- */
.intro{padding:30px var(--face-pad);text-align:center}
.intro .big{font-size:28px;font-weight:800;color:var(--text);letter-spacing:-.02em;margin:4px 0 8px}
.intro p{margin:0 0 6px;color:var(--muted);font-size:14px;line-height:1.6}
.intro .facts{display:flex;justify-content:center;gap:8px;margin:18px 0 26px;flex-wrap:wrap}
.progress{height:10px;border-radius:999px;overflow:hidden;margin:0 2px 14px;padding:2px}
.bar{height:100%;width:0;border-radius:999px;background:var(--text-2);transition:width .45s var(--ease)}
.q-card{padding:var(--face-pad)}
.q-meta{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:var(--muted);font-weight:700}
.q-meta button{color:var(--faint);font-weight:700;font-size:12px;text-decoration:underline;text-underline-offset:3px}
.q-sentence{font-size:21px;line-height:1.6;font-weight:600;margin:16px 0 4px;color:var(--text)}
.q-trans{font-size:14px;color:var(--muted);line-height:1.5;margin:0 0 16px}
.blank{display:inline-block;min-width:96px;border-bottom:3px solid var(--faint);text-align:center;color:var(--text);padding:0 4px;line-height:1.3}
.blank.good{color:#57d38a;border-color:var(--good)}
.blank.bad{color:#ff7b7e;border-color:var(--bad)}
.answer-row{display:flex;gap:10px;margin-top:16px}
.input{flex:1;min-width:0;height:52px;border-radius:999px;border:1.5px solid #3f4147;padding:0 18px;font-size:18px;font-family:inherit;background:var(--bg-deep);color:var(--text);outline:none;transition:border-color .2s,box-shadow .2s;user-select:text;-webkit-user-select:text}
.input::placeholder{color:var(--faint)}
.input:focus{border-color:var(--text-2);box-shadow:0 0 0 4px rgba(255,255,255,.08)}
.input.good{border-color:var(--good);box-shadow:0 0 0 4px rgba(35,165,90,.15)}
.input.bad{border-color:var(--bad);box-shadow:0 0 0 4px rgba(242,63,67,.15)}
.feedback{margin-top:14px;padding:16px;border-radius:16px;display:none}
.feedback.show{display:block;animation:pop .35s var(--spring)}
.feedback.good{background:rgba(35,165,90,.10);box-shadow:inset 0 0 0 1px rgba(35,165,90,.45),0 10px 30px rgba(35,165,90,.12)}
.feedback.bad{background:rgba(242,63,67,.10);box-shadow:inset 0 0 0 1px rgba(242,63,67,.45),0 10px 30px rgba(242,63,67,.12)}
.fb-title{font-weight:800;font-size:16px;margin-bottom:10px;color:var(--text)}
.fb-line{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border-radius:12px;background:rgba(0,0,0,.25);margin-bottom:10px}
.fb-line p{margin:0;flex:1;font-size:15px;line-height:1.5;color:var(--text-2)}
.fb-line b{color:var(--text)}
.say{flex:none;width:34px;height:34px;border-radius:999px;display:grid;place-items:center;background:rgba(255,255,255,.08);color:var(--text)}
.say svg{width:17px;height:17px}
.fb-note{font-size:14px;line-height:1.55;color:var(--text-2)}
.fb-note b{color:var(--text)}
.result{padding:28px var(--face-pad)}
.score{text-align:center;font-size:58px;font-weight:800;letter-spacing:-.03em;color:var(--text)}
.score span{font-size:24px;color:var(--muted)}
.result>p{text-align:center;color:var(--muted);line-height:1.5;margin:4px 0 20px;font-size:14px}
.result .row s{color:#ff7b7e}
@keyframes pop{from{transform:scale(.96);opacity:0}to{transform:none;opacity:1}}
@keyframes shake{0%,100%{transform:none}25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}
.shake{animation:shake .3s}

/* ---------- review ---------- */
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:14px;border-radius:24px;text-align:center}
.stats b{display:block;font-size:22px;font-weight:800;color:var(--text)}
.stats span{font-size:12px;color:var(--muted);font-weight:600}
.list{display:flex;flex-direction:column;gap:10px;margin-top:14px}
.item{padding:14px 16px;border-radius:20px;display:flex;justify-content:space-between;gap:12px;align-items:center;text-align:left;width:100%}
.item .w{font-weight:800;font-size:18px;color:var(--text)}
.item .w small{font-size:11px;font-weight:700;color:var(--muted);margin-left:6px}
.item .m{font-size:13px;color:var(--muted);margin-top:2px}
.item .d{font-size:13px;margin-top:6px;color:var(--text-2)}
.item s{color:#ff7b7e}
.count{flex:none;min-width:38px;height:28px;padding:0 8px;border-radius:999px;background:rgba(242,63,67,.15);color:#ff7b7e;font-weight:800;font-size:13px;display:grid;place-items:center}
.voice-box{padding:16px;border-radius:20px}
.voice-row{display:flex;gap:10px;align-items:center}
.select{flex:1;min-width:0;height:44px;border-radius:999px;border:1.5px solid #3f4147;background:var(--bg-deep);color:var(--text);padding:0 14px;font:inherit;font-size:14px;outline:none}
.select:focus{border-color:var(--text-2)}
.voice-note{margin:10px 2px 0;font-size:12px;color:var(--muted);line-height:1.55}
.empty{text-align:center;padding:36px 20px;color:var(--muted);line-height:1.6;margin-top:14px;font-size:14px}

/* ---------- tab bar ---------- */
.tabbar{position:absolute;left:50%;bottom:calc(18px + env(safe-area-inset-bottom));transform:translateX(-50%);
  width:calc(100% - 40px);max-width:350px;height:66px;border-radius:999px;padding:6px;
  display:grid;grid-template-columns:repeat(3,1fr);z-index:10;touch-action:none;
  background:linear-gradient(140deg,rgba(64,66,73,.62),rgba(43,45,49,.52))}
.lens{position:absolute;top:6px;left:6px;bottom:6px;width:calc((100% - 12px)/3);border-radius:999px;
  background:linear-gradient(140deg,rgba(255,255,255,.16),rgba(255,255,255,.07));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.22),0 4px 14px rgba(0,0,0,.3);
  transition:transform .45s var(--spring);z-index:0}
.lens.dragging{transition:none}
.tab{position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;
  font-size:11px;font-weight:700;color:var(--muted);border-radius:999px;transition:color .3s,transform .35s var(--spring)}
.tab svg{width:22px;height:22px}
.tab[aria-selected="true"]{color:var(--text)}
.tab:active{transform:scale(.92)}
.dot{position:absolute;top:4px;left:calc(50% + 6px);min-width:18px;height:18px;padding:0 5px;border-radius:999px;background:var(--bad);color:#fff;font-size:10px;font-weight:800;display:none;place-items:center}
.dot.on{display:grid}

/* ---------- toast ---------- */
.toast{position:absolute;top:calc(16px + env(safe-area-inset-top));left:50%;transform:translate(-50%,-14px);opacity:0;pointer-events:none;
  padding:10px 16px;border-radius:999px;font-size:13px;font-weight:700;color:var(--text);z-index:20;transition:opacity .3s var(--ease),transform .3s var(--ease);white-space:nowrap}
.toast.show{opacity:1;transform:translate(-50%,0)}

@media (prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}
</style>

<style>
:root{--bg:#f5f7fc;--bg-deep:#edf1fa;--panel:#fff;--raised:#f0f4fb;--line:#dfe6f2;--line-2:#d4def0;--text:#23314c;--text-2:#344360;--muted:#65728b;--faint:#8794a8;--good:#21946c;--bad:#dc5b61;color-scheme:light}
body{background:#f0f3fb}.device{background:#f7f9fd;color:var(--text-2)}
@media(min-width:520px){body{background:#edf1fa}.device{width:min(640px,96vw);height:min(900px,calc(100dvh - 32px));border:1px solid #dbe2f0;box-shadow:0 18px 55px #33436b22;border-radius:30px}}
.surface,.glass{background:#fff;border:1px solid var(--line);box-shadow:0 6px 18px #24355d10}
.btn.primary{background:#506be9;color:white;box-shadow:0 5px 12px #506be929}
.glass.glow{background:#fff}.tabbar{background:#fff}.lens{background:#e9eeff;box-shadow:none}.tab[aria-selected=true]{color:#3d5ed1}
.flashcard{height:min(390px,48vh)}.face{overflow:auto}.word{color:#293b60}.badge{background:#ecf1ff}
.input,.select{background:#f8faff;color:#23314c;border:1px solid #d7dfed}.q-sentence{overflow-wrap:anywhere}
.feedback.good{background:#e7f8ef}.feedback.bad{background:#fff0f0}.fb-line{background:#fff}
:focus-visible{outline:2px solid #526ce6}.pane{padding-top:12px}
.page-top{padding:13px 20px 5px;display:flex;justify-content:space-between;align-items:center;gap:10px}
.page-top h1{margin:0;font-size:19px;letter-spacing:-.03em;color:#293b60}.page-top small{font-size:12px;color:#75829a}
.toolbar{display:flex;gap:7px;align-items:center}.small-btn{border-radius:999px;border:1px solid #dbe2f1;background:#fff;padding:7px 12px;font-size:12px;font-weight:750;color:#435579}
.over-screen{position:absolute;inset:0;z-index:30;background:linear-gradient(135deg,#f6f9ff,#e8efff);overflow-y:auto;padding:28px 22px 50px}
.over-screen.hidden{display:none}.hero{margin:30px auto 20px;max-width:450px;text-align:center}.hero-symbol{font-size:40px}.hero h2{font-size:32px;color:#2c417c;margin:12px 0}.hero p{line-height:1.7;color:#60708f}
.overlay-box{max-width:470px;margin:auto;background:#fff;border:1px solid #dce5f6;border-radius:23px;padding:23px;box-shadow:0 14px 40px #314a8014}
.levels{display:flex;gap:6px;margin:13px 0;flex-wrap:wrap}.level-pill{font-size:12px;font-weight:800;padding:7px 11px;border-radius:50px;background:#e8efff;color:#405dc9}
.level-1{background:#e3f7ed;color:#14865d}.level-2{background:#e8efff;color:#405dc9}.level-3{background:#fff0df;color:#a86a1c}
.options{display:grid;gap:9px;margin-top:16px}.option{display:block;text-align:left;background:#f7f9fd;color:#273758;border:1.5px solid #dee6f4;border-radius:14px;padding:13px 15px;font-weight:750}.option.good{border-color:#1f9a72;background:#e5f9ef}.option.bad{border-color:#e05f6a;background:#fff0f0}.option:disabled{cursor:default}
.muted{font-size:13px;color:#6f7e96;line-height:1.6}.head-row{display:flex;gap:8px;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap}
.streak-days{display:grid;grid-template-columns:repeat(7,1fr);gap:5px;margin:12px 0}.day{text-align:center;border-radius:13px;background:#f0f3fa;padding:9px 1px;font-size:11px;color:#7a869c}.day.on{background:#dff7eb;color:#087e56;font-weight:850}.day.today{outline:2px solid #718bf1}.day b{display:block;font-size:17px;margin-top:5px}
.review-quiz{margin-top:14px}.q-card .meaning-hint{font-weight:750;color:#5065b3}.flashcard .face.back .ex{overflow-wrap:anywhere}.level-select{border-radius:12px;padding:7px 11px;border:1px solid #ccd8ed;background:#fff;color:#2d426a}
@media(max-width:360px){.word{font-size:34px}.face{padding:15px}.btn{padding:0 12px}.page-top{padding:10px 14px 2px}}

/* Home is a menu, but the original three tabs remain the primary shortcuts. */
.over-screen.with-tabs{bottom:90px;padding-bottom:24px;background:linear-gradient(145deg,#f7faff,#eef3ff)}
.home-wrap{max-width:540px;margin:0 auto;padding-bottom:18px}
.home-greeting{margin:4px 0 20px}.home-greeting h2{font-size:27px;line-height:1.3;color:#273d73;letter-spacing:-.04em;margin:13px 0 7px}
.home-greeting p{font-size:14px;line-height:1.6;color:#657590;margin:0}
.home-section{margin-bottom:17px}.home-section h3{font-size:16px;margin:0 0 11px;color:#314778}
.home-grid{display:grid;grid-template-columns:1fr 1fr;gap:11px}
.home-feature{display:flex;flex-direction:column;align-items:flex-start;gap:7px;min-height:146px;padding:16px;text-align:left;border-radius:19px;background:white;border:1px solid #dce5f6;box-shadow:0 7px 20px #334f8520;transition:transform .18s}
.home-feature:active{transform:scale(.97)}.home-feature strong{font-size:16px;color:#263c72}
.home-feature small{font-size:12px;color:#65738b;line-height:1.5}.home-icon{font-size:23px}
.home-arrow{font-size:12px;color:#4666cb;font-weight:800;margin-top:auto}
.home-feature-wide{grid-column:span 2;min-height:105px;display:grid;grid-template-columns:40px 1fr;grid-template-rows:auto auto auto;gap:1px 5px;align-content:center}
.home-feature-wide .home-icon{grid-row:span 3}.home-feature-wide .home-arrow{margin:3px 0 0}
.home-panel{background:white;border:1px solid #dfe7f5;border-radius:20px;padding:17px 16px;box-shadow:0 6px 20px #334f850e}
.home-section-head{display:flex;justify-content:space-between;align-items:center;gap:10px}
.home-section-head h3{margin:0}.home-test-btn{background:#eef2ff;color:#3d58b7;border:1px solid #d7e0ff;height:45px;margin-top:8px}
.home-bottom-hint{text-align:center;font-size:12px;color:#8490a5;line-height:1.5;margin:8px 0}
.welcome-badge{display:inline-block;background:#e4f3e9;color:#23785a;border-radius:40px;padding:6px 13px;font-size:12px;font-weight:800}
.tutorial-step{display:flex;align-items:flex-start;gap:13px;padding:14px 0;border-bottom:1px solid #e7ecf6}
.tutorial-step>b{background:#e9eeff;color:#4260bc;border-radius:50%;width:29px;height:29px;display:grid;place-items:center;flex:none}
.tutorial-step strong{color:#283e70;font-size:14px}.tutorial-step p{margin:4px 0 0;color:#718099;font-size:12px;line-height:1.6}
@media(max-width:370px){.over-screen{padding-left:15px;padding-right:15px}.home-feature{padding:13px}.home-feature strong{font-size:14px}}
</style>
<style>
/* ---------- fill-in-the-blank quiz (bq-*) : only the quiz play screen uses these ---------- */
.bq-top{display:flex;justify-content:space-between;align-items:center;margin:4px 2px 10px}
.bq-top .sec-title{margin:0 4px}
.bq-quit{font-size:12px;font-weight:750;color:var(--muted);padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:#fff}
.bq-quit:hover{color:var(--text)}
.bq-progress{display:flex;align-items:center;gap:12px;margin:0 4px 14px}
.bq-track{flex:1;height:8px;border-radius:999px;background:#e3e9f6;overflow:hidden}
.bq-track i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#7b90f2,#506be9);transition:width .45s var(--ease)}
.bq-progress>span{font-size:15px;font-weight:800;color:var(--text);min-width:44px;text-align:right}
.bq-progress small{font-size:12px;color:var(--muted);font-weight:700}
.bq-card{padding:20px}
.bq-kind{display:inline-flex;font-size:11.5px;font-weight:800;padding:5px 10px;border-radius:999px;background:#ecf1ff;color:#405dc9}
.bq-sentence{font-size:21px;line-height:1.8;font-weight:650;color:var(--text);margin:14px 0 4px;overflow-wrap:anywhere}
.bq-meaning{font-size:27px;font-weight:800;color:var(--text);text-align:center;letter-spacing:-.02em;margin:22px 0 4px}
.bq-solo{text-align:center;margin:6px 0 10px}
.bq-trans{font-size:14px;color:var(--muted);line-height:1.55;margin:0}
.bq-blank{display:inline-block;min-width:88px;margin:0 3px;padding:0 12px;border-radius:10px;background:#f1f4ff;border:1.5px dashed #a8b7ee;color:#3d5ed1;text-align:center;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em;font-weight:700;letter-spacing:.06em;line-height:1.6;white-space:nowrap;transition:background .25s,border-color .25s,color .25s}
.bq-blank.good{background:#e5f9ef;border:1.5px solid var(--good);color:#14865d;font-family:var(--font);letter-spacing:0}
.bq-blank.bad{background:#fff0f0;border:1.5px solid var(--bad);color:#c2434a;font-family:var(--font);letter-spacing:0}
.bq-hints{margin-top:16px;padding:14px;border-radius:16px;background:#f7f9fd;border:1px solid var(--line)}
.bq-hints-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.bq-hints-head b{font-size:13px;color:var(--text)}
.bq-hints-head span{font-size:12px;font-weight:700;color:var(--muted)}
.bq-chips{display:flex;flex-wrap:wrap;gap:7px}
.bq-chip{font-size:12.5px;font-weight:750;padding:7px 11px;border-radius:999px;background:#fff;border:1px solid #dbe2f1;color:#435579;transition:border-color .2s,background .2s,color .2s,transform .3s var(--spring)}
.bq-chip:hover{border-color:#a8b7ee;color:#3d5ed1}
.bq-chip:active{transform:scale(.94)}
.bq-chip.on{background:#e9eeff;border-color:#c3cffa;color:#3d5ed1}
.bq-chip:disabled{opacity:.55;cursor:default;transform:none}
.bq-revealed{display:grid;gap:7px;margin-top:10px}
.bq-revealed:empty{display:none}
.bq-hint{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border-radius:12px;background:#fff;border:1px solid var(--line);font-size:14px;line-height:1.5;color:var(--text-2);animation:pop .3s var(--spring)}
.bq-hint-icon{flex:none;font-size:16px;line-height:1.4}
.bq-hint b{display:block;font-size:12px;color:var(--muted);font-weight:800;margin-bottom:1px}
.bq-tiles{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.bq-tiles span{min-width:28px;height:30px;padding:0 6px;display:grid;place-items:center;border-radius:8px;background:#eef2ff;color:#3d5ed1;font-weight:800;font-size:15px}
.bq-replay{display:block;margin-top:5px;font-size:12px;font-weight:750;color:#3d5ed1;text-decoration:underline;text-underline-offset:3px}
.bq-answer{display:flex;gap:10px;margin-top:16px}
.bq-input{flex:1;min-width:0;height:52px;border-radius:14px;border:1.5px solid #d7dfed;padding:0 16px;font-size:18px;font-family:inherit;background:#fff;color:#23314c;outline:none;transition:border-color .2s,box-shadow .2s;user-select:text;-webkit-user-select:text}
.bq-input::placeholder{color:var(--faint);font-size:15px}
.bq-input:focus{border-color:#506be9;box-shadow:0 0 0 4px #506be91f}
.bq-input.good{border-color:var(--good);box-shadow:0 0 0 4px rgba(33,148,108,.15)}
.bq-input.bad{border-color:var(--bad);box-shadow:0 0 0 4px rgba(220,91,97,.15)}
.bq-input:disabled{background:#f8faff}
.bq-check{height:52px;border-radius:14px;padding:0 22px;flex:none}
.bq-used{font-size:12px;color:var(--muted)}
@media(max-width:360px){.bq-card{padding:16px}.bq-sentence{font-size:19px}.bq-meaning{font-size:23px}.bq-check{padding:0 16px}}
</style>
</head>
<body>
<div class="device" id="device">
<div class="page-top"><div><h1>Daily Words</h1><small id="levelText">오늘도 한 단어씩!</small></div><div class="toolbar"><button class="small-btn" id="menuBtn">홈</button><button class="small-btn" id="soundBtn" aria-label="효과음 음소거">소리 켬</button></div></div>
<div id="overlay" class="over-screen"></div>

  <main class="viewport" id="viewport">
    <div class="track" id="track">
      <section class="pane" id="pane0" role="tabpanel" aria-labelledby="tab0"><div id="flashBody"></div></section>
      <section class="pane" id="pane1" role="tabpanel" aria-labelledby="tab1"><div id="quizBody"></div></section>
      <section class="pane" id="pane2" role="tabpanel" aria-labelledby="tab2"><div id="reviewBody"></div></section>
    </div>
  </main>

  <nav class="tabbar glass glow" id="tabbar" role="tablist" aria-label="학습 메뉴">
    <div class="lens" id="lens" aria-hidden="true"></div>
    <button class="tab" id="tab0" role="tab" aria-controls="pane0" aria-selected="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="3" y="6" width="13" height="15" rx="3"/><path d="M8 3h10a3 3 0 0 1 3 3v12"/></svg>
      단어 카드
    </button>
    <button class="tab" id="tab1" role="tab" aria-controls="pane1" aria-selected="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="4"/><path d="M7 10h4M7 14h2"/><path d="M13 15h5"/></svg>
      빈칸 퀴즈
    </button>
    <button class="tab" id="tab2" role="tab" aria-controls="pane2" aria-selected="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4v5h-5"/></svg>
      복습
      <span class="dot" id="reviewDot">0</span>
    </button>
  </nav>

  <div class="toast glass" id="toast" role="status" aria-live="polite"></div>
</div>

<script>
const AUDIO = /*__AUDIO_JSON__*/{};
</script>
<script>
/* =========================================================
   WORD DATA — keep all word data in this one array.
   Later, the full 3,000-word list can replace or extend it.
   Every 5 words in order form one flashcard set (4 sets).
   level: 1 = ★ (초등 권장 *), 2 = ★★ (중·고 공통 **), 3 = ★★★ (표시 없음, 고등 선택)
   ========================================================= */
const ORIGINAL_WORDS = /*__ORIGINAL_WORDS_JSON__*/[];


/* ============================================================
   DATA - Original teaching materials are preserved.
   ============================================================ */
const WORDS = /*__WORDS_JSON__*/[].map(w=>({...w}));
const originalByWord = new Map(ORIGINAL_WORDS.map(w=>[w.word.toLowerCase(),w]));
WORDS.forEach((w,i)=>{let old=originalByWord.get(w.word.toLowerCase());if(old){WORDS[i]={...w,...old,level:w.level,meaning:w.meaning};}});
const byWord = new Map(WORDS.map(w=>[w.word,w]));
const LEVELS={1:{label:'Level 1 · 기본',stars:'★'},2:{label:'Level 2 · 핵심',stars:'★★'},3:{label:'Level 3 · 심화',stars:'★★★'}};
const KEY='daily-words-g2-3000-v1';
const defaults=()=>({placed:false,level:1,wrong:{},status:{},solved:0,correct:0,streak:[],muted:false});
let S=defaults();try{const value=JSON.parse(localStorage.getItem(KEY)||'null');if(value&&typeof value==='object') S={...defaults(),...value};}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(S));}catch(e){/* Storage can be disabled in private mode. */}}
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm=v=>String(v??'').trim().toLowerCase().replace(/\s+/g,' ');
const shuffle=list=>{let a=[...list];for(let i=a.length-1;i>0;i--){let j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];}return a;};
const choose=(list,n)=>shuffle(list).slice(0,n);
function localDate(d=new Date()){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
function addStudyDay(){let day=localDate();if(!Array.isArray(S.streak))S.streak=[];if(!S.streak.includes(day)){S.streak.push(day);S.streak=S.streak.slice(-400);save();sound('streak');}}
function streakCount(){let dates=new Set(S.streak||[]),d=new Date(),n=0;if(!dates.has(localDate(d)))d.setDate(d.getDate()-1);while(dates.has(localDate(d))){n++;d.setDate(d.getDate()-1);}return n;}
function weekHtml(){let d=new Date();d.setDate(d.getDate()-((d.getDay()+6)%7));let arr=[];for(let i=0;i<7;i++){let x=new Date(d);x.setDate(d.getDate()+i);let day=localDate(x);arr.push(`<div class="day ${(S.streak||[]).includes(day)?'on':''} ${day===localDate()?'today':''}">${'월화수목금토일'[i]}<b>${(S.streak||[]).includes(day)?'✓':'·'}</b></div>`);}return `<div class="streak-days">${arr.join('')}</div><p class="muted">연속 학습 ${streakCount()}일 · 퀴즈 한 회를 끝내면 출석으로 기록돼요.</p>`;}
/* Gentle sounds use no sound files or network requests. */
let audioContext;
function sound(kind){if(S.muted)return;try{audioContext??=new (window.AudioContext||window.webkitAudioContext)();const seq={click:[[440,.055]],correct:[[560,.07],[720,.07]],wrong:[[280,.11]],finish:[[480,.08],[620,.08],[800,.12]],streak:[[600,.06],[790,.10]]}[kind]||[];let t=audioContext.currentTime;seq.forEach(([freq,duration])=>{let o=audioContext.createOscillator(),g=audioContext.createGain();o.type='sine';o.frequency.value=freq;g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.035,t+.012);g.gain.exponentialRampToValueAtTime(.0001,t+duration);o.connect(g);g.connect(audioContext.destination);o.start(t);o.stop(t+duration+.01);t+=duration;});}catch(e){}}
$('soundBtn').addEventListener('click',()=>{S.muted=!S.muted;save();$('soundBtn').textContent=S.muted?'소리 끔':'소리 켬';if(!S.muted)sound('click');});$('soundBtn').textContent=S.muted?'소리 끔':'소리 켬';
const overlay=$('overlay');let overlayMode='landing';
// The home dashboard shares the original three-tab navigation.
function showOverlay(markup){
  overlay.classList.remove('hidden');overlay.innerHTML=markup;
  const hasTabs=S.placed&&(overlayMode==='home');
  $('tabbar').style.visibility=hasTabs?'visible':'hidden';
  overlay.classList.toggle('with-tabs',hasTabs);
}
function closeOverlay(){
  if(!S.placed){tutorial();return;}
  overlay.classList.add('hidden');$('tabbar').style.visibility='visible';refresh();
}
function landing(){
  overlayMode='home';
  if(!S.placed){tutorial();return;}
  const mistakes=Object.keys(S.wrong||{}).length;
  showOverlay(`<div class="home-wrap">
    <div class="home-greeting"><span class="level-pill level-${S.level}">나의 시작 레벨 · Level ${S.level}</span>
      <h2>오늘도 한 단어씩 🌿</h2><p>고2 영어 단어 3,000개, 내 수준에 맞게 꾸준히 배워요.</p></div>
    <div class="home-section"><h3>학습 메뉴</h3><div class="home-grid">
      <button class="home-feature" data-page="cards"><span class="home-icon">📖</span><strong>단어 카드</strong><small>뜻·예문·철자 익히기</small><span class="home-arrow">시작하기 →</span></button>
      <button class="home-feature" data-page="quiz"><span class="home-icon">✏️</span><strong>빈칸 퀴즈</strong><small>문장 속 알맞은 단어 쓰기</small><span class="home-arrow">풀어보기 →</span></button>
      <button class="home-feature home-feature-wide" data-page="review"><span class="home-icon">🔁</span><strong>오답 복습</strong><small>틀린 단어 ${mistakes}개 · 다른 유형으로 다시 도전</small><span class="home-arrow">복습하기 →</span></button>
    </div></div>
    <div class="home-section home-panel"><div class="home-section-head"><h3>내 레벨 확인하기</h3><span class="level-pill level-${S.level}">Level ${S.level}</span></div>
      <p class="muted">처음 테스트를 마쳤어요. 지금 내 실력이 궁금하면 9문항으로 다시 확인할 수 있어요.</p>
      <button class="btn home-test-btn full" data-page="placement">레벨 테스트 다시 하기 →</button></div>
    <div class="home-section home-panel"><h3>이번 주 학습 기록 🔥</h3>${weekHtml()}</div>
    <p class="home-bottom-hint">아래 메뉴에서도 단어 카드 · 빈칸 퀴즈 · 복습으로 바로 이동할 수 있어요.</p>
  </div>`);
}
// First-time learners follow a short, unskippable introduction to placement.
function tutorial(){
  overlayMode='tutorial';
  showOverlay(`<div class="hero"><span class="welcome-badge">처음 방문했나요?</span><div class="hero-symbol">🌱</div>
    <h2>Daily Words에 온 걸 환영해요!</h2><p>고2 단어 학습, 내 수준부터 시작하면 훨씬 편해요.</p></div>
    <div class="overlay-box"><h3>시작하기 전, 딱 3가지만!</h3>
      <div class="tutorial-step"><b>1</b><div><strong>9문항 레벨 테스트</strong><p>기본·핵심·심화 단어가 골고루 나와요.</p></div></div>
      <div class="tutorial-step"><b>2</b><div><strong>틀려도 괜찮아요</strong><p>시험 점수가 아니라 나에게 편한 시작점을 찾는 과정이에요.</p></div></div>
      <div class="tutorial-step"><b>3</b><div><strong>테스트 후 자유롭게 학습</strong><p>아래 메뉴에서 단어 카드·퀴즈·복습을 이용하고 언제든 재시험할 수 있어요.</p></div></div>
      <button class="btn primary full" data-page="placement" style="margin-top:20px">레벨 테스트 시작 →</button>
      <p class="muted" style="text-align:center;margin-bottom:0">약 2분 · 정답을 몰라도 부담 없이 선택하세요.</p>
    </div>`);
}
function menu(){landing();}
$('menuBtn').addEventListener('click',()=>{sound('click');landing();});
/* Placement: 9 meaning-matching questions, 3 per level. */
let P={items:[],index:0,correct:{1:0,2:0,3:0},answered:false};
function placement(){overlayMode='placement';P={items:shuffle([1,2,3].flatMap(l=>choose(WORDS.filter(w=>w.level===l&&w.word.length>2),3))),index:0,correct:{1:0,2:0,3:0},answered:false};renderPlacement();}
function meanings(w){let distractors=choose(WORDS.filter(x=>x.level===w.level&&x.word!==w.word&&x.meaning!==w.meaning),3).map(x=>x.meaning);return shuffle([w.meaning,...distractors]);}
function renderPlacement(){let w=P.items[P.index];if(!w){let score=P.correct;S.level=score[3]>=2?3:score[2]>=2?2:1;S.placed=true;save();sound('finish');showOverlay(`<div class="hero"><h2>테스트 완료! 🎉</h2><p>레벨별 정답: 기본 ${score[1]}/3 · 핵심 ${score[2]}/3 · 심화 ${score[3]}/3</p></div><div class="overlay-box"><h2 style="text-align:center;color:#395ad2">Level ${S.level}에서 시작해요!</h2><p class="muted">원한다면 홈에서 언제든지 다시 테스트할 수 있어요.</p><button class="btn primary full" data-page="home">학습 메뉴로</button></div>`);return;}
P.answered=false;P.options=meanings(w);showOverlay(`<div class="hero" style="margin:12px auto"><h2>나의 단어 레벨 찾기</h2><p>문제 ${P.index+1} / ${P.items.length} · 뜻을 골라 주세요.</p></div><div class="overlay-box"><span class="level-pill level-${w.level}">Level ${w.level}</span><h2 style="color:#263c73;text-align:center;margin:23px 0">${esc(w.word)}</h2><div class="options">${P.options.map((m,i)=>`<button class="option" data-placement="${i}">${esc(m)}</button>`).join('')}</div><div id="placementFeedback" class="muted" style="margin-top:12px" aria-live="polite"></div><button class="btn primary full" id="placementNext" data-page="nextPlacement" style="margin-top:12px" disabled>다음</button></div>`);}
overlay.addEventListener('click',e=>{let b=e.target.closest('[data-page],[data-placement]');if(!b)return;if(b.dataset.placement!==undefined){if(P.answered)return;P.answered=true;let w=P.items[P.index],choice=P.options[+b.dataset.placement],ok=choice===w.meaning;if(ok)P.correct[w.level]++;sound(ok?'correct':'wrong');overlay.querySelectorAll('[data-placement]').forEach(x=>{let v=P.options[+x.dataset.placement];x.disabled=true;if(v===w.meaning)x.classList.add('good');else if(x===b)x.classList.add('bad');});$('placementFeedback').textContent=ok?'정답이에요!':`정답: ${w.meaning}`;$('placementNext').disabled=false;return;}sound('click');let act=b.dataset.page;if(act==='placement')placement();else if(act==='nextPlacement'){P.index++;renderPlacement();}else if(act==='home'||act==='menu')landing();else if(act==='cards'){closeOverlay();setTab(0);}else if(act==='quiz'){closeOverlay();setTab(1);}else if(act==='review'){closeOverlay();setTab(2);}else if(act==='study')closeOverlay();});
/* Three preserved tabs: card, fill in the blank, review. */
const tabs=[$('tab0'),$('tab1'),$('tab2')];let tab=0;
function setTab(i){tab=i;$('track').style.transform=`translateX(${-i*100/3}%)`;$('lens').style.transform=`translateX(${i*100}%)`;tabs.forEach((b,k)=>b.setAttribute('aria-selected',String(i===k)));[$('pane0'),$('pane1'),$('pane2')].forEach((p,k)=>p.inert=k!==i);refresh();}
tabs.forEach((b,i)=>b.addEventListener('click',()=>{sound('click');if(!S.placed){tutorial();return;}if(!overlay.classList.contains('hidden'))closeOverlay();setTab(i);}));
function pool(){return WORDS.filter(w=>w.level===S.level);}
let FC={i:0,flipped:false,items:[],session:[]};
function startCards(word){FC.items=choose(pool(),20);if(word){let w=byWord.get(word);if(w&&!FC.items.some(x=>x.word===word))FC.items.unshift(w);FC.i=FC.items.findIndex(x=>x.word===word);}else FC.i=0;FC.flipped=false;renderCard();}
function formatExample(w){let escaped=esc(w.ex);let token=esc(w.exForm||w.word);if(token){let i=escaped.toLowerCase().indexOf(token.toLowerCase());if(i>=0)escaped=escaped.slice(0,i)+'<mark>'+escaped.slice(i,i+token.length)+'</mark>'+escaped.slice(i+token.length);}return escaped;}
function renderCard(){let w=FC.items[FC.i];if(!w){$('flashBody').innerHTML='<div class="empty surface">이 레벨의 카드가 없어요.</div>';return;}
$('flashBody').innerHTML=`<div class="head-row"><span class="sec-title">Level ${S.level} · 단어 카드</span><button class="small-btn" data-card="shuffle">다른 단어 20개</button></div><div class="study-top"><button class="small-btn" data-card="prev" ${FC.i===0?'disabled':''}>이전</button><span>${FC.i+1} / ${FC.items.length}</span><button class="small-btn" data-card="next">다음</button></div><div class="stage-wrap"><div class="stage"><div class="flashcard ${FC.flipped?'flipped':''}" id="card" tabindex="0" role="button" aria-label="카드 뒤집기"><div class="face front surface"><span class="badge">${LEVELS[w.level].label}</span><div class="word">${esc(w.word)}</div><div class="pos">${esc(w.pos||'Vocabulary')}</div><button class="speak" data-card="speak" aria-label="발음 듣기">🔊</button><div class="hint">카드를 눌러 뜻과 예문 보기</div></div><div class="face back surface"><span class="badge">${LEVELS[w.level].label}</span><div class="meaning">${esc(w.meaning)}</div><div class="sub">${esc(w.word)}</div><div class="label">예문</div><p class="ex">${formatExample(w)}</p>${w.exampleSource==='needs_review'?'<p class="muted">학습용 임시 문장 · 교사 검토 필요</p>':''}${w.family.length?`<div class="label">단어 가족</div><div class="chips">${w.family.map(x=>`<span class="chip">${esc(x.w)}</span>`).join('')}</div>`:''}${w.variation.length?`<div class="label">Variation</div><div class="chips">${w.variation.map(x=>`<span class="chip">${esc(x)}</span>`).join('')}</div>`:''}</div></div></div></div><div class="duo study-actions"><button class="btn glass" data-card="dont">모르겠어요</button><button class="btn primary" data-card="know">알아요</button></div>`;
$('card').addEventListener('click',e=>{if(e.target.closest('[data-card=speak]'))return;FC.flipped=!FC.flipped;$('card').classList.toggle('flipped',FC.flipped);});$('card').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();FC.flipped=!FC.flipped;$('card').classList.toggle('flipped',FC.flipped);}});
}
function nextCard(step=1){FC.i+=step;if(FC.i>=FC.items.length){startCards();return;}FC.i=Math.max(0,FC.i);FC.flipped=false;renderCard();}
function speak(text){try{if(AUDIO[text]){let clip=new Audio(AUDIO[text]);clip.volume=.7;clip.play().catch(()=>speakFallback(text));}else speakFallback(text);}catch(e){speakFallback(text);}}
function speakFallback(text){try{if('speechSynthesis' in window){window.speechSynthesis.cancel();let u=new SpeechSynthesisUtterance(text);u.lang='en-US';u.rate=.88;window.speechSynthesis.speak(u);}}catch(e){}}
function wrong(word,kind,last){let x=S.wrong[word]||{count:0};S.wrong[word]={count:x.count+1,kind,last};save();refreshDot();}
$('flashBody').addEventListener('click',e=>{let b=e.target.closest('[data-card]');if(!b)return;let act=b.dataset.card,w=FC.items[FC.i];sound('click');if(act==='shuffle')startCards();else if(act==='next')nextCard();else if(act==='prev')nextCard(-1);else if(act==='speak')speak(w.word);else if(act==='know'){S.status[w.word]='know';save();nextCard();}else if(act==='dont'){S.status[w.word]='dont';wrong(w.word,'card',w.word);nextCard();}});
/* Fill-in questions: existing 20 keep their sentence and grammar feedback.
   Other words get a blank question and step-by-step hints prepared by app.py (w.blank). */
let Q={view:'intro',items:[],i:0,score:0,answered:false,log:[],used:[]};
function startQuiz(){Q={view:'play',items:choose(pool(),10),i:0,score:0,answered:false,log:[],used:[]};renderQuiz();}
function question(w){if(w.blank)return w.blank;if(originalByWord.has(w.word.toLowerCase()))return w.quiz;return {s:`영어로 쓰세요: ___`,tr:w.meaning,a:[w.word],note:'기본형 철자를 확인해 보세요.'};}
/* The blank shows letter slots once a length/letter hint has been opened. */
function blankPattern(q){let a=String(q.a[0]),u=Q.used;if(!['length','first','last','half'].some(k=>u.includes(k)))return '?';let half=u.includes('half')?Math.ceil(a.length/2):0;return [...a].map((c,i)=>c===' '?' ':(i<half||(i===0&&u.includes('first'))||(i===a.length-1&&u.includes('last')))?c:'_').join(' ');}
function hintCard(h){return `<div class="bq-hint"><span class="bq-hint-icon">${h.icon}</span><div><b>${esc(h.label)}</b>${h.text?`<span>${esc(h.text)}</span>`:''}${h.tiles?`<div class="bq-tiles">${h.tiles.map(t=>`<span>${esc(t)}</span>`).join('')}</div>`:''}${h.say?`<button class="bq-replay" data-hint="${esc(h.id)}">다시 듣기</button>`:''}</div></div>`;}
function renderQuiz(){let body=$('quizBody');if(Q.view==='intro'){body.innerHTML=`<div class="sec-title">Level ${S.level} · 빈칸 퀴즈</div><div class="intro surface"><div class="big">오늘의 10문제</div><p>예문과 뜻을 참고해 정답을 입력하세요.<br>막히면 💡 힌트를 하나씩 열어 보세요.<br>틀린 단어는 자동으로 복습에 모여요.</p><button class="btn primary full" data-quiz="start">퀴즈 시작</button></div>`;return;}
if(Q.view==='done'){body.innerHTML=`<div class="surface result"><div class="score">${Q.score}<span> / ${Q.items.length}</span></div><p>수고했어요! 틀린 문제는 복습 탭에서 다른 유형으로 다시 풀어봐요.</p><button class="btn primary full" data-quiz="start">다시 도전</button><button class="btn full" data-quiz="review">복습으로 이동</button></div>`;return;}
if(!Q.items.length){body.innerHTML=`<div class="sec-title">Level ${S.level} · 빈칸 퀴즈</div><div class="empty surface">이 레벨의 단어를 불러오지 못했어요.<br>voca_3000.csv 파일이 저장소에 있는지 확인해 주세요.</div>`;return;}
let w=Q.items[Q.i],q=question(w),hints=q.hints||[],blank=`<span class="bq-blank" id="blank">${esc(blankPattern(q))}</span>`;
let prompt=q.kind==='meaning'?`<div class="bq-meaning">${esc(q.tr)}</div><div class="bq-sentence bq-solo">${blank}</div>`:`<div class="bq-sentence">${esc(q.s).replace('___',blank)}</div><p class="bq-trans">${esc(q.tr)}</p>`;
body.innerHTML=`<div class="bq-top"><span class="sec-title">Level ${S.level} · 빈칸 퀴즈</span><button class="bq-quit" data-quiz="quit">그만하기</button></div>
<div class="bq-progress"><div class="bq-track"><i style="width:${Q.i/Q.items.length*100}%"></i></div><span>${Q.i+1}<small> / ${Q.items.length}</small></span></div>
<div class="bq-card surface"><span class="bq-kind">${q.kind==='meaning'?'뜻 보고 쓰기':'문장 빈칸'}</span>${prompt}
<div class="bq-answer"><input id="ans" class="bq-input" autocorrect="off" autocapitalize="off" spellcheck="false" autocomplete="off" placeholder="빈칸에 들어갈 단어"><button id="checkBtn" class="btn primary bq-check" data-quiz="check">확인</button></div><div id="fb" class="feedback" aria-live="polite"></div>
${hints.length?`<div class="bq-hints"><div class="bq-hints-head"><b>💡 힌트</b><span id="hintCount">${Q.used.length} / ${hints.length} 사용</span></div><div class="bq-chips">${hints.map(h=>`<button class="bq-chip ${Q.used.includes(h.id)?'on':''}" data-hint="${esc(h.id)}">${h.icon} ${esc(h.label)}</button>`).join('')}</div><div class="bq-revealed" id="hintList">${hints.filter(h=>Q.used.includes(h.id)).map(hintCard).join('')}</div></div>`:''}</div>`;
$('ans').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();if(Q.answered)advanceQuiz();else checkQuiz();}});
}
function useHint(id){let q=question(Q.items[Q.i]),h=(q.hints||[]).find(x=>x.id===id);if(!h)return;if(h.say)speak(h.say);if(Q.used.includes(id)||Q.answered)return;sound('click');Q.used.push(id);
document.querySelectorAll('.bq-chip').forEach(c=>c.classList.toggle('on',Q.used.includes(c.dataset.hint)));$('hintList').insertAdjacentHTML('beforeend',hintCard(h));$('hintCount').textContent=`${Q.used.length} / ${q.hints.length} 사용`;$('blank').textContent=blankPattern(q);}
function checkQuiz(){if(Q.answered)return;let w=Q.items[Q.i],q=question(w),input=$('ans'),v=input.value.trim();if(!v){input.focus();return;}let ok=q.a.map(norm).includes(norm(v));Q.answered=true;Q.log.push({word:w.word,ok});S.solved++;if(ok){Q.score++;S.correct++;sound('correct');}else{wrong(w.word,'blank',v);sound('wrong');input.classList.add('shake');}save();input.classList.add(ok?'good':'bad');$('fb').className='feedback '+(ok?'good':'bad')+' show';$('fb').innerHTML=`<div class="fb-title">${ok?'정답이에요!':'괜찮아요. 다시 기억해 봐요.'}</div><div class="fb-note">정답: <b>${esc(q.a.join(' / '))}</b><br>${esc(q.note)}${Q.used.length?`<br><span class="bq-used">💡 힌트 ${Q.used.length}개 사용</span>`:''}</div>`;$('blank').textContent=q.a[0];$('blank').classList.add(ok?'good':'bad');document.querySelectorAll('.bq-chip').forEach(c=>c.disabled=true);$('ans').disabled=true;$('checkBtn').dataset.quiz='next';$('checkBtn').textContent=Q.i===Q.items.length-1?'결과 보기':'다음';}
function advanceQuiz(){if(Q.i===Q.items.length-1){Q.view='done';addStudyDay();}else{Q.i++;Q.answered=false;Q.used=[];}renderQuiz();}
$('quizBody').addEventListener('click',e=>{let h=e.target.closest('[data-hint]');if(h){useHint(h.dataset.hint);return;}let b=e.target.closest('[data-quiz]');if(!b)return;let a=b.dataset.quiz;if(a==='start'){sound('click');startQuiz();}else if(a==='check')checkQuiz();else if(a==='next')advanceQuiz();else if(a==='quit'){Q.view='intro';renderQuiz();}else if(a==='review')setTab(2);});
/* Review switches question type: blank -> multiple choice; card -> spelling. */
let R={word:null,answers:[],answered:false};
function refreshDot(){let n=Object.keys(S.wrong).length;$('reviewDot').textContent=n;$('reviewDot').classList.toggle('on',n>0);}
function renderReview(){let keys=Object.keys(S.wrong).filter(w=>byWord.has(w)),rate=S.solved?Math.round(S.correct/S.solved*100)+'%':'-';$('reviewBody').innerHTML=`<div class="sec-title">나만의 복습 목록</div><div class="stats glass"><div><b>${S.solved}</b><span>푼 문제</span></div><div><b>${rate}</b><span>정답률</span></div><div><b>${keys.length}</b><span>복습 단어</span></div></div><p class="muted">복습 문제를 맞히면 목록에서 사라져요. 정답은 문제를 푼 뒤에 보여 줘요.</p>${keys.length?`<div class="list">${keys.slice(0,100).map(key=>{let w=byWord.get(key);return `<button class="item surface" data-review="${esc(key)}"><div>${retryMode(key)==='choice'?`<div class="w">${esc(w.word)} <small>Level ${w.level}</small></div><div class="m">뜻 고르기 문제</div>`:`<div class="w">${esc(w.meaning)} <small>Level ${w.level}</small></div><div class="m">영어 철자 쓰기 문제</div>`}</div><span class="count">×${S.wrong[key].count}</span></button>`;}).join('')}</div>`:'<div class="empty surface">아직 복습 단어가 없어요. 👍</div>'}${keys.length>100?'<p class="muted">먼저 100개를 보여주고 있어요.</p>':''}`;}
/* The list only shows the question side, so the answer is never visible before solving. */
function retryMode(word){return S.wrong[word]?.kind==='blank'?'choice':'spelling';}
function openRetry(word){let w=byWord.get(word);if(!w)return;R={word,answered:false,mode:retryMode(word),answers:[]};if(R.mode==='choice'){R.answers=shuffle([w.meaning,...choose(WORDS.filter(x=>x.word!==word&&x.level===w.level&&x.meaning!==w.meaning),3).map(x=>x.meaning)]);}renderRetry();}
function renderRetry(){let w=byWord.get(R.word);$('reviewBody').innerHTML=`<div class="head-row"><button class="small-btn" data-ract="back">← 복습 목록</button><span class="level-pill level-${w.level}">Level ${w.level}</span></div><div class="surface q-card"><h3>${R.mode==='choice'?'뜻을 골라보세요':'영어 단어를 써보세요'}</h3><div class="q-sentence">${R.mode==='choice'?esc(w.word):esc(w.meaning)}</div>${R.mode==='choice'?`<div class="options">${R.answers.map((x,i)=>`<button class="option" data-retry="${i}">${esc(x)}</button>`).join('')}</div>`:'<div class="answer-row"><input id="retryInput" class="input" placeholder="영어 철자"><button class="btn primary" data-ract="check">확인</button></div>'}<div id="retryFb" class="feedback" aria-live="polite"></div></div>`;if(R.mode==='spelling')$('retryInput').addEventListener('keydown',e=>{if(e.key==='Enter')checkRetry($('retryInput').value);});}
function checkRetry(value){if(R.answered)return;if(!String(value).trim())return;let w=byWord.get(R.word);let ok=R.mode==='choice'?value===w.meaning:[w.word,...(w.variation||[])].map(norm).includes(norm(value));R.answered=true;S.solved++;if(ok){S.correct++;delete S.wrong[w.word];sound('correct');}else{wrong(w.word,R.mode==='choice'?'choice':'blank',value);sound('wrong');}save();refreshDot();$('retryFb').className='feedback '+(ok?'good':'bad')+' show';$('retryFb').innerHTML=`<div class="fb-title">${ok?'맞혔어요! 복습 목록에서 뺐어요.':'아직 연습 중이에요. 다음에도 나올 거예요.'}</div><div class="fb-note">${esc(w.word)} — ${esc(w.meaning)}<br>${esc(w.ex)}</div><button class="btn primary full" data-ract="back" style="margin-top:12px">복습 목록으로</button>`;document.querySelectorAll('[data-retry]').forEach(x=>x.disabled=true);if($('retryInput'))$('retryInput').disabled=true;}
$('reviewBody').addEventListener('click',e=>{let b=e.target.closest('[data-review],[data-retry],[data-ract]');if(!b)return;if(b.dataset.review){openRetry(b.dataset.review);return;}if(b.dataset.retry!==undefined)checkRetry(R.answers[+b.dataset.retry]);if(b.dataset.ract==='back')renderReview();if(b.dataset.ract==='check')checkRetry($('retryInput').value);});
function refresh(){$('levelText').textContent=`Level ${S.level} · ${pool().length}개 단어`;if(!FC.items.length||!FC.items.some(w=>w.level===S.level))startCards();else renderCard();if(Q.view!=='play')renderQuiz();renderReview();refreshDot();}
refresh();setTab(0);if(S.placed)landing();else tutorial();
</script>
</body>
</html>
'''


components.html(build_page(), height=APP_HEIGHT, scrolling=False)
