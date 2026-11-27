#!/usr/bin/env python3
"""렌트드림 Journal 빌드 스크립트

_journal/queue.json 순서대로 글을 공개한다.
  python3 _tools/journal.py build     공개된 글만 다시 만든다
  python3 _tools/journal.py publish   다음 글 1편을 오늘 날짜로 공개하고 다시 만든다

글 원고는 _journal/posts/<slug>.txt (밑줄로 시작하는 폴더라 사이트에는 올라가지 않음)
"""
import datetime
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "_journal")
OUT = os.path.join(ROOT, "journal")
SITE = "https://rentdream.kr"
KST = datetime.timezone(datetime.timedelta(hours=9))


def today():
    return datetime.datetime.now(KST).date().isoformat()


def load_queue():
    with open(os.path.join(SRC, "queue.json"), encoding="utf-8") as f:
        return json.load(f)


def save_queue(q):
    with open(os.path.join(SRC, "queue.json"), "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_post(slug):
    with open(os.path.join(SRC, "posts", slug + ".txt"), encoding="utf-8") as f:
        raw = f.read()
    head, body = raw.split("\n---\n", 1)
    meta = {}
    for line in head.strip().splitlines():
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    meta["slug"] = slug
    meta["body"] = body.strip()
    return meta


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\[\[(.+?)\|(.+?)\]\]", r'<a href="\2">\1</a>', t)
    return t


def render_body(body):
    """간단한 원고 문법
    ## 소제목 / 문단 / - 목록 / ![img/x.jpg|설명] / Q: 질문 + A: 답변 / [[글자|링크]]"""
    out, faq, lst = [], [], []
    num = 0

    def flush():
        if lst:
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in lst) + "</ul>")
            lst.clear()

    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
    for b in blocks:
        lines = b.splitlines()
        if all(l.startswith("- ") for l in lines):
            lst.extend(l[2:] for l in lines)
            continue
        flush()
        if b.startswith("## "):
            num += 1
            out.append(f'<h2><span>{num:02d}</span>{inline(b[3:])}</h2>')
        elif b.startswith("### "):
            out.append(f"<h3>{inline(b[4:])}</h3>")
        elif b.startswith("!["):
            src, alt = b[2:-1].split("|", 1)
            out.append(f'<figure><img src="/{src}" alt="{html.escape(alt)}" width="960" height="527" loading="lazy"><figcaption>{html.escape(alt)}</figcaption></figure>')
        elif b.startswith("Q: "):
            q = lines[0][3:]
            a = " ".join(l[3:] if l.startswith("A: ") else l for l in lines[1:])
            faq.append((q, a))
        else:
            out.append(f"<p>{inline(' '.join(lines))}</p>")
    flush()
    if faq:
        out.append('<h2 class="fq"><span>FAQ</span>자주 묻는 질문</h2><div class="faq">')
        for q, a in faq:
            out.append(f"<details><summary>{inline(q)}</summary><p>{inline(a)}</p></details>")
        out.append("</div>")
    return "\n".join(out), faq


def tpl(name):
    with open(os.path.join(SRC, "templates", name), encoding="utf-8") as f:
        return f.read()


def fmt_date(d):
    return d.replace("-", ".")


def build(queue):
    published = [p for p in queue if p.get("date")]
    posts = [dict(parse_post(p["slug"]), date=p["date"]) for p in published]
    shell = tpl("shell.html")
    os.makedirs(OUT, exist_ok=True)

    # 공개 글이 아닌 폴더는 지운다
    keep = {p["slug"] for p in posts}
    for d in os.listdir(OUT):
        full = os.path.join(OUT, d)
        if os.path.isdir(full) and d not in keep:
            for fn in os.listdir(full):
                os.remove(os.path.join(full, fn))
            os.rmdir(full)

    for i, p in enumerate(posts):
        body, faq = render_body(p["body"])
        url = f"{SITE}/journal/{p['slug']}/"
        cover = p.get("cover", "")
        ld = [{
            "@context": "https://schema.org", "@type": "Article",
            "headline": p["title"], "description": p["description"],
            "datePublished": p["date"], "dateModified": p["date"],
            "author": {"@type": "Organization", "name": "렌트드림"},
            "publisher": {"@type": "Organization", "name": "렌트드림", "logo": {"@type": "ImageObject", "url": f"{SITE}/favicon-512.png"}},
            "mainEntityOfPage": url,
            **({"image": f"{SITE}/{cover}"} if cover else {}),
        }]
        if faq:
            ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"\[\[(.+?)\|.+?\]\]", r"\1", a)}} for q, a in faq]})
        others = [o for o in posts if o["slug"] != p["slug"]][-3:]
        rel = "".join(
            f'<a href="/journal/{o["slug"]}/"><small>{html.escape(o["cat"])}</small><b>{html.escape(o["h1"].replace("|", " "))}</b></a>' for o in others)
        cover_html = (f'<div class="cover"><img src="/{cover}" alt="{html.escape(p.get("cover_alt", ""))}" width="960" height="527"></div>'
                      if cover else "")
        art = tpl("post.html")
        art = (art.replace("{{CAT}}", html.escape(p["cat"]))
               .replace("{{H1}}", "<br>".join(html.escape(x.strip()) for x in p["h1"].split("|")))
               .replace("{{DATE}}", fmt_date(p["date"]))
               .replace("{{ISO}}", p["date"])
               .replace("{{READ}}", str(max(2, round(len(re.sub(r'\s', '', p['body'])) / 500))))
               .replace("{{COVER}}", cover_html)
               .replace("{{BODY}}", body)
               .replace("{{REL}}", f'<nav class="rel" aria-label="다른 글"><span>More Journal</span>{rel}</nav>' if rel else ""))
        page = (shell.replace("{{TITLE}}", html.escape(p["title"]))
                .replace("{{DESC}}", html.escape(p["description"]))
                .replace("{{URL}}", url)
                .replace("{{OGIMG}}", f"{SITE}/{cover}" if cover else f"{SITE}/og-image.jpg")
                .replace("{{OGTYPE}}", "article")
                .replace("{{LD}}", "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld))
                .replace("{{MAIN}}", art))
        d = os.path.join(OUT, p["slug"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)

    # 목록 페이지
    cards = "".join(
        f'<a class="card" href="/journal/{p["slug"]}/">'
        + (f'<img src="/{p["cover"]}" alt="" width="960" height="527" loading="lazy">' if p.get("cover") else f'<div class="ph"><span>{html.escape(p["cat"])}</span></div>')
        + f'<small>{html.escape(p["cat"])} · {fmt_date(p["date"])}</small><b>{html.escape(p["h1"].replace("|", " "))}</b><p>{html.escape(p["description"])}</p></a>'
        for p in reversed(posts))
    lst = tpl("list.html").replace("{{CARDS}}", cards)
    page = (shell.replace("{{TITLE}}", "Journal | 렌트드림 수입차·슈퍼카 렌트 가이드")
            .replace("{{DESC}}", "수입차·슈퍼카 렌트를 준비할 때 알아두면 좋은 차량별 안내와 이용 가이드. 렌트드림 Journal.")
            .replace("{{URL}}", f"{SITE}/journal/")
            .replace("{{OGIMG}}", f"{SITE}/og-image.jpg")
            .replace("{{OGTYPE}}", "website")
            .replace("{{LD}}", "")
            .replace("{{MAIN}}", lst))
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)

    # 사이트맵
    last = posts[-1]["date"] if posts else today()
    urls = [(f"{SITE}/", None, "1.0"), (f"{SITE}/journal/", last, "0.6")]
    urls += [(f"{SITE}/journal/{p['slug']}/", p["date"], "0.8") for p in posts]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    old = open(os.path.join(ROOT, "sitemap.xml"), encoding="utf-8").read()
    home_mod = re.search(r"<loc>https://rentdream.kr/</loc>\s*<lastmod>([^<]+)</lastmod>", old)
    for loc, mod, pr in urls:
        mod = mod or (home_mod.group(1) if home_mod else today())
        sm.append(f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{mod}</lastmod>\n    <priority>{pr}</priority>\n  </url>")
    sm.append("</urlset>")
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(sm) + "\n")
    return posts


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    q = load_queue()
    if cmd == "publish":
        nxt = next((p for p in q if not p.get("date")), None)
        if not nxt:
            print("공개할 글이 없습니다")
            return
        if any(p.get("date") == today() for p in q):
            print("오늘 이미 공개함")
            return
        nxt["date"] = today()
        save_queue(q)
        print("공개:", nxt["slug"])
    posts = build(q)
    print("공개된 글", len(posts), "편")


if __name__ == "__main__":
    main()
