// 在线工具站自检：用轻量 DOM stub 在 Node 里跑 docs/tools/csv-cleaner.html 的真实脚本，
// 验证 CSV 解析、智能规范化、去重、排序、分组汇总是否真的正确。
// 运行：node tests/tools-selftest.js
'use strict';
const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, '..', 'docs', 'tools', 'csv-cleaner.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('没找到 script 块'); process.exit(1); }
const code = m[1];

// ---------- DOM stub ----------
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: '', textContent: '', innerHTML: '', className: '', addEventListener() {}, files: [] };
  return els[id];
}
els.delim = Object.assign(el('delim'), { value: ',' });
els.enc = Object.assign(el('enc'), { value: 'utf-8' });
els.sortDir = Object.assign(el('sortDir'), { value: 'desc' });
els.dedupeCol = Object.assign(el('dedupeCol'), { value: '手机' });
els.sortCol = Object.assign(el('sortCol'), { value: '金额' });
els.groupCol = Object.assign(el('groupCol'), { value: '城市' });
els.sumCol = Object.assign(el('sumCol'), { value: '金额' });
els.splitCol = Object.assign(el('splitCol'), { value: '' });

// 勾选：手机(2) 邮箱(3) 金额(5) 日期(6)
var checkedCols = [{ value: '2' }, { value: '3' }, { value: '5' }, { value: '6' }];

global.document = {
  getElementById: el,
  querySelectorAll: function () { return checkedCols; },
  createElement: function () { return { style: {}, click() {}, remove() {}, href: '', download: '' }; },
  body: { appendChild() {} }
};
try {
  Object.defineProperty(global, 'navigator', {
    value: { clipboard: { writeText: () => Promise.resolve() } },
    configurable: true, writable: true
  });
} catch (e) { /* Node 24 内置 navigator 只读时忽略，测试不调用剪贴板 */ }
global.Blob = function () {};
global.URL = { createObjectURL: () => 'blob:stub', revokeObjectURL() {} };
global.FileReader = function () {};

// ---------- 载入页面脚本 ----------
const api = new Function(code + `
  return { get state(){return state;}, setTable, doClean, doTrim, doDedupe, doSort, doGroup,
           parseCSV, toCSV, cleanVal, guessKind, render };
`)();

let pass = 0, fail = 0;
function check(name, actual, expect) {
  const a = JSON.stringify(actual), e = JSON.stringify(expect);
  if (a === e) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + '\n        期望 ' + e + '\n        实际 ' + a); }
}

const demo = [
  ['订单号', '姓名', '手机', '邮箱', '城市', '金额', '日期'],
  ['A001', '张伟', '138 0013 8000', 'ZhangWei@QQ.com', '上海', '1,200', '2026/9/1'],
  ['A002', '李娜', '139-0013-9000', 'lina@gmail.com', '北京', '980', '2026年9月2日'],
  ['A003', '王芳', ' 13800138000 ', 'zhangwei@qq.com', '上海', '1500', '2026.9.3'],
  ['A004', '刘洋', '1371234', 'bad-email', '广州', '800', '2026-09-04'],
  ['B001', '陈静', '13611112222', 'chenjing@163.com', '广州', '2,300', '20260905'],
  ['B002', '杨帆', '13500001111', 'yangfan@qq.com', '北京', '￥1200', '2026/9/6'],
  ['B003', '赵磊', '136 1111 2222', 'chenjing@163.com', '广州', '700', '2026-09-07']
];

console.log('== 1. CSV 解析（含引号、含逗号） ==');
const parsed = api.parseCSV('a,b,c\n1,"含,逗号","含""引号"""\n2,x,y', ',');
check('行数', parsed.length, 3);
check('引号内逗号未被拆分', parsed[1], ['1', '含,逗号', '含"引号"']);

console.log('== 2. 载入示例数据 ==');
api.setTable(demo);
check('列数', api.state.fields.length, 7);
check('行数', api.state.rows.length, 7);

console.log('== 3. 智能规范化（手机/邮箱/金额/日期） ==');
api.doClean();
const col = (n) => api.state.fields.indexOf(n);
const cell = (r, n) => api.state.rows[r][col(n)];
check('手机 138 0013 8000 -> 13800138000', cell(0, '手机'), '13800138000');
check('手机 139-0013-9000 -> 13900139000', cell(1, '手机'), '13900139000');
check('邮箱转小写 ZhangWei@QQ.com', cell(0, '邮箱'), 'zhangwei@qq.com');
check('非法邮箱保持原样 bad-email', cell(3, '邮箱'), 'bad-email');
check('金额去千分位 1,200 -> 1200', cell(0, '金额'), '1200');
check('金额去货币符 ￥1200 -> 1200', cell(5, '金额'), '1200');
check('日期 2026/9/1 -> 2026-09-01', cell(0, '日期'), '2026-09-01');
check('日期 2026年9月2日 -> 2026-09-02', cell(1, '日期'), '2026-09-02');
check('日期 2026.9.3 -> 2026-09-03', cell(2, '日期'), '2026-09-03');
check('日期 20260905 -> 2026-09-05', cell(4, '日期'), '2026-09-05');
check('已是标准格式的不动 2026-09-04', cell(3, '日期'), '2026-09-04');

console.log('== 4. 按手机去重（应有 2 组重复） ==');
api.doDedupe();
check('7 行去重后剩 5 行', api.state.rows.length, 5);

console.log('== 5. 按金额从大到小排序 ==');
api.doSort();
check('最大金额排第一', api.state.rows[0][col('金额')], '2300');
// 去重后剩 A001 1200 / A002 980 / A004 800 / B001 2300 / B002 1200，最小是 800
check('最小金额排最后', api.state.rows[api.state.rows.length - 1][col('金额')], '800');

console.log('== 6. 按城市分组求和（去重后 5 行） ==');
// 手工核对：北京 980+1200=2180；上海 1200；广州 800+2300=3100；总额 6480
api.doGroup();
const g = {};
api.state.group.forEach(function (r) { g[r[0]] = [r[1], r[2]]; });
check('北京 2 条 / 合计 2180', g['北京'], ['2', '2180']);
check('上海 1 条 / 合计 1200', g['上海'], ['1', '1200']);
check('广州 2 条 / 合计 3100', g['广州'], ['2', '3100']);
const total = api.state.group.reduce(function (s, r) { return s + Number(r[2]); }, 0);
const rowTotal = api.state.rows.reduce(function (s, r) { return s + Number(r[col('金额')]); }, 0);
check('分组合计总额 = 明细总额（6480）', total, rowTotal);

console.log('== 7. 导出 CSV 往返 ==');
const round = api.parseCSV(api.toCSV([api.state.fields].concat(api.state.rows)), ',');
check('导出再解析行数一致', round.length, api.state.rows.length + 1);

console.log('\n通过 ' + pass + ' 项，失败 ' + fail + ' 项');
process.exit(fail ? 1 : 0);
