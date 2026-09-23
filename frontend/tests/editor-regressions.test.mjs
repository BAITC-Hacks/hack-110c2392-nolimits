import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import test from 'node:test'
import { transformWithOxc } from 'vite'

// Exercise actual component event handlers with deterministic request ordering.
// Browser layout and native focus behavior are checked separately in the UI.
const source = name => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8')
const flush = async () => { await new Promise(setImmediate); await new Promise(setImmediate) }
function harness() {
  const slots = [], effects = []; let cursor = 0; let pending = []; let confirms = 0
  const hooks = {
    React: { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) },
    useState: initial => { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value }] },
    useRef: value => { const i = cursor++; return slots[i] ||= { current: value } },
    useMemo: fn => fn(),
    useEffect: (fn, deps) => { const i = cursor++; if (!effects[i] || deps.some((dep, j) => dep !== effects[i].deps[j])) pending.push(() => { effects[i]?.cleanup?.(); effects[i] = { deps, cleanup: fn() } }) },
    window: { confirm: () => { confirms++; return true }, setTimeout, clearTimeout },
    crypto: globalThis.crypto, translateText: value => value, useI18n: () => ({ t: value => value, formatNumber: value => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value), formatDate: value => value }), RawDataEditor: () => null,
  }
  return { hooks, render: fn => { cursor = 0; const tree = fn(); const next = pending; pending = []; next.forEach(fn => fn()); return tree }, confirms: () => confirms }
}
async function component(name, env) {
  const input = source(name + '.tsx').replace(/^import\s[\s\S]*?from\s+(['"])[^'"\r\n]+\1[^\r\n]*$/gm, '').replace('export default function ', 'function ')
  const { code } = await transformWithOxc(input + `\nreturn ${name};`, name + '.tsx', { jsx: { runtime: 'classic' } })
  return Function(...Object.keys(env), code)(...Object.values(env))
}
function nodes(node, predicate, result = []) { if (!node || typeof node !== 'object') return result; if (Array.isArray(node)) node.forEach(n => nodes(n, predicate, result)); else { if (predicate(node)) result.push(node); nodes(node.props?.children, predicate, result) } return result }
function text(node) { if (node == null || typeof node === 'boolean') return ''; if (typeof node !== 'object') return String(node); return Array.isArray(node) ? node.map(text).join('') : text(node.props?.children) }
function button(tree, label) { const found = nodes(tree, n => n.type === 'button' && text(n) === label)[0]; assert.ok(found, `button ${label}`); return found }
const stateCode = await transformWithOxc(source('editorState.ts').replace(/^export /gm, '') + '\nreturn { localDate, readMovementDraft, storeMovementDraft };', 'editorState.ts')
const storage = new Map()
const state = Function('sessionStorage', stateCode.code)({ getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) })

test('local calendar date is used instead of UTC date', () => {
  assert.equal(state.localDate({ getFullYear: () => 2026, getMonth: () => 8, getDate: () => 23 }), '2026-09-23')
})

test('active movement tab keeps lines; remount restores the entire document and request key', async () => {
  storage.clear()
  async function mount() {
    const h = harness()
    const C = await component('DataEditor', { ...h.hooks, ...state, getInventoryCatalog: async () => ({ products: [] }), getInventoryStock: async () => ({ rows: [] }), getInventoryMovements: async () => ({ movements: [] }), inventoryExportUrl: () => '#', postInventoryMovement: async () => { throw Error('not used') } })
    const render = () => h.render(() => C({ onToast() {}, onRefresh() {}, recommendations: [] }))
    return { h, render }
  }
  const { h, render } = await mount(); let tree = render(); await flush(); tree = render()
  button(tree, 'Движения товаров').props.onClick(); tree = render()
  nodes(tree, n => n.type === 'input' && n.props.list === 'catalog-skus')[0].props.onChange({ target: { value: 'AUDIT-SKU' } }); tree = render()
  const label = nodes(tree, n => n.type === 'label' && text(n).startsWith('Название *'))[0]
  nodes(label, n => n.type === 'input')[0].props.onChange({ target: { value: 'Audit item' } }); tree = render()
  nodes(tree, n => n.type === 'input' && n.props.inputMode === 'decimal')[0].props.onChange({ target: { value: '1500,50' } }); tree = render()
  button(tree, '＋ В документ').props.onClick(); tree = render()
  const key = state.readMovementDraft().requestId
  button(tree, 'Поступление').props.onClick(); tree = render()
  assert.equal(nodes(tree, n => n.type === 'button' && text(n) === 'Убрать').length, 1)
  assert.equal(h.confirms(), 0)
  const second = await mount(); const restored = second.render()
  assert.equal(nodes(restored, n => n.type === 'button' && text(n) === 'Убрать').length, 1)
  assert.equal(state.readMovementDraft().requestId, key)
  assert.equal(state.readMovementDraft().lines[0].unit_price, 1500.5)
})

test('late Products response cannot replace the selected Stock table', async () => {
  const h = harness(), requests = []
  const C = await component('RawDataEditor', { ...h.hooks, ...state, getEditorState: async () => ({ draft: null }), getEditorRows: (dataset, offset, limit) => limit === 50 ? new Promise(resolve => requests.push({ dataset, resolve })) : Promise.resolve({ rows: [], total: 0 }), saveEditorDraft: async () => ({}), clearEditorDraft: async () => ({}), createEditorRow: async () => ({}), updateEditorRow: async () => ({}), deleteEditorRow: async () => ({}), editorExportUrl: () => '#' })
  const render = () => h.render(() => C({ onToast() {}, onRefresh() {} }))
  let tree = render(); await flush(); tree = render()
  button(tree, 'stockstockDescription').props.onClick(); tree = render()
  requests.find(r => r.dataset === 'stock').resolve({ rows: [{ row_id: 42, sku: 'CORRECT-STOCK', warehouse: 'WH-A', current_stock: 10 }], total: 1 }); await flush(); tree = render()
  requests.find(r => r.dataset === 'products').resolve({ rows: [{ row_id: 12, sku: 'STALE-PRODUCT' }], total: 1 }); await flush(); tree = render()
  assert.ok(text(tree).includes('CORRECT-STOCK'))
  assert.ok(!text(tree).includes('STALE-PRODUCT'))
})

test('chart periods use different history windows and retain the forecast', async () => {
  const input = source('chart.ts').replace(/^import[^\r\n]*$/gm, '').replace(/^export /gm, '')
  const { code } = await transformWithOxc(input + '\nreturn prepareChartPoints;', 'chart.ts')
  const prepare = Function(code)()
  const points = Array.from({ length: 181 }, (_, i) => ({ date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10), actual_sales: i, adjusted_demand: i }))
  const future = { date: '2026-07-01', actual_sales: null, adjusted_demand: null, forecast: 42 }
  points.push(future)
  assert.equal(prepare(points, 'day').length, 2)
  assert.equal(prepare(points, 'week').length, 8)
  assert.notDeepEqual(prepare(points, 'week'), prepare(points, '3m'))
  assert.deepEqual(prepare(points, '9m').at(-1), future)
})

test('dashboard navigation, actions and static copy have English and Kazakh translations', async () => {
  const dictionaryCode = await transformWithOxc(source('dashboardTranslations.ts').replace(/^export /gm, '') + '\nreturn dashboardTranslations;', 'dictionary.ts')
  const dictionary = Function(dictionaryCode.code)()
  const input = source('i18n.tsx').replace(/^import[^\r\n]*$/gm, '').replace(/^export /gm, '')
  const { code } = await transformWithOxc(input + '\nreturn translateText;', 'i18n.tsx', { jsx: { runtime: 'classic' } })
  const texts = new Set()
  for (const file of ['App', 'DataEditor', 'DataPages', 'Procurement', 'ItemDetail', 'OrderHistory', 'ui']) {
    for (const match of source(file + '.tsx').matchAll(/translateText\(["']([^"']+)["']\)/g)) texts.add(match[1])
  }
  for (const locale of ['en', 'kk']) {
    const translate = Function('createContext', 'window', 'dashboardTranslations', code)(() => null, { localStorage: { getItem: key => key === 'stockpilot.locale' ? locale : '{}' } }, dictionary)
    for (const text of texts) if (/[А-Яа-яЁё]/.test(text)) {
      assert.ok(translate(text).length, `${locale} translation empty: ${text}`)
      if (locale === 'en') assert.doesNotMatch(translate(text), /[А-Яа-яЁё]/, text)
    }
    assert.ok(!translate('Операция сохранена: {count} позиций. Excel обновлён.', { count: 3 }).includes('{count}'))
  }
})
