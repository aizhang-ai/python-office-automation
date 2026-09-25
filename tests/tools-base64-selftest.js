// Base64 工具自检：用 DOM stub 在 Node 里加载 docs/tools/base64.html 的真实脚本，
// 验证 UTF-8 中文编解码、URL-safe、填充处理、非法输入拦截、data URI、页面动作。
// 运行：node tests/tools-base64-selftest.js
'use strict';
const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, '..', 'docs', 'tools', 'base64.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('没找到 script 块'); process.exit(1); }
const code = m[1];

// ---------- DOM stub ----------
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: '', textContent: '', innerHTML: '', className: '', checked: false, files: null };
  return els[id];
}
global.document = {
  getElementById: el,
  createElement: function () { return { style: {}, click() {}, remove() {}, href: '', download: '', type: '', onchange: null }; },
  body: { appendChild() {} }
};
try {
  Object.defineProperty(global, 'navigator', {
    value: { clipboard: { writeText: () => Promise.resolve() } },
    configurable: true, writable: true
  });
} catch (e) { /* 忽略 */ }
global.Blob = function () {};
global.URL = { createObjectURL: () => 'blob:stub', revokeObjectURL() {} };
global.FileReader = function () {};

const api = new Function(code + `
  return { bytesToB64, b64ToBytes, normalizeB64, wrapLines, isLikelyText,
           utf8Bytes, utf8Text, b64Val, dataUri, parseDataUri, extToMime,
           runEncode, runDecode, swapIn, clearEnc, clearDec, saveAsFile,
           get lastEnc(){return lastEnc;}, get lastBytes(){return lastBytes;} };
`)();

let pass = 0, fail = 0;
function check(name, actual, expect) {
  const a = JSON.stringify(actual), e = JSON.stringify(expect);
  if (a === e) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + '\n        期望 ' + e + '\n        实际 ' + a); }
}
const arr = (u) => Array.prototype.slice.call(u);
const B = (list) => new Uint8Array(list);

console.log('== 1. 标准已知值（RFC 4648 测试向量）==');
check('空 -> 空', api.bytesToB64(B([]), false, false), '');
check('"f" -> Zg==', api.bytesToB64(B([102]), false, false), 'Zg==');
check('"fo" -> Zm8=', api.bytesToB64(B([102, 111]), false, false), 'Zm8=');
check('"foo" -> Zm9v', api.bytesToB64(B([102, 111, 111]), false, false), 'Zm9v');
check('"foob" -> Zm9vYg==', api.bytesToB64(B([102, 111, 111, 98]), false, false), 'Zm9vYg==');
check('"fooba" -> Zm9vYmE=', api.bytesToB64(B([102, 111, 111, 98, 97]), false, false), 'Zm9vYmE=');
check('"foobar" -> Zm9vYmFy', api.bytesToB64(B([102, 111, 111, 98, 97, 114]), false, false), 'Zm9vYmFy');

console.log('== 2. 中文 / UTF-8（老式 btoa 会在这里翻车）==');
check('"中" -> 5Lit', api.bytesToB64(api.utf8Bytes('中'), false, false), '5Lit');
check('"你好" -> 5L2g5aW9', api.bytesToB64(api.utf8Bytes('你好'), false, false), '5L2g5aW9');
check('中文字节数正确', api.utf8Bytes('中').length, 3);
check('emoji 字节数正确', api.utf8Bytes('\u{1F600}').length, 4);
check('中文往返', api.utf8Text(api.b64ToBytes(api.bytesToB64(api.utf8Bytes('张明一的自动化小店'), false, false))), '张明一的自动化小店');
check('中英混排往返', api.utf8Text(api.b64ToBytes(api.bytesToB64(api.utf8Bytes('Hello, 世界! \u{1F680}'), false, false))), 'Hello, 世界! \u{1F680}');

console.log('== 3. URL-safe 与填充 ==');
// [251,255,254] 的 6 位分组是 62,63,63,62
check('+/ -> -_', api.bytesToB64(B([251, 255, 254]), true, false), '-__-');
check('标准下是 +//+', api.bytesToB64(B([251, 255, 254]), false, false), '+//+');
check('去掉填充', api.bytesToB64(B([102]), false, true), 'Zg');
check('去掉填充（2 字节）', api.bytesToB64(B([102, 111]), false, true), 'Zm8');
check('URL-safe 解码回原字节', arr(api.b64ToBytes('-__-')), [251, 255, 254]);
check('-_ 与 +/ 解出同样结果', arr(api.b64ToBytes('+//+')), arr(api.b64ToBytes('-__-')));
check('缺等号也能解', arr(api.b64ToBytes('Zg')), [102]);
check('缺两个等号也能解', arr(api.b64ToBytes('Zm8')), [102, 111]);

console.log('== 4. 归一化（空白 / 换行 / 长度校验）==');
check('去空格', api.normalizeB64('Zm 9v\nYmFy'), 'Zm9vYmFy');
check('去换行', api.normalizeB64('Zm9v\nYmFy\r\n'), 'Zm9vYmFy');
check('补 2 个等号', api.normalizeB64('Zg'), 'Zg==');
check('补 1 个等号', api.normalizeB64('Zm8'), 'Zm8=');
check('长度 4n+1 -> null', api.normalizeB64('Zm9vx'), null);
check('空串 -> 空串', api.normalizeB64(''), '');
check('url-safe 归一成标准', api.normalizeB64('-__-'), '+//+');

console.log('== 5. 非法输入拦截 ==');
check('含中文字符 -> null', api.b64ToBytes('Zm9v中文'), null);
check('含 @ -> null', api.b64ToBytes('Zm9v@'), null);
check('含 * -> null', api.b64ToBytes('Zm9v*'), null);
check('长度 4n+1 -> null', api.b64ToBytes('Zm9vx'), null);
check('b64Val 越界返回 -1', api.b64Val('#'), -1);
check('b64Val A=0', api.b64Val('A'), 0);
check('b64Val /=63', api.b64Val('/'), 63);
check('b64Val -=62', api.b64Val('-'), 62);

console.log('== 6. 二进制往返（随机字节）==');
const rnd = [];
let seed = 12345;
for (let i = 0; i < 300; i++) { seed = (seed * 1103515245 + 12345) & 0x7fffffff; rnd.push(seed % 256); }
check('300 随机字节往返一致', arr(api.b64ToBytes(api.bytesToB64(B(rnd), false, false))), rnd);
check('300 随机字节 URL-safe 往返一致', arr(api.b64ToBytes(api.bytesToB64(B(rnd), true, true))), rnd);

console.log('== 7. 折行 ==');
check('76 字符一行', api.wrapLines('a'.repeat(100), 76).split('\n'), ['a'.repeat(76), 'a'.repeat(24)]);
check('正好 76 不产生空行', api.wrapLines('a'.repeat(76), 76).split('\n').length, 1);
const wrapped = api.wrapLines(api.bytesToB64(api.utf8Bytes('你好，世界'), false, false), 76);
check('折行后仍能解回来', api.utf8Text(api.b64ToBytes(wrapped)), '你好，世界');

console.log('== 8. 是否像文本 ==');
check('中文算文本', api.isLikelyText(api.utf8Bytes('张明一的自动化小店')), true);
check('PNG 头不算文本', api.isLikelyText(B([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00])), false);
check('纯 ASCII 算文本', api.isLikelyText(api.utf8Bytes('hello world')), true);
check('空算文本', api.isLikelyText(B([])), true);

console.log('== 9. data URI ==');
const pngB64 = api.bytesToB64(B([0x89, 0x50, 0x4E, 0x47]), false, false);
check('拼 data URI', api.dataUri('image/png', pngB64), 'data:image/png;base64,' + pngB64);
check('缺省 mime', api.dataUri('', pngB64), 'data:application/octet-stream;base64,' + pngB64);
check('解析 data URI', api.parseDataUri('data:image/png;base64,' + pngB64), { mime: 'image/png', b64: pngB64 });
check('解析带换行的 URI', api.parseDataUri('data:image/png;base64,' + api.wrapLines(pngB64, 2)).b64.replace(/\n/g, ''), pngB64);
check('非 data URI -> null', api.parseDataUri('https://a.com/x.png'), null);
check('extToMime png', api.extToMime('a.PNG'), 'image/png');
check('extToMime jpg', api.extToMime('b.jpeg'), 'image/jpeg');
check('extToMime 未知', api.extToMime('c.zzz'), 'application/octet-stream');

console.log('== 10. 页面动作：编码 ==');
el('src').value = '你好，世界';
check('不勾任何选项', api.runEncode(), '5L2g5aW977yM5LiW55WM');
check('结果写进 DOM', el('outEnc').textContent, '5L2g5aW977yM5LiW55WM');
check('提示语报出字节数', el('msgEnc').textContent.indexOf('15 字节') >= 0, true);
el('nopad').checked = true;
api.runEncode();
check('去填充后无等号', el('outEnc').textContent.indexOf('='), -1);
el('nopad').checked = false;
el('wrap').checked = true;
el('src').value = '张明一的自动化小店'.repeat(20);   // 180 字节 -> 240 字符，够折 3 行
api.runEncode();
check('长文本折行后含换行', el('outEnc').textContent.indexOf('\n') >= 0, true);
check('折行每行不超过 76 字符', Math.max.apply(null, el('outEnc').textContent.split('\n').map(function (x){ return x.length; })), 76);
el('b64').value = el('outEnc').textContent;
check('折行解码结果正确', api.runDecode(), '张明一的自动化小店'.repeat(20));
el('wrap').checked = false;
el('src').value = '';
check('空输入返回 null', api.runEncode(), null);
check('空输入给错误提示', el('msgEnc').className.indexOf('err') >= 0, true);

console.log('== 11. 页面动作：解码 ==');
el('b64').value = '5L2g5aW977yM5LiW55WM';
check('解出原文', api.runDecode(), '你好，世界');
check('结果写进 DOM', el('outDec').textContent, '你好，世界');
check('提示语报出字节数', el('msgDec').textContent.indexOf('15 字节') >= 0, true);
check('文件名自动填好', el('fname').value, 'decoded.bin');
el('b64').value = 'Zm9v  YmFy\n';
check('带空格换行也能解', api.runDecode(), 'foobar');
el('b64').value = 'iVBORw0KGgo=';
api.runDecode();
check('二进制提示用户下载', el('msgDec').textContent.indexOf('还原成文件下载') >= 0, true);
el('b64').value = 'Zm9vx';
check('非法长度 -> null', api.runDecode(), null);
check('非法长度给错误提示', el('msgDec').className.indexOf('err') >= 0, true);
el('b64').value = 'Zm9v@';
check('非法字符 -> null', api.runDecode(), null);
el('b64').value = '';
check('空输入 -> null', api.runDecode(), null);

console.log('== 12. 用上面结果 / 清空 ==');
el('src').value = 'abc';
api.runEncode();
el('b64').value = '';
api.swapIn();
check('填入上一步的编码结果', el('b64').value, 'YWJj');
check('解回来是 abc', api.runDecode(), 'abc');
api.clearEnc(); api.clearDec();
check('清空后输入为空', [el('src').value, el('b64').value], ['', '']);
check('清空后输出复位', el('outEnc').textContent.indexOf('（点上面的'), 0);

console.log('\n通过 ' + pass + ' 项，失败 ' + fail + ' 项');
process.exit(fail ? 1 : 0);
