export function localDate(value = new Date()): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

export const MOVEMENT_DRAFT_KEY = 'basqar.movement-draft.v1'

export function readMovementDraft<T>(): Partial<T> {
  try { return JSON.parse(sessionStorage.getItem(MOVEMENT_DRAFT_KEY) || '{}') as Partial<T> }
  catch { return {} }
}

export function storeMovementDraft(value: unknown): void {
  try { sessionStorage.setItem(MOVEMENT_DRAFT_KEY, JSON.stringify(value)) } catch { /* The active form still works if storage is disabled. */ }
}
