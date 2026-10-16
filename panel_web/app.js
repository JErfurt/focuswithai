'use strict';

// ---------- утилиты ----------

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clone = (o) => (o === undefined ? undefined : JSON.parse(JSON.stringify(o)));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const MASK = '••••••••';

function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}
const pad = (n) => String(n).padStart(2, '0');
function hhmm(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtMS(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
const fmtHM = (sec) => { const m = Math.floor((sec || 0) / 60); return `${Math.floor(m / 60)}:${pad(m % 60)}`; };
function fmtMin(min) {
  min = Math.round(min || 0);
  if (min < 60) return `${min} мин`;
  return `${Math.floor(min / 60)} ч ${pad(min % 60)} мин`;
}
const isToday = (ts) => ts && new Date(ts * 1000).toDateString() === new Date().toDateString();

const I = {
  x: '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6"/></svg>',
  x16: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
  chev: '<svg class="chev" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>',
  play: '<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true"><path d="M3 2l9 5-9 5z"/></svg>',
  up: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 9l4-4 4 4"/></svg>',
  down: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 5l4 4 4-4"/></svg>',
  grip: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M2 4h10M2 7h10M2 10h10"/></svg>',
  speak: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 6h2.5L9 3v10L5.5 10H3z"/><path d="M11.5 5.5a3.5 3.5 0 010 5"/></svg>',
};

// ---------- состояние ----------

const S = {
  cfg: null, defaults: {}, unknown: [], mtime: null,
  draft: null, touched: new Set(),
  sess: null, sessOrig: null,
  status: null, statusAt: 0, conn: true,
  route: 'today', loaded: {}, open: {},
  tab: { event: 'punishment', raw: 'config' },
  mem: null, tts: null, wins: null, backups: null,
  logs: [], logSeq: 0, logPaused: false,
  raw: { text: '', orig: '', lines: 0 },
  reply: null, busy: {},
};

async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opts.body); }
  if (opts.raw !== undefined) o.body = opts.raw;
  if (o.method !== 'GET') o.headers['X-Panel'] = '1';
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch (e) { /* не JSON */ }
  if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
}

// ---------- черновик настроек ----------

function getP(o, p) {
  for (const k of p.split('.')) {
    if (o == null || typeof o !== 'object') return undefined;
    o = o[k];
  }
  return o;
}
function setP(o, p, v) {
  const ks = p.split('.');
  let c = o;
  for (const k of ks.slice(0, -1)) {
    if (typeof c[k] !== 'object' || c[k] === null || Array.isArray(c[k])) c[k] = {};
    c = c[k];
  }
  if (v === undefined) delete c[ks[ks.length - 1]];
  else c[ks[ks.length - 1]] = v;
}
function eff(p, src = S.draft) {
  const v = getP(src, p);
  return v !== undefined ? v : clone(getP(S.defaults, p));
}
function setv(p, v) {
  setP(S.draft, p, v);
  S.touched.add(p);
  updateDirty();
}
const dirtyPaths = () => [...S.touched].filter((p) => !same(eff(p), eff(p, S.cfg)));
const sessDirty = () => S.sess && !same(S.sess, S.sessOrig);
const dirtyCount = () => dirtyPaths().length + (sessDirty() ? 1 : 0);
const live = () => !!(S.status && S.status.live);

function loadCfg(r) {
  S.cfg = r.config; S.defaults = r.defaults; S.unknown = r.unknown; S.mtime = r.mtime;
  S.draft = clone(r.config); S.touched.clear();
}

async function saveAll() {
  const paths = dirtyPaths();
  const set = {}, unset = [];
  for (const p of paths) {
    let v = getP(S.draft, p);
    if (Array.isArray(v) && v.every((x) => typeof x === 'string')) v = v.map((x) => x.trim()).filter(Boolean);
    if (v === undefined) unset.push(p); else set[p] = v;
  }
  let cfgSaved = false, sessSaved = false;
  try {
    if (paths.length) { loadCfg(await api('/api/config', { method: 'PUT', body: { set, unset } })); cfgSaved = true; }
    if (sessDirty()) {
      const r = await api('/api/sessions', { method: 'PUT', body: { sessions: S.sess } });
      S.sess = r.sessions; S.sessOrig = clone(r.sessions); sessSaved = true;
    }
  } catch (e) {
    toast(e.message, { bad: true });
    return;
  }
  render();
  if (cfgSaved) toast('Сохранено. Новые настройки заработают после перезапуска.', live() ? { action: ['Перезапустить', restart] } : {});
  else if (sessSaved) toast(live() ? 'Расписание сохранено и уже действует' : 'Расписание сохранено');
}

function revertAll() {
  S.draft = clone(S.cfg); S.touched.clear();
  S.sess = clone(S.sessOrig);
  render();
}

function saveBar() {
  const n = dirtyCount();
  if (!n) return '<div class="savebar" id="savebar">Всё сохранено</div>';
  return `<div class="savebar" id="savebar"><span class="cnt"><span class="dot warn"></span>${n} ${plural(n, 'изменение', 'изменения', 'изменений')}</span>
    <button class="btn" type="button" data-act="revert">Отменить</button>
    <button class="btn dark" type="button" data-act="save">Сохранить</button></div>`;
}
function updateDirty() {
  const el = $('#savebar');
  if (el) el.outerHTML = saveBar();
  const d = new Set(dirtyPaths());
  $$('[data-k]').forEach((f) => {
    if (f.type !== 'radio' && f.type !== 'checkbox' && f.type !== 'range') f.classList.toggle('changed', d.has(f.dataset.k));
  });
}

// ---------- построители полей ----------

let uid = 0;
const nid = () => `f${++uid}`;

function row(label, help, key, ctl, id) {
  return `<div class="row"><div class="lbl">${id ? `<label for="${id}">${label}</label>` : `<div class="t">${label}</div>`}${help ? `<div class="help">${help}</div>` : ''}${key ? `<div class="key">${key}</div>` : ''}</div><div class="ctl">${ctl}</div></div>`;
}
function num(k, o = {}) {
  const int = o.int !== false;
  return `<input${o.id ? ` id="${o.id}"` : ''} class="field num${o.sm ? ' sm' : ''}" type="number" data-k="${k}" data-t="num"${o.scale ? ` data-scale="${o.scale}"` : ''}${o.opt ? ' data-opt="1"' : ''}${int ? ' data-int="1"' : ''} step="${o.step || (int && !o.scale ? 1 : 'any')}"${o.min !== undefined ? ` min="${o.min}"` : ''}${o.max !== undefined ? ` max="${o.max}"` : ''}${o.label ? ` aria-label="${esc(o.label)}"` : ''}${o.ph ? ` placeholder="${esc(o.ph)}"` : ''}${o.style ? ` style="${o.style}"` : ''}>`;
}
function txt(k, o = {}) {
  return `<input${o.id ? ` id="${o.id}"` : ''} class="field${o.mono ? ' mono' : ''}" type="${o.secret ? 'password' : 'text'}" data-k="${k}" data-t="str" autocomplete="off" spellcheck="false"${o.ph ? ` placeholder="${esc(o.ph)}"` : ''}${o.label ? ` aria-label="${esc(o.label)}"` : ''}${o.list ? ` list="${o.list}"` : ''} style="${o.style || 'max-width: 420px; width: 100%'}">`;
}
function area(k, rows, o = {}) {
  return `<textarea${o.id ? ` id="${o.id}"` : ''} class="area" rows="${rows}" data-k="${k}" data-t="str"${o.label ? ` aria-label="${esc(o.label)}"` : ''}></textarea>`;
}
function tog(k, label, extra = '') {
  return `<label class="togl"><input class="tog" type="checkbox" data-k="${k}" data-t="bool">${label}${extra}</label>`;
}
function sel(k, options, o = {}) {
  return `<select${o.id ? ` id="${o.id}"` : ''} class="field${o.mono ? ' mono' : ''}" data-k="${k}" data-t="${o.t || 'str'}" style="max-width: ${o.w || 220}px">${options.map(([v, l]) => `<option value="${esc(v)}">${esc(l ?? v)}</option>`).join('')}</select>`;
}
function pills(k, options, o = {}) {
  return `<div class="pills" role="radiogroup" aria-label="${esc(o.label || k)}">${options.map(([v, l]) => `<label class="pill"><input type="radio" name="${k}" value="${esc(v)}" data-k="${k}" data-t="${o.t || 'str'}">${esc(l)}</label>`).join('')}</div>`;
}
function rangeF(k, o = {}) {
  const out = nid();
  return `<div class="inl" style="max-width: 420px; gap: 14px"><input type="range" min="${o.min ?? 0}" max="${o.max ?? 100}" step="1" data-k="${k}" data-t="num" data-scale="${o.scale}" data-out="${out}" aria-label="${esc(o.label || k)}" style="flex: 1; accent-color: var(--focus); height: 44px"><span id="${out}" class="mono" style="font-size: 14px; min-width: 48px; text-align: right"></span></div>`;
}
function jsonF(k, o = {}) {
  return `<input class="field mono" type="text" data-k="${k}" data-t="json" spellcheck="false"${o.label ? ` aria-label="${esc(o.label)}"` : ''} style="width: 100%; max-width: 520px">`;
}
const lw = (k, kind, o = {}) => `<div class="lw" data-lw="${k}" data-kind="${kind}" data-ph="${esc(o.ph || '')}" data-add="${esc(o.add || '')}" data-name="${esc(o.name || 'Элемент')}"></div>`;
function det(id, summary, body, o = {}) {
  const open = S.open[id] ?? !!o.open;
  return `<details class="${o.cls || 'card'}" data-det="${id}"${open ? ' open' : ''}><summary><span class="t"><b>${summary}</b>${o.sub ? `<span>${o.sub}</span>` : ''}</span>${I.chev}</summary>${body}</details>`;
}

function fmtOut(el) {
  const v = Number(el.value) * Number(el.dataset.scale || 1);
  const out = $(`#${el.dataset.out}`);
  if (out) out.textContent = Number(el.dataset.scale) === 0.01 && el.dataset.k === 'reminder_volume' ? `${el.value}%` : v.toFixed(2);
}

function hydrate(root) {
  $$('[data-k]', root).forEach((el) => {
    const k = el.dataset.k, t = el.dataset.t;
    let v = eff(k);
    if (k === 'ai_provider' && v === 'gemini') v = 'google_assistant';
    if (el.type === 'radio') el.checked = String(v ?? '') === el.value;
    else if (el.type === 'checkbox') el.checked = !!v;
    else if (t === 'num') {
      el.value = v === undefined || v === null || v === '' ? '' : String(+(v / Number(el.dataset.scale || 1)).toFixed(4));
      if (el.dataset.out) fmtOut(el);
    } else if (t === 'json') el.value = v === undefined ? '' : JSON.stringify(v);
    else if (el.tagName === 'SELECT') {
      if (![...el.options].some((op) => op.value === String(v))) el.add(new Option(String(v), String(v)));
      el.value = String(v);
    } else el.value = v ?? '';
  });
  $$('.lw', root).forEach(renderLW);
  updateDirty();
}

function onField(el) {
  const k = el.dataset.k, t = el.dataset.t;
  let v;
  if (el.type === 'radio') {
    if (!el.checked) return;
    v = t === 'int' ? parseInt(el.value, 10) : el.value;
  } else if (el.type === 'checkbox') v = el.checked;
  else if (t === 'num') {
    if (el.value === '') {
      if (!el.dataset.opt) { el.classList.add('bad'); return; }
      v = undefined;
    } else {
      let n = Number(el.value);
      if (!Number.isFinite(n)) { el.classList.add('bad'); return; }
      n *= Number(el.dataset.scale || 1);
      v = el.dataset.int ? Math.round(n) : +n.toFixed(6);
    }
    if (el.dataset.out) fmtOut(el);
  } else if (t === 'json') {
    try { v = el.value.trim() === '' ? undefined : JSON.parse(el.value); } catch (e) { el.classList.add('bad'); return; }
  } else if (t === 'int') v = parseInt(el.value, 10);
  else v = el.value;
  el.classList.remove('bad');
  setv(k, v);
  if (el.dataset.rerender) render();
}

// Списки строк: строки с полями ввода или «чипсы»
function renderLW(el) {
  const k = el.dataset.lw, kind = el.dataset.kind, name = el.dataset.name;
  const items = eff(k) || [];
  if (kind === 'rows') {
    el.innerHTML = `<div class="lrows">${items.map((s, i) => `<div class="li"><input class="field sm" type="text" value="${esc(s)}" data-li="${i}" aria-label="${esc(name)} ${i + 1}"><button class="ico" type="button" data-lwdel="${i}" aria-label="Удалить">${I.x}</button></div>`).join('')}</div>
      <div class="inl" style="margin-top: 6px"><button class="btn" type="button" data-lwadd>+ ${esc(el.dataset.add || 'Добавить')}</button></div>`;
  } else {
    el.innerHTML = `<div class="chips">${items.map((s, i) => `<span class="chip">${esc(s)}<button type="button" data-lwdel="${i}" aria-label="Убрать ${esc(s)}">${I.x}</button></span>`).join('') || '<span class="note">Список пуст</span>'}</div>
      <div class="inl" style="margin-top: 12px"><input class="field" type="text" data-lwnew placeholder="${el.dataset.ph}" aria-label="${esc(el.dataset.ph || 'Добавить')}" style="flex: 1 1 260px"><button class="btn" type="button" data-lwadd>Добавить</button></div>`;
  }
}
function lwAdd(el, value) {
  const k = el.dataset.lw, items = clone(eff(k) || []);
  if (el.dataset.kind === 'rows') {
    items.push('');
    setv(k, items); renderLW(el);
    const inputs = $$('[data-li]', el);
    inputs[inputs.length - 1].focus();
    return;
  }
  const input = $('[data-lwnew]', el);
  const v = (value ?? input.value).trim();
  if (!v) { input.focus(); return; }
  if (!items.includes(v)) items.push(v);
  setv(k, items); renderLW(el);
  $('[data-lwnew]', el).focus();
}

// ---------- навигация ----------

const NAV = [
  ['Работа', [['today', 'Сегодня'], ['schedule', 'Расписание'], ['rules', 'Правила фокуса']]],
  ['Ассистент', [['assistant', 'Характер и реплики'], ['model', 'Модель'], ['voice', 'Голос']]],
  ['Система', [['memory', 'Память ассистента'], ['system', 'Discord и отладка'], ['files', 'config.json вручную']]],
];
const TITLES = Object.fromEntries(NAV.flatMap(([, items]) => items));
const PROVIDERS = { openai: 'OpenAI-совместимый API', llama: 'llama.cpp /completion', google_assistant: 'Google Gemini' };
const normProv = (p) => (p === 'gemini' ? 'google_assistant' : p);

function statusLine() {
  const st = S.status;
  if (!S.conn) return '<span class="dot warn"></span>Нет связи с панелью';
  if (!st) return '<span class="dot off"></span>Подключение…';
  if (!st.live) return '<span class="dot off"></span>Трекер не запущен';
  if (st.paused) return '<span class="dot warn"></span>Пауза';
  const b = st.block;
  if (!b) return '<span class="dot on"></span>Работает';
  const end = st.now + b.remaining_s;
  return `<span class="dot ${b.focus ? 'on' : 'off'}"></span>Работает · ${b.focus ? 'фокус' : 'перерыв'} до ${hhmm(end)}`;
}

function renderNav() {
  if (!S.cfg) { $('#nav').innerHTML = '<div class="brand"><b>workReminder</b></div>'; return; }
  const counts = {
    schedule: S.sess ? `${S.sess.length} ${plural(S.sess.length, 'блок', 'блока', 'блоков')}` : '',
    rules: `${(eff('target_apps') || []).length} прил.`,
    model: ({ openai: eff('openai_model'), google_assistant: eff('google_model'), llama: 'llama.cpp' })[normProv(eff('ai_provider'))] || '',
    voice: ((eff('tts_engines') || [])[0] || '—').replace(/^./, (c) => c.toUpperCase()),
  };
  const saved = S.mtime ? (isToday(S.mtime) ? `в ${hhmm(S.mtime)}` : new Date(S.mtime * 1000).toLocaleDateString('ru-RU')) : '—';
  setHtml($('#nav'), `
    <div class="brand"><b>workReminder</b><div class="st">${statusLine()}</div></div>
    ${NAV.map(([group, items]) => `<div class="navg"><h2>${group}</h2>${items.map(([id, title]) => `<a href="#/${id}"${S.route === id ? ' aria-current="page"' : ''}>${title}${counts[id] ? `<span>${esc(counts[id])}</span>` : ''}</a>`).join('')}</div>`).join('')}
    <div class="side-foot"><div>Конфиг сохранён ${saved}</div>
      ${live() ? '<button class="btn wide" type="button" data-act="restart">Перезапустить скрипт</button>' : '<div>Трекер запускается через <span class="mono">start.bat</span></div>'}</div>`);
}

// Опрос идёт каждые 2 секунды: DOM меняется только когда разметка правда другая,
// иначе кнопки под курсором пересоздавались бы и клики терялись
function setHtml(el, html) {
  if (el._html === html) return false;
  el._html = html;
  el.innerHTML = html;
  return true;
}

function routeFromHash() {
  const r = location.hash.replace(/^#\/?/, '');
  return TITLES[r] ? r : 'today';
}

function render() {
  renderNav();
  const page = PAGES[S.route];
  const main = $('#main');
  main.className = `main${page.narrow ? ' narrow' : ''}`;
  if (!S.cfg) { main.innerHTML = '<div class="loading">Загрузка…</div>'; return; }
  if (page.load && !S.loaded[S.route]) {
    S.loaded[S.route] = true;
    page.load().then(() => { if (S.route) render(); }).catch((e) => toast(e.message, { bad: true }));
  }
  const html = page.render();
  main._html = html;
  main.innerHTML = html;
  document.title = `${TITLES[S.route]} — workReminder`;
  hydrate(main);
  if (page.after) page.after();
}

// ---------- Сегодня ----------

function classifyEvent(text) {
  const m = /^отвлечение на (.+) \((\d+) с\)$/.exec(text);
  if (m) return ['отвлечение', 'k-d', `${m[1]} — ${m[2]} с`];
  if (/^(завершена|закончился)/.test(text)) return ['сессия', 'k-s', text.replace(/^./, (c) => c.toUpperCase())];
  if (/^похвала/.test(text)) return ['похвала', 'k-s', text.replace(/^похвала /, 'Похвала ')];
  if (/^рассказан факт/.test(text)) return ['факт', 'k-a', 'Рассказан интересный факт'];
  return ['событие', 'k-a', text];
}

function remaining() {
  const b = S.status && S.status.block;
  if (!b) return 0;
  const passed = S.status.paused ? 0 : (Date.now() - S.statusAt) / 1000;
  return Math.max(0, b.remaining_s - passed);
}

function planBlocks(st) {
  const sess = st.sessions || [];
  const b = st.block, idx = b ? b.index : -1;
  return sess.map((s, i) => {
    const kind = s.focus ? 'f' : 'b';
    const label = `${s.focus ? 'Фокус' : 'Перерыв'}${s.name ? ` «${s.name}»` : ''}, ${s.min} мин`;
    if (i < idx) return `<div class="${kind} done" style="flex: ${s.min}" title="${esc(label)}, завершён"></div>`;
    if (i === idx) {
      return `<div class="cur ${kind}" style="flex: ${b.min + b.extra_min}" title="${esc(label)}, идёт"><i data-plancur></i></div>`;
    }
    return `<div class="${kind} next" style="flex: ${s.min}" title="${esc(label)}"></div>`;
  }).join('');
}

const PAGES = {};

PAGES.today = {
  render() {
    const st = S.status;
    if (!st) return '<div class="loading">Загрузка…</div>';
    const sess = st.sessions || [];
    const d = new Date();
    const date = d.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' });
    const header = `<header class="ph"><h1>Сегодня</h1><div class="sub" style="margin: 0">${date}</div></header>`;
    const b = st.block;
    let top = '';
    if (!st.live) {
      top = `<div class="offline"><div style="display: flex; flex-direction: column; gap: 4px"><b>Трекер не запущен</b><span class="help">Панель открыта отдельно и работает только с файлами. Запусти <code>start.bat</code> или <code>python main.py</code> — тогда здесь появится таймер и управление.</span></div></div>`;
    } else if (!b) {
      top = '<div class="offline"><b>План пуст</b><a class="btn" href="#/schedule">Добавить блоки</a></div>';
    } else {
      const next = sess[b.index + 1];
      top =`<div class="grid">
        <section class="card pad span2" aria-labelledby="cur" style="display: flex; flex-direction: column; gap: 20px">
          <div style="display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; align-items: flex-start">
            <div style="display: flex; flex-direction: column; gap: 4px">
              <h2 id="cur" class="lbl-sm">Текущий блок · ${b.index + 1} из ${sess.length}${st.paused ? ' · на паузе' : ''}</h2>
              <div style="font-size: 22px; font-weight: 600"><span style="color: ${b.focus ? 'var(--focus)' : 'var(--warn-text)'}">${b.focus ? 'Фокус' : 'Перерыв'}</span> ${b.min + b.extra_min} минут${b.name ? ` <span style="font-weight: 400; color: var(--muted)">· ${esc(b.name)}</span>` : ''}</div>
            </div>
            <div class="timer" id="timer"${st.paused ? ' style="color: var(--muted)"' : ''}></div>
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px">
            <div class="bar${b.focus ? '' : ' brk'}"><div id="tbar"></div></div>
            <div class="mono" style="display: flex; justify-content: space-between; font-size: 13px; color: var(--muted)"><span>${hhmm(b.started_at)}</span><span id="tend"></span></div>
          </div>
          <div class="inl" style="gap: 10px">
            ${st.paused ? '<button class="btn dark" type="button" data-ctl="resume" style="min-width: 120px">Продолжить</button>' : '<button class="btn dark" type="button" data-ctl="pause" style="min-width: 120px">Пауза</button>'}
            <button class="btn" type="button" data-ctl="skip">Пропустить блок</button>
            <button class="btn" type="button" data-ctl="extend">+5 минут</button>
            <div class="help" style="margin-left: auto">${next ? `Дальше: ${next.focus ? 'фокус' : 'перерыв'} ${next.min} мин` : 'Это последний блок плана'}</div>
          </div>
        </section>
        <section class="card pad" aria-labelledby="now" style="padding-bottom: 8px; display: flex; flex-direction: column">
          <h2 id="now" class="lbl-sm" style="margin-bottom: 12px">Сейчас</h2>
          <div style="display: flex; flex-direction: column; gap: 2px; padding-bottom: 14px; border-bottom: 1px solid var(--line2)">
            <div class="note">Активное окно</div>
            <div class="ellip" style="font-weight: 600" title="${esc(st.active_window || '')}">${b.focus ? esc(st.active_window || '—') : 'не отслеживается'}</div>
            ${b.focus && st.active_window ? `<div style="font-size: 13px; font-weight: 500; color: ${st.is_target ? 'var(--focus)' : 'var(--warn-text)'}">${st.is_target ? 'рабочее приложение' : 'не рабочее'}</div>` : `<div class="note">${b.focus ? '' : 'идёт перерыв'}</div>`}
          </div>
          ${[['sound', 'Звук напоминаний'], ['ai', 'Реплики ассистента'], ['discord', 'Статус в Discord']].map(([k, l]) => `<label class="swrow"><span>${l}</span><input class="tog" type="checkbox" data-ctltog="${k}"${st.toggles[k] ? ' checked' : ''}></label>`).join('')}
          <div class="note" style="padding: 6px 0 4px">Переключатели действуют до перезапуска</div>
        </section>
      </div>`;
    }

    const planMin = sess.reduce((a, s) => a + s.min, 0);
    let range = '';
    if (st.live && b) {
      const before = sess.slice(0, b.index).reduce((a, s) => a + s.min, 0);
      const after = sess.slice(b.index + 1).reduce((a, s) => a + s.min, 0);
      range = `${hhmm(b.started_at - before * 60)} → ${hhmm(Date.now() / 1000 + remaining() + after * 60)}`;
    }
    const plan = `<section class="card pad" aria-labelledby="plan" style="display: flex; flex-direction: column; gap: 14px">
      <div class="card-top" style="align-items: baseline"><h2 id="plan" class="lbl-sm" style="padding: 0">План дня · ${fmtMin(planMin)}</h2><a href="#/schedule" style="font-size: 14px; font-weight: 500">Изменить расписание</a></div>
      ${sess.length ? `<div class="plan">${planBlocks(st)}</div>` : '<div class="empty">В расписании нет блоков</div>'}
      <div class="legend"><span><i style="background: var(--focus)"></i>фокус</span><span><i style="background: var(--break)"></i>перерыв</span>${range ? `<span class="mono">${range}</span>` : ''}</div>
    </section>`;

    const t = st.today || { focus_seconds: 0, lost_seconds: 0, distractions: 0 };
    const stats = `<section class="stats" aria-label="Итоги дня">
      <div><span>В фокусе сегодня</span><b>${fmtHM(t.focus_seconds)}</b></div>
      <div><span>Отвлечений</span><b>${t.distractions || 0}</b></div>
      <div><span>Потеряно на отвлечения</span><b>${fmtMin((t.lost_seconds || 0) / 60)}</b></div>
      <div><span>Завершено блоков</span><b>${(st.stats && st.stats.completed_sessions) || 0}</b></div>
    </section>`;

    const events = [...(st.events || [])].reverse().slice(0, 8);
    const log = events.length ? `<div class="log">${events.map(([ts, text]) => {
      const [kind, cls, shown] = classifyEvent(text);
      return `<div class="t">${hhmm(ts)}</div><div class="${cls}">${kind}</div><div>${esc(shown)}</div>`;
    }).join('')}</div>` : '<div class="empty" style="margin-bottom: 12px">Сегодня событий ещё не было</div>';

    const dist = Object.entries(st.block_distractions || {}).sort((a, b2) => b2[1] - a[1]).slice(0, 6);
    const max = dist.length ? dist[0][1] : 1;
    const attention = dist.length ? dist.map(([name, n]) => `<div class="meter"><div class="top"><span class="ellip" title="${esc(name)}">${esc(name)}</span><span class="mono">${n}</span></div><div class="trk"><div style="width: ${(n / max) * 100}%"></div></div></div>`).join('') : '<div class="empty">В этом блоке отвлечений нет</div>';

    return `${header}${top}${plan}${stats}
      <div class="grid">
        <section class="card pad span2" aria-labelledby="log" style="padding-bottom: 8px">
          <div class="card-top" style="margin-bottom: 6px"><h2 id="log" class="lbl-sm">Журнал</h2><a href="#/memory" style="font-size: 14px; font-weight: 500">Вся память</a></div>
          ${log}
        </section>
        <section class="card pad" aria-labelledby="top" style="display: flex; flex-direction: column; gap: 12px">
          <h2 id="top" class="lbl-sm">Куда уходит внимание <span class="note">· в этом блоке</span></h2>
          ${attention}
          <a href="#/rules" style="font-size: 14px; font-weight: 500; padding-top: 4px">Сделать что-то рабочим</a>
        </section>
      </div>`;
  },
  after() { tick(); },
};

// ---------- Расписание ----------

const PRESETS = [['Помодоро', 25, 5, 4], ['Длинные блоки', 45, 10, 4], ['Глубокая работа', 90, 15, 2]];

function schedTimes() {
  const st = S.status;
  const idx = live() && st.block ? st.block.index : -1;
  let t = Date.now() / 1000;
  if (idx >= 0) t = st.block.started_at;
  return S.sess.map((s, i) => {
    if (idx >= 0 && i < idx) return '';
    if (i === idx) { const start = t; t = Date.now() / 1000 + remaining(); return start === null ? '' : 'идёт'; }
    const start = t; t += s.min * 60; return hhmm(start);
  });
}
function schedSummary() {
  const f = S.sess.filter((s) => s.focus).reduce((a, s) => a + s.min, 0);
  const b = S.sess.filter((s) => !s.focus).reduce((a, s) => a + s.min, 0);
  const end = Date.now() / 1000 + (f + b) * 60;
  return `<div style="display: grid; grid-template-columns: 1fr auto; row-gap: 8px; font-size: 14px">
      <span>Фокус</span><span class="mono">${fmtMin(f)}</span>
      <span>Перерывы</span><span class="mono">${fmtMin(b)}</span>
      <span style="font-weight: 600; padding-top: 8px; border-top: 1px solid var(--line2)">Весь план</span><span class="mono" style="font-weight: 600; padding-top: 8px; border-top: 1px solid var(--line2)">${fmtMin(f + b)}</span>
    </div>
    <div class="mini">${S.sess.map((s) => `<div style="flex: ${s.min}; background: ${s.focus ? 'var(--focus)' : 'var(--break)'}"></div>`).join('')}</div>
    <div class="note">${S.sess.length ? `Если начать сейчас, план закончится в ${hhmm(end)}.` : 'Добавь хотя бы один блок.'}</div>`;
}
function refreshSched() {
  const times = schedTimes();
  $$('[data-stime]').forEach((el) => { el.textContent = times[+el.dataset.stime]; });
  const sum = $('#ssum');
  if (sum) sum.innerHTML = schedSummary();
  updateDirty();
}

PAGES.schedule = {
  render() {
    const idx = live() && S.status.block ? S.status.block.index : -1;
    const times = schedTimes();
    const rows = S.sess.map((s, i) => `<div class="srow${i === idx ? ' cur' : ''}" data-srow="${i}">
        <button class="ico handle" type="button" data-handle="${i}" aria-label="Переместить блок ${i + 1}: перетащи или нажимай стрелки">${I.grip}</button>
        <span class="n"${i === idx ? ' style="color: var(--focus); font-weight: 500"' : ''}>${i + 1}</span>
        <div class="seg" role="group" aria-label="Тип блока ${i + 1}"><button type="button" data-sfocus="${i}" data-v="1" aria-pressed="${s.focus}">Фокус</button><button type="button" data-sfocus="${i}" data-v="0" aria-pressed="${!s.focus}">Перерыв</button></div>
        <input class="field sm" type="text" data-sname="${i}" value="${esc(s.name)}" placeholder="без подписи" aria-label="Подпись блока ${i + 1}">
        <div class="inl" style="gap: 6px"><input class="field sm num" type="number" min="1" max="600" step="1" data-smin="${i}" value="${s.min}" aria-label="Минут в блоке ${i + 1}" style="width: 64px"><span style="font-size: 13px">мин</span></div>
        <span class="tm" data-stime="${i}"${i === idx ? ' style="color: var(--focus); font-weight: 600; font-family: inherit"' : ''}>${times[i]}</span>
        <button class="ico" type="button" data-sdel="${i}" aria-label="Удалить блок ${i + 1}">${I.x16}</button>
      </div>`).join('');
    return `<header class="ph"><div><h1>Расписание</h1><div class="sub">Блоки идут сверху вниз. Файл <span class="mono" style="font-size: 13px">sessions.jsonl</span>${live() ? ', изменения применяются сразу после сохранения' : ''}</div></div>${saveBar()}</header>
      <div class="grid">
        <section class="card flat span2" aria-label="Блоки">
          <div class="sched"><div class="sched-in">
            <div class="srow head"><span></span><span>№</span><span>Тип</span><span>Подпись</span><span>Длительность</span><span>Начало</span><span></span></div>
            ${rows || '<div class="empty" style="margin: 16px">Блоков нет. Добавь фокус и перерыв или выбери шаблон.</div>'}
          </div></div>
          <div class="inl" style="gap: 10px; padding: 14px 16px">
            <button class="btn" type="button" data-sadd="focus">+ Фокус</button>
            <button class="btn" type="button" data-sadd="break">+ Перерыв</button>
            <button class="btn" type="button" data-srepeat style="margin-left: auto">Повторить пару фокус + перерыв</button>
          </div>
        </section>
        <div class="col">
          <section class="card pad" aria-labelledby="sum" style="display: flex; flex-direction: column; gap: 14px">
            <h2 id="sum" class="lbl-sm" style="padding: 0">Итого</h2>
            <div id="ssum" style="display: flex; flex-direction: column; gap: 14px">${schedSummary()}</div>
          </section>
          <section class="card pad" aria-labelledby="tpl" style="display: flex; flex-direction: column; gap: 10px">
            <h2 id="tpl" class="lbl-sm" style="padding: 0 0 4px">Заменить шаблоном</h2>
            ${PRESETS.map(([n, f, b, c], i) => `<button class="btn between" type="button" data-preset="${i}">${n}<span class="hint">${f} / ${b} × ${c}</span></button>`).join('')}
            <div class="note">Текущий план можно вернуть кнопкой «Отменить», пока он не сохранён.</div>
          </section>
        </div>
      </div>`;
  },
};

function moveSess(from, to) {
  if (to < 0 || to >= S.sess.length || from === to) return;
  const [item] = S.sess.splice(from, 1);
  S.sess.splice(to, 0, item);
  render();
  const h = $(`[data-handle="${to}"]`);
  if (h) h.focus();
}

// ---------- Правила фокуса ----------

PAGES.rules = {
  narrow: true,
  load: async () => {
    S.wins = null;
    api('/api/windows').then((r) => { S.wins = r.windows; renderWins(); }).catch(() => { S.wins = []; renderWins(); });
  },
  render() {
    const sound = eff('reminder_sound');
    return `<header class="ph"><div><h1>Правила фокуса</h1><div class="sub">Что считается работой и как быстро реагировать, когда ты из неё вышел</div></div>${saveBar()}</header>
      <section class="card" aria-labelledby="apps">
        <h2 id="apps">Рабочие приложения</h2>
        ${row('Список', 'Окно считается рабочим, если его заголовок содержит одну из этих строк. Регистр букв важен.', 'target_apps', lw('target_apps', 'chips', { ph: 'Часть заголовка окна, например Figma' }))}
        ${row('Открыто сейчас', 'Окна, которые не попали в список. Нажми, чтобы сделать рабочим.', '', `<div id="wins" class="chips"><span class="note">Ищу окна…</span></div><div><button class="btn sm" type="button" data-act="wins">Обновить список</button></div>`)}
      </section>
      <section class="card" aria-labelledby="react" style="padding-bottom: 12px">
        <h2 id="react" style="padding-bottom: 4px">Когда отвлёкся</h2>
        <div class="help" style="padding-bottom: 16px">Отсчёт идёт с момента, когда рабочее окно потеряло фокус. Только во время фокус-блоков.</div>
        <div style="display: grid; grid-template-columns: 20px minmax(0, 1fr); column-gap: 18px; border-top: 1px solid var(--line2); padding-top: 20px">
          <div style="display: flex; flex-direction: column; align-items: center"><span style="width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--muted2); margin-top: 4px"></span><span style="flex: 1; width: 2px; background: var(--line); margin-top: 4px"></span></div>
          <div style="padding-bottom: 22px"><div style="font-weight: 500">Ушёл из рабочего окна</div><div class="help">0 секунд</div></div>
          <div style="display: flex; flex-direction: column; align-items: center"><span style="width: 12px; height: 12px; border-radius: 50%; background: var(--warn); margin-top: 14px"></span><span style="flex: 1; width: 2px; background: var(--line); margin-top: 4px"></span></div>
          <div class="inl" style="justify-content: space-between; gap: 12px; padding-bottom: 22px; align-items: flex-start">
            <div style="display: flex; flex-direction: column; gap: 2px"><div style="font-weight: 500">Звук напоминания</div><div class="help">Короткий сигнал, без ИИ. Повторяется, пока не вернёшься.</div><div class="key">reminder_interval</div></div>
            <div class="inl"><span>через</span>${num('reminder_interval', { label: 'Секунд до звука', min: 1 })}<span>с</span></div>
          </div>
          <div style="display: flex; flex-direction: column; align-items: center"><span style="width: 12px; height: 12px; border-radius: 50%; background: var(--ink); margin-top: 14px"></span></div>
          <div style="display: flex; flex-direction: column; gap: 14px; padding-bottom: 8px">
            <div class="inl" style="justify-content: space-between; gap: 12px; align-items: flex-start">
              <div style="display: flex; flex-direction: column; gap: 2px"><div style="font-weight: 500">Выговор от ассистента</div><div class="help">Голосом, с названием окна, где ты сидишь</div><div class="key">punishment_interval</div></div>
              <div class="inl"><span>через</span>${num('punishment_interval', { label: 'Секунд до выговора', min: 1 })}<span>с</span></div>
            </div>
            <div class="inl" style="justify-content: space-between; gap: 12px; padding: 12px 14px; background: var(--soft); border-radius: 6px">
              <div style="display: flex; flex-direction: column; gap: 2px"><div style="font-size: 14px">Следующий выговор — не раньше чем через</div><div class="key">punishment_cooldown</div></div>
              <div class="inl">${num('punishment_cooldown', { label: 'Пауза между выговорами, секунд', min: 0 })}<span>с</span></div>
            </div>
          </div>
        </div>
      </section>
      <section class="card" aria-labelledby="good">
        <h2 id="good">Когда работаешь</h2>
        ${row('Похвала', 'После непрерывной работы без отвлечений', 'praise_interval', `<div class="inl"><span>каждые</span>${num('praise_interval', { scale: 60, label: 'Минут до похвалы', min: 1 })}<span>мин</span></div>`)}
        ${row('Интересный факт', 'Короткая разминка для головы', 'interesting_fact_interval', `<div class="inl"><span>каждые</span>${num('interesting_fact_interval', { scale: 60, label: 'Минут до факта', min: 1 })}<span>мин</span></div>`)}
      </section>
      <section class="card" aria-labelledby="snd">
        <h2 id="snd">Звук напоминания</h2>
        ${row('Файл', '', 'reminder_sound', `<div class="inl" style="gap: 10px">
          <span class="ro mono">${esc(sound)}</span>
          <button class="btn" type="button" data-act="testsound">${I.play}Прослушать</button>
          <label class="btn" style="cursor: pointer">Заменить<input type="file" accept=".mp3,.wav,.ogg,audio/*" data-upload class="sr"></label>
        </div>`)}
        ${row('Громкость', '', 'reminder_volume', rangeF('reminder_volume', { scale: 0.01, label: 'Громкость напоминания' }))}
      </section>`;
  },
};

function renderWins() {
  const el = $('#wins');
  if (!el) return;
  if (S.wins === null) { el.innerHTML = '<span class="note">Ищу окна…</span>'; return; }
  const apps = eff('target_apps') || [];
  const items = S.wins.filter((w) => !apps.some((a) => w.title.includes(a))).slice(0, 16);
  el.innerHTML = items.length ? items.map((w) => `<button class="btn sm dash" type="button" data-addapp="${esc(w.name)}" title="${esc(w.title)}">+ ${esc(w.name)}</button>`).join('') : '<span class="note">Других окон не видно</span>';
}

// ---------- Характер и реплики ----------

const EVENTS = {
  punishment: { title: 'Выговор', ph: [['target', 'рабочее приложение'], ['distraction', 'окно, где сидит пользователь'], ['distracted_seconds', 'сколько секунд отвлечён'], ['count', 'какое по счёту отвлечение']] },
  praise: { title: 'Похвала', ph: [['target', 'рабочее приложение'], ['minutes', 'минут без отвлечений'], ['seconds', 'то же в секундах']] },
  fact: { title: 'Интересный факт', ph: [] },
};

PAGES.assistant = {
  narrow: true,
  render() {
    const ev = S.tab.event, E = EVENTS[ev];
    const ins = nid(), nm = nid(), pr = nid(), rl = nid();
    const r = S.reply && S.reply.event === ev ? S.reply : null;
    const ti = S.replyInputs || {};
    const tester = {
      punishment: `<label>Сидит в окне<input class="field" type="text" id="tw" value="${esc(ti.window || 'Telegram')}"></label><label>Сколько секунд<input class="field" type="number" id="ts" value="${ti.seconds || 75}" min="1"></label>`,
      praise: `<label>Минут без отвлечений<input class="field" type="number" id="tm" value="${ti.minutes || 60}" min="1"></label>`,
      fact: '<div class="note">Тема выбирается случайно из списка ниже.</div>',
    }[ev];
    const memOn = eff('ai_memory_file') !== null;
    return `<header class="ph"><div><h1>Характер и реплики</h1><div class="sub">Кто говорит, как говорит и что говорит в каждой ситуации</div></div>${saveBar()}</header>
      <section class="card" aria-labelledby="who">
        <h2 id="who">Персона</h2>
        ${row('Имя', '', 'assistant_name', txt('assistant_name', { id: nm, style: 'max-width: 280px' }), nm)}
        ${row('Характер', 'Кто она и зачем нужна. Без примеров фраз: маленькие модели их копируют.', 'prompt', area('prompt', 4, { id: pr }), pr)}
        ${row('Правила ответа', 'Добавляются к характеру в каждом запросе', 'ai_response_rules', area('ai_response_rules', 5, { id: rl }), rl)}
        ${row('Длина реплики', 'Жёсткая обрезка перед озвучкой', '', `<div class="inl gap">
            <label class="inl">не больше${num('ai_max_sentences', { min: 0, style: 'width: 64px' })}предложений <span class="key">ai_max_sentences</span></label>
            <label class="inl">и${num('ai_max_chars', { min: 20 })}символов <span class="key">ai_max_chars</span></label></div>
          ${tog('ai_drop_questions', 'Убирать вопрос в конце — ответить голосом всё равно нельзя', ' <span class="key">ai_drop_questions</span>')}`)}
      </section>
      <section class="card" aria-labelledby="ev" style="padding-bottom: 24px">
        <h2 id="ev" style="padding-bottom: 8px">Реплики по событиям</h2>
        <div class="tabs" role="tablist" aria-label="Событие">${Object.entries(EVENTS).map(([k, e]) => `<button class="tab" role="tab" type="button" data-evtab="${k}" aria-selected="${k === ev}">${e.title}</button>`).join('')}</div>
        <div class="split">
          <div style="display: flex; flex-direction: column; gap: 22px; min-width: 0">
            <div style="display: flex; flex-direction: column; gap: 8px">
              <div class="card-top"><label for="${ins}" style="font-weight: 500">Задание для модели</label><span class="key">${ev}_instruction</span></div>
              ${area(`${ev}_instruction`, 3, { id: ins })}
              ${E.ph.length ? `<div class="inl" style="gap: 6px; font-size: 13px; color: var(--muted)"><span>Вставить:</span>${E.ph.map(([p, t]) => `<button class="phb" type="button" title="${t}" data-ins="{${p}}" data-for="${ins}">{${p}}</button>`).join('')}</div>` : '<div class="note">Для фактов подстановок нет: тема и список уже рассказанного добавляются сами.</div>'}
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px">
              <div class="card-top"><div style="font-weight: 500">Подсказки стиля</div><span class="key">ai_style_hints.${ev}</span></div>
              <div class="help">К каждому запросу добавляется одна случайная, подряд не повторяются.</div>
              ${lw(`ai_style_hints.${ev}`, 'rows', { add: 'Подсказка', name: 'Подсказка' })}
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px">
              <div class="card-top"><div style="font-weight: 500">Запасные фразы</div><span class="key">fallback_phrases.${ev}</span></div>
              <div class="help">Говорятся, если модель не ответила или повторилась дважды.</div>
              ${lw(`fallback_phrases.${ev}`, 'rows', { add: 'Фраза', name: 'Фраза' })}
            </div>
          </div>
          <aside class="side-panel" aria-labelledby="try">
            <h3 id="try">Проверить на примере</h3>
            ${tester}
            <div class="inl"><button class="btn dark" type="button" data-act="reply" style="flex: 1"${S.busy.reply ? ' disabled' : ''}>${S.busy.reply ? '<span class="spin"></span>Думает…' : 'Сгенерировать'}</button>
              <button class="btn" type="button" data-act="replyspeak" aria-label="Озвучить ответ"${r && r.text ? '' : ' disabled'}>${I.speak}</button></div>
            <div class="answer">
              <div class="cap">Ответ модели</div>
              <div style="font-size: 15px; line-height: 1.5">${r ? (r.text ? esc(r.text) : `<span class="err">${esc(r.error || 'Модель вернула пустой ответ')}</span>`) : '<span class="note">Здесь появится реплика с текущими, ещё не сохранёнными настройками. Ничего не озвучивается и не попадает в память.</span>'}</div>
              ${r && r.style ? `<div class="key">стиль: «${esc(r.style)}»</div>` : ''}
            </div>
          </aside>
        </div>
      </section>
      <section class="card" aria-labelledby="topics">
        <h2 id="topics">Темы фактов</h2>
        ${row('Темы', 'Берётся случайная, недавние пропускаются', 'ai_fact_topics', lw('ai_fact_topics', 'chips', { ph: 'Новая тема' }))}
      </section>
      ${det('mem', 'Память и защита от повторов', `<div style="padding-bottom: 8px">
        ${row('История диалога', '0 — выключено. Маленькие модели копируют свои старые ответы, для них оставь 0.', 'ai_history_size', `<label class="inl">${num('ai_history_size', { min: 0 })}сообщений</label>`)}
        ${row('Журнал событий', 'Сколько последних событий модель видит списком', 'ai_event_log_size', `<label class="inl">${num('ai_event_log_size', { min: 0 })}событий</label>`)}
        ${row('Порог повтора', 'Похожесть, выше которой ответ переспрашивается', 'ai_repeat_threshold', rangeF('ai_repeat_threshold', { scale: 0.01, label: 'Порог повтора' }))}
        ${row('Бюджет контекста', 'При переполнении сам уменьшается вдвое', 'ai_context_budget', `<label class="inl">${num('ai_context_budget', { min: 200, step: 100 })}токенов</label>`)}
        ${row('Файл памяти', 'Без сохранения память живёт до перезапуска', 'ai_memory_file', `<div class="inl" style="gap: 10px">
          <input class="field mono" type="text" id="memfile" aria-label="Файл памяти" style="flex: 1 1 220px; max-width: 320px" value="${esc(memOn ? eff('ai_memory_file') : '')}"${memOn ? '' : ' disabled'} data-memfile>
          <label class="togl"><input class="tog" type="checkbox" data-memsave${memOn ? ' checked' : ''}>сохранять</label></div>`)}
      </div>`, { sub: 'Трогать, если реплики повторяются или модель теряет контекст', cls: 'card' })}`;
  },
};

// ---------- Модель ----------

function providerFields(p) {
  const id = nid();
  if (p === 'openai') {
    return `${row('Адрес сервера', '', 'openai_base_url', txt('openai_base_url', { id, mono: true }), id)}
      ${row('Модель', '', 'openai_model', `<div class="inl" style="max-width: 420px">${txt('openai_model', { mono: true, list: 'models', style: 'flex: 1 1 200px', label: 'Модель' })}<button class="btn" type="button" data-act="models">Список с сервера</button></div><datalist id="models">${(S.models || []).map((m) => `<option value="${esc(m)}">`).join('')}</datalist>${S.modelsNote ? `<div class="note">${esc(S.modelsNote)}</div>` : ''}`)}
      ${row('API-ключ', 'Для локального сервера не нужен', 'openai_api_key', txt('openai_api_key', { secret: true, mono: true, ph: 'не задан', label: 'API-ключ' }))}
      ${row('Ответ', '', '', `<label class="inl">до${num('openai_max_tokens', { min: 1 })}токенов <span class="key">openai_max_tokens</span></label>
        ${tog('openai_thinking', 'Разрешить рассуждения', ' <span class="key">openai_thinking</span>')}
        <div class="note" style="max-width: 520px">Рассуждающие модели (Qwen3, LFM2.5) могут потратить весь лимит на размышления и вернуть пустой ответ. Оставь выключенным.</div>`)}
      ${det('osamp', 'Параметры генерации', `<div class="fgrid">${['temperature', 'top_p', 'top_k', 'min_p', 'presence_penalty', 'frequency_penalty', 'repeat_penalty'].map((k) => `<label>${k}${num(`openai_${k}`, { opt: true, int: k === 'top_k', ph: 'по умолчанию', style: 'width: 100%; text-align: left' })}</label>`).join('')}</div>`, { cls: 'sub', sub: 'Пустые не отправляются — сервер берёт значения, рекомендованные авторами модели' })}`;
  }
  if (p === 'google_assistant') {
    return `${row('API-ключ', '', 'google_assistant_api_key', txt('google_assistant_api_key', { secret: true, mono: true, ph: 'не задан', label: 'API-ключ Gemini' }))}
      ${row('Модель', '', 'google_model', txt('google_model', { id, mono: true }), id)}
      ${row('Ответ', '', '', `<div class="fgrid" style="padding: 0">
        <label>max_tokens${num('google_max_tokens', { min: 1, style: 'width: 100%; text-align: left' })}</label>
        <label>temperature${num('google_temperature', { int: false, style: 'width: 100%; text-align: left' })}</label>
        <label>top_p${num('google_top_p', { int: false, style: 'width: 100%; text-align: left' })}</label>
        <label>top_k${num('google_top_k', { style: 'width: 100%; text-align: left' })}</label>
        <label>thinking_budget${num('google_thinking_budget', { opt: true, ph: 'авто', style: 'width: 100%; text-align: left' })}</label></div>
        <div class="note">Пустой thinking_budget: 0 для моделей 2.5-flash, иначе по умолчанию сервиса.</div>`)}`;
  }
  return `${row('Адрес', '', 'llama_url', txt('llama_url', { id, mono: true }), id)}
    ${row('Метка событий', 'Как подписаны события в транскрипте', 'llama_user_label', txt('llama_user_label', { style: 'max-width: 220px', label: 'Метка событий' }))}
    ${row('API-ключ', '', 'api_key', txt('api_key', { secret: true, mono: true, ph: 'не задан', label: 'API-ключ llama.cpp' }))}
    ${row('Сэмплинг', 'Остальные параметры — в config.json вручную', '', `<div class="fgrid" style="padding: 0">
      <label>n_predict${num('n_predict', { style: 'width: 100%; text-align: left' })}</label>
      <label>temperature${num('temperature', { int: false, style: 'width: 100%; text-align: left' })}</label>
      <label>top_k${num('top_k', { style: 'width: 100%; text-align: left' })}</label>
      <label>top_p${num('top_p', { int: false, style: 'width: 100%; text-align: left' })}</label>
      <label>min_p${num('min_p', { int: false, style: 'width: 100%; text-align: left' })}</label>
      <label>repeat_penalty${num('repeat_penalty', { int: false, style: 'width: 100%; text-align: left' })}</label></div>`)}
    ${row('Стоп-строки', 'JSON-список', 'stop', jsonF('stop', { label: 'Стоп-строки' }))}`;
}

PAGES.model = {
  narrow: true,
  render() {
    const main = normProv(eff('ai_provider'));
    const chain = (eff('ai_fallback_providers') || []).map(normProv).filter((p) => p !== main);
    const others = Object.keys(PROVIDERS).filter((p) => p !== main);
    const ai = S.aiTest && S.aiTest.provider === main ? S.aiTest : null;
    return `<header class="ph"><div><h1>Модель</h1><div class="sub">Откуда берутся реплики и что делать, если сервер не отвечает</div></div>${saveBar()}</header>
      <section class="card" aria-labelledby="prov" style="padding-bottom: 24px">
        <div class="card-top"><h2 id="prov">Основной провайдер</h2><span class="key">ai_provider</span></div>
        <fieldset class="opts"><legend class="sr">Провайдер</legend>
          ${[['openai', 'llama.cpp /v1, Ollama, LM Studio, vLLM, OpenRouter. Сервер сам применяет шаблон чата модели.'], ['llama', 'Сырой промпт без шаблона чата. Для старых сборок.'], ['google_assistant', 'Облако, нужен API-ключ']].map(([p, d]) => `<label class="opt"><input type="radio" name="ai_provider" value="${p}" data-k="ai_provider" data-t="str" data-rerender="1"><span style="display: flex; flex-direction: column; gap: 2px"><span style="font-weight: 600">${PROVIDERS[p]}</span><span class="help">${d}</span></span><span class="mono" style="font-size: 12px; color: var(--muted)">${p}</span></label>`).join('')}
        </fieldset>
        <div style="margin-top: 22px">${providerFields(main)}</div>
        <div class="check">
          <button class="btn" type="button" data-act="testai" data-p="${main}"${S.busy.ai ? ' disabled' : ''}>${S.busy.ai ? '<span class="spin"></span>Проверяю…' : 'Проверить соединение'}</button>
          ${ai ? (ai.ok ? `<span class="res"><span class="dot on"></span>Сервер ответил</span><span class="mono note">${ai.seconds} с · «${esc(ai.reply)}»</span>` : `<span class="res err"><span class="dot warn"></span>${esc(ai.error)}</span>`) : '<span class="note">Проверка идёт с текущими, ещё не сохранёнными настройками</span>'}
        </div>
      </section>
      <section class="card" aria-labelledby="chain" style="padding-bottom: 22px">
        <div class="card-top"><h2 id="chain" style="padding-bottom: 4px">Если основной не ответил</h2><span class="key">ai_fallback_providers</span></div>
        <div class="help" style="padding-bottom: 16px">Провайдеры пробуются по порядку сверху вниз</div>
        <ol class="chain">
          <li class="main-item"><span class="mono note">1</span><span><span style="font-weight: 500">${PROVIDERS[main]}</span> <span class="note">· основной</span></span><span></span></li>
          ${chain.map((p, i) => `<li><span class="mono note">${i + 2}</span><span style="font-weight: 500">${PROVIDERS[p] || esc(p)}</span><span class="acts">
            <button class="ico" type="button" data-fb="up" data-i="${i}" aria-label="Выше"${i === 0 ? ' disabled' : ''}>${I.up}</button>
            <button class="ico" type="button" data-fb="down" data-i="${i}" aria-label="Ниже"${i === chain.length - 1 ? ' disabled' : ''}>${I.down}</button>
            <button class="ico" type="button" data-fb="del" data-i="${i}" aria-label="Убрать из цепочки">${I.x}</button></span></li>`).join('')}
          <li class="tail"><span class="mono">${chain.length + 2}</span><span>Запасные фразы из «<a href="#/assistant">Характер и реплики</a>» <span class="note">· всегда последние</span></span><span></span></li>
        </ol>
        <div class="inl" style="margin-top: 12px">${others.filter((p) => !chain.includes(p)).map((p) => `<button class="btn" type="button" data-fb="add" data-p="${p}">+ ${PROVIDERS[p]}</button>`).join('')}</div>
        ${row('Ожидание ответа', '', '', `<div class="inl gap"><label class="inl">таймаут${num('ai_timeout', { min: 1 })}с <span class="key">ai_timeout</span></label><label class="inl">повторов${num('ai_retries', { min: 0, style: 'width: 64px' })}<span class="key">ai_retries</span></label></div>`)}
      </section>
      ${others.map((p) => det(`prov-${p}`, PROVIDERS[p], `<div style="padding-bottom: 12px">${providerFields(p)}</div>`, { sub: chain.includes(p) ? 'Запасной провайдер' : 'Не используется' })).join('')}`;
  },
};

// ---------- Голос ----------

const ENG = { silero: ['Silero', 'офлайн, CPU'], edge: ['Edge', 'онлайн'], piper: ['Piper', 'офлайн'], sapi: ['Windows SAPI', 'встроенный'] };

PAGES.voice = {
  narrow: true,
  load: async () => { S.tts = (await api('/api/tts')).engines; },
  render() {
    const on = (eff('tts_engines') || []).filter((n) => ENG[n]);
    const all = [...on, ...Object.keys(ENG).filter((n) => !on.includes(n))];
    const st = Object.fromEntries((S.tts || []).map((e) => [e.name, e]));
    const ph = nid();
    const res = S.ttsRes;
    return `<header class="ph"><div><h1>Голос</h1><div class="sub">Говорит первый рабочий движок из списка. Сломался — слово берёт следующий.</div></div>${saveBar()}</header>
      <section class="card pad" aria-labelledby="test" style="display: flex; flex-direction: column; gap: 10px">
        <label id="test" for="${ph}" style="font-weight: 600">Проверить, как звучит</label>
        <div class="inl"><input id="${ph}" class="field" type="text" data-ttsphrase value="${esc(S.ttsPhrase || 'Так, работа сама себя не сделает.')}" style="flex: 1 1 320px">
          <button class="btn dark" type="button" data-act="tts"${S.busy.tts ? ' disabled' : ''}>${S.busy.tts ? '<span class="spin"></span>Говорит…' : `${I.play}Озвучить`}</button></div>
        <div class="note">${res ? (res.ok ? `Сказал ${ENG[res.engine] ? ENG[res.engine][0] : res.engine}, синтез ${res.seconds} с` : `<span class="err">${esc(res.error)}</span>`) : 'Скажет первый движок цепочки с текущими, ещё не сохранёнными настройками. Чтобы послушать другой, нажми ▸ в его строке.'}</div>
      </section>
      <section class="card" aria-labelledby="chain" style="padding-bottom: 24px">
        <div class="card-top"><h2 id="chain">Порядок движков</h2><span class="key">tts_engines</span></div>
        <ol class="chain">${all.map((n) => {
          const i = on.indexOf(n), s = st[n];
          const failed = s && s.failed_until;
          return `<li class="eng${i === 0 ? ' first' : ''}${i < 0 ? ' off' : ''}">
            <span class="mono note">${i >= 0 ? i + 1 : ''}</span>
            <input class="tog" type="checkbox" data-eng="${n}"${i >= 0 ? ' checked' : ''} aria-label="${ENG[n][0]} включён">
            <span style="display: flex; flex-direction: column; min-width: 0"><span style="font-weight: 600">${ENG[n][0]} <span style="font-weight: 400; font-size: 13px; color: var(--muted)">· ${ENG[n][1]}</span></span>
              <span style="font-size: 13px; color: ${s ? (s.ok && !failed ? 'var(--focus)' : 'var(--danger)') : 'var(--muted)'}">${s ? esc(failed ? `сбой, пропускается до ${hhmm(failed)}` : s.note) : 'проверяю…'}</span></span>
            <button class="ico" type="button" data-act="tts" data-engine="${n}" aria-label="Прослушать ${ENG[n][0]}"${s && !s.ok ? ' disabled' : ''}>${I.play}</button>
            <span class="acts">${i >= 0 ? `<button class="ico" type="button" data-engm="up" data-n="${n}" aria-label="Выше"${i === 0 ? ' disabled' : ''}>${I.up}</button><button class="ico" type="button" data-engm="down" data-n="${n}" aria-label="Ниже"${i === on.length - 1 ? ' disabled' : ''}>${I.down}</button>` : ''}</span>
          </li>`;
        }).join('')}</ol>
        <div class="inl" style="margin-top: 14px"><span>Упавший движок пропускать</span>${num('tts_failure_cooldown', { sm: true, min: 0, label: 'Секунд пропуска' })}<span>с</span><span class="key" style="margin-left: 6px">tts_failure_cooldown</span></div>
      </section>
      <section class="card" aria-labelledby="sil">
        <div class="card-top"><h2 id="sil">Silero</h2><span class="note">Модель CC BY-NC 4.0 — только некоммерческое использование</span></div>
        ${row('Голос', '', 'silero_speaker', pills('silero_speaker', ['xenia', 'baya', 'kseniya', 'aidar', 'eugene'].map((v) => [v, v]), { label: 'Голос Silero' }))}
        ${row('Темп', '', 'silero_rate', pills('silero_rate', [['x-slow', 'очень медленно'], ['slow', 'медленно'], ['', 'обычно'], ['fast', 'быстро'], ['x-fast', 'очень быстро']], { label: 'Темп' }))}
        ${row('Высота', '', 'silero_pitch', pills('silero_pitch', [['x-low', 'очень низко'], ['low', 'низко'], ['', 'обычно'], ['high', 'высоко'], ['x-high', 'очень высоко']], { label: 'Высота' }))}
        ${det('silx', `Частота ${eff('silero_sample_rate')} Гц · ${eff('silero_threads')} потоков · ${esc(eff('silero_model'))}`, `<div style="padding-bottom: 8px">
          ${row('Частота', '', 'silero_sample_rate', sel('silero_sample_rate', [['8000'], ['24000'], ['48000']], { t: 'int', mono: true }))}
          ${row('Потоков CPU', 'Больше 8 обычно не быстрее', 'silero_threads', num('silero_threads', { min: 1 }))}
          ${row('Модель', '', 'silero_model', txt('silero_model', { mono: true, label: 'Модель Silero' }))}</div>`, { cls: 'sub' })}
      </section>
      ${det('engx', 'Edge, Piper, SAPI', `<div style="padding-bottom: 12px">
        ${row('Edge: голос', '', 'edge_tts_voice', sel('edge_tts_voice', [['ru-RU-SvetlanaNeural'], ['ru-RU-DmitryNeural']], { mono: true, w: 280 }))}
        ${row('Edge: скорость', 'Например +10% или -5%', 'edge_tts_rate', txt('edge_tts_rate', { mono: true, style: 'max-width: 140px', label: 'Скорость Edge' }))}
        ${row('Piper: модель', 'Другие русские голоса: denis, dmitri, ruslan', 'piper_model', txt('piper_model', { mono: true, label: 'Модель Piper' }))}
        ${row('Piper: темп', 'Больше 1 — медленнее, меньше 1 — быстрее', 'piper_length_scale', num('piper_length_scale', { int: false, step: 0.05, min: 0.3 }))}
        ${row('SAPI: голос', 'Часть названия голоса Windows', 'sapi_voice', txt('sapi_voice', { style: 'max-width: 220px', label: 'Голос SAPI' }))}
        ${row('SAPI: скорость', 'От -10 до 10', 'sapi_rate', num('sapi_rate', { min: -10, max: 10 }))}</div>`, { sub: 'Голос и скорость запасных движков' })}
      <section class="card" aria-labelledby="out">
        <h2 id="out" style="padding-bottom: 4px">Вывод звука</h2>
        <div class="help" style="padding-bottom: 14px">Если слышишь треск — увеличь буфер до 4096</div>
        ${row('Частота', '', 'audio_frequency', sel('audio_frequency', [['44100'], ['48000']], { t: 'int', mono: true }))}
        ${row('Буфер', '', 'audio_buffer', sel('audio_buffer', [['1024'], ['2048'], ['4096']], { t: 'int', mono: true }))}
      </section>`;
  },
};

// ---------- Память ----------

PAGES.memory = {
  load: async () => { S.mem = await api('/api/memory'); },
  render() {
    const m = S.mem;
    const head = `<header class="ph"><div><h1>Память ассистента</h1><div class="sub">Что ассистент помнит о сегодняшнем дне. Утром всё, кроме фактов, начинается заново.</div></div>
      <div class="mono note">${m ? `${esc(m.file || 'память выключена')}${m.date ? ` · ${m.date.split('-').reverse().join('.')}` : ''}` : ''}</div></header>`;
    if (!m) return `${head}<div class="loading">Загрузка…</div>`;
    const stale = m.date && !m.is_today ? `<div class="offline"><span class="help">Это память за ${m.date.split('-').reverse().join('.')}. При следующем запуске трекера всё, кроме фактов, начнётся заново.</span></div>` : '';
    const forget = (kind, i, what) => `<button class="ico" type="button" data-forget="${kind}" data-i="${i}" aria-label="Забыть ${what}">${I.x}</button>`;
    const events = m.events.map(([ts, text], i) => [ts, text, i]).reverse();
    const dist = Object.entries(m.distractions).sort((a, b) => b[1] - a[1]);
    const st = m.stats || {};
    return `${head}${!m.file ? '<div class="offline"><span class="help">Сохранение памяти выключено (ai_memory_file = null). Включить можно в «Характер и реплики» → «Память и защита от повторов».</span></div>' : ''}${stale}
      <div class="grid">
        <section class="card pad span2" aria-labelledby="mev" style="padding-bottom: 10px">
          <div class="card-top" style="margin-bottom: 4px"><h2 id="mev" style="margin: 0; font-size: 17px; font-weight: 600">Журнал событий</h2><span class="note">модель видит последние ${m.event_log_size} · <a href="#/assistant">изменить</a></span></div>
          <div class="help" style="margin-bottom: 8px">Удалённое событие ассистент больше не упомянет</div>
          ${events.length ? events.map(([ts, text, i]) => `<div class="ln"><span class="mono note">${hhmm(ts)}</span><span class="ellip" title="${esc(text)}">${esc(text)}</span>${forget('events', i, 'событие')}</div>`).join('') : '<div class="empty" style="margin-bottom: 10px">Событий нет</div>'}
        </section>
        <section class="card pad" aria-labelledby="mdis" style="padding-bottom: 12px">
          <h2 id="mdis" style="margin: 0 0 4px; font-size: 17px; font-weight: 600">Отвлечения в блоке</h2>
          <div class="help" style="margin-bottom: 10px">Счётчик идёт в выговор как «{count}-е отвлечение» и обнуляется после фокус-блока</div>
          ${dist.length ? dist.map(([n, c]) => `<div class="ln kv"><span class="ellip" title="${esc(n)}">${esc(n)}</span><span class="mono">${c}</span></div>`).join('') : '<div class="empty">Пока ни одного</div>'}
        </section>
      </div>
      <section class="card pad" aria-labelledby="mrep" style="padding-bottom: 10px">
        <div class="card-top" style="margin-bottom: 4px"><h2 id="mrep" style="margin: 0; font-size: 17px; font-weight: 600">Что ассистент уже говорил</h2><span class="key">recent_replies</span></div>
        <div class="help" style="margin-bottom: 8px">С этим сравнивается каждая новая реплика. Убери неудачную — и ассистент перестанет её избегать.</div>
        ${m.recent_replies.length ? m.recent_replies.map((t, i) => [t, i]).reverse().map(([t, i]) => `<div class="ln two"><span>${esc(t)}</span>${forget('recent_replies', i, 'реплику')}</div>`).join('') : '<div class="empty" style="margin-bottom: 10px">Сегодня ещё ничего не сказано</div>'}
      </section>
      <div class="grid">
        <section class="card pad" aria-labelledby="mf">
          <div class="card-top" style="margin-bottom: 4px"><h2 id="mf" style="margin: 0; font-size: 17px; font-weight: 600">Рассказанные факты</h2><span class="key">recent_facts</span></div>
          <div class="help" style="margin-bottom: 14px">Хранятся между днями, чтобы не повторяться</div>
          ${m.recent_facts.length ? m.recent_facts.map((t, i) => `<div class="ln two"><span>${esc(t)}</span>${forget('recent_facts', i, 'факт')}</div>`).join('') : `<div class="empty">Пока ни одного. Первый будет через ${Math.round(eff('interesting_fact_interval') / 60)} мин работы.</div>`}
        </section>
        <section class="card pad" aria-labelledby="mst">
          <div class="card-top" style="margin-bottom: 12px"><h2 id="mst" style="margin: 0; font-size: 17px; font-weight: 600">Статистика плана</h2><span class="key">session_stats.json</span></div>
          <div class="ln kv"><span>В фокусе</span><span class="mono">${fmtMin(st.total_focus_time)}</span></div>
          <div class="ln kv"><span>На перерывах</span><span class="mono">${fmtMin(st.total_break_time)}</span></div>
          <div class="ln kv"><span>Завершено блоков</span><span class="mono">${st.completed_sessions || 0}</span></div>
          <div class="note" style="padding-top: 8px">Обнуляется, когда план пройден до конца</div>
        </section>
      </div>
      <section class="card pad" aria-labelledby="mclr" style="display: flex; flex-direction: column; gap: 14px">
        <h2 id="mclr" style="margin: 0; font-size: 17px; font-weight: 600">Очистка</h2>
        <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px">
          <div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start"><button class="btn warnb" type="button" data-clear="today">Забыть сегодняшний день</button><span class="note">Журнал, реплики, история и счётчик отвлечений. Факты останутся.</span></div>
          <div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start"><button class="btn warnb" type="button" data-clear="facts">Забыть рассказанные факты</button><span class="note">Темы снова станут доступны.</span></div>
          <div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start"><button class="btn warnb" type="button" data-act="resetstats">Обнулить статистику</button><span class="note">Минуты и блоки плана. Итоги сегодняшнего дня останутся.</span></div>
        </div>
      </section>`;
  },
};

// ---------- Discord и отладка ----------

PAGES.system = {
  narrow: true,
  render() {
    const st = S.status || {};
    const proc = live()
      ? `<div style="display: flex; flex-direction: column; gap: 2px"><div style="display: flex; align-items: center; gap: 8px; font-weight: 600"><span class="dot on"></span>Скрипт работает</div><div class="help">запущен в ${hhmm(st.started_at)} · PID ${st.pid}</div></div>
         <div class="inl" style="gap: 10px; margin-left: auto"><button class="btn" type="button" data-act="stop">Остановить</button><button class="btn dark" type="button" data-act="restart">Перезапустить</button></div>`
      : `<div style="display: flex; flex-direction: column; gap: 2px"><div style="display: flex; align-items: center; gap: 8px; font-weight: 600"><span class="dot off"></span>Трекер не запущен</div><div class="help">Панель открыта через <span class="mono">python panel.py</span>. Трекер запускается через <span class="mono">start.bat</span>.</div></div>`;
    return `<header class="ph"><div><h1>Discord и отладка</h1><div class="sub">Статус для друзей, подробность логов и сам процесс скрипта</div></div>${saveBar()}</header>
      <section class="card pad" aria-label="Процесс" style="display: flex; flex-wrap: wrap; align-items: center; gap: 16px 28px">${proc}</section>
      <section class="card" aria-labelledby="dc">
        <div class="card-top" style="align-items: center"><h2 id="dc">Статус в Discord</h2>${tog('discord_presence', 'Показывать')}</div>
        ${row('Как это видят', 'Меняется при переходе фокус ↔ отвлечение', 'discord_presence', `<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px">
          <div class="preview"><div class="img">cat</div><div style="display: flex; flex-direction: column; gap: 2px; font-size: 14px"><b>Focus State</b><span>Time in full focus:</span><span class="mono note">таймер с начала фокуса</span></div></div>
          <div class="preview"><div class="img w">fix</div><div style="display: flex; flex-direction: column; gap: 2px; font-size: 14px"><b>Unfocus State</b><span>Time in full focus:</span><span class="mono note">таймер с начала фокуса</span></div></div></div>`)}
        ${row('Кнопки в профиле', '', '', `<div style="display: grid; grid-template-columns: minmax(0, 160px) minmax(0, 1fr); gap: 8px">
          <span class="ro">Repository</span><span class="ro mono ellip" style="font-size: 13px">github.com/JErfurt/focuswithai</span>
          <span class="ro">Example</span><span class="ro mono ellip" style="font-size: 13px">youtube.com/watch?v=AqjlrRfCPb8</span></div>
          <div class="note">Тексты и кнопки заданы в <span class="mono">discord.py</span>, поэтому здесь только для просмотра.</div>`)}
      </section>
      <section class="card" aria-labelledby="dbg" style="padding-bottom: 22px">
        <div class="card-top"><h2 id="dbg">Логи</h2><span class="key">debug_level</span></div>
        <div class="inl gap" style="margin-bottom: 16px"><span>Писать в лог</span>${pills('debug_level', [['0', 'только ошибки'], ['1', '+ предупреждения'], ['2', '+ события'], ['3', 'всё']], { t: 'int', label: 'Подробность логов' })}</div>
        <div class="logbox">
          <div class="lb-top"><span class="note">${live() ? 'Последние строки, обновляются сами' : 'Логи видны, когда запущен трекер'}</span>
            <span class="inl" style="gap: 6px"><button class="btn sm" type="button" data-act="logpause">${S.logPaused ? 'Продолжить' : 'Пауза'}</button><button class="btn sm" type="button" data-act="logcopy">Скопировать</button></span></div>
          <pre id="logpre" tabindex="0" aria-label="Логи"></pre>
        </div>
      </section>`;
  },
  after() { renderLogs(true); },
};

function renderLogs(scroll) {
  const pre = $('#logpre');
  if (!pre) return;
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  pre.innerHTML = S.logs.length ? S.logs.map((l) => `<span class="note">${new Date(l.ts * 1000).toLocaleTimeString('ru-RU')}</span>  <span class="lv-${l.level}">${esc(l.text)}</span>`).join('\n') : '<span class="note">Пока пусто</span>';
  if (scroll || atBottom) pre.scrollTop = pre.scrollHeight;
}

async function pollLogs() {
  if (S.route !== 'system' || S.logPaused) return;
  try {
    const r = await api(`/api/logs?after=${S.logSeq}`);
    if (r.lines.length) {
      S.logs.push(...r.lines);
      S.logs = S.logs.slice(-500);
      S.logSeq = r.lines[r.lines.length - 1].seq;
      renderLogs(false);
    }
  } catch (e) { /* панель недоступна */ }
}

// ---------- config.json вручную ----------

function rawCheck(text) {
  if (S.tab.raw === 'config') {
    try { const v = JSON.parse(text); if (typeof v !== 'object' || Array.isArray(v) || v === null) return 'нужен объект { ... }'; return null; } catch (e) { return e.message; }
  }
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    try { const v = JSON.parse(lines[i]); if (!Number.isInteger(v.min)) return `строка ${i + 1}: нет целого min`; } catch (e) { return `строка ${i + 1}: ${e.message}`; }
  }
  return null;
}
function rawStatus() {
  const err = rawCheck(S.raw.text);
  return err ? `<span class="res err" style="display: inline-flex; gap: 8px; align-items: center; font-size: 13px"><span class="dot warn"></span>${esc(err)}</span>`
    : `<span style="display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--focus); font-weight: 500"><span class="dot on"></span>${S.tab.raw === 'config' ? 'JSON корректен' : 'Строки корректны'}</span>`;
}
function rawBar() {
  const dirty = S.raw.text !== S.raw.orig;
  return `<div class="savebar" id="rawbar">${dirty ? `<span class="cnt"><span class="dot warn"></span>Файл изменён</span><button class="btn" type="button" data-act="rawrevert">Отменить</button><button class="btn dark" type="button" data-act="rawsave"${rawCheck(S.raw.text) ? ' disabled' : ''}>Сохранить</button>` : 'Сохранено'}</div>`;
}
async function loadRaw() {
  const r = await api(`/api/raw?file=${S.tab.raw}`);
  S.raw = { text: r.text, orig: r.text, lines: r.lines };
}

PAGES.files = {
  load: async () => {
    await loadRaw();
    S.backups = (await api('/api/backups')).backups;
  },
  render() {
    const file = S.tab.raw === 'config' ? 'config.json' : 'sessions.jsonl';
    return `<header class="ph"><div><h1>Файлы вручную</h1><div class="sub">Для того, чего нет в разделах. Перед каждым сохранением config.json делается копия.</div></div>${rawBar()}</header>
      <div class="grid">
        <section class="card flat span2" aria-label="Редактор">
          <div class="ed-top"><div class="tabs" role="tablist" aria-label="Файл" style="border: 0; margin: 0">
            <button class="tab" role="tab" type="button" data-rawtab="config" aria-selected="${S.tab.raw === 'config'}">config.json</button>
            <button class="tab" role="tab" type="button" data-rawtab="sessions" aria-selected="${S.tab.raw === 'sessions'}">sessions.jsonl</button></div>
            <span id="rawst">${rawStatus()}</span></div>
          <label for="raw" class="sr">Содержимое ${file}</label>
          <textarea id="raw" class="code" spellcheck="false" data-raw>${esc(S.raw.text)}</textarea>
          <div class="ed-foot"><span>${S.tab.raw === 'config' ? 'Ключи API скрыты. Строка с ними не изменится, если её не трогать.' : 'Одна строка — один блок: name, focus, min.'}</span><span class="mono" id="rawlines">${S.raw.text.split('\n').length} строк</span></div>
        </section>
        <div class="col">
          <section class="card pad" aria-labelledby="unk" style="padding-bottom: 8px">
            <h2 id="unk" style="margin: 0 0 4px; font-size: 15px; font-weight: 600">Программа не читает</h2>
            <div class="note" style="margin-bottom: 6px">Эти ключи ни на что не влияют, их можно убрать</div>
            ${S.unknown.length ? S.unknown.map((k) => `<div class="ln kv"><span class="mono ellip" style="font-size: 13px">${esc(k)}</span><button class="btn sm" type="button" data-dropkey="${esc(k)}">Убрать</button></div>`).join('') : '<div class="note" style="padding: 10px 0">Лишних ключей нет</div>'}
            <div class="note" style="padding: 10px 0">Остальное разложено по разделам панели.</div>
          </section>
          <section class="card pad" aria-labelledby="bak" style="padding-bottom: 8px">
            <h2 id="bak" style="margin: 0 0 4px; font-size: 15px; font-weight: 600">Копии перед сохранением</h2>
            <div class="note" style="margin-bottom: 6px">Хранятся последние 10, папка <span class="mono">backups</span></div>
            ${S.backups && S.backups.length ? S.backups.map((b) => `<div class="ln kv"><span class="mono" style="font-size: 13px">${isToday(b.mtime) ? 'сегодня' : new Date(b.mtime * 1000).toLocaleDateString('ru-RU')}, ${new Date(b.mtime * 1000).toLocaleTimeString('ru-RU')}</span><button class="btn sm" type="button" data-restore="${esc(b.name)}">Вернуть</button></div>`).join('') : '<div class="note" style="padding: 10px 0">Копий пока нет: они появятся после первого сохранения</div>'}
          </section>
          <section class="card pad" aria-labelledby="io" style="display: flex; flex-direction: column; gap: 10px">
            <h2 id="io" style="margin: 0 0 4px; font-size: 15px; font-weight: 600">Перенос</h2>
            <a class="btn" href="/api/export" download>Скачать настройки</a>
            <label class="btn" style="cursor: pointer">Загрузить из файла<input type="file" accept=".json,application/json" class="sr" data-import></label>
            <div class="note">В скачанном файле ключи API пустые. Загруженный файл попадёт в редактор, сохранишь сам.</div>
          </section>
        </div>
      </div>`;
  },
};

// ---------- действия ----------

let toastTimer = null;
function toast(msg, o = {}) {
  const el = $('#toast');
  el.className = `toast${o.bad ? ' bad' : ''}`;
  el.innerHTML = `<span>${esc(msg)}</span>${o.action ? '<button class="btn" type="button" id="toastact"></button>' : ''}<button class="x" type="button" id="toastx" aria-label="Закрыть">${I.x}</button>`;
  if (o.action) { const b = $('#toastact'); b.textContent = o.action[0]; b.onclick = () => { el.hidden = true; o.action[1](); }; }
  $('#toastx').onclick = () => { el.hidden = true; };
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, o.action ? 12000 : o.bad ? 8000 : 4000);
}

async function restart() {
  if (dirtyCount() && !confirm('Есть несохранённые изменения. Перезапустить без них?')) return;
  const before = S.status && S.status.started_at;
  try { await api('/api/process', { method: 'POST', body: { action: 'restart' } }); } catch (e) { toast(e.message, { bad: true }); return; }
  toast('Перезапускаю скрипт…');
  const started = Date.now();
  const wait = async () => {
    try {
      const st = await api('/api/status');
      if (st.live && st.started_at !== before) {
        setStatus(st);
        loadCfg(await api('/api/config'));
        render();
        toast('Скрипт перезапущен, настройки применены');
        return;
      }
    } catch (e) { /* ещё поднимается */ }
    if (Date.now() - started < 90000) setTimeout(wait, 1000);
    else toast('Скрипт не поднялся за 90 секунд, посмотри окно консоли', { bad: true });
  };
  setTimeout(wait, 1500);
}

async function control(action, value) {
  try {
    await api('/api/control', { method: 'POST', body: { action, value } });
    await poll();
  } catch (e) { toast(e.message, { bad: true }); }
}

function draftConfig() {
  const d = clone(S.draft);
  for (const p of S.touched) {
    const v = getP(S.draft, p);
    if (Array.isArray(v) && v.every((x) => typeof x === 'string')) setP(d, p, v.map((x) => x.trim()).filter(Boolean));
  }
  return d;
}

async function busy(key, fn) {
  S.busy[key] = true; render();
  try { await fn(); } catch (e) { toast(e.message, { bad: true }); }
  S.busy[key] = false; render();
}

const ACTIONS = {
  save: saveAll,
  revert: revertAll,
  restart,
  async stop() {
    if (!confirm('Остановить трекер? Панель закроется вместе с ним.')) return;
    try { await api('/api/process', { method: 'POST', body: { action: 'stop' } }); toast('Трекер останавливается'); } catch (e) { toast(e.message, { bad: true }); }
  },
  async wins() { S.wins = null; renderWins(); try { S.wins = (await api('/api/windows')).windows; } catch (e) { S.wins = []; } renderWins(); },
  async testsound() {
    try { await api('/api/test/sound', { method: 'POST', body: { draft: draftConfig() } }); } catch (e) { toast(e.message, { bad: true }); }
  },
  reply: () => busy('reply', async () => {
    const ev = S.tab.event;
    const values = ev === 'punishment' ? { window: $('#tw').value, seconds: +$('#ts').value } : ev === 'praise' ? { minutes: +$('#tm').value } : {};
    S.replyInputs = { ...S.replyInputs, ...values };
    const r = await api('/api/test/reply', { method: 'POST', body: { draft: draftConfig(), event: ev, values } });
    S.reply = { ...r, event: ev };
  }),
  async replyspeak() {
    if (!S.reply || !S.reply.text) return;
    try { await api('/api/test/tts', { method: 'POST', body: { draft: draftConfig(), text: S.reply.text } }); } catch (e) { toast(e.message, { bad: true }); }
  },
  testai: (el) => busy('ai', async () => {
    const r = await api('/api/test/ai', { method: 'POST', body: { draft: draftConfig(), provider: el.dataset.p } });
    S.aiTest = { ...r, provider: el.dataset.p };
  }),
  async models() {
    try {
      const r = await api('/api/models', { method: 'POST', body: { draft: draftConfig() } });
      S.models = r.ok ? r.models : [];
      S.modelsNote = r.ok ? (r.models.length ? `Сервер отдал ${r.models.length}: ${r.models.slice(0, 5).join(', ')}${r.models.length > 5 ? '…' : ''}` : 'Сервер не вернул ни одной модели') : `Не удалось получить список: ${r.error}`;
    } catch (e) { S.modelsNote = e.message; }
    render();
    const input = $('[data-k="openai_model"]');
    if (input && S.models.length) input.focus();
  },
  tts: (el) => {
    S.ttsPhrase = ($('[data-ttsphrase]') || {}).value || S.ttsPhrase;
    return busy('tts', async () => {
      S.ttsRes = await api('/api/test/tts', { method: 'POST', body: { draft: draftConfig(), text: S.ttsPhrase || 'Проверка голоса.', engine: el.dataset.engine } });
    });
  },
  async resetstats() {
    if (!confirm('Обнулить минуты и число завершённых блоков?')) return;
    try { S.mem = await api('/api/stats/reset', { method: 'POST', body: {} }); render(); } catch (e) { toast(e.message, { bad: true }); }
  },
  logpause() { S.logPaused = !S.logPaused; render(); },
  async logcopy() {
    try { await navigator.clipboard.writeText(S.logs.map((l) => l.text).join('\n')); toast('Логи скопированы'); } catch (e) { toast('Не удалось скопировать', { bad: true }); }
  },
  rawrevert() { S.raw.text = S.raw.orig; render(); },
  async rawsave() {
    if (S.tab.raw === 'config' && dirtyCount() && !confirm('Несохранённые изменения в разделах будут потеряны. Продолжить?')) return;
    try {
      const r = await api('/api/raw', { method: 'PUT', body: { file: S.tab.raw, text: S.raw.text } });
      if (S.tab.raw === 'config') loadCfg(r);
      else { S.sess = r.sessions; S.sessOrig = clone(r.sessions); }
      await loadRaw();
      S.backups = (await api('/api/backups')).backups;
      render();
      toast(S.tab.raw === 'config' ? 'config.json сохранён. Заработает после перезапуска.' : 'sessions.jsonl сохранён', S.tab.raw === 'config' && live() ? { action: ['Перезапустить', restart] } : {});
    } catch (e) { toast(e.message, { bad: true }); }
  },
};

document.addEventListener('click', async (e) => {
  const t = e.target.closest('button, a, [data-sfocus]');
  if (!t) return;
  const d = t.dataset;
  if (d.act && ACTIONS[d.act]) { e.preventDefault(); ACTIONS[d.act](t); return; }
  if (d.ctl) { control(d.ctl, d.ctl === 'extend' ? 5 : undefined); return; }

  // списки
  const lwEl = t.closest('.lw');
  if (lwEl && d.lwdel !== undefined) {
    const items = clone(eff(lwEl.dataset.lw) || []);
    items.splice(+d.lwdel, 1);
    setv(lwEl.dataset.lw, items); renderLW(lwEl);
    if (lwEl.dataset.lw === 'target_apps') { renderWins(); renderNav(); }
    return;
  }
  if (lwEl && d.lwadd !== undefined) { lwAdd(lwEl); if (lwEl.dataset.lw === 'target_apps') { renderWins(); renderNav(); } return; }
  if (d.addapp) {
    const el = $('[data-lw="target_apps"]');
    lwAdd(el, d.addapp); renderWins(); renderNav();
    return;
  }

  // расписание
  if (d.sfocus !== undefined) { S.sess[+d.sfocus].focus = d.v === '1'; render(); return; }
  if (d.sdel !== undefined) { S.sess.splice(+d.sdel, 1); render(); return; }
  if (d.sadd) { S.sess.push(d.sadd === 'focus' ? { name: '', focus: true, min: 45 } : { name: '', focus: false, min: 10 }); render(); return; }
  if (d.srepeat !== undefined) {
    const f = [...S.sess].reverse().find((s) => s.focus) || { min: 45 };
    const b = [...S.sess].reverse().find((s) => !s.focus) || { min: 10 };
    S.sess.push({ name: '', focus: true, min: f.min }, { name: '', focus: false, min: b.min });
    render(); return;
  }
  if (d.preset !== undefined) {
    const [, f, b, c] = PRESETS[+d.preset];
    S.sess = [];
    for (let i = 0; i < c; i++) { S.sess.push({ name: '', focus: true, min: f }); S.sess.push({ name: '', focus: false, min: b }); }
    render(); return;
  }

  // характер
  if (d.evtab) { S.tab.event = d.evtab; render(); return; }
  if (d.ins) {
    const ta = $(`#${d.for}`);
    const s = ta.selectionStart ?? ta.value.length, en = ta.selectionEnd ?? s;
    ta.value = ta.value.slice(0, s) + d.ins + ta.value.slice(en);
    ta.focus(); ta.selectionStart = ta.selectionEnd = s + d.ins.length;
    onField(ta); return;
  }

  // модель
  if (d.fb) {
    const main = normProv(eff('ai_provider'));
    const chain = (eff('ai_fallback_providers') || []).map(normProv).filter((p) => p !== main);
    const i = +d.i;
    if (d.fb === 'add') chain.push(d.p);
    if (d.fb === 'del') chain.splice(i, 1);
    if (d.fb === 'up' && i > 0) [chain[i - 1], chain[i]] = [chain[i], chain[i - 1]];
    if (d.fb === 'down' && i < chain.length - 1) [chain[i + 1], chain[i]] = [chain[i], chain[i + 1]];
    setv('ai_fallback_providers', chain); render(); return;
  }

  // голос
  if (d.engm) {
    const on = (eff('tts_engines') || []).slice();
    const i = on.indexOf(d.n), j = d.engm === 'up' ? i - 1 : i + 1;
    if (i < 0 || j < 0 || j >= on.length) return;
    [on[i], on[j]] = [on[j], on[i]];
    setv('tts_engines', on); render(); return;
  }

  // память
  if (d.forget) {
    try { S.mem = await api('/api/memory/forget', { method: 'POST', body: { kind: d.forget, index: +d.i } }); render(); } catch (err) { toast(err.message, { bad: true }); }
    return;
  }
  if (d.clear) {
    const q = d.clear === 'facts' ? 'Забыть все рассказанные факты?' : 'Забыть журнал, реплики и счётчик отвлечений за сегодня?';
    if (!confirm(q)) return;
    try { S.mem = await api('/api/memory/clear', { method: 'POST', body: { scope: d.clear } }); render(); } catch (err) { toast(err.message, { bad: true }); }
    return;
  }

  // файлы
  if (d.rawtab) {
    if (S.raw.text !== S.raw.orig && !confirm('Изменения в редакторе пропадут. Переключить файл?')) return;
    S.tab.raw = d.rawtab;
    try { await loadRaw(); } catch (err) { toast(err.message, { bad: true }); }
    render(); return;
  }
  if (d.dropkey) {
    try {
      loadCfg(await api('/api/config', { method: 'PUT', body: { set: {}, unset: [d.dropkey] } }));
      await loadRaw(); S.backups = (await api('/api/backups')).backups; render();
      toast(`Ключ ${d.dropkey} убран`);
    } catch (err) { toast(err.message, { bad: true }); }
    return;
  }
  if (d.restore) {
    if (!confirm('Заменить config.json этой копией? Текущий файл тоже сохранится в копиях.')) return;
    try {
      loadCfg(await api('/api/backups/restore', { method: 'POST', body: { name: d.restore } }));
      await loadRaw(); S.backups = (await api('/api/backups')).backups; render();
      toast('Копия восстановлена. Заработает после перезапуска.', live() ? { action: ['Перезапустить', restart] } : {});
    } catch (err) { toast(err.message, { bad: true }); }
  }
});

document.addEventListener('input', (e) => {
  const el = e.target;
  if (el.dataset.k && el.type !== 'radio' && el.type !== 'checkbox' && el.tagName !== 'SELECT') { onField(el); return; }
  if (el.dataset.li !== undefined) {
    const lwEl = el.closest('.lw');
    const items = clone(eff(lwEl.dataset.lw) || []);
    items[+el.dataset.li] = el.value;
    setv(lwEl.dataset.lw, items); return;
  }
  if (el.dataset.sname !== undefined) { S.sess[+el.dataset.sname].name = el.value; updateDirty(); return; }
  if (el.dataset.smin !== undefined) {
    const n = parseInt(el.value, 10);
    if (!(n >= 1 && n <= 600)) { el.classList.add('bad'); return; }
    el.classList.remove('bad');
    S.sess[+el.dataset.smin].min = n; refreshSched(); return;
  }
  if (el.dataset.memfile !== undefined) { setv('ai_memory_file', el.value.trim() || 'assistant_memory.json'); return; }
  if (el.dataset.raw !== undefined) {
    S.raw.text = el.value;
    $('#rawst').innerHTML = rawStatus();
    $('#rawbar').outerHTML = rawBar();
    $('#rawlines').textContent = `${el.value.split('\n').length} строк`;
  }
});

document.addEventListener('change', async (e) => {
  const el = e.target;
  if (el.dataset.k && (el.type === 'radio' || el.type === 'checkbox' || el.tagName === 'SELECT')) { onField(el); if (el.dataset.k === 'tts_engines') render(); return; }
  if (el.dataset.ctltog) { control(el.dataset.ctltog, el.checked); return; }
  if (el.dataset.eng) {
    let on = (eff('tts_engines') || []).slice();
    on = el.checked ? [...on.filter((n) => n !== el.dataset.eng), el.dataset.eng] : on.filter((n) => n !== el.dataset.eng);
    setv('tts_engines', on); render(); return;
  }
  if (el.dataset.memsave !== undefined) {
    const f = $('[data-memfile]');
    setv('ai_memory_file', el.checked ? (f.value.trim() || 'assistant_memory.json') : null);
    f.disabled = !el.checked; return;
  }
  if (el.dataset.upload !== undefined && el.files[0]) {
    const file = el.files[0];
    try {
      const r = await api(`/api/upload/sound?name=${encodeURIComponent(file.name)}`, { method: 'POST', raw: file });
      setv('reminder_sound', r.path); render();
      toast(`Файл загружен в ${r.path}. Сохрани, чтобы использовать.`);
    } catch (err) { toast(err.message, { bad: true }); }
    return;
  }
  if (el.dataset.import !== undefined && el.files[0]) {
    const text = await el.files[0].text();
    S.tab.raw = 'config';
    if (S.raw.orig === '' || S.tab.raw !== 'config') await loadRaw();
    S.raw.text = text; render();
    toast('Файл в редакторе. Проверь и нажми «Сохранить».');
  }
});

document.addEventListener('keydown', (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.lwnew !== undefined && e.key === 'Enter') {
    e.preventDefault(); const lwEl = el.closest('.lw'); lwAdd(lwEl);
    if (lwEl.dataset.lw === 'target_apps') { renderWins(); renderNav(); }
  }
  if (el.dataset && el.dataset.handle !== undefined && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
    e.preventDefault(); const i = +el.dataset.handle; moveSess(i, e.key === 'ArrowUp' ? i - 1 : i + 1);
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault();
    if (S.route === 'files') { if (S.raw.text !== S.raw.orig && !rawCheck(S.raw.text)) ACTIONS.rawsave(); } else if (dirtyCount()) saveAll();
  }
});

document.addEventListener('toggle', (e) => {
  if (e.target.dataset && e.target.dataset.det) S.open[e.target.dataset.det] = e.target.open;
}, true);

// перетаскивание блоков расписания за ручку
let dragFrom = null;
document.addEventListener('mousedown', (e) => {
  const h = e.target.closest('[data-handle]');
  if (h) h.closest('.srow').draggable = true;
});
document.addEventListener('dragstart', (e) => {
  const r = e.target.closest && e.target.closest('[data-srow]');
  if (!r) return;
  dragFrom = +r.dataset.srow;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', String(dragFrom));
});
document.addEventListener('dragover', (e) => {
  const r = e.target.closest && e.target.closest('[data-srow]');
  if (!r || dragFrom === null) return;
  e.preventDefault();
  $$('.drag-over').forEach((x) => x.classList.remove('drag-over'));
  r.classList.add('drag-over');
});
document.addEventListener('drop', (e) => {
  const r = e.target.closest && e.target.closest('[data-srow]');
  if (!r || dragFrom === null) return;
  e.preventDefault();
  const to = +r.dataset.srow, from = dragFrom;
  dragFrom = null;
  moveSess(from, to);
});
document.addEventListener('dragend', () => {
  dragFrom = null;
  $$('.drag-over').forEach((x) => x.classList.remove('drag-over'));
  $$('.srow[draggable="true"]').forEach((x) => { x.draggable = false; });
});

window.addEventListener('beforeunload', (e) => {
  if (dirtyCount() || (S.raw.text !== S.raw.orig)) { e.preventDefault(); e.returnValue = ''; }
});

// ---------- опрос состояния ----------

function setStatus(st) {
  S.status = st; S.statusAt = Date.now(); S.conn = true;
  if (st.config_mtime && S.mtime && st.config_mtime > S.mtime + 0.5 && !dirtyCount()) {
    // config.json изменили снаружи (вручную или из другой вкладки)
    api('/api/config').then((r) => { loadCfg(r); render(); }).catch(() => {});
  }
}

async function poll() {
  if (document.hidden) return;
  try {
    setStatus(await api('/api/status'));
  } catch (e) {
    S.conn = false;
  }
  renderNav();
  if (S.route === 'today' && S.cfg) {
    const sel = document.activeElement;
    const focusKey = sel && sel.dataset ? sel.dataset.ctltog || sel.dataset.ctl : null;
    const main = $('#main');
    if (setHtml(main, PAGES.today.render())) {
      hydrate(main);
      if (focusKey) { const again = $(`[data-ctltog="${focusKey}"], [data-ctl="${focusKey}"]`); if (again) again.focus(); }
    }
    tick();
  }
}

function tick() {
  if (S.route !== 'today' || !S.status || !S.status.block) return;
  const rem = remaining();
  const t = $('#timer');
  if (t) t.textContent = fmtMS(rem);
  const b = S.status.block, total = (b.min + b.extra_min) * 60;
  const pct = total ? ((total - rem) / total) * 100 : 0;
  const bar = $('#tbar');
  if (bar) bar.style.width = `${pct}%`;
  const cur = $('[data-plancur]');
  if (cur) cur.style.width = `${Math.min(100, pct)}%`;
  const end = $('#tend');
  if (end) end.textContent = hhmm(Date.now() / 1000 + rem);
}

async function boot() {
  S.route = routeFromHash();
  window.addEventListener('hashchange', () => {
    const next = routeFromHash();
    if (S.route === 'files' && next !== 'files' && S.raw.text !== S.raw.orig) {
      if (!confirm('Изменения в редакторе файла не сохранены. Уйти без них?')) { history.replaceState(null, '', '#/files'); return; }
      S.raw.text = S.raw.orig;
    }
    S.route = next;
    S.loaded[S.route] = false;
    render();
    window.scrollTo(0, 0);
  });
  try {
    const [c, s, st] = await Promise.all([api('/api/config'), api('/api/sessions'), api('/api/status')]);
    loadCfg(c);
    S.sess = s.sessions; S.sessOrig = clone(s.sessions);
    setStatus(st);
  } catch (e) {
    $('#main').innerHTML = `<div class="offline"><div><b>Не удалось загрузить настройки</b><div class="err">${esc(e.message)}</div></div></div>`;
    return;
  }
  render();
  setInterval(poll, 2000);
  setInterval(tick, 1000);
  setInterval(pollLogs, 2000);
}

boot();
