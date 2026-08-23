export function scheduleWeeklyReportBodyScroll(reportId: string, aligned: { current: string }) {
  if (aligned.current === reportId) return () => undefined;
  let tries = 0;
  let timer = 0;
  let userMoved = false;
  let main: HTMLElement | null = null;

  const pinTop = () => {
    if (userMoved) return;
    main = document.querySelector<HTMLElement>('[data-agent-main-shell="true"]');
    if (!main) return;
    if (main.scrollTop !== 0) main.scrollTo({ top: 0, behavior: "auto" });
  };

  const markUserMoved = () => {
    userMoved = true;
  };

  const onScroll = () => {
    if (userMoved) return;
    pinTop();
  };

  const apply = () => {
    pinTop();
    if (!main) {
      if (tries < 12) {
        tries += 1;
        timer = window.setTimeout(apply, 80);
      }
      return;
    }
    if (tries === 0) {
      main.addEventListener("wheel", markUserMoved, { passive: true, capture: true });
      main.addEventListener("touchmove", markUserMoved, { passive: true, capture: true });
      main.addEventListener("pointerdown", markUserMoved, { passive: true, capture: true });
      main.addEventListener("scroll", onScroll, { passive: true });
    }
    tries += 1;
    if (tries < 12) {
      timer = window.setTimeout(apply, 80);
      return;
    }
    aligned.current = reportId;
  };

  timer = window.setTimeout(apply, 0);
  return () => {
    window.clearTimeout(timer);
    main?.removeEventListener("wheel", markUserMoved, true);
    main?.removeEventListener("touchmove", markUserMoved, true);
    main?.removeEventListener("pointerdown", markUserMoved, true);
    main?.removeEventListener("scroll", onScroll);
  };
}
