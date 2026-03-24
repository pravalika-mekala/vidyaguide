(function () {
  const MAIN_SELECTOR = "#page-main";
  const PAGE_SCRIPTS_SELECTOR = "#page-scripts";
  const NAV_LINK_SELECTOR = "a[data-nav-shell]";

  function isSameShellLink(link) {
    const shell = link.getAttribute("data-nav-shell");
    if (!shell) {
      return false;
    }

    const currentShellLink = document.querySelector(`${NAV_LINK_SELECTOR}[data-nav-shell="${shell}"]`);
    return Boolean(currentShellLink);
  }

  function isInterceptableClick(event, link) {
    if (!link || event.defaultPrevented || event.button !== 0) {
      return false;
    }

    if (
      link.target === "_blank" ||
      link.hasAttribute("download") ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return false;
    }

    const href = link.getAttribute("href");
    if (!href || href.startsWith("#") || href.startsWith("javascript:")) {
      return false;
    }

    const nextUrl = new URL(link.href, window.location.href);
    if (nextUrl.origin !== window.location.origin) {
      return false;
    }

    return nextUrl;
  }

  function executeScripts(scope) {
    if (!scope) {
      return;
    }

    scope.querySelectorAll("script").forEach((oldScript) => {
      const type = (oldScript.getAttribute("type") || "").trim().toLowerCase();
      const executable =
        !type ||
        type === "text/javascript" ||
        type === "application/javascript" ||
        type === "module";

      if (!executable) {
        return;
      }

      const newScript = document.createElement("script");
      Array.from(oldScript.attributes).forEach((attr) => {
        newScript.setAttribute(attr.name, attr.value);
      });
      newScript.textContent = oldScript.textContent;
      oldScript.replaceWith(newScript);
    });
  }

  function syncTitle(doc) {
    if (doc.title) {
      document.title = doc.title;
    }
  }

  function markActiveLink(pathname) {
    document.querySelectorAll(NAV_LINK_SELECTOR).forEach((link) => {
      const url = new URL(link.href, window.location.href);
      const isActive = url.pathname === pathname;
      link.setAttribute("aria-current", isActive ? "page" : "false");
    });
  }

  async function swapPage(url, pushState) {
    const response = await fetch(url.href, {
      headers: {
        "X-Requested-With": "fetch",
      },
      credentials: "same-origin",
    });

    if (!response.ok) {
      window.location.href = url.href;
      return;
    }

    const html = await response.text();
    const parser = new DOMParser();
    const nextDoc = parser.parseFromString(html, "text/html");
    const nextMain = nextDoc.querySelector(MAIN_SELECTOR);
    const currentMain = document.querySelector(MAIN_SELECTOR);

    if (!nextMain || !currentMain) {
      window.location.href = url.href;
      return;
    }

    const nextPageScripts = nextDoc.querySelector(PAGE_SCRIPTS_SELECTOR);
    const currentPageScripts = document.querySelector(PAGE_SCRIPTS_SELECTOR);

    currentMain.innerHTML = nextMain.innerHTML;
    if (currentPageScripts) {
      currentPageScripts.innerHTML = nextPageScripts ? nextPageScripts.innerHTML : "";
    }

    syncTitle(nextDoc);
    markActiveLink(url.pathname);

    executeScripts(currentMain);
    if (currentPageScripts) {
      executeScripts(currentPageScripts);
    }

    if (pushState) {
      window.history.pushState({}, "", url.href);
    }

    window.scrollTo(0, 0);
    document.dispatchEvent(new CustomEvent("page:loaded", { detail: { path: url.pathname } }));
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest(NAV_LINK_SELECTOR);
    if (!link || !isSameShellLink(link)) {
      return;
    }

    const nextUrl = isInterceptableClick(event, link);
    if (!nextUrl) {
      return;
    }

    if (nextUrl.pathname === window.location.pathname) {
      event.preventDefault();
      return;
    }

    event.preventDefault();
    swapPage(nextUrl, true).catch(() => {
      window.location.href = nextUrl.href;
    });
  });

  window.addEventListener("popstate", () => {
    const nextUrl = new URL(window.location.href);
    swapPage(nextUrl, false).catch(() => {
      window.location.reload();
    });
  });

  document.addEventListener("DOMContentLoaded", () => {
    markActiveLink(window.location.pathname);
  });
})();
