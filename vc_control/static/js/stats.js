(function () {
  function animateBars() {
    document.querySelectorAll(".bar-fill[data-bar-width]").forEach((bar) => {
      const activate = () => {
        bar.classList.add("is-animated");
      };

      if (!("IntersectionObserver" in window)) {
        activate();
        return;
      }

      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }
          activate();
          observer.unobserve(entry.target);
        });
      }, { threshold: 0.22 });

      observer.observe(bar);
    });
  }

  function animateRows(selector, delayStep = 16) {
    document.querySelectorAll(selector).forEach((element, index) => {
      element.style.animation = "fadeSlide 0.24s ease both";
      element.style.animationDelay = `${index * delayStep}ms`;
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const page = document.body.dataset.page;
    if (!["stats", "rankings", "dashboard"].includes(page)) {
      return;
    }
    animateBars();
    animateRows(".compact-table-row");
    animateRows(".flat-list-row");
    animateRows(".top-rank-row");
  });
})();
