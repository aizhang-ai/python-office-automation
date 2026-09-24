// 文本差异对比工具自检：用 DOM stub 在 Node 里加载 docs/tools/text-diff.html 的真实脚本，
// 验证切行、归一化、LCS 逐行比对、统计与渲染是否真的正确。
// 运行：node tests/tools-diff-selftest.js
'use strict';
const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, '..', 'docs', 'tools', 'text-diff.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('没找到 script 块'); process.exit(1); }
const code = m[1];

// ---------- DOM stub ----------
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: '', textContent: '', innerHTML: '', className: '' };
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
} catch (e) { /* 忽略：Node 内置 navigator 只读，测试不调用剪贴板 */ }
global.Blob = function () {};
global.URL = { createObjectURL: () => 'blob:stub', revokeObjectURL() {} };

// ---------- 载入页面脚本 ----------
const api = new Function(code + `
  return { splitLines, norm, diffLines, lcsOps, stats, toUnified, renderSide,
           runDiff, get lastOut(){return lastOut;} };
`)();

let pass = 0, fail = 0;
function check(name, actual, expect) {
  const a = JSON.stringify(actual), e = JSON.stringify(expect);
  if (a === e) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + '\n        期望 ' + e + '\n        实际 ' + a); }
}

function setAB(a, b, opt) {
  el('a').value = a; el('b').value = b;
  el('igcase').checked = !!(opt && opt.ignoreCase);
  el('igspace').checked = !!(opt && opt.ignoreSpace);
  return api.runDiff();
}

console.log('== 1. 切行：CRLF / CR / 末尾换行 ==');
check('\\r\\n 归一', api.splitLines('a\r\nb\r\n'), ['a', 'b']);
check('单独 \\r 归一', api.splitLines('a\rb'), ['a', 'b']);
check('末尾多余换行不产生空行', api.splitLines('a\nb\n'), ['a', 'b']);
check('空输入 -> 空数组', api.splitLines(''), []);

console.log('== 2. 归一化 ==');
check('忽略大小写', api.norm('AbC', { ignoreCase: true }), 'abc');
check('忽略空白：多空格压成一个', api.norm('a   b ', { ignoreSpace: true }), 'a b');
check('不忽略时原样', api.norm('a   b ', {}), 'a   b ');

console.log('== 3. 完全相同 -> 全部未改动 ==');
let r = setAB('甲\n乙\n丙', '甲\n乙\n丙');
check('无新增无删除', [r.stats.add, r.stats.del, r.stats.same], [0, 0, 3]);

console.log('== 4. 末尾新增 1 行 ==');
r = setAB('甲\n乙', '甲\n乙\n丙');
check('新增 1 行', [r.stats.add, r.stats.del, r.stats.same], [1, 0, 2]);

console.log('== 5. 删掉 1 行 ==');
r = setAB('甲\n乙\n丙', '甲\n丙');
check('删除 1 行', [r.stats.add, r.stats.del, r.stats.same], [0, 1, 2]);

console.log('== 6. 改了中间 1 行 -> 1 删 1 增 ==');
r = setAB('第一行\n第二行\n第三行', '第一行\n第二行改了\n第三行');
check('1 增 1 删', [r.stats.add, r.stats.del, r.stats.same], [1, 1, 2]);

console.log('== 7. 忽略大小写 / 忽略空白 ==');
r = setAB('ABC\nDEF', 'abc\ndef', { ignoreCase: true });
check('忽略大小写后视为未改动', [r.stats.add, r.stats.del], [0, 0]);
r = setAB('a  b\nc', 'a b\nc', { ignoreSpace: true });
check('忽略空白后视为未改动', [r.stats.add, r.stats.del], [0, 0]);
r = setAB('a  b\nc', 'a b\nc');
check('不勾忽略空白时算 1 删 1 增', [r.stats.add, r.stats.del], [1, 1]);

console.log('== 8. 不变式：删除行+未改动行 = 原文；新增行+未改动行 = 新文 ==');
const A = ['合同甲方：张明一', '金额：9800 元', '交付：2026-09-30', '备注：无'];
const B = ['合同甲方：张明一', '金额：12800 元', '交付：2026-09-30', '备注：无', '违约：逾期计息'];
const ops = api.diffLines(A, B, {});
const fromA = ops.filter(o => o.t !== 'add').map(o => A[o.a]);
const fromB = ops.filter(o => o.t !== 'del').map(o => B[o.b]);
check('删除行+未改动行 拼回原文', fromA, A);
check('新增行+未改动行 拼回新文', fromB, B);

console.log('== 9. 统一视图输出前缀 ==');
const uni = api.toUnified(ops, A, B);
check('含 - 行（旧金额）', uni.indexOf('- 金额：9800 元') >= 0, true);
check('含 + 行（新金额）', uni.indexOf('+ 金额：12800 元') >= 0, true);
check('未改动行前缀两个空格', uni.indexOf('  合同甲方：张明一') >= 0, true);

console.log('== 10. 左右并排渲染 ==');
const side = api.renderSide(ops, A, B);
check('左栏有删除行样式', side.left.indexOf('class="ln del"') >= 0, true);
check('右栏有新增行样式', side.right.indexOf('class="ln add"') >= 0, true);
check('HTML 已转义 & <', api.renderSide([{ t: 'eq', a: 0, b: 0 }], ['a&b<c'], ['a&b<c']).left.indexOf('a&amp;b&lt;c') >= 0, true);

console.log('== 11. 一边为空 ==');
r = setAB('', '新增的第一行');
check('原文空时全是新增', [r.stats.add, r.stats.del], [1, 0]);

console.log('== 12. 大文本自动降级（不卡死） ==');
const big1 = [], big2 = [];
for (let i = 0; i < 3000; i++) big1.push('行' + i);
for (let i = 0; i < 3000; i++) big2.push('行' + (i + 1));
const t0 = Date.now();
const bigOps = api.diffLines(big1, big2, {});
const cost = Date.now() - t0;
check('3000 行 × 3000 行能出结果', bigOps.length > 0, true);
check('降级后条目数不超 6000', bigOps.length <= 6000, true);
console.log('        （耗时 ' + cost + ' ms）');

console.log('\n通过 ' + pass + ' 项，失败 ' + fail + ' 项');
process.exit(fail ? 1 : 0);
