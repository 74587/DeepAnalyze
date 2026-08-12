export function buildSessionStorageKey(sessionId: string): string;
export function normalizeSessionMessages(
  messages: unknown[],
  now?: () => Date
): any[];
export function serializeSessionMessages(
  messages: any[]
): any[];
export function toServerMessages(
  messages: any[]
): any[];
export function toggleSelectedPath(
  currentPaths: Iterable<string>,
  path: string,
  selected: boolean
): Set<string>;
export function appendAdditionalRequirements(
  messages: Array<{ role: string; content?: string }>,
  requirements: string
): Array<{ role: string; content?: string }>;
