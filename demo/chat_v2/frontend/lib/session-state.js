function buildSessionStorageKey(sessionId) {
  return `chat_messages_v2:${String(sessionId || "default")}`;
}

function normalizeSessionMessages(messages, now = () => new Date()) {
  if (!Array.isArray(messages)) return [];
  return messages
    .filter((message) => message && (message.role || message.sender))
    .map((message, index) => {
      const role = message.role || (message.sender === "user" ? "user" : "assistant");
      return {
        id: String(message.id || `restored-${index}`),
        content: String(message.content || ""),
        sender: role === "user" ? "user" : "ai",
        timestamp: message.timestamp ? new Date(message.timestamp) : now(),
        attachments: Array.isArray(message.attachments) ? message.attachments : undefined,
        ...(message.localOnly ? { localOnly: true } : {}),
      };
    });
}

function serializeSessionMessages(messages) {
  if (!Array.isArray(messages)) return [];
  return messages.map((message) => ({
    ...message,
    timestamp:
      message.timestamp instanceof Date
        ? message.timestamp.toISOString()
        : new Date(message.timestamp).toISOString(),
  }));
}

function toServerMessages(messages) {
  return serializeSessionMessages(messages)
    .filter((message) => !message.localOnly)
    .map((message) => ({
      id: message.id,
      role: message.sender === "user" ? "user" : "assistant",
      content: message.content,
      timestamp: message.timestamp,
      attachments: message.attachments || [],
    }));
}

function toggleSelectedPath(currentPaths, path, selected) {
  const next = new Set(currentPaths || []);
  if (selected) next.add(path);
  else next.delete(path);
  return next;
}

function appendAdditionalRequirements(messages, requirements) {
  const trimmed = String(requirements || "").trim();
  const next = Array.isArray(messages) ? messages.map((message) => ({ ...message })) : [];
  if (!trimmed) return next;
  for (let index = next.length - 1; index >= 0; index -= 1) {
    if (next[index]?.role !== "user") continue;
    const content = String(next[index].content || "").trimEnd();
    next[index].content = `${content}\n\n# Additional Requirements\n${trimmed}`;
    break;
  }
  return next;
}

module.exports = {
  buildSessionStorageKey,
  normalizeSessionMessages,
  serializeSessionMessages,
  toServerMessages,
  toggleSelectedPath,
  appendAdditionalRequirements,
};
