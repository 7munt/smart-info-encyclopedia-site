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

class GeminiQuotaError(RuntimeError):
 pass

_LAST_GEMINI_REQUEST_AT = 0.0
_GEMINI_MIN_REQUEST_INTERVAL = 8.0

def gemini(prompt, temperature=0.55, grounded_search=False):
 if not API_KEY:
  raise RuntimeError("Missing GEMINI_API_KEY repository secret")
 payload = {"contents":[{"role":"user","parts":[{"text":prompt}]}],
            "generationConfig":{"temperature":temperature,"responseMimeType":"application/json","maxOutputTokens":8192}}
 if grounded_search:
  payload["tools"] = [{"googleSearch": {}}]
  payload["generationConfig"].pop("responseMimeType", None)
 last = None
 for attempt in range(5):
  try:
   global _LAST_GEMINI_REQUEST_AT
   elapsed = time.monotonic() - _LAST_GEMINI_REQUEST_AT
   if elapsed < _GEMINI_MIN_REQUEST_INTERVAL:
    time.sleep(_GEMINI_MIN_REQUEST_INTERVAL - elapsed)
   r = requests.post(API, headers={"x-goog-api-key": API_KEY}, json=payload, timeout=120)
   _LAST_GEMINI_REQUEST_AT = time.monotonic()
   if r.status_code == 429:
    last = f"Gemini HTTP 429: {r.text[:300]}"
    retry_after = r.headers.get("Retry-After", "")
    try:
     delay = min(90, max(60, int(retry_after)))
    except (TypeError, ValueError):
     delay = 60
    if "exceeded your current quota" in r.text.lower() or "resource_exhausted" in r.text.lower():
     print("Gemini returned HTTP 429. Waiting 60 seconds before one controlled retry; if quota remains exhausted, the run will stop.")
    else:
     print(f"Gemini rate limit reached; retry {attempt + 1}/5 in {delay}s.")
    if attempt >= 1 and ("exceeded your current quota" in r.text.lower() or "resource_exhausted" in r.text.lower()):
     raise GeminiQuotaError("Gemini API returned 429 repeatedly. Check the free-tier RPM limit and project quota in AI Studio.")
    time.sleep(delay)
    continue
   if r.status_code in (500, 502, 503, 504):
    last = f"Gemini HTTP {r.status_code}: {r.text[:300]}"
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
    parsed = json.loads(generated, strict=False)
   except json.JSONDecodeError:
    start = generated.find("{")
    end = generated.rfind("}")
    if start < 0 or end <= start:
     raise ValueError("Gemini response did not contain a JSON object")
    parsed = json.loads(generated[start:end + 1], strict=False)
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
 # Topic selection is local and consumes no Gemini API request.
 candidates = [
  ("كيف تعمل تقنية eSIM وما الذي يميزها عن شرائح الاتصال التقليدية؟", "tech"),
  ("كيف تحمي حساباتك الرقمية باستخدام مفاتيح المرور Passkeys؟", "apps"),
  ("ما الفرق بين التخزين السحابي والنسخ الاحتياطي؟", "tech"),
  ("كيف تقرأ ملصق كفاءة الطاقة على الأجهزة المنزلية؟", "life"),
  ("كيف تعمل أنظمة الملاحة عبر الأقمار الصناعية؟", "science"),
  ("ما الذي يجب فحصه قبل شراء سيارة مستعملة؟", "cars"),
  ("كيف تخطط لرحلة متعددة الوجهات بميزانية واضحة؟", "travel"),
  ("كيف تميز بين سعر الفائدة السنوي ومعدل النسبة السنوي؟", "money"),
  ("كيف تنظّم كلمات المرور بأمان دون إعادة استخدامها؟", "apps"),
  ("كيف تعمل البطاريات القابلة لإعادة الشحن؟", "science"),
  ("ما الفرق بين Wi-Fi 6 وWi-Fi 7؟", "tech"),
  ("كيف تقلل استهلاك الوقود أثناء القيادة؟", "cars"),
  ("كيف تختار جهاز راوتر مناسباً للمنزل؟", "tech"),
  ("ما خطوات حماية الهاتف عند فقدانه أو سرقته؟", "apps"),
  ("كيف تقارن بين الشاشات من حيث الدقة ومعدل التحديث؟", "tech"),
  ("كيف تعمل الألواح الشمسية وتحوّل ضوء الشمس إلى كهرباء؟", "science"),
  ("كيف تختار الثلاجة وفق السعة واستهلاك الطاقة؟", "life"),
  ("ما الفرق بين تأجير السيارة اليومي والشهري؟", "travel"),
  ("كيف تجهز حقيبة سفر خفيفة ومنظمة؟", "travel"),
  ("كيف تقرأ تقرير فحص السيارة قبل الشراء؟", "cars"),
  ("كيف تعمل تقنية الدفع اللاتلامسي NFC؟", "tech"),
  ("ما أفضل الممارسات لحماية شبكة Wi-Fi المنزلية؟", "apps"),
  ("كيف تنشئ ميزانية شهرية وتتبع المصروفات؟", "money"),
  ("ما الفرق بين الادخار والاستثمار وإدارة المخاطر؟", "money"),
  ("كيف تختار مرتبة نوم مناسبة لاحتياجاتك؟", "life"),
  ("كيف تتعامل مع ارتفاع حرارة محرك السيارة؟", "cars"),
  ("كيف تعمل الطباعة ثلاثية الأبعاد واستخداماتها؟", "science"),
  ("كيف تتحقق من موثوقية متجر إلكتروني قبل الشراء؟", "apps"),
  ("ما الفرق بين أنواع منافذ USB وسرعاتها؟", "tech"),
  ("كيف تخطط لصيانة منزلية دورية وتقلل الأعطال؟", "life"),
  ("كيف تختار تأمين السفر وتفهم التغطيات الأساسية؟", "travel"),
  ("ما العوامل التي تؤثر في مدى السيارات الكهربائية؟", "cars"),
  ("كيف تقارن بين باقات الإنترنت المنزلي؟", "tech"),
  ("كيف تكتشف الرسائل الاحتيالية وروابط التصيد؟", "apps"),
  ("كيف تعمل الأقمار الصناعية الخاصة بالطقس؟", "science"),
  ("كيف تحافظ على الأجهزة المنزلية وتطيل عمرها؟", "life")
 ]
 used={norm(x) for x in used_topics}
 for topic, category in candidates:
  if norm(topic) not in existing_titles and norm(topic) not in used:
   return {"topic":topic,"category":category}
 raise RuntimeError("No unused topic remains in the built-in topic list; add new topics before publishing.")


def generate_article(topic, category):
 cat_ar, cat_en, icon = CATEGORIES[category]
 data = gemini(f"""
اكتب مقالاً تعليمياً أصلياً لموسوعة المعلومة الذكية باللغة العربية أولاً، مع نسخة إنجليزية موجزة.
استخدم بحث Google المدمج للعثور على مصادر منشورة فعلية قبل كتابة المقال، واستند إلى نتائج البحث.
الموضوع: {topic}
التصنيف: {cat_ar}
أعد كائن JSON واحداً فقط بالمفاتيح:
slug (إنجليزي kebab-case من 3 إلى 7 كلمات)، title_ar، title_en، description_ar، description_en،
sections (6 إلى 8 عناصر، لكل عنصر heading_ar و paragraphs_ar من فقرتين إلى 3 فقرات)،
summary_en (فقرتان)، sources (3 إلى 5 عناصر، لكل عنصر title و url).
اكتب 600 إلى 850 كلمة عربية فعلية. لا تختصر. اجعل كل قسم مفيداً ومختلفاً عن الآخر.
المصادر يجب أن تكون صفحات محددة وجديرة بالثقة، ويفضل جهات حكومية أو جامعات أو منظمات معيارية. استخدم الروابط التي ظهرت في نتائج البحث فقط، ولا تخترع أي رابط.
لا تخترع أرقاماً أو دراسات أو اقتباسات. لا تكتب نصائح طبية أو قانونية أو مالية شخصية. لا تضع أي نص خارج JSON.
""", temperature=0.25, grounded_search=True)
 def count_words(item):
  return len(" ".join(str(p) for sec in item.get("sections",[]) if isinstance(sec,dict) for p in (sec.get("paragraphs_ar",[]) if isinstance(sec.get("paragraphs_ar",[]),list) else [])).split())
 if not isinstance(data.get("sections"), list) or not 6 <= len(data["sections"]) <= 8:
  raise ValueError("Article must contain 6 to 8 sections")
 if count_words(data) < 600:
  raise ValueError(f"Article is too short ({count_words(data)} words; minimum 600). No expansion call was made.")
 for sec in data["sections"]:
  if not isinstance(sec,dict) or not str(sec.get("heading_ar","")).strip():
   raise ValueError("Article section is missing its heading")
  paragraphs=sec.get("paragraphs_ar")
  if not isinstance(paragraphs,list) or len(paragraphs)<2 or any(not isinstance(p,str) or len(p.strip())<80 for p in paragraphs):
   raise ValueError("Article section has missing or very short paragraphs")
 for field in ("title_ar","title_en","description_ar","description_en"):
  if not isinstance(data.get(field),str) or not data[field].strip():
   raise ValueError(f"Missing required article field: {field}")
 if not 70 <= len(data["description_ar"]) <= 200:
  raise ValueError("Arabic description length must be between 70 and 200 characters")
 slug=data.get("slug","")
 if not isinstance(slug,str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2,6}",slug.lower()):
  raise ValueError("Invalid slug; expected 3 to 7 lowercase English words")
 data["slug"]=slug.lower()
 data["category"]=category
 data["icon"]=icon
 data["category_ar"]=cat_ar
 data["category_en"]=cat_en
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

def editorial_review(article, sources):
 result=gemini(f"""
أنت مراجع تحريري مستقل. افحص المقال قبل النشر من حيث الدقة، وضوح الشرح، التكرار، اللغة، سلامة المصادر، وعدم وجود ادعاءات غير مسندة أو نصائح عالية المخاطر.
المصادر التي تم فتحها والتحقق من استجابتها: {json.dumps(sources,ensure_ascii=False)}
المقال: {json.dumps(article,ensure_ascii=False)}
أعد JSON فقط بالمفاتيح: approved (true/false), score (0-100), reasons (مصفوفة).
وافق فقط إذا كان المقال صالحاً للنشر دون تعديلات جوهرية، والدرجة 90 على الأقل. لا تطلب تحسينات شكلية اختيارية.
""", temperature=0.1)
 try:
  score=int(result.get("score",0))
 except (TypeError,ValueError):
  score=0
 reasons=result.get("reasons",[])
 approved=result.get("approved") is True and score>=90 and isinstance(reasons,list)
 print(f"Editorial review: approved={approved}, score={score}, reasons={reasons}")
 return approved


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
  raise SystemExit(f"Invalid ARTICLE_COUNT value: {raw_count!r}. Use 1 through 10.")
 count = max(1, min(10, int(count_match.group(0))))
 if raw_count != count_match.group(0):
  print(f"ARTICLE_COUNT input {raw_count!r} normalized to {count}.")
 used=[]
 published=0
 max_attempts = min(40, count * 4)
 for n in range(max_attempts):
  if published >= count:
   break
  try:
   topic_data=make_topic(titles,slugs,used)
   topic=str(topic_data.get("topic","")).strip()
   category=topic_data.get("category")
   if not topic or category not in CATEGORIES: raise ValueError("Invalid topic/category")
   used.append(topic)
   article=generate_article(topic,category)
   slug=article["slug"]
   if slug in slugs or norm(article["title_ar"]) in titles: raise ValueError("Duplicate slug/title")
   if (ROOT/"articles"/f"{slug}.html").exists(): raise ValueError("Article file already exists")
   ok, sources, source_error=verify_sources(article.get("sources",[]))
   if not ok:
    raise ValueError(f"Could not verify 3 sources; no extra repair calls were made: {source_error}")
   if len(sources) < 3: raise ValueError("Fewer than 3 verified sources")
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
   slugs.add(slug); titles.add(norm(article["title_ar"])); published+=1
   print(f"Published candidate {published}: {slug}")
  except GeminiQuotaError as exc:
   print(f"STOPPING: {exc}")
   raise SystemExit(str(exc))
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
