// CSV↔JSON 互转工具自检：用 DOM stub 在 Node 里加载 docs/tools/csv-json.html 的真实脚本。
// 运行：node tests/tools-csvjson-selftest.js
'use strict';
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'docs', 'tools', 'csv-json.html'), 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('没找到 script 块'); process.exit(1); }

const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: '', textContent: '', innerHTML: '', className: '', checked: false, addEventListener() {} };
  return els[id];
}
els.delim = Object.assign(el('delim'), { value: ',' });
els.indent = Object.assign(el('indent'), { value: '2' });
els.hdr = Object.assign(el('hdr'), { checked: true });

global.document = {
  getElementById: el,
  querySelectorAll: () => [],
  createElement: () => ({ style: {}, click() {}, remove() {}, href: '', download: '' }),
  body: { appendChild() {} }
};
try {
  Object.defineProperty(global, 'navigator', {
    value: { clipboard: { writeText: () => Promise.resolve() } },
    configurable: true, writable: true
  });
} catch (e) {}
global.Blob = function () {};
global.URL = { createObjectURL: () => 'blob:stub', revokeObjectURL() {} };

const api = new Function(m[1] + `
  return { parseCSV, toCSV, csvToJson, jsonToCsv, parseDelim };
`)();

let pass = 0, fail = 0;
function check(name, actual, expect) {
  const a = JSON.stringify(actual), e = JSON.stringify(expect);
  if (a === e) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + '\n        期望 ' + e + '\n        实际 ' + a); }
}

console.log('== 1. CSV → JSON（首行为表头） ==');
const csv = 'name,city,amount\n张伟,上海,1200\n李娜,北京,980';
const arr = api.csvToJson(csv, true, ',');
check('2 条记录', arr.length, 2);
check('第一条字段正确', arr[0], { name: '张伟', city: '上海', amount: '1200' });
check('第二条字段正确', arr[1], { name: '李娜', city: '北京', amount: '980' });

console.log('== 2. CSV → JSON（无表头，转成二维数组） ==');
const arr2 = api.csvToJson('a,b\n1,2', false, ',');
check('第一行保持数组形态', arr2[0], ['a', 'b']);

console.log('== 3. JSON → CSV ==');
const objs = [
  { name: '张伟', city: '上海', amount: 1200 },
  { name: '李娜', city: '北京', amount: 980 }
];
const out = api.jsonToCsv(objs);
check('表头 + 2 行', out.split('\r\n').length, 3);
check('表头内容', out.split('\r\n')[0], 'name,city,amount');
check('数据行', out.split('\r\n')[1], '张伟,上海,1200');

console.log('== 4. 含逗号 / 引号的值必须被正确转义 ==');
const tricky = api.jsonToCsv([{ a: '含,逗号', b: '含"引号"' }]);
check('逗号与引号被包裹转义', tricky.split('\r\n')[1], '"含,逗号","含""引号"""');
check('转义后可被解析回来', api.parseCSV(tricky, ',')[1], ['含,逗号', '含"引号"']);

console.log('== 5. 字段不一致时取并集，缺失留空 ==');
const mixed = api.jsonToCsv([{ a: 1 }, { b: 2 }, { a: 3, b: 4 }]);
check('表头为并集', mixed.split('\r\n')[0], 'a,b');
check('缺失字段留空', mixed.split('\r\n')[1], '1,');

console.log('== 6. 往返一致：CSV → JSON → CSV ==');
const back = api.jsonToCsv(api.csvToJson(csv, true, ','));
check('往返后数据行一致', back.split('\r\n')[1], '张伟,上海,1200');
check('往返后行数一致', back.split('\r\n').length, 3);

console.log('\n通过 ' + pass + ' 项，失败 ' + fail + ' 项');
process.exit(fail ? 1 : 0);
