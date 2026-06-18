const routes = {
  home: {
    file: "content/home.md",
    kicker: "MIPAL",
  },
  notice: {
    file: "content/notice.md",
    kicker: "Updates",
  },
  members: {
    file: "content/members.md",
    kicker: "People",
  },
  publications: {
    file: "content/publications.md",
    kicker: "Research output",
  },
  gallery: {
    file: "content/gallery.md",
    kicker: "Lab moments",
  },
};

const content = document.querySelector("#content");
const kicker = document.querySelector("#content-kicker");
const navToggle = document.querySelector(".nav-toggle");
const navLinks = document.querySelector(".nav-links");

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inlineMarkdown(value) {
  let text = escapeHtml(value);
  text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/\*(.+?)\*/g, "<em>$1</em>");
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
  return text;
}

function stripFrontMatter(markdown) {
  if (!markdown.startsWith("---")) {
    return markdown;
  }

  const end = markdown.indexOf("\n---", 3);
  if (end === -1) {
    return markdown;
  }

  return markdown.slice(end + 4).trim();
}

function renderMarkdown(markdown) {
  const lines = stripFrontMatter(markdown).split(/\r?\n/);
  const html = [];
  let listItems = [];
  let paragraph = [];
  let inQuote = false;
  let quote = [];

  function flushParagraph() {
    if (!paragraph.length) {
      return;
    }

    html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  }

  function flushList() {
    if (!listItems.length) {
      return;
    }

    html.push(`<ul>${listItems.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ul>`);
    listItems = [];
  }

  function flushQuote() {
    if (!inQuote) {
      return;
    }

    html.push(`<blockquote>${quote.map((line) => `<p>${inlineMarkdown(line)}</p>`).join("")}</blockquote>`);
    quote = [];
    inQuote = false;
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushList();
      flushQuote();
      continue;
    }

    if (line === "---") {
      flushParagraph();
      flushList();
      flushQuote();
      html.push("<hr />");
      continue;
    }

    if (line.startsWith("> ")) {
      flushParagraph();
      flushList();
      inQuote = true;
      quote.push(line.slice(2));
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      flushQuote();
      html.push(`<h${heading[1].length}>${inlineMarkdown(heading[2])}</h${heading[1].length}>`);
      continue;
    }

    const listItem = line.match(/^[-*]\s+(.+)$/);
    if (listItem) {
      flushParagraph();
      flushQuote();
      listItems.push(listItem[1]);
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  flushQuote();
  return html.join("");
}

function setActiveRoute(routeName) {
  document.querySelectorAll("[data-route]").forEach((link) => {
    link.classList.toggle("is-active", link.dataset.route === routeName);
  });
}

async function loadRoute(routeName) {
  const route = routes[routeName] || routes.home;
  setActiveRoute(routes[routeName] ? routeName : "home");
  kicker.textContent = route.kicker;
  content.innerHTML = '<p class="loading">Loading content...</p>';

  try {
    const response = await fetch(route.file, { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`Could not load ${route.file}`);
    }

    const markdown = await response.text();
    content.innerHTML = renderMarkdown(markdown);
  } catch (error) {
    content.innerHTML = `
      <h1>Content unavailable</h1>
      <p>This site loads Markdown files over HTTP. Start a local web server or publish it with GitHub Pages.</p>
    `;
  }
}

function currentRoute() {
  return window.location.hash.replace("#", "") || "home";
}

window.addEventListener("hashchange", () => {
  loadRoute(currentRoute());
  navLinks.classList.remove("is-open");
  navToggle.setAttribute("aria-expanded", "false");
});

navToggle.addEventListener("click", () => {
  const isOpen = navLinks.classList.toggle("is-open");
  navToggle.setAttribute("aria-expanded", String(isOpen));
});

loadRoute(currentRoute());
