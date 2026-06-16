/**
 * Small parsing helpers used by the plans editor and the
 * scale input. Kept in their own module so both the
 * :func:`usePlansPage` hook and the editor component can import
 * them without dragging in the React dependencies of either
 * consumer.
 */

/**
 * Parse a textual scale (e.g. ``"1:50"`` or ``"1/100"``) into a
 * numeric ratio. Returns ``null`` when the input is malformed or
 * the denominator is not a positive finite number.
 */
export function parseScaleRatio(value: string): number | null {
  const match = value.trim().match(/^1\s*[:/]\s*(\d+(?:[.,]\d+)?)$/)
  if (!match) return null
  const parsed = Number(match[1].replace(",", "."))
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

/**
 * Coerce a string input into a number, returning ``null`` for
 * empty or unparseable values. The backend expects ``null`` for
 * missing measurements so it can distinguish "user cleared the
 * field" from "user typed 0".
 */
export function numberOrNull(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}
