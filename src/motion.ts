/** Decorative motion only: content and controls never depend on animation. */
export function initMotion() {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const precise = matchMedia('(hover: hover) and (pointer: fine)');
  const progress = document.querySelector<HTMLElement>('.reading-progress');
  const hero = document.querySelector<HTMLElement>('.hero');
  const grid = document.querySelector<HTMLElement>('#feed-grid');
  let frame = 0;
  let active: HTMLElement | null = null;
  let pointer: { x: number; y: number } | null = null;
  const animated = new Set<Animation>();
  const revealed = new Set<string>();
  const play = (el: Element, frames: Keyframe[], options: KeyframeAnimationOptions) => {
    if (reduced.matches) return;
    const animation = el.animate(frames, options);
    animated.add(animation);
    animation.finished.catch(() => {}).finally(() => animated.delete(animation));
  };
  const resetPointer = () => {
    active?.classList.remove('pointer-active');
    active?.style.removeProperty('--tilt-x');
    active?.style.removeProperty('--tilt-y');
    active = null;
    pointer = null;
  };
  const update = () => {
    frame = 0;
    const max = document.documentElement.scrollHeight - innerHeight;
    if (progress)
      progress.style.transform =
        'scaleX(' + (max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0) + ')';
    document.querySelector('.site-header')?.classList.toggle('is-scrolled', scrollY > 20);
    if (!active || !pointer || reduced.matches || !precise.matches) return;
    const rect = active.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (pointer.x - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (pointer.y - rect.top) / rect.height));
    active.style.setProperty('--hero-x', (x - 0.5) * 15 + 'px');
    active.style.setProperty('--hero-y', (y - 0.5) * 15 + 'px');
    active.style.setProperty('--spot-x', x * 100 + '%');
    active.style.setProperty('--spot-y', y * 100 + '%');
    active.style.setProperty('--tilt-x', (0.5 - y) * 3 + 'deg');
    active.style.setProperty('--tilt-y', (x - 0.5) * 3 + 'deg');
    active.classList.add('pointer-active');
  };
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(update);
  };
  document.addEventListener(
    'pointermove',
    (event) => {
      if (reduced.matches || !precise.matches || event.pointerType === 'touch') return;
      const target =
        event.target instanceof Element
          ? event.target.closest<HTMLElement>('.hero, .news-card')
          : null;
      if (active !== target) {
        resetPointer();
        active = target;
      }
      pointer = { x: event.clientX, y: event.clientY };
      schedule();
    },
    { passive: true },
  );
  document.addEventListener('pointerleave', resetPointer);
  window.addEventListener('blur', resetPointer);
  window.addEventListener(
    'scroll',
    () => {
      resetPointer();
      schedule();
    },
    { passive: true },
  );
  window.addEventListener('resize', schedule, { passive: true });
  new ResizeObserver(schedule).observe(document.body);
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        const key = entry.target.querySelector<HTMLAnchorElement>('.card-title')?.href;
        if (key && revealed.has(key)) continue;
        if (key) revealed.add(key);
        play(
          entry.target,
          [
            { opacity: 0.5, translate: '0 18px' },
            { opacity: 1, translate: '0 0' },
          ],
          { duration: 520, easing: 'cubic-bezier(.2,.7,.2,1)' },
        );
      }
    },
    { threshold: 0.08 },
  );
  const watchCards = () => {
    observer.disconnect();
    document
      .querySelectorAll('.news-card:not(.skeleton)')
      .forEach((card) => observer.observe(card));
  };
  if (grid) new MutationObserver(watchCards).observe(grid, { childList: true });
  watchCards();
  if (hero)
    play(
      hero,
      [
        { opacity: 0.6, translate: '0 12px' },
        { opacity: 1, translate: '0 0' },
      ],
      { duration: 650, easing: 'ease-out' },
    );
  document.addEventListener('click', (event) => {
    const button =
      event.target instanceof Element ? event.target.closest('button, .primary-button') : null;
    if (!button || !button.isConnected || button.hasAttribute('disabled')) return;
    play(button, [{ scale: '1' }, { scale: '.96', offset: 0.35 }, { scale: '1' }], {
      duration: 240,
      easing: 'ease-out',
    });
  });
  const stopMotion = () => {
    resetPointer();
    if (reduced.matches) for (const animation of animated) animation.cancel();
  };
  reduced.addEventListener('change', stopMotion);
  precise.addEventListener('change', stopMotion);
  schedule();
}
