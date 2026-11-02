/**
 * Intelligence Designed To Evolve - Landing Page Logic
 * Vanilla JavaScript (No frameworks)
 */

document.addEventListener("DOMContentLoaded", () => {
  initMobileMenu();
  initStatsCountUp();
  initNavLinks();
});

/**
 * Mobile Navigation Toggle & Drawer Handler
 */
function initMobileMenu() {
  const burgerBtn = document.getElementById("burger-btn");
  const overlay = document.getElementById("mobile-overlay");
  const sheet = document.getElementById("mobile-sheet");
  const links = document.querySelectorAll(".mobile-nav-link, .mobile-sign-in-btn");

  if (!burgerBtn || !overlay || !sheet) return;

  function openMenu() {
    burgerBtn.classList.add("open");
    burgerBtn.setAttribute("aria-expanded", "true");
    overlay.hidden = false;
    sheet.hidden = false;
    document.body.classList.add("menu-open");
  }

  function closeMenu() {
    burgerBtn.classList.remove("open");
    burgerBtn.setAttribute("aria-expanded", "false");
    overlay.hidden = true;
    sheet.hidden = true;
    document.body.classList.remove("menu-open");
  }

  function toggleMenu() {
    const isExpanded = burgerBtn.getAttribute("aria-expanded") === "true";
    if (isExpanded) {
      closeMenu();
    } else {
      openMenu();
    }
  }

  burgerBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleMenu();
  });

  overlay.addEventListener("click", closeMenu);

  // Close on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && burgerBtn.getAttribute("aria-expanded") === "true") {
      closeMenu();
    }
  });

  // Close when any mobile navigation link is clicked
  links.forEach((link) => {
    link.addEventListener("click", () => {
      closeMenu();
    });
  });

  // Close if window resized above 720px
  window.addEventListener("resize", () => {
    if (window.innerWidth > 720 && burgerBtn.getAttribute("aria-expanded") === "true") {
      closeMenu();
    }
  });
}

/**
 * Stats Count-Up Animation
 * Easing: easeOutCubic
 * Duration: 1500 + i * 80 ms
 * Start Offset: 480 + i * 90 ms
 * Triggered once via IntersectionObserver (threshold 0.25)
 */
function initStatsCountUp() {
  const statsSection = document.getElementById("stats-section");
  const statItems = document.querySelectorAll(".stat-item");

  if (!statsSection || statItems.length === 0) return;

  // Check for prefers-reduced-motion
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let hasAnimated = false;

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function animateStat(item, index) {
    const valueEl = item.querySelector(".stat-value");
    if (!valueEl) return;

    const target = parseFloat(item.dataset.target || "0");
    const suffix = item.dataset.suffix || "";
    const decimals = parseInt(item.dataset.decimals || "0", 10);

    if (prefersReducedMotion) {
      valueEl.textContent = target.toFixed(decimals) + suffix;
      return;
    }

    const duration = 1500 + index * 80;
    const startOffset = 480 + index * 90;

    setTimeout(() => {
      const startTime = performance.now();

      function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const easedProgress = easeOutCubic(progress);
        const currentValue = easedProgress * target;

        valueEl.textContent = currentValue.toFixed(decimals) + suffix;

        if (progress < 1) {
          requestAnimationFrame(update);
        } else {
          valueEl.textContent = target.toFixed(decimals) + suffix;
        }
      }

      requestAnimationFrame(update);
    }, startOffset);
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && !hasAnimated) {
          hasAnimated = true;
          statItems.forEach((item, index) => {
            animateStat(item, index);
          });
          observer.unobserve(statsSection);
        }
      });
    },
    { threshold: 0.25 }
  );

  observer.observe(statsSection);
}

/**
 * Desktop Nav Active State
 */
function initNavLinks() {
  const navLinks = document.querySelectorAll(".nav-link");
  navLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      const href = link.getAttribute("href");
      if (href && href.startsWith("#")) {
        e.preventDefault();
        navLinks.forEach((l) => l.classList.remove("active"));
        link.classList.add("active");
      }
    });
  });
}
