const nativeFetch = globalThis.fetch.bind(globalThis);

globalThis.fetch = async (input, init = {}) => {
  const target = typeof input === "string" || input instanceof URL
    ? new URL(input)
    : new URL(input.url);

  if (target.hostname !== "api.anthropic.com" || target.pathname !== "/v1/messages") {
    return nativeFetch(input, init);
  }

  const headers = {};
  new Headers(init.headers ?? input.headers ?? {}).forEach((value, key) => {
    headers[key] = value;
  });

  const body = typeof init.body === "string"
    ? init.body
    : init.body
      ? Buffer.from(init.body).toString("utf8")
      : "";

  if (process.env.MOCK_ANTHROPIC_CAPTURE_URL) {
    await nativeFetch(process.env.MOCK_ANTHROPIC_CAPTURE_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        url: target.toString(),
        method: init.method ?? input.method ?? "GET",
        headers,
        body,
      }),
    });
  }

  return new Response(
    JSON.stringify({
      content: [
        {
          type: "text",
          text: process.env.MOCK_ANTHROPIC_RESPONSE_TEXT ?? "mock explanation",
        },
      ],
    }),
    {
      status: 200,
      headers: { "content-type": "application/json" },
    },
  );
};
