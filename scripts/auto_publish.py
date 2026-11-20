#!/usr/bin/env python3
"""Generate, independently review, and publish Arabic encyclopedia articles."""
import os, re, json, html, time, unicodedata, datetime, pathlib, sys, socket, ipaddress
from urllib.parse import urlparse, urljoin
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://smart-info-encyclopedia-site.pages.dev"
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = "gemini-3.5-flash-lite"
API = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
CATEGORIES = {
 "tech": ("التقنية والذكاء الاصطناعي", "Technology & AI", "🤖"),
 "cars": ("السيارات والنقل", "Cars & Transport", "🚗"),
 "money": ("المال والاقتصاد", "Money & Economy", "📊"),
 "science": ("العلوم والمعرفة", "Science & Knowledge", "🔬"),
 "travel": ("السفر والجغرافيا", "Travel & Geography", "🧭"),
 "life": ("الحياة اليومية", "Everyday Life", "💡"),
 "apps": ("التطبيقات والخدمات", "Apps & Services", "📱"),
}
TODAY = datetime.date.today().isoformat()

def norm(s):
 s = unicodedata.normalize("NFKD", str(s or "")).lower()
 s = "".join(c for c in s if not unicodedata.combining(c))
 s = re.sub(r"[أإآٱ]", "ا", s)
 s = re.sub(r"[\W_]+", "", s, flags=re.UNICODE)
 return s

def gemini(prompt, temperature=0.55):
 if not API_KEY:
  raise RuntimeError("Missing GEMINI_API_KEY repository secret")
 payload = {"contents":[{"role":"user","parts":[{"text":prompt}]}],
            "generationConfig":{"temperature":temperature,"responseMimeType":"application/json","maxOutputTokens":8192}}
 last = None
 for attempt in range(5):
  try:
   r = requests.post(API, headers={"x-goog-api-key": API_KEY}, json=payload, timeout=120)
   if r.status_code in (429, 500, 502, 503, 504):
    last = f"Gemini HTTP {r.status_code}: {r.text[:300]}"
    retry_after = r.headers.get("Retry-After", "")
    try:
     delay = min(45, max(5, int(retry_after)))
    except (TypeError, ValueError):
     delay = min(40, 5 * (2 ** attempt))
    print(f"Gemini temporarily unavailable (HTTP {r.status_code}); retry {attempt + 1}/5 in {delay}s.")
    time.sleep(delay)
    continue
   r.raise_for_status()
   response = r.json()
   candidates = response.get("candidates") or []
   parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
   generated = next((part.get("text") for part in parts if isinstance(part,dict) and part.get("text")), "")
   if not generated:
    finish = candidates[0].get("finishReason", "no candidate") if candidates else "no candidate"
    raise ValueError(f"Gemini returned no text content (finishReason={finish})")
   generated = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", generated).strip()
   try:
    parsed = json.loads(generated)
   except json.JSONDecodeError:
    start = generated.find("{")
    end = generated.rfind("}")
    if start < 0 or end <= start:
     raise ValueError("Gemini response did not contain a JSON object")
    parsed = json.loads(generated[start:end + 1])
   if isinstance(parsed, list):
    if len(parsed) == 1 and isinstance(parsed[0], dict):
     parsed = parsed[0]
    elif parsed and all(isinstance(item,dict) and "url" in item for item in parsed):
     parsed = {"sources": parsed}
   if not isinstance(parsed, dict):
    raise ValueError(f"Gemini response must be a JSON object (received {type(parsed).__name__})")
   return parsed
  except (requests.Timeout, requests.ConnectionError) as exc:
   last = f"Gemini network error: {type(exc).__name__}"
   delay = min(40, 5 * (2 ** attempt))
   print(f"{last}; retry {attempt + 1}/5 in {delay}s.")
   time.sleep(delay)
 raise RuntimeError(last or "Gemini request failed after retries")

def load_existing():
 index = (ROOT / "index.html").read_text(encoding="utf-8")
 sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
 slugs = set(re.findall(r'(?:"slug"|slug)\s*:\s*"([a-z0-9-]+)"', index))
 titles = set()
 for t in re.findall(r'(?:"ar"|ar)\s*:\s*("(?:\\.|[^"\\])*")', index):
  try: titles.add(norm(json.loads(t)))
  except Exception: titles.add(norm(t))
 return index, sitemap, slugs, titles

def make_topic(existing_titles, existing_slugs, used_topics):
 cats = ", ".join(f"{k}: {v[0]}" for k,v in CATEGORIES.items())
 return gemini(f"""
أنت محرر موسوعة عربية عامة. اقترح موضوع مقال واحد جديد ومحدد ومفيد وغير مكرر.
التصنيفات المتاحة: {cats}
عناوين منشورة سابقاً (تجنبها والموضوعات القريبة جداً منها): {list(existing_titles)[:220]}
الموضوعات المستخدمة في هذه الدفعة: {used_topics}
أعد JSON فقط بالمفاتيح: topic, category.
category يجب أن تكون واحداً من: {list(CATEGORIES)}.
اجعل الموضوع غير حساس وغير طبي/قانوني/استثماري توجيهي، ولا تختر أخباراً أو أسعاراً متغيرة.
""")

def generate_article(topic, category):
 cat_ar, cat_en, icon = CATEGORIES[category]
 data = gemini(f"""
اكتب مقالاً تعليمياً أصلياً ومفيداً لموسوعة المعلومة الذكية باللغة العربية أولاً، مع نسخة إنجليزية موجزة دقيقة.
الموضوع: {topic}
التصنيف: {cat_ar}
أعد JSON فقط بالمفاتيح التالية:
slug (إنجليزي kebab-case قصير، 3-7 كلمات، فريد)،
title_ar (عنوان عربي واضح)، title_en،
description_ar (وصف 120-160 حرفاً تقريباً)، description_en،
sections (مصفوفة من 5 إلى 8 عناصر، لكل عنصر heading_ar و paragraphs_ar كمصفوفة من 1-3 فقرات)،
summary_en (فقرتان موجزتان باللغة الإنجليزية)،
sources (مصفوفة من 3 إلى 5 مصادر أصلية موثوقة، لكل مصدر title و url).
المقال العربي يجب أن يكون بين 700 و1000 كلمة فعلية، ولا يقل مطلقاً عن 600 كلمة. اكتب 6 إلى 8 أقسام، وفي كل قسم فقرتان شارحتان على الأقل، مع مقدمة وخطوات أو أمثلة وأسئلة شائعة عند ملاءمة الموضوع.
خصص مساحة كافية للشرح ولا تختصر الإجابة في تعريفات عامة. لا تخترع أرقاماً أو دراسات أو اقتباسات. اعتمد على 5 مصادر رسمية/أكاديمية/معايير معروفة ذات صلة مباشرة، بروابط صفحات محددة لا صفحات رئيسية عامة. لا تضع روابط تتوقع أنها غير موجودة ولا تكرر النطاق نفسه أكثر من مرتين. لا تستخدم نصاً تسويقياً ولا تدعِ أن المقال تمت مراجعته بشرياً.
اكتب بصياغة طبيعية غير مكررة، وابتعد عن النصائح الطبية أو القانونية أو المالية الشخصية.
""")
 def count_words(item):
  return len(" ".join(str(p) for sec in item.get("sections",[]) if isinstance(sec,dict) for p in (sec.get("paragraphs_ar",[]) if isinstance(sec.get("paragraphs_ar",[]),list) else [])).split())
 if count_words(data) < 600:
  print(f"Generated article is short ({count_words(data)} words); requesting an expansion.")
  expanded = gemini(f"""
وسّع المقال التالي دون تغيير موضوعه أو عنوانه أو رابطه أو مصادره.
المطلوب: نص عربي أصلي لا يقل عن 700 كلمة فعلية، موزع على 6 إلى 8 أقسام واضحة. أعد كائن JSON واحداً فقط وليس مصفوفة، ولا تضع أي شرح خارج JSON.
أضف شرحاً عملياً وأمثلة مفيدة وتفاصيل دقيقة، ولا تكرر الأفكار ولا تخترع معلومات أو مصادر.
احتفظ بنفس مفاتيح JSON وبنية sections و paragraphs_ar. أعد JSON كاملاً فقط.
المقال الحالي: {json.dumps(data,ensure_ascii=False)}
""", temperature=0.35)
  if isinstance(expanded, dict) and isinstance(expanded.get("sections"), list):
   for key in ("slug","title_ar","title_en","description_ar","description_en","sources","summary_en"):
    if key not in expanded and key in data: expanded[key] = data[key]
   data = expanded
 if not isinstance(data.get("sections"), list) or not 5 <= len(data["sections"]) <= 8:
  raise ValueError("Article must contain 5 to 8 sections")
 if count_words(data) < 600:
  raise ValueError(f"Article is too short after expansion ({count_words(data)} words; minimum 600)")
 for sec in data["sections"]:
  if not isinstance(sec,dict) or not str(sec.get("heading_ar","")).strip():
   raise ValueError("Article section is missing its heading")
  paragraphs=sec.get("paragraphs_ar")
  if not isinstance(paragraphs,list) or not paragraphs or any(not isinstance(p,str) or len(p.strip()) < 40 for p in paragraphs):
   raise ValueError("Article section has missing or very short paragraphs")
 for field in ("title_ar","title_en","description_ar","description_en"):
  if not isinstance(data.get(field),str) or not data[field].strip():
   raise ValueError(f"Missing required article field: {field}")
 if not 70 <= len(data["description_ar"]) <= 200:
  raise ValueError("Arabic description length must be between 70 and 200 characters")
 slug = data.get("slug","")
 if not isinstance(slug,str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2,6}",slug.lower()):
  raise ValueError("Invalid slug; expected 3 to 7 lowercase English words")
 slug = slug.lower()
 data["slug"] = slug
 data["category"] = category
 data["icon"] = icon
 data["category_ar"] = cat_ar
 data["category_en"] = cat_en
 return data

def is_public_https_url(url):
 try:
  parsed = urlparse(url)
  if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
   return False
  if parsed.port not in (None, 443):
   return False
  host = parsed.hostname.rstrip(".").lower()
  if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
   return False
  addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
  return bool(addresses) and all(ipaddress.ip_address(addr).is_global for addr in addresses)
 except (ValueError, OSError):
  return False

def verify_sources(sources):
 if not isinstance(sources, list) or len(sources) < 3:
  return False, [], "Need at least 3 candidate sources"
 good=[]
 failures=[]
 headers={"User-Agent":"Mozilla/5.0 (compatible; SmartInfoEditorialBot/1.0; +https://smart-info-encyclopedia-site.pages.dev)"}
 for src in sources[:6]:
  if not isinstance(src, dict): continue
  url=str(src.get("url","")).strip()
  if not is_public_https_url(url):
   failures.append("blocked unsafe or non-HTTPS source URL")
   continue
  try:
   current=url
   response=None
   for _ in range(6):
    if not is_public_https_url(current):
     raise ValueError("redirect target is not a public HTTPS URL")
    response=requests.get(current, timeout=15, headers=headers, allow_redirects=False, stream=True)
    if response.is_redirect or response.is_permanent_redirect:
     target=urljoin(current, response.headers.get("Location", ""))
     response.close()
     current=target
     continue
    break
   if response is None:
    raise ValueError("source request did not complete")
   if response.is_redirect or response.is_permanent_redirect:
    response.close()
    raise ValueError("source exceeded redirect limit")
   status=response.status_code
   final_url=current
   response.close()
   if status < 400:
    good.append({"title":str(src.get("title") or "Source"),"url":final_url})
   else:
    failures.append(f"{url} returned HTTP {status}")
  except (requests.RequestException, ValueError) as exc:
   if response is not None:
    response.close()
   failures.append(f"{url}: {type(exc).__name__}")
 if len(good) >= 3:
  return True, good[:5], ""
 return False, good, f"Only {len(good)} sources could be opened; need at least 3. " + "; ".join(failures[:3])

def repair_sources(article, source_error):
 failed = article.get("sources", [])
 for attempt in range(3):
  replacement = gemini(f"""
أنت مساعد بحث للمراجع. نحتاج خمسة مصادر بديلة حقيقية ومباشرة لمقال موسوعي عربي.
الموضوع: {article.get("title_ar")}
ملخص المقال: {json.dumps(article.get("sections", [])[:3], ensure_ascii=False)[:3500]}
روابط سبق اقتراحها ولا نريد تكرارها: {json.dumps(failed, ensure_ascii=False)}
نتيجة فحص الروابط: {source_error}
في هذه المحاولة رقم {attempt + 1}: اقترح خمسة روابط مختلفة تماماً قدر الإمكان، من صفحات محددة في مواقع حكومية أو جامعات أو منظمات معيارية معروفة، وتأكد من كتابة المسار الكامل للصفحة لا اسم النطاق فقط.
لا تستخدم أي رابط من القائمة السابقة ولا تخترع عناوين أو مسارات تخمينية. إذا لم تكن واثقاً من وجود الرابط فلا تضعه.
أعد JSON فقط بالشكل: {{"sources":[{{"title":"اسم الصفحة","url":"https://..."}}]}}
""", temperature=0.1)
  proposed = replacement.get("sources", []) if isinstance(replacement, dict) else []
  if proposed:
   ok, checked, err = verify_sources(proposed)
   if ok:
    return checked
   source_error = err
   failed.extend(proposed)
 return []

def editorial_review(article, sources):
 for round_no in range(3):
  result=gemini(f"""
أنت مراجع تحريري مستقل. قيّم المقال التالي قبل النشر.
تحقق من: الدقة العامة، وضوح الشرح، التكرار، سلامة اللغة، العنوان والوصف، وعدم وجود ادعاءات رقمية/علمية غير مسندة أو نصائح عالية المخاطر.
روابط المصادر التي أمكن فتحها فعلياً: {json.dumps(sources,ensure_ascii=False)}
المقال: {json.dumps(article,ensure_ascii=False)}
أعد JSON فقط: approved (true/false), score (0-100), reasons (مصفوفة قصيرة), corrections (مصفوفة تعديلات محددة).
إذا وجدت تعديلات لغوية أو تنظيمية أو توضيحات ضرورية، اذكرها بوضوح في corrections ولا تكتفِ برفض المقال. لا توافق لمجرد أن النص منظم.
""", temperature=0.1)
  try:
   score = int(result.get("score",0))
  except (TypeError, ValueError):
   score = 0
  corrections = result.get("corrections", [])
  reasons = result.get("reasons", [])
  if not isinstance(corrections,list) or not isinstance(reasons,list):
   print("Rejected: invalid editorial review format:", result)
   return False
  if result.get("approved") is True and score >= 90 and not corrections:
   return True
  if round_no == 2 or not corrections:
   print("Rejected by editorial review:", result)
   return False
  print(f"Applying editorial corrections and requesting review round {round_no + 2}/3.")
  revised=gemini(f"""
أنت محرر عربي. نفّذ التعديلات المحددة أدناه على المقال، ثم أعد المقال كاملاً ككائن JSON فقط.
التعديلات المطلوبة من المراجع: {json.dumps(corrections,ensure_ascii=False)}
حافظ على الموضوع والعنوان والرابط والمصادر والتصنيف، ولا تضف ادعاءات أو أرقاماً أو مراجع جديدة.
حافظ على 5 إلى 8 أقسام، وعلى 600 كلمة عربية على الأقل، وعلى مفاتيح JSON وبنية الأقسام الأصلية.
المقال الحالي: {json.dumps(article,ensure_ascii=False)}
""", temperature=0.2)
  if not isinstance(revised,dict):
   print("Editorial correction response was not a JSON object.")
   return False
  for key in ("slug","title_ar","title_en","description_ar","description_en","sources","summary_en","category","icon","category_ar","category_en"):
   if key not in revised and key in article:
    revised[key]=article[key]
  sections=revised.get("sections")
  if not isinstance(sections,list) or not 5 <= len(sections) <= 8:
   print("Editorial correction produced invalid section count.")
   return False
  word_count=len(" ".join(str(p) for sec in sections if isinstance(sec,dict) for p in (sec.get("paragraphs_ar",[]) if isinstance(sec.get("paragraphs_ar",[]),list) else [])).split())
  if word_count < 600:
   print(f"Editorial correction left article too short ({word_count} words).")
   return False
  article.clear()
  article.update(revised)
 return False

def build_html(a, sources):
 title=html.escape(a["title_ar"])
 desc=html.escape(a["description_ar"])
 slug=a["slug"]
 canonical=f"{BASE}/articles/{slug}.html"
 sections=[]
 for i,sec in enumerate(a["sections"],1):
  heading=html.escape(sec.get("heading_ar",""))
  paras="".join(f"<p>{html.escape(p)}</p>" for p in sec.get("paragraphs_ar",[]) if p.strip())
  sections.append(f'<section class="article-section"><h2>{heading}</h2>{paras}</section>')
 body="\n".join(sections)
 refs="".join(f'<li><a href="{html.escape(s["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(s["title"])}</a></li>' for s in sources)
 en=html.escape(a.get("summary_en",""))
 schema={"@context":"https://schema.org","@type":"Article","headline":a["title_ar"],"description":a["description_ar"],"datePublished":TODAY,"dateModified":TODAY,"mainEntityOfPage":{"@type":"WebPage","@id":canonical},"author":{"@type":"Organization","name":"المعلومة الذكية"},"publisher":{"@type":"Organization","name":"المعلومة الذكية"},"inLanguage":"ar"}
 return f'''<!doctype html>
<html lang="ar" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-KQ2NGJXXKC"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-KQ2NGJXXKC');
</script>

<title>{title} | المعلومة الذكية</title><meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}"><meta name="robots" content="index,follow,max-image-preview:large">
<meta property="og:type" content="article"><meta property="og:title" content="{title} | المعلومة الذكية"><meta property="og:description" content="{desc}"><meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="{title}"><meta name="twitter:description" content="{desc}">
<link rel="icon" href="../favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="../assets/brand.css">
<script type="application/ld+json">{json.dumps(schema,ensure_ascii=False)}</script>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2953917327439885" crossorigin="anonymous"></script>
</head><body><div class="reading-progress" aria-hidden="true"><span id="readingProgressBar"></span></div><header class="top"><div class="nav"><a href="../index.html">المعلومة الذكية</a><a href="../index.html">العودة إلى الموسوعة</a></div></header>
<main class="wrap"><p class="crumb"><a href="../index.html">الرئيسية</a> / {html.escape(a["category_ar"])}</p>
<article class="article"><div class="icon">{a["icon"]}</div><div class="category">{html.escape(a["category_ar"])}</div>
<h1>{title}</h1><p class="desc">{desc}</p><div class="reading-meta" aria-live="polite"><strong id="readingTime">وقت القراءة: —</strong><span aria-hidden="true">•</span><span>مقال تعليمي</span></div><div class="body" id="articleContent">{body}</div>
<section class="references"><strong>المصادر والمراجع</strong><ol>{refs}</ol></section>
<div class="note">محتوى تعليمي عام. راجع المصادر الأصلية، وتحقق من المعلومات المتغيرة قبل اتخاذ القرارات.</div>
</article></main><footer class="footer"><a href="../index.html">العودة إلى الموسوعة</a> · <a href="../about.html">من نحن</a> · <a href="../privacy.html">سياسة الخصوصية</a> · <a href="../editorial-policy.html">معايير المحتوى</a> · <a href="../contact.html">اتصل بنا</a></footer>
<script>
(function(){{
 const content=document.getElementById("articleContent");
 const time=document.getElementById("readingTime");
 const bar=document.getElementById("readingProgressBar");
 if(content&&time){{
  const words=(content.innerText||content.textContent||"").trim().split(/\\s+/).filter(Boolean).length;
  const minutes=Math.max(1,Math.ceil(words/200));
  time.textContent="وقت القراءة: "+minutes+" دقائق تقريباً";
 }}
 function updateProgress(){{
  if(!bar)return;
  const max=document.documentElement.scrollHeight-window.innerHeight;
  const progress=max>0?Math.min(100,Math.max(0,(window.scrollY/max)*100)):0;
  bar.style.width=progress+"%";
 }}
 window.addEventListener("scroll",updateProgress,{{passive:true}});
 window.addEventListener("resize",updateProgress);
 updateProgress();
}})();
</script></body></html>'''

def install_analytics_on_existing_articles():
 tag = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-KQ2NGJXXKC"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-KQ2NGJXXKC');
</script>
"""
 changed = 0
 for path in (ROOT / "articles").glob("*.html"):
  page = path.read_text(encoding="utf-8")
  if "G-KQ2NGJXXKC" in page: continue
  marker = '<meta charset="utf-8">'
  if marker not in page: continue
  path.write_text(page.replace(marker, marker + "\n" + tag, 1), encoding="utf-8")
  changed += 1
 print(f"Added Google Analytics to {changed} existing article pages.")

def main():
 install_analytics_on_existing_articles()
 if not API_KEY: raise SystemExit("GEMINI_API_KEY is not configured in repository secrets.")
 index,sitemap,slugs,titles=load_existing()
 raw_count = str(os.getenv("ARTICLE_COUNT","3") or "3").strip()
 count_match = re.search(r"\d+", raw_count)
 if not count_match:
  raise SystemExit(f"Invalid ARTICLE_COUNT value: {raw_count!r}. Use 1, 2, or 3.")
 count = max(1, min(3, int(count_match.group(0))))
 if raw_count != count_match.group(0):
  print(f"ARTICLE_COUNT input {raw_count!r} normalized to {count}.")
 used=[]
 published=0
 max_attempts = min(12, count * 4)
 for n in range(max_attempts):
  if published >= count:
   break
  try:
   topic_data=make_topic(titles,slugs,used)
   topic=str(topic_data.get("topic","")).strip()
   category=topic_data.get("category")
   if not topic or category not in CATEGORIES: raise ValueError("Invalid topic/category")
   article=generate_article(topic,category)
   slug=article["slug"]
   if slug in slugs or norm(article["title_ar"]) in titles: raise ValueError("Duplicate slug/title")
   if (ROOT/"articles"/f"{slug}.html").exists(): raise ValueError("Article file already exists")
   ok, sources, source_error=verify_sources(article.get("sources",[]))
   if not ok:
    print("Repairing source links:", source_error)
    sources = repair_sources(article, source_error)
   if len(sources) < 3: raise ValueError(f"Could not verify 3 reliable sources: {source_error}")
   if not editorial_review(article,sources): raise ValueError("Editorial review did not approve")
   # The homepage data model is intentionally bilingual and uses plain text for bodyAr.
   post={"cat":category,"slug":slug,"icon":article["icon"],"ar":article["title_ar"],"en":article.get("title_en",article["title_ar"]),"descAr":article["description_ar"],"descEn":article.get("description_en",article["description_ar"]),"bodyAr":"\n\n".join(sec.get("heading_ar","")+"\n"+"\n".join(sec.get("paragraphs_ar",[])) for sec in article["sections"]),"bodyEn":article.get("summary_en","")}
   safe_post_json=json.dumps(post,ensure_ascii=False,separators=(",",":")).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
   index=index.replace("const posts=[","const posts=[\n"+safe_post_json+",",1)
   (ROOT/"articles"/f"{slug}.html").write_text(build_html(article,sources),encoding="utf-8")
   loc=f"{BASE}/articles/{slug}.html"
   if loc not in sitemap:
    entry=f'  <url><loc>{loc}</loc><lastmod>{TODAY}</lastmod></url>\n'
    sitemap=sitemap.replace("</urlset>",entry+"</urlset>")
   slugs.add(slug); titles.add(norm(article["title_ar"])); used.append(topic); published+=1
   print(f"Published candidate {published}: {slug}")
  except Exception as exc:
   print(f"Article attempt {n+1} skipped: {exc}")
   continue
 if published:
  (ROOT/"index.html").write_text(index,encoding="utf-8")
  (ROOT/"sitemap.xml").write_text(sitemap,encoding="utf-8")
 print(f"Finished. Published {published} of {count} requested after {n + 1 if 'n' in locals() else 0} attempts.")
 if published == 0: print("No changes made; inspect workflow logs for rejection reasons.")

if __name__=="__main__":
 main()
