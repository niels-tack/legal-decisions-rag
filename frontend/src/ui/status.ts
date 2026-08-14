/**
 * Update the status/loading line. Kept as a single small helper rather than
 * a state-management library, per the "no heavy framework" preference.
 *
 * @param element - The status element (`role="status"` for accessibility).
 * @param message - Text to show, or an empty string to clear it.
 */
export function setStatus(element: HTMLElement, message: string): void {
  element.textContent = message;
}
