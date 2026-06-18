from __future__ import annotations

import argparse
import io
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.request import HTTPCookieProcessor, build_opener
from http.cookiejar import CookieJar
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from PIL import Image


ROOT = "https://mipal.snu.ac.kr"

MEMBER_PAGES = [
    ("Professor", "/members"),
    ("Ph.D. Students", "/members/ph-d-students"),
    ("Integrated M.S./Ph.D. Students", "/members/integrated-m-s-ph-d-students"),
    ("M.S. Students", "/members/m-s-students"),
    ("Alumni", "/members/alumni"),
]

PUBLICATION_PAGES = [
    ("Arxiv", "/publications/arxiv"),
    ("International Conferences", "/publications/international-conferences"),
    ("International Journals", "/publications/international-journals"),
    ("Domestic", "/publications/domestic"),
    ("Thesis & Patents", "/publications/thesis-patents"),
    ("Others", "/publications/others"),
]

MISC_PAGES = [
    ("Gallery", "/gallery"),
    ("Notice", "/notice"),
]

NOISE_EXACT = {
    "",
    "mipal",
    "mipa laboratory",
    "notice",
    "members",
    "ph.d. students",
    "integrated m.s./ph.d. students",
    "m.s. students",
    "alumni",
    "gallery",
    "publications",
    "arxiv",
    "international conferences",
    "international journals",
    "domestic",
    "thesis & patents",
    "others",
    "skip to main content",
    "skip to navigation",
    "google sites",
    "embedded files",
    "page details",
    "back to site",
    "search",
    "clear search",
    "expand/collapse",
    "open search bar",
    "copy heading link",
    "site actions",
    "image carousel",
    "carousel image",
    "previous",
    "next",
    "students",
    "ph.d. candidate",
    "integrated m.s./ph.d candidate",
    "m.s. candidate",
}

NOISE_CONTAINS = (
    "© 2024 mipa laboratory",
    "mipa laboratory - ",
    "page updated",
    "report abuse",
    "search this site",
)

BLOCK_TAGS = {
    "address",
    "blockquote",
    "caption",
    "dd",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "td",
    "th",
}

SKIP_TAGS = {"script", "style", "svg", "noscript"}


def normalize_text(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    value = value.replace(" - ", " - ").strip()
    return value


def clean_href(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    href = unescape(href.strip())
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return None
    href = urljoin(base_url, href)
    parsed = urlparse(href)
    if "google.com" in parsed.netloc and parsed.path.startswith("/url"):
        query = parse_qs(parsed.query)
        target = query.get("q") or query.get("url")
        if target:
            return unquote(target[0])
    return href


def clean_image_url(base_url: str, url: str | None) -> str | None:
    if not url:
        return None
    url = unescape(url.strip().strip("\"'"))
    if not url or url.startswith("data:"):
        return None
    url = urljoin(base_url, url)
    if "googleusercontent.com" not in url and "ggpht.com" not in url:
        return None
    return url


def should_keep_line(line: str) -> bool:
    if not line:
        return False
    lowered = line.lower().strip()
    link_match = re.fullmatch(r"\[([^\]]+)\]\(.+\)", line.strip())
    if link_match and link_match.group(1).lower().strip() in NOISE_EXACT:
        return False
    if lowered in NOISE_EXACT:
        return False
    if any(token in lowered for token in NOISE_CONTAINS):
        return False
    if lowered.startswith("http") and len(lowered) > 120:
        return False
    return True


@dataclass
class Block:
    tag: str
    text: str


@dataclass
class ExtractedPage:
    title: str
    source: str
    blocks: list[Block] = field(default_factory=list)
    images: list[str] = field(default_factory=list)


class MipalParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.skip_depth = 0
        self.current_tag: str | None = None
        self.current_parts: list[str] = []
        self.href_stack: list[str | None] = []
        self.li_depth = 0
        self.li_parts: list[str] = []
        self.blocks: list[Block] = []
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value for name, value in attrs}
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return

        if self.skip_depth:
            return

        if tag == "a":
            self.href_stack.append(clean_href(self.base_url, attrs_dict.get("href")))

        if tag == "img":
            for attr in ("src", "data-src"):
                image_url = clean_image_url(self.base_url, attrs_dict.get(attr))
                if image_url:
                    self.images.append(image_url)

        style = attrs_dict.get("style") or ""
        for match in re.findall(r"url\(([^)]+)\)", style):
            image_url = clean_image_url(self.base_url, match)
            if image_url:
                self.images.append(image_url)

        for attr in ("alt", "aria-label", "title"):
            attr_text = normalize_text(attrs_dict.get(attr) or "")
            if attr_text and attr_text.lower() not in {"image", "picture", "link"}:
                self.blocks.append(Block("attr", attr_text))

        if tag == "li":
            self.flush_block()
            if self.li_depth == 0:
                self.li_parts = []
            self.li_depth += 1
            return

        if tag in BLOCK_TAGS:
            self.flush_block()
            self.current_tag = tag
            self.current_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return

        if self.skip_depth:
            return

        if tag == "a" and self.href_stack:
            self.href_stack.pop()

        if tag == "li" and self.li_depth:
            self.li_depth -= 1
            if self.li_depth == 0:
                text = normalize_text(" ".join(self.li_parts))
                if should_keep_line(text):
                    self.blocks.append(Block("li", text))
                self.li_parts = []
            return

        if tag == self.current_tag:
            self.flush_block()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = normalize_text(data)
        if not text:
            return
        href = self.href_stack[-1] if self.href_stack else None
        if href and not text.startswith("["):
            text = f"[{text}]({href})"
        if self.li_depth:
            self.li_parts.append(text)
            return
        if self.current_tag is None:
            if should_keep_line(text):
                self.blocks.append(Block("text", text))
            return
        self.current_parts.append(text)

    def flush_block(self) -> None:
        if self.current_tag is None:
            return
        text = normalize_text(" ".join(self.current_parts))
        if should_keep_line(text):
            self.blocks.append(Block(self.current_tag, text))
        self.current_tag = None
        self.current_parts = []


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = normalize_text(value).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def fetch_page(title: str, path: str) -> ExtractedPage:
    url = urljoin(ROOT, path)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 Codex content migration"})
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", "replace")

    parser = MipalParser(url)
    parser.feed(html)
    parser.flush_block()

    lines: list[Block] = []
    for block in parser.blocks:
        text = normalize_text(block.text)
        if should_keep_line(text):
            lines.append(Block(block.tag, text))

    images = dedupe_keep_order(parser.images)
    return ExtractedPage(title=title, source=url, blocks=lines, images=images)


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "page"


def download_page_images(page: ExtractedPage, site_root: Path, category: str) -> None:
    if not page.images:
        return

    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    page_request = Request(page.source, headers={"User-Agent": "Mozilla/5.0 Codex content migration"})
    with opener.open(page_request, timeout=30) as response:
        html = response.read().decode("utf-8", "replace")

    fresh_parser = MipalParser(page.source)
    fresh_parser.feed(html)
    fresh_parser.flush_block()
    source_images = dedupe_keep_order(fresh_parser.images)
    if source_images:
        page.images = source_images

    image_dir = site_root / "assets" / category
    image_dir.mkdir(parents=True, exist_ok=True)
    local_images: list[str] = []
    page_slug = slugify(page.title)
    max_dimension = 300 if category == "gallery" else 160
    quality = 42 if category == "gallery" else 28

    for index, image_url in enumerate(page.images, start=1):
        image_request = Request(
            image_url,
            headers={
                "Referer": page.source,
                "User-Agent": "Mozilla/5.0 Codex content migration",
            },
        )
        try:
            with opener.open(image_request, timeout=45) as response:
                raw = response.read()
        except Exception as error:
            print(f"warning: could not download {image_url}: {error}")
            continue

        try:
            image = Image.open(io.BytesIO(raw))
            image.thumbnail((max_dimension, max_dimension))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            out_name = f"{page_slug}-{index:02d}.jpg"
            out_path = image_dir / out_name
            image.save(out_path, "JPEG", quality=quality, optimize=True, progressive=True)
            local_images.append(f"assets/{category}/{out_name}")
        except Exception as error:
            print(f"warning: could not process {image_url}: {error}")

    page.images = local_images


def md_escape(value: str) -> str:
    return value.replace("\n", " ").strip()


def bulletize(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in dedupe_keep_order(lines):
        line = md_escape(line)
        if not should_keep_line(line):
            continue
        if len(line) < 2:
            continue
        result.append(f"- {line}")
    return result


def blocks_to_lines(page: ExtractedPage) -> list[str]:
    lines = []
    for block in page.blocks:
        text = md_escape(block.text)
        lowered = text.lower()
        if lowered == page.title.lower():
            continue
        lines.append(text)
    return dedupe_keep_order(lines)


def looks_like_person_name(line: str) -> bool:
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line).strip()
    lowered = plain.lower()
    if any(token in lowered for token in ("tel:", "e-mail", "email", "mailto:", "http", "laboratory")):
        return False
    if "@" in plain or "#" in plain or ":" in plain or "," in plain or "(" in plain or ")" in plain:
        return False
    words = plain.split()
    if not 1 < len(words) <= 4:
        return False
    if not all(re.search(r"[A-Za-z]", word) for word in words):
        return False
    return sum(word[:1].isupper() for word in words) >= len(words) - 1


def render_member_bullets(lines: list[str]) -> list[str]:
    grouped: list[tuple[str | None, list[str]]] = []
    current_name: str | None = None
    current_details: list[str] = []

    for line in dedupe_keep_order(lines):
        if looks_like_person_name(line):
            if current_name or current_details:
                grouped.append((current_name, current_details))
            current_name = line
            current_details = []
            continue
        if current_name:
            current_details.append(line)
        else:
            grouped.append((None, [line]))

    if current_name or current_details:
        grouped.append((current_name, current_details))

    bullets: list[str] = []
    for name, details in grouped:
        details = [detail for detail in details if should_keep_line(detail)]
        if name:
            if details:
                bullets.append(f"- **{name}** - {'; '.join(details)}")
            else:
                bullets.append(f"- **{name}**")
        else:
            bullets.extend(f"- {detail}" for detail in details)
    return bullets


def render_publication_items(page: ExtractedPage) -> list[str]:
    rendered: list[str] = []
    current: list[str] = []
    saw_structured_items = any(block.tag == "li" for block in page.blocks)

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        title, *details = current
        details = [detail for detail in details if should_keep_line(detail)]
        if details:
            rendered.append(f"- **{title}** - {'; '.join(details)}")
        else:
            rendered.append(f"- **{title}**")
        current = []

    if not saw_structured_items:
        return bulletize(blocks_to_lines(page))

    for block in page.blocks:
        text = md_escape(block.text)
        if not should_keep_line(text) or text.lower() == page.title.lower():
            continue

        if block.tag in {"h2", "h3"}:
            flush_current()
            if re.fullmatch(r"(19|20)\d{2}", text):
                rendered.extend(["", f"### {text}", ""])
            continue

        if block.tag == "li":
            flush_current()
            current = [text]
            continue

        if block.tag == "p" and current:
            current.append(text)
            continue

        if block.tag == "p":
            rendered.append(f"- {text}")

    flush_current()
    return [line for line in rendered if line != "" or rendered.count(line) <= 1]


def render_members(pages: list[ExtractedPage]) -> str:
    output = [
        "---",
        "title: Members",
        "---",
        "",
        "# Members",
        "",
        "This page mirrors the current member sections from the original MIPAL website.",
        "",
    ]
    image_counts = Counter(image for page in pages for image in page.images)
    common_images = {image for image, count in image_counts.items() if count > 1}

    for page in pages:
        output.extend([f"## {page.title}", ""])
        lines = blocks_to_lines(page)
        bullets = render_member_bullets(lines)
        if bullets:
            output.extend(bullets)
        else:
            output.append("- Content will be updated from the original site.")
        output.append("")

        section_images = [image for image in page.images if image not in common_images]
        if section_images:
            output.extend([f"### {page.title} Photos", ""])
            for index, image in enumerate(section_images, start=1):
                output.append(f"![{page.title} photo {index}]({image})")
            output.append("")

    return "\n".join(output).strip() + "\n"


def render_publications(pages: list[ExtractedPage]) -> str:
    output = [
        "---",
        "title: Publications",
        "---",
        "",
        "# Publications",
        "",
        "Publication lists are organized following the original MIPAL categories.",
        "",
    ]

    for page in pages:
        output.extend([f"## {page.title}", ""])
        bullets = render_publication_items(page)
        if bullets:
            output.extend(bullets)
        else:
            output.append("- Content will be updated from the original site.")
        output.append("")

    return "\n".join(output).strip() + "\n"


def render_gallery(page: ExtractedPage) -> str:
    output = [
        "---",
        "title: Gallery",
        "---",
        "",
        "# Gallery",
        "",
        "A migrated gallery draft using photos from the original MIPAL site.",
        "",
    ]

    lines = blocks_to_lines(page)
    if lines:
        output.extend(["## Notes", ""])
        output.extend(bulletize(lines[:30]))
        output.append("")

    if page.images:
        output.extend(["## Photos", ""])
        for index, image in enumerate(page.images[:80], start=1):
            output.append(f"![MIPAL gallery photo {index}]({image})")
        output.append("")
    else:
        output.append("- Gallery photos will be updated from the original site.")

    return "\n".join(output).strip() + "\n"


def render_notice(page: ExtractedPage) -> str:
    output = [
        "---",
        "title: Notice",
        "---",
        "",
        "# Notice",
        "",
        "Recent notices migrated from the original MIPAL site.",
        "",
    ]

    lines = blocks_to_lines(page)
    bullets = bulletize(lines)
    if bullets:
        output.extend(bullets)
    else:
        output.append("- Notice content will be updated from the original site.")
    output.append("")
    return "\n".join(output).strip() + "\n"


def save_json(path: Path, pages: list[ExtractedPage]) -> None:
    payload = [
        {
            "title": page.title,
            "source": page.source,
            "blocks": [{"tag": block.tag, "text": block.text} for block in page.blocks],
            "images": page.images,
        }
        for page in pages
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="work/extracted")
    parser.add_argument("--site-root", default="outputs/nojunk-site")
    parser.add_argument("--write-site", action="store_true")
    parser.add_argument("--download-images", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    site_root = Path(args.site_root).resolve()

    member_pages = [fetch_page(title, path) for title, path in MEMBER_PAGES]
    publication_pages = [fetch_page(title, path) for title, path in PUBLICATION_PAGES]
    gallery_page = fetch_page("Gallery", "/gallery")
    notice_page = fetch_page("Notice", "/notice")

    if args.download_images:
        shutil.rmtree(site_root / "assets" / "members", ignore_errors=True)
        shutil.rmtree(site_root / "assets" / "gallery", ignore_errors=True)
        member_image_counts = Counter(image for page in member_pages for image in page.images)
        common_member_images = {image for image, count in member_image_counts.items() if count > 1}
        for page in member_pages:
            page.images = [image for image in page.images if image not in common_member_images]
            download_page_images(page, site_root, "members")
        download_page_images(gallery_page, site_root, "gallery")

    save_json(out_dir / "members.json", member_pages)
    save_json(out_dir / "publications.json", publication_pages)
    save_json(out_dir / "gallery.json", [gallery_page])
    save_json(out_dir / "notice.json", [notice_page])

    outputs = {
        "members.md": render_members(member_pages),
        "publications.md": render_publications(publication_pages),
        "gallery.md": render_gallery(gallery_page),
        "notice.md": render_notice(notice_page),
    }

    for filename, markdown in outputs.items():
        (out_dir / filename).write_text(markdown, encoding="utf-8")

    if args.write_site:
        site_content = site_root / "content"
        site_content.mkdir(parents=True, exist_ok=True)
        for filename, markdown in outputs.items():
            (site_content / filename).write_text(markdown, encoding="utf-8")

    summary = {
        "members": [{"title": page.title, "blocks": len(page.blocks), "images": len(page.images)} for page in member_pages],
        "publications": [{"title": page.title, "blocks": len(page.blocks), "images": len(page.images)} for page in publication_pages],
        "gallery": {"blocks": len(gallery_page.blocks), "images": len(gallery_page.images)},
        "notice": {"blocks": len(notice_page.blocks), "images": len(notice_page.images)},
        "out": str(out_dir),
        "wrote_site": args.write_site,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
