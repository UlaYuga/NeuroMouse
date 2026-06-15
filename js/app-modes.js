export function resolveAppModes(params) {
  const searchParams = params instanceof URLSearchParams ? params : new URLSearchParams(params);
  const backendMode = searchParams.has("backend") && searchParams.get("backend") !== "0";
  const privateMethodsMode = !backendMode && searchParams.get("privateMethods") !== "0";
  return { backendMode, privateMethodsMode };
}
