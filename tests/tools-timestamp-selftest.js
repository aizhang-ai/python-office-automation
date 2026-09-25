// 时间戳/日期换算工具自检：用 DOM stub 在 Node 里加载 docs/tools/timestamp.html 的真实脚本，
// 验证秒/毫秒识别、时区换算、日期解析（含非法日期拦截）、相对时间、时间差与页面动作。
// 运行：node tests/tools-timestamp-selftest.js
'use strict';
const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, '..', 'docs', 'tools', 'timestamp.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('没找到 script 块'); process.exit(1); }
const code = m[1];

// ---------- DOM stub ----------
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: '', textContent: '', innerHTML: '', className: '', checked: false };
  return els[id];
}
global.document = {
  getElementById: el,
  createElement: function () { return { style: {}, click() {}, remove() {}, href: '', download: '' }; },
  body: { appendChild() {} }
};
try {
  Object.defineProperty(global, 'navigator', {
    value: { clipboard: { writeText: () => Promise.resolve() } },
    configurable: true, writable: true
  });
} catch (e) { /* 忽略 */ }

const api = new Function(code + `
  return { pad, fmt, fmtUtc, fmtLocal, fmtIso, isoUtc, weekdayOf, offsetLabel,
           parseTsInput, parseDateInput, parseAny, humanAgo, diffBetween, rows,
           runTs, runDate, runDiff, useNow, nowIntoDate, clearTs, clearDate, clearDiff };
`)();

let pass = 0, fail = 0;
function check(name, actual, expect) {
  const a = JSON.stringify(actual), e = JSON.stringify(expect);
  if (a === e) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + '\n        期望 ' + e + '\n        实际 ' + a); }
}
const K = (s) => Date.UTC.apply(null, s);

console.log('== 1. 补零 ==');
check('个位补 0', api.pad(7), '07');
check('两位不动', api.pad(12), '12');
check('毫秒补到 3 位', api.pad(5, 3), '005');

console.log('== 2. 按偏移格式化（与本机时区无关）==');
check('UTC+0 的 1970 起点', api.fmt(0, 0), '1970-01-01 00:00:00');
check('UTC+8 的 1970 起点', api.fmt(0, 480), '1970-01-01 08:00:00');
check('UTC-5 的 1970 起点', api.fmt(0, -300), '1969-12-31 19:00:00');
check('UTC+0 格式化已知值 1700000000s', api.fmt(1700000000000, 0), '2023-11-14 22:13:20');
check('UTC+8 同一时刻差 8 小时', api.fmt(1700000000000, 480), '2023-11-15 06:13:20');
check('fmtUtc 等于偏移 0', api.fmtUtc(1700000000000), '2023-11-14 22:13:20');
check('fmtLocal 能跑通且是字符串', typeof api.fmtLocal(1700000000000), 'string');

console.log('== 3. ISO 8601 ==');
check('UTC 的 ISO 带毫秒 Z', api.isoUtc(1700000000000), '2023-11-14T22:13:20.000Z');
check('带偏移的 ISO（+8）', api.fmtIso(1700000000000, 480), '2023-11-15T06:13:20+08:00');
check('带偏移的 ISO（-5）', api.fmtIso(1700000000000, -300), '2023-11-14T17:13:20-05:00');
check('偏移标签 +8', api.offsetLabel(480), 'UTC+8');
check('偏移标签 -5', api.offsetLabel(-300), 'UTC-5');
check('偏移标签 0', api.offsetLabel(0), 'UTC+0');

console.log('== 4. 星期 ==');
check('1970-01-01 是星期四', api.weekdayOf(0, 0), '星期四');
check('2023-11-14 是星期二', api.weekdayOf(1700000000000, 0), '星期二');
check('同一时刻 UTC+8 已是星期三', api.weekdayOf(1700000000000, 480), '星期三');

console.log('== 5. 时间戳输入解析 ==');
check('10 位识别为秒', api.parseTsInput('1700000000', 'auto').ms, 1700000000000);
check('10 位 unit=s', api.parseTsInput('1700000000', 'auto').unit, 's');
check('13 位识别为毫秒', api.parseTsInput('1700000000000', 'auto').ms, 1700000000000);
check('13 位 unit=ms', api.parseTsInput('1700000000000', 'auto').unit, 'ms');
check('带千分位逗号', api.parseTsInput('1,700,000,000', 'auto').ms, 1700000000000);
check('带空格', api.parseTsInput('  1700000000  ', 'auto').ms, 1700000000000);
check('负数（1970 前）', api.parseTsInput('-1000', 'auto').ms, -1000000);
check('显式指定毫秒', api.parseTsInput('1700000000', 'ms').ms, 1700000000);
check('显式指定秒', api.parseTsInput('1700000000000', 's').ms, 1700000000000000);
check('字母 -> null', api.parseTsInput('abc', 'auto'), null);
check('小数 -> null', api.parseTsInput('12.5', 'auto'), null);
check('空 -> null', api.parseTsInput('', 'auto'), null);
check('中文 -> null', api.parseTsInput('二零二六年', 'auto'), null);

console.log('== 6. 日期输入解析（按 UTC+0）==');
check('完整时间', api.parseDateInput('2023-11-14 22:13:20', 0), 1700000000000);
check('只到分钟', api.parseDateInput('2023-11-14 22:13', 0), K([2023, 10, 14, 22, 13, 0, 0]));
check('只到日期', api.parseDateInput('2023-11-14', 0), K([2023, 10, 14, 0, 0, 0, 0]));
check('斜杠分隔', api.parseDateInput('2023/11/14', 0), K([2023, 10, 14, 0, 0, 0, 0]));
check('T 分隔', api.parseDateInput('2023-11-14T22:13:20', 0), 1700000000000);
check('按 UTC+8 解析（减 8 小时）', api.parseDateInput('2023-11-15 06:13:20', 480), 1700000000000);
check('按 UTC-5 解析（加 5 小时）', api.parseDateInput('2023-11-14 17:13:20', -300), 1700000000000);
check('2026-02-30 不存在 -> null', api.parseDateInput('2026-02-30', 0), null);
check('13 月 -> null', api.parseDateInput('2026-13-01', 0), null);
check('25 点 -> null', api.parseDateInput('2026-09-25 25:00:00', 0), null);
check('乱写 -> null', api.parseDateInput('下周三', 0), null);
check('空 -> null', api.parseDateInput('', 0), null);

console.log('== 7. 往返一致 ==');
check('UTC 往返', api.fmt(api.parseDateInput('2026-09-25 11:30:00', 0), 0), '2026-09-25 11:30:00');
check('+8 往返', api.fmt(api.parseDateInput('2026-09-25 11:30:00', 480), 480), '2026-09-25 11:30:00');
check('同一时刻两种写法指向同一毫秒',
  [api.parseDateInput('2026-09-25 11:30:00', 480), api.parseDateInput('2026-09-25 03:30:00', 0)],
  [api.parseDateInput('2026-09-25 03:30:00', 0), api.parseDateInput('2026-09-25 03:30:00', 0)]);

console.log('== 8. 相对时间 ==');
const NOW = 1700000000000;
check('1 小时前', api.humanAgo(NOW - 3600000, NOW), '1 小时前');
check('3 天 2 小时后', api.humanAgo(NOW + (3 * 86400 + 2 * 3600) * 1000, NOW), '3 天 2 小时后');
check('90 分钟前', api.humanAgo(NOW - 90 * 60000, NOW), '1 小时 30 分钟前');
check('同一刻 -> 此刻', api.humanAgo(NOW, NOW), '此刻');
check('25 小时前按天+小时', api.humanAgo(NOW - 25 * 3600000, NOW), '1 天 1 小时前');

console.log('== 9. 时间差 ==');
let d = api.diffBetween(1700000000000, 1700086400000);
check('正好一天', [d.days, d.hours, d.minutes, d.seconds], [1, 24, 1440, 86400]);
check('文字描述', d.text, '1 天');
check('sign 为正', d.sign, 1);
d = api.diffBetween(1700086400000, 1700000000000);
check('反序 sign 为负', d.sign, -1);
check('反序绝对值不变', d.days, 1);
d = api.diffBetween(0, 3600000 + 60000 + 1000);
check('1 小时 1 分 1 秒', d.text, '1 小时 1 分钟 1 秒');
d = api.diffBetween(1000, 1000);
check('零差', d.text, '0 秒');

console.log('== 10. parseAny（时间戳或日期都吃）==');
check('纯数字当时间戳', api.parseAny('1700000000', 0), 1700000000000);
check('日期串当日期', api.parseAny('2023-11-14 22:13:20', 0), 1700000000000);
check('认不出来 -> null', api.parseAny('昨天下午', 0), null);
check('空 -> null', api.parseAny('', 0), null);

console.log('== 11. 页面动作：时间戳 → 日期 ==');
el('ts').value = '1700000000'; el('tsUnit').value = 'auto'; el('tz1').value = '0';
let r = api.runTs();
check('识别为秒级', r.unit, 's');
check('毫秒值正确', r.ts, 1700000000000);
check('UTC 行正确', r.items[1][1], '2023-11-14 22:13:20');
check('结果写进 DOM', el('outTs').innerHTML.indexOf('2023-11-14 22:13:20') >= 0, true);
check('提示语报出位数', el('msgTs').textContent.indexOf('10 位数字') >= 0, true);
el('ts').value = '1700000000000';
r = api.runTs();
check('13 位识别为毫秒级', r.unit, 'ms');
check('13 位换算结果一致', r.ts, 1700000000000);
el('tz1').value = '480';
r = api.runTs();
check('切到 UTC+8 显示 +8 小时', r.items[0][1], '2023-11-15 06:13:20');
el('ts').value = '不是数字';
r = api.runTs();
check('非法输入返回 null', r, null);
check('非法输入给出错误提示', el('msgTs').className.indexOf('err') >= 0, true);
check('非法输入清空结果', el('outTs').innerHTML, '');

console.log('== 12. 页面动作：日期 → 时间戳 ==');
el('dt').value = '2023-11-14 22:13:20'; el('tz2').value = '0';
let r2 = api.runDate();
check('秒级时间戳', r2.items[0][1], 1700000000);
check('毫秒级时间戳', r2.items[1][1], 1700000000000);
check('结果写进 DOM', el('outDt').innerHTML.indexOf('1700000000') >= 0, true);
el('dt').value = '2023-11-15 06:13:20'; el('tz2').value = '480';
r2 = api.runDate();
check('按 +8 解析得到同一时间戳', r2.items[0][1], 1700000000);
check('提示语含时区标签', el('msgDt').textContent.indexOf('UTC+8') >= 0, true);
el('dt').value = '2026-02-30';
r2 = api.runDate();
check('不存在的日期被拦下', r2, null);

console.log('== 13. 页面动作：两个时间相差 ==');
el('d1').value = '1700000000'; el('d2').value = '1700086400'; el('tz2').value = '0';
let r3 = api.runDiff();
check('相差文字', r3.items[2][1], '1 天');
check('折合小时', r3.items[4][1], '24 小时');
check('折合分钟', r3.items[5][1], '1440 分钟');
el('d1').value = '2026-09-01'; el('d2').value = '2026-09-25 18:00:00';
r3 = api.runDiff();
check('日期串也能算', r3.d.days, 24);
el('d1').value = ''; el('d2').value = '2026-09-25';
r3 = api.runDiff();
check('一边为空返回 null', r3, null);
check('一边为空给出错误提示', el('msgDiff').className.indexOf('err') >= 0, true);

console.log('== 14. 辅助动作 ==');
api.useNow(1);
check('用此刻填入的是 10 位', /^\d{10}$/.test(el('ts').value), true);
api.useNow(0);
check('毫秒模式填入 13 位', /^\d{13}$/.test(el('ts').value), true);
api.nowIntoDate();
check('填入此刻日期格式正确', /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(el('dt').value), true);
api.clearTs(); api.clearDate(); api.clearDiff();
check('清空后各输入框为空', [el('ts').value, el('dt').value, el('d1').value], ['', '', '']);

console.log('== 15. 渲染行 ==');
const rr = api.rows([['甲', '2026-09-25'], ['乙', 1700000000]]);
check('两行', (rr.match(/<div>/g) || []).length, 2);
check('含键名', rr.indexOf('<b>甲</b>') >= 0, true);
check('含值', rr.indexOf('<span>1700000000</span>') >= 0, true);

console.log('\n通过 ' + pass + ' 项，失败 ' + fail + ' 项');
process.exit(fail ? 1 : 0);
