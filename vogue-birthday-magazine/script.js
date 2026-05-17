/* ═══════════════════════════════════════════════════════════
   VOGUE BIRTHDAY MAGAZINE — PREMIUM JAVASCRIPT
   Supports double-sided pages with front & back content
   ═══════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  const loader       = document.getElementById('loader');
  const wrapper      = document.getElementById('magazine-wrapper');
  const magazine     = document.getElementById('magazine');
  const pages        = document.querySelectorAll('.page');
  const btnPrev      = document.getElementById('nav-prev');
  const btnNext      = document.getElementById('nav-next');
  const currentNum   = document.getElementById('current-page-num');
  const totalNum     = document.getElementById('total-pages-num');
  const keyboardHint = document.getElementById('keyboard-hint');

  const totalPages   = pages.length;
  let currentPage    = 0;
  let isAnimating    = false;
  const FLIP_DURATION = 1000;

  const musicToggle = document.getElementById('music-toggle');
  const bgMusic     = document.getElementById('bg-music');
  const iconPlay    = musicToggle.querySelector('.icon-play');
  const iconPause   = musicToggle.querySelector('.icon-pause');

  const videoLeft  = document.getElementById('video-left');
  const videoRight = document.getElementById('video-right');

  function init() {
    totalNum.textContent = totalPages;
    setupZIndex();
    updateNavState();
    bindEvents();
    setupMusic();
    setupVideoSync();
    startLoader();
  }

  function setupVideoSync() {
    if (!videoLeft || !videoRight) return;

    // Sync play/pause
    const syncPlay = () => {
      videoLeft.play();
      videoRight.play();
    };
    const syncPause = () => {
      videoLeft.pause();
      videoRight.pause();
    };

    // Keep currentTime in sync
    videoLeft.addEventListener('timeupdate', () => {
      if (Math.abs(videoLeft.currentTime - videoRight.currentTime) > 0.1) {
        videoRight.currentTime = videoLeft.currentTime;
      }
    });

    // Start playing when the magazine is revealed or when the specific page is reached
    // For now, we'll try to play them both whenever the magazine is active
  }

  function setupMusic() {
    musicToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      if (bgMusic.paused) {
        bgMusic.play();
        iconPlay.classList.add('hidden');
        iconPause.classList.remove('hidden');
      } else {
        bgMusic.pause();
        iconPlay.classList.remove('hidden');
        iconPause.classList.add('hidden');
      }
    });

    // Optional: Start music on first click if not already playing
    document.addEventListener('click', () => {
      if (bgMusic.paused && iconPause.classList.contains('hidden')) {
        // We don't force play here as it might be intrusive, 
        // but it's an option if the user wants autoplay-like behavior
      }
    }, { once: true });
  }

  function setupZIndex() {
    pages.forEach((page, i) => {
      page.style.zIndex = totalPages - i;
    });
  }

  function startLoader() {
    const allImages = document.querySelectorAll('img');
    let loaded = 0;
    const total = allImages.length;
    const minDelay = 2800;
    const startTime = Date.now();

    function tryReveal() {
      const elapsed = Date.now() - startTime;
      const remaining = Math.max(0, minDelay - elapsed);
      setTimeout(revealMagazine, remaining);
    }

    if (total === 0) { tryReveal(); return; }

    allImages.forEach(img => {
      if (img.complete) {
        loaded++;
        if (loaded >= total) tryReveal();
      } else {
        img.addEventListener('load', () => { loaded++; if (loaded >= total) tryReveal(); });
        img.addEventListener('error', () => { loaded++; if (loaded >= total) tryReveal(); });
      }
    });

    setTimeout(tryReveal, 5000);
  }

  function revealMagazine() {
    loader.classList.add('fade-out');
    setTimeout(() => {
      loader.style.display = 'none';
      wrapper.classList.remove('hidden');
      animatePageContent(0, 'front');
      showKeyboardHint();
    }, 800);
  }

  function showKeyboardHint() {
    keyboardHint.classList.remove('hidden');
    setTimeout(() => { keyboardHint.classList.add('hidden'); }, 4000);
  }

  function flipForward() {
    if (currentPage >= totalPages - 1 || isAnimating) return;
    isAnimating = true;

    const page = pages[currentPage];
    page.style.zIndex = totalPages + 2;
    page.classList.add('flipped');

    currentPage++;
    updateNavState();
    updatePageCounter();

    // When flipping forward, the back of the flipped page becomes visible
    // and the front of the next page is revealed
    setTimeout(() => {
      animatePageContent(currentPage - 1, 'back');
      animatePageContent(currentPage, 'front');
    }, 400);

    setTimeout(() => {
      page.style.zIndex = 0;
      isAnimating = false;
    }, FLIP_DURATION);
  }

  function flipBackward() {
    if (currentPage <= 0 || isAnimating) return;
    isAnimating = true;

    currentPage--;
    const page = pages[currentPage];
    page.style.zIndex = totalPages + 2;
    page.classList.remove('flipped');

    updateNavState();
    updatePageCounter();

    setTimeout(() => {
      animatePageContent(currentPage, 'front');
    }, 400);

    setTimeout(() => {
      page.style.zIndex = totalPages - currentPage;
      isAnimating = false;
    }, FLIP_DURATION);
  }

  function updateNavState() {
    btnPrev.disabled = currentPage <= 0;
    btnNext.disabled = currentPage >= totalPages - 1;
  }

  function updatePageCounter() {
    currentNum.textContent = currentPage + 1;
  }

  function animatePageContent(pageIndex, side) {
    const page = pages[pageIndex];
    if (!page) return;

    let container;
    if (side === 'back') {
      container = page.querySelector('.page-back');
    } else {
      container = page.querySelector('.page-front');
    }
    if (!container) return;

    const animElements = container.querySelectorAll('.anim-text, .anim-fade');
    animElements.forEach((el, i) => {
      setTimeout(() => { el.classList.add('visible'); }, i * 120);
    });

    // Auto-play videos when page is revealed
    const videos = container.querySelectorAll('video');
    videos.forEach(v => {
      v.play().catch(e => console.log("Autoplay blocked:", e));
      // Ensure the other half is also playing
      if (v.id === 'video-left' && videoRight) videoRight.play();
      if (v.id === 'video-right' && videoLeft) videoLeft.play();
    });
  }

  function bindEvents() {
    btnPrev.addEventListener('click', flipBackward);
    btnNext.addEventListener('click', flipForward);

    document.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === ' ') { e.preventDefault(); flipForward(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); flipBackward(); }
    });

    let touchStartX = 0, touchStartY = 0;
    magazine.addEventListener('touchstart', (e) => {
      touchStartX = e.changedTouches[0].clientX;
      touchStartY = e.changedTouches[0].clientY;
    }, { passive: true });

    magazine.addEventListener('touchend', (e) => {
      const dx = e.changedTouches[0].clientX - touchStartX;
      const dy = e.changedTouches[0].clientY - touchStartY;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
        if (dx < 0) flipForward(); else flipBackward();
      }
    }, { passive: true });

    magazine.addEventListener('click', (e) => {
      const rect = magazine.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const pageWidth = rect.width;
      if (clickX > pageWidth * 0.65) flipForward();
      else if (clickX < pageWidth * 0.35) flipBackward();
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
