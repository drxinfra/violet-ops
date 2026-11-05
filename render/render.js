#!/usr/bin/env node
// Рендер образцов кода темой Violet Ops тем же движком подсветки, что у VS Code
// (vscode-textmate + oniguruma, грамматики из установленных расширений).
// Для задач Ansible поверх накладывается то, что в редакторе даёт ansible language server:
// модуль = class, параметр модуля = method, ключ задачи = keyword.
//
//   node render.js spec.json        → <out>/<slug>-frame.html, <out>/<slug>-code.html
'use strict';
const fs = require('fs');
const path = require('path');
const tm = require('vscode-textmate');
const onig = require('vscode-oniguruma');

const FONT_STYLE_MASK = 0b00000000000000000111100000000000, FONT_STYLE_OFFSET = 11;
const FOREGROUND_MASK = 0b00000000111111111000000000000000, FOREGROUND_OFFSET = 15;
const TOKEN_TYPE_MASK = 0b00000000000000000000001100000000, TOKEN_TYPE_OFFSET = 8;   // 0 код, 1 коммент, 2 строка, 3 regexp

// Раскраска пар скобок, как в VS Code (editor.bracketPairColorization): только в коде, не в строках и
// комментариях; цвет по глубине вложенности, стек тянется через весь файл.
function bracketMatcher(pairs) {
  const opens = [], closes = [];
  for (const [o, c] of pairs) {
    const kind = o.replace(/-/g, '');
    opens.push({ tok: o, kind });
    closes.push({ tok: c, kind });
  }
  const byLen = (a, b) => b.tok.length - a.tok.length;
  opens.sort(byLen); closes.sort(byLen);
  return { opens, closes };
}

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// ---- ansible: эвристика language server ------------------------------------
const KEYWORDS = new Set(('name when register loop loop_control become become_user become_method vars tags notify ' +
  'with_items with_dict with_fileglob block rescue always delegate_to delegate_facts run_once changed_when ' +
  'failed_when until retries delay ignore_errors ignore_unreachable environment args no_log check_mode diff ' +
  'listen hosts gather_facts roles tasks handlers pre_tasks post_tasks any_errors_fatal serial collections ' +
  'module_defaults timeout throttle async poll local_action connection port remote_user strategy ' +
  'vars_files max_fail_percentage debugger').split(/\s+/));
const SHORT_MODULES = new Set(('debug set_fact file copy template stat command shell service systemd systemd_service ' +
  'apt yum dnf package lineinfile blockinfile user group get_url uri unarchive assert fail include_tasks ' +
  'import_tasks include_role import_role meta pause wait_for find replace sysctl mount cron git pip setup ' +
  'slurp fetch synchronize reboot add_host group_by script raw tempfile known_hosts authorized_key ' +
  'include_vars getent').split(/\s+/));
const FREEFORM = new Set(['set_fact', 'ansible.builtin.set_fact', 'add_host', 'ansible.builtin.add_host']);
const TASK_LISTS = new Set(['block', 'rescue', 'always', 'tasks', 'handlers', 'pre_tasks', 'post_tasks']);
const FQCN = /^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$/;

function ansibleOverlay(lines) {
  const res = {};
  const stack = [];
  let blockIndent = -1;
  lines.forEach((line, i) => {
    const indent = line.length - line.trimStart().length;
    if (blockIndent >= 0) {
      if (!line.trim() || indent > blockIndent) return;   // содержимое блочного скаляра
      blockIndent = -1;
    }
    const m = line.match(/^(\s*)(-\s+)?([A-Za-z_][\w.\-]*)(\s*):(\s|$)/);
    if (!m || line.trimStart().startsWith('#')) return;
    const col = m[1].length + (m[2] ? m[2].length : 0);
    const key = m[3];
    while (stack.length && stack[stack.length - 1].col >= col) stack.pop();
    const parent = stack.length ? stack[stack.length - 1] : null;
    let role = null;
    const atTaskLevel = !parent || (parent.role === 'keyword' && TASK_LISTS.has(parent.key));
    if (parent && parent.role === 'class') role = FREEFORM.has(parent.key) ? null : 'method';
    else if (atTaskLevel && KEYWORDS.has(key)) role = 'keyword';
    else if (atTaskLevel && (FQCN.test(key) || SHORT_MODULES.has(key))) role = 'class';
    stack.push({ col, key, role });
    if (role) (res[i] = res[i] || []).push({ start: col, end: col + key.length, role });
    if (/:\s*[>|][-+0-9]*\s*(#.*)?$/.test(line)) blockIndent = col;
  });
  return res;
}

function semStyle(v) {
  if (!v) return null;
  if (typeof v === 'string') return { fg: v };
  return { fg: v.foreground, bold: !!v.bold, italic: !!v.italic };
}

// ---- токенизация -----------------------------------------------------------
async function renderSample(registry, colorMap, theme, smp) {
  const g = await registry.loadGrammar(smp.scope);
  if (!g) throw new Error('нет грамматики ' + smp.scope);
  const lines = fs.readFileSync(smp.file, 'utf8').split(/\r?\n/);
  const overlay = smp.ansible ? ansibleOverlay(lines) : {};
  const sem = theme.semanticTokenColors || {};
  const bm = bracketMatcher(spec.brackets[smp.scope] || spec.brackets.default);
  const bcol = [1, 2, 3, 4, 5, 6].map((k) => theme.colors[`editorBracketHighlight.foreground${k}`]);
  const bbad = theme.colors['editorBracketHighlight.unexpectedBracket.foreground'];
  const bstack = [];
  let stack = tm.INITIAL;
  const rows = [];
  const last = Math.min(lines.length, smp.to);
  for (let i = 0; i < last; i++) {
    const line = lines[i];
    const r = g.tokenizeLine2(line, stack);
    stack = r.ruleStack;
    const n = line.length;
    const fg = new Array(n), st = new Array(n), ty = new Array(n);
    const t = r.tokens;
    for (let k = 0; k < t.length; k += 2) {
      const s = t[k], e = k + 2 < t.length ? t[k + 2] : n;
      const meta = t[k + 1];
      const color = colorMap[(meta & FOREGROUND_MASK) >>> FOREGROUND_OFFSET];
      const fs_ = (meta & FONT_STYLE_MASK) >>> FONT_STYLE_OFFSET;
      const tt = (meta & TOKEN_TYPE_MASK) >>> TOKEN_TYPE_OFFSET;
      for (let c = s; c < e; c++) { fg[c] = color; st[c] = fs_; ty[c] = tt; }
    }
    // пары скобок: считаем по всему файлу, чтобы глубина совпала с редактором
    for (let c = 0; c < n;) {
      if (ty[c] !== 0) { c++; continue; }
      const at = (tok) => line.startsWith(tok, c) && [...tok].every((_, j) => ty[c + j] === 0);
      const cl = bm.closes.find((x) => at(x.tok));
      const op = bm.opens.find((x) => at(x.tok));
      if (cl && (!op || cl.tok.length >= op.tok.length)) {
        let color = bbad;
        if (bstack.length && bstack[bstack.length - 1] === cl.kind) { bstack.pop(); color = bcol[bstack.length % 6]; }
        for (let j = 0; j < cl.tok.length; j++) fg[c + j] = color;
        c += cl.tok.length;
      } else if (op) {
        const color = bcol[bstack.length % 6];
        bstack.push(op.kind);
        for (let j = 0; j < op.tok.length; j++) fg[c + j] = color;
        c += op.tok.length;
      } else c++;
    }
    if (i + 1 < smp.from) continue;
    for (const o of overlay[i] || []) {
      const s = semStyle(sem[`${o.role}:ansible`] || sem[o.role]);   // как в VS Code: правило языка важнее общего
      if (!s) continue;
      for (let c = o.start; c < o.end; c++) { fg[c] = s.fg; st[c] = (s.bold ? 2 : 0) | (s.italic ? 1 : 0); }
    }
    let html = '';
    let c = 0;
    while (c < n) {
      let e = c + 1;
      while (e < n && fg[e] === fg[c] && st[e] === st[c]) e++;
      const css = `color:${fg[c]}` + (st[c] & 2 ? ';font-weight:700' : '') + (st[c] & 1 ? ';font-style:italic' : '') +
        (st[c] & 4 ? ';text-decoration:underline' : '');
      html += `<span style="${css}">${esc(line.slice(c, e).replace(/\t/g, '    '))}</span>`;
      c = e;
    }
    rows.push({ n: i + 1, html });
  }
  return rows;
}

function codeTable(rows, colors, highlight) {
  return '<table class="code">' + rows.map((r) => {
    const hl = r.n === highlight;
    return `<tr${hl ? ` style="background:${colors['editor.lineHighlightBackground']}"` : ''}>` +
      `<td class="ln" style="color:${hl ? colors['editorLineNumber.activeForeground'] : colors['editorLineNumber.foreground']}">${r.n}</td>` +
      `<td class="tx">${r.html || '&nbsp;'}</td></tr>`;
  }).join('') + '</table>';
}

function css(c) {
  return `
body{margin:0;background:#0b0b0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.code{border-collapse:collapse;font-family:'MesloLGS NF',Menlo,monospace;font-size:15px;line-height:23px;width:100%}
.code td{vertical-align:top;padding:0}
.ln{width:44px;text-align:right;padding-right:16px!important;user-select:none;font-size:13px}
.tx{white-space:pre-wrap;word-break:break-word;color:${c['editor.foreground']}}
.win{width:1560px;margin:16px auto;border-radius:10px;overflow:hidden;border:1px solid ${c['titleBar.border']};
  display:grid;grid-template-rows:32px 1fr 24px;height:900px}
.title{background:${c['titleBar.activeBackground']};color:${c['titleBar.activeForeground']};text-align:center;line-height:32px;
  font-size:13px;border-bottom:1px solid ${c['titleBar.border']}}
.main{display:grid;grid-template-columns:48px 290px 1fr;min-height:0}
.act{background:${c['activityBar.background']};padding-top:8px}
.ic{width:24px;height:24px;margin:12px auto;border-radius:5px;border:2px solid ${c['activityBar.inactiveForeground']}}
.ic.on{border-color:${c['activityBar.foreground']};box-shadow:-12px 0 0 -10px ${c['activityBar.activeBorder']}}
.side{background:${c['sideBar.background']};color:${c['sideBar.foreground']};border-right:1px solid ${c['sideBar.border']};font-size:14px}
.sh{color:${c['sideBarTitle.foreground']};font-size:11px;letter-spacing:.06em;padding:10px 16px}
.row{padding:2px 0;white-space:nowrap}
.ed{background:${c['editor.background']};display:grid;grid-template-rows:36px 24px 1fr;min-height:0}
.tabs{background:${c['editorGroupHeader.tabsBackground']};display:flex}
.tab{padding:0 18px;line-height:35px;font-size:13px;border-right:1px solid ${c['tab.border']}}
.crumbs{color:${c['breadcrumb.foreground']};font-size:12px;line-height:24px;padding-left:16px}
.status{background:${c['statusBar.background']};color:${c['statusBar.foreground']};font-size:12px;line-height:24px;
  border-top:1px solid ${c['statusBar.border']};display:flex;gap:18px}
.remote{background:${c['statusBarItem.remoteBackground']};color:${c['statusBarItem.remoteForeground']};padding:0 10px}
.grid{width:1560px;margin:16px auto;display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:${c['editor.background']};border:1px solid ${c['editorGroup.border']};border-radius:6px;overflow:hidden}
.hd{background:${c['editorGroupHeader.tabsBackground']};color:${c['tab.activeForeground']};font-size:13px;padding:7px 14px;
  border-bottom:1px solid ${c['editorGroup.border']}}
.cb{padding:8px 0 10px}
.cap{width:1560px;margin:12px auto 0;color:#ddd;font-size:15px}`;
}

function sidebar(c, tree) {
  const st = {
    sel: `background:${c['list.activeSelectionBackground']};color:${c['list.activeSelectionForeground']}`,
    mod: `color:${c['gitDecoration.modifiedResourceForeground']}`,
    unt: `color:${c['gitDecoration.untrackedResourceForeground']}`,
    bold: 'font-weight:600', '': '',
  };
  return `<div class="sh">EXPLORER</div>` +
    tree.map(([lvl, t, s]) => `<div class="row" style="padding-left:${12 + lvl * 14}px;${st[s || '']}">${esc(t)}</div>`).join('');
}

async function main() {
  const wasm = fs.readFileSync(require.resolve('vscode-oniguruma/release/onig.wasm')).buffer;
  await onig.loadWASM(wasm);
  const onigLib = Promise.resolve({
    createOnigScanner: (p) => new onig.OnigScanner(p),
    createOnigString: (s) => new onig.OnigString(s),
  });
  fs.mkdirSync(spec.out, { recursive: true });
  for (const th of spec.themes) {
    const theme = JSON.parse(fs.readFileSync(th.path, 'utf8'));
    const c = theme.colors;
    const registry = new tm.Registry({
      onigLib,
      loadGrammar: async (sc) => {
        const p = spec.grammars[sc];
        return p ? tm.parseRawGrammar(fs.readFileSync(p, 'utf8'), p) : null;
      },
      getInjections: (sc) => spec.injections[sc] || [],
    });
    registry.setTheme({ name: theme.name, settings: theme.tokenColors });
    const colorMap = registry.getColorMap();

    // кадр окна VS Code
    const f = spec.frame;
    const frows = await renderSample(registry, colorMap, theme, f);
    const tab = (t, on, it) => `<div class="tab" style="background:${on ? c['tab.activeBackground'] : c['tab.inactiveBackground']};` +
      `color:${on ? c['tab.activeForeground'] : c['tab.inactiveForeground']};${on ? `box-shadow:inset 0 1px 0 ${c['tab.activeBorderTop']};` : ''}` +
      `${it ? 'font-style:italic;' : ''}">${esc(t)}</div>`;
    const cap = th.caption ? `<div class="cap">${esc(th.caption)}</div>` : '';
    const tabs = (f.tabs || []).map((x, k) => tab(x, k === 0, k === 1)).join('');
    const frame = `<!doctype html><meta charset="utf-8"><style>${css(c)}</style>
${cap}<div class="win"><div class="title">${esc(f.title || '')}</div>
<div class="main"><div class="act"><div class="ic on"></div><div class="ic"></div><div class="ic"></div><div class="ic"></div></div>
<div class="side">${sidebar(c, f.tree || [])}</div>
<div class="ed"><div class="tabs">${tabs}</div>
<div class="crumbs">${esc(f.crumbs || '')}</div>
<div style="overflow:hidden;padding-top:6px">${codeTable(frows, c, f.highlight)}</div></div></div>
<div class="status"><span class="remote">⎇ main</span><span>${esc(f.language || '')}</span><span>UTF-8</span><span>Ln ${f.highlight}, Col 5</span></div></div>`;
    fs.writeFileSync(path.join(spec.out, `${th.slug}-frame.html`), frame);

    // сетка образцов по языкам
    const cards = [];
    for (const smp of spec.samples) {
      const rows = await renderSample(registry, colorMap, theme, smp);
      cards.push(`<div class="card"><div class="hd">${esc(smp.label)}</div><div class="cb">${codeTable(rows, c)}</div></div>`);
    }
    const code = `<!doctype html><meta charset="utf-8"><style>${css(c)}</style>
${th.caption ? `<div class="cap">${esc(th.caption)}</div>` : ''}
<div class="grid">${cards.join('\n')}</div>`;
    fs.writeFileSync(path.join(spec.out, `${th.slug}-code.html`), code);
    console.log('  отрисовано:', th.slug);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
