export function createDisposables() {
  const disposers = [];

  function add(disposer) {
    if (typeof disposer === "function") disposers.push(disposer);
    return disposer;
  }

  function listen(target, type, handler, options) {
    if (!target) return null;
    target.addEventListener(type, handler, options);
    return add(() => target.removeEventListener(type, handler, options));
  }

  function dispose() {
    while (disposers.length) {
      const disposer = disposers.pop();
      try {
        disposer();
      } catch {
        // Best-effort teardown; later disposers should still run.
      }
    }
  }

  return { add, listen, dispose };
}
