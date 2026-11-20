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
            "generationConfig":{"temperature":temperature,"responseMimeType":"application/json"}}
 last = None
 for attempt in range(6):
  r = requests.post(API, headers={"x-goog-api-key": API_KEY}, json=payload, timeout=120)
  if r.status_code in (429, 500, 502, 503):
   last = f"Gemini HTTP {r.status_code}: {r.text[:500]}"
   time.sleep(15 * (attempt + 1)); continue
  r.raise_for_status()
  data = r.json()
  text = data["candidates"][0]["content"]["parts"][0]["text"]
  text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text)
  return json.loads(text)
 raise RuntimeError(last or "Gemini request failed")

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
المقال العربي يجب أن يكون بين 650 و1000 كلمة قدر الإمكان، ولا يقل عن 500 كلمة، يتضمن مقدمة وعناوين فرعية وخطوات أو أمثلة وأسئلة شائعة عند ملاءمة الموضوع.
لا تخترع أرقاماً أو دراسات أو اقتباسات. اعتمد على مصادر رسمية/أكاديمية/معايير معروفة ذات صلة مباشرة، وتجنب الروابط الرئيسية العامة إن أمكن. لا تضع مصادر وهمية. لا تستخدم نصاً تسويقياً ولا تدعِ أن المقال تمت مراجعته بشرياً.
اكتب بصياغة طبيعية غير مكررة، وابتعد عن النصائح الطبية أو القانونية أو المالية الشخصية.
""")
 def count_words(item):
  return len(" ".join(str(p) for sec in item.get("sections",[]) if isinstance(sec,dict) for p in (sec.get("paragraphs_ar",[]) if isinstance(sec.get("paragraphs_ar",[]),list) else [])).split())
 if count_words(data) < 500:
  print(f"Generated article is short ({count_words(data)} words); requesting an expansion.")
  expanded = gemini(f"""
وسّع المقال التالي دون تغيير موضوعه أو عنوانه أو رابطه أو مصادره.
المطلوب: نص عربي أصلي لا يقل عن 650 كلمة فعلية، موزع على 6 إلى 8 أقسام واضحة.
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
 if count_words(data) < 500:
  raise ValueError(f"Article is too short after expansion ({count_words(data)} words; minimum 500)")
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
 replacement = gemini(f"""
روابط المصادر المقترحة للمقال التالي تعذر فتح بعضها. اقترح 3 إلى 5 روابط بديلة مباشرة لصفحات رسمية/أكاديمية حقيقية تتناول نفس الادعاءات.
لا تضع الصفحة الرئيسية للمؤسسة إن أمكن، ولا تخترع روابط أو عناوين.
الموضوع: {article.get("title_ar")}
الروابط التي فشلت: {json.dumps(article.get("sources", []), ensure_ascii=False)}
سبب الفشل: {source_error}
أعد JSON فقط بالشكل: {{"sources":[{{"title":"اسم الصفحة","url":"https://..."}}]}}
""", temperature=0.1)
 return replacement.get("sources", []) if isinstance(replacement, dict) else []

def editorial_review(article, sources):
 result=gemini(f"""
أنت مراجع تحريري مستقل. قيّم المقال التالي قبل النشر.
تحقق من: الدقة العامة، وضوح الشرح، التكرار، سلامة اللغة، العنوان والوصف، وعدم وجود ادعاءات رقمية/علمية غير مسندة أو نصائح عالية المخاطر.
روابط المصادر التي أمكن فتحها فعلياً: {json.dumps(sources,ensure_ascii=False)}
المقال: {json.dumps(article,ensure_ascii=False)}
أعد JSON فقط: approved (true/false), score (0-100), reasons (مصفوفة قصيرة), corrections (مصفوفة تعديلات نصية ضرورية).
ارفض إذا كان المحتوى يتضمن ادعاءات رئيسية غير موثوقة، أو إذا كانت المصادر لا تدعم الموضوع، أو المقال ضعيف/قصير/مكرر. لا توافق لمجرد أن النص منظم.
""", temperature=0.1)
 try:
  score = int(result.get("score",0))
 except (TypeError, ValueError):
  score = 0
 corrections = result.get("corrections", [])
 reasons = result.get("reasons", [])
 if (result.get("approved") is not True or score < 90
     or not isinstance(corrections,list) or len(corrections) > 0
     or not isinstance(reasons,list)):
  print("Rejected by editorial review:", result)
  return False
 return True

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
  function gtag(){dataLayer.push(arguments);}
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
(function(){
 const content=document.getElementById("articleContent");
 const time=document.getElementById("readingTime");
 const bar=document.getElementById("readingProgressBar");
 if(content&&time){
  const words=(content.innerText||content.textContent||"").trim().split(/\\s+/).filter(Boolean).length;
  const minutes=Math.max(1,Math.ceil(words/200));
  time.textContent="وقت القراءة: "+minutes+" دقائق تقريباً";
 }
 function updateProgress(){
  if(!bar)return;
  const max=document.documentElement.scrollHeight-window.innerHeight;
  const progress=max>0?Math.min(100,Math.max(0,(window.scrollY/max)*100)):0;
  bar.style.width=progress+"%";
 }
 window.addEventListener("scroll",updateProgress,{passive:true});
 window.addEventListener("resize",updateProgress);
 updateProgress();
})();
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
 count=max(1,min(3,int(os.getenv("ARTICLE_COUNT","3") or "3")))
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
    article["sources"] = repair_sources(article, source_error)
    ok, sources, source_error=verify_sources(article.get("sources",[]))
   if not ok: raise ValueError(source_error)
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
