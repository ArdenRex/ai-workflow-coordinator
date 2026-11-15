// Mirrors the server's rule (app/kernel/permissions.py): exact match, a trailing wildcard such as "audit:*", or "*".
// The server stays the authority; this only decides which buttons to show.
export function permissionMatches(granted, required) {
  if (granted === required || granted === "*") return true;
  return granted.endsWith(":*") && required.startsWith(granted.slice(0, -1));
}
export const hasPermission = (list, required) => Array.isArray(list) && list.some((g) => permissionMatches(g, required));
