/** One parsed `text/event-stream` frame. */
export interface SseFrame {
  event: string;
  data: string;
}

/**
 * Parse one raw frame body (the lines between two blank-line separators).
 * Returns `null` for comment-only / empty frames (e.g. `: keepalive`).
 */
function parseFrame(raw: string): SseFrame | null {
  let event = "";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data.push(line.slice(5).replace(/^ /, ""));
    }
  }
  if (event === "" && data.length === 0) {
    return null;
  }
  return { event: event === "" ? "message" : event, data: data.join("\n") };
}

/**
 * Consume a `text/event-stream` body, invoking `onFrame` for every complete
 * frame. Frames are separated by a blank line; chunk boundaries may split a
 * frame, so the trailing partial frame is carried over into the next read.
 * A frame left unterminated when the stream closes is still dispatched.
 */
export async function parseSseStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onFrame: (frame: SseFrame) => void,
): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = parseFrame(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (frame !== null) {
        onFrame(frame);
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
  const tail = parseFrame(buffer + decoder.decode());
  if (tail !== null) {
    onFrame(tail);
  }
}
