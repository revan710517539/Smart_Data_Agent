type BeforeLogoutHandler = () => Promise<void> | void;

const handlers = new Set<BeforeLogoutHandler>();

export function registerBeforeLogout(handler: BeforeLogoutHandler) {
  handlers.add(handler);
  return () => {
    handlers.delete(handler);
  };
}

export async function runBeforeLogout() {
  await Promise.allSettled([...handlers].map((handler) => Promise.resolve().then(handler)));
}
