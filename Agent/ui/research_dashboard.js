(() => {
  if (!window.rdDashboardScrollBound) {
    window.rdDashboardScrollBound = true;
    const updateVisibleReports = () => {
      for (const root of document.querySelectorAll(".rd-report[data-interactive]")) {
        root.rdUpdateActive?.();
      }
    };
    document.addEventListener("scroll", updateVisibleReports, {capture:true, passive:true});
    window.addEventListener("resize", updateVisibleReports);
  }
  for (const root of document.querySelectorAll(".rd-report:not([data-interactive])")) {
    root.dataset.interactive = "true";
    const nav = [...root.querySelectorAll(".rd-nav [data-section]")];
    const sections = nav.map(link => root.querySelector(link.getAttribute("href")));
    const sticky = root.querySelector(".rd-nav");
    const scroll = sticky.querySelector(".rd-nav-links");
    let previousActive;
    const updateActive = () => {
      let index = 0;
      const edge = sticky.getBoundingClientRect().bottom + 36;
      sections.forEach((section, i) => {
        if (section && section.getBoundingClientRect().top <= edge) index = i;
      });
      nav.forEach((link, i) => {
        if (i === index) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
      const active = nav[index];
      if (active && active !== previousActive) {
        previousActive = active;
        const left = active.getBoundingClientRect().left - scroll.getBoundingClientRect().left + scroll.scrollLeft;
        if (left < scroll.scrollLeft) scroll.scrollLeft = left;
        else if (left + active.offsetWidth > scroll.scrollLeft + scroll.clientWidth) {
          scroll.scrollLeft = left + active.offsetWidth - scroll.clientWidth;
        }
      }
    };
    root.rdUpdateActive = updateActive;
    updateActive();

    const topics = [...root.querySelectorAll("[data-topic]")];
    const panels = [...root.querySelectorAll("[data-topic-panel]")];
    const activateTopic = id => {
      for (const panel of panels) panel.hidden = panel.id !== id;
      for (const link of topics) {
        if (link.dataset.topic === id) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
      }
    };
    if (topics.length) activateTopic(
      topics.find(link => "#" + link.dataset.topic === location.hash)?.dataset.topic || topics[0].dataset.topic
    );

    const dialog = root.querySelector("dialog");
    const closeButton = dialog.querySelector("button");
    let opener;
    root.addEventListener("click", event => {
      const topic = event.target.closest("[data-topic]");
      if (topic && root.contains(topic)) {
        event.preventDefault();
        activateTopic(topic.dataset.topic);
        return;
      }
      const link = event.target.closest("[data-evidence]");
      if (!link || !root.contains(link) || typeof dialog.showModal !== "function") return;
      const source = root.querySelector(link.getAttribute("href"));
      const body = source?.querySelector(".rd-source-body");
      if (!body) return;
      event.preventDefault();
      opener = link;
      dialog.querySelector("h2").textContent = "证据 " + link.dataset.evidence;
      dialog.querySelector("[data-dialog-content]").replaceChildren(body.cloneNode(true));
      dialog.showModal();
    });
    closeButton.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", event => {
      if (event.target === dialog) {
        const box = dialog.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right ||
            event.clientY < box.top || event.clientY > box.bottom) dialog.close();
      }
    });
    dialog.addEventListener("close", () => {
      dialog.querySelector("[data-dialog-content]").replaceChildren();
      opener?.focus({preventScroll:true});
    });
  }
})();
