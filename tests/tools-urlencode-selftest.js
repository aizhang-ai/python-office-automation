// URL 编码解码工具自检：用 DOM stub 在 Node 里加载 docs/tools/url-encode.html 的真实脚本，
// 验证组件编码与整串编码的差别、%20 与 +、中文往返、残缺编码拦截、查询串拆装、
// 重复键与无值键保留、批量处理，以及页面动作。
// 运行：node tests/tools-urlencode-selftest.js
'use strict';
const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, '..', 'docs', 'tools', 'url-encode.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('没找到 script 块'); process.exit(1); }
const code = m[1];

// ---------- DOM stub ----------
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: '', textContent: '', innerHTML: '', className: '', checked: false, style: {} };
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
  return { encComp, encKeep, encText, decSafe, decForm, decText,
           toPairs, safeDec, baseOf, hashOf, buildQuery, pairsToText, textToPairs,
           runEnc, runDec, swap, clearEnc, runSplit, runJoin, clearQ, runBatch, esc };
`)();

let pass = 0, fail = 0;
function check(name, actual, expect) {
  const a = JSON.stringify(actual), e = JSON.stringify(expect);
  if (a === e) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + '\n        期望 ' + e + '\n        实际 ' + a); }
}
function ok(name, cond) { check(name, !!cond, true); }

console.log('== 1. 组件编码 encComp ==');
check('中文', api.encComp('张三'), '%E5%BC%A0%E4%B8%89');
check('空格 -> %20', api.encComp('a b'), 'a%20b');
check('斜杠被转义', api.encComp('a/b'), 'a%2Fb');
check('冒号被转义', api.encComp('a:b'), 'a%3Ab');
check('问号被转义', api.encComp('a?b'), 'a%3Fb');
check('& 被转义', api.encComp('a&b'), 'a%26b');
check('= 被转义', api.encComp('a=b'), 'a%3Db');
check('# 被转义', api.encComp('a#b'), 'a%23b');
check('字母数字不转义', api.encComp('abc123'), 'abc123');
check('-_.~ 不转义', api.encComp('a-_.~b'), 'a-_.~b');
check('空串', api.encComp(''), '');
check('null 当空串', api.encComp(null), '');

console.log('== 2. 整串编码 encKeep（保留结构字符）==');
check('保留 /', api.encKeep('a/b'), 'a/b');
check('保留 : 与 //', api.encKeep('https://a.com'), 'https://a.com');
check('保留 ?', api.encKeep('a?b'), 'a?b');
check('保留 &', api.encKeep('a&b'), 'a&b');
check('保留 =', api.encKeep('a=b'), 'a=b');
check('保留 #', api.encKeep('a#b'), 'a#b');
check('中文仍转义', api.encKeep('https://a.com/搜?q=张三'), 'https://a.com/%E6%90%9C?q=%E5%BC%A0%E4%B8%89');
ok('整串模式下不再含 %2F', api.encKeep('a/b').indexOf('%2F') < 0);

console.log('== 3. encText 的两种模式 ==');
check('参数值模式', api.encText('a/b=1', false, false), 'a%2Fb%3D1');
check('整串模式', api.encText('a/b=1', true, false), 'a/b=1');
check('空格转 +', api.encText('a b c', false, true), 'a+b+c');
check('空格默认 %20', api.encText('a b c', false, false), 'a%20b%20c');
check('中文 + 空格', api.encText('张三 北京', false, true), '%E5%BC%A0%E4%B8%89+%E5%8C%97%E4%BA%AC');

console.log('== 4. 解码 ==');
check('解中文', api.decSafe('%E5%BC%A0%E4%B8%89'), '张三');
check('解空格', api.decSafe('a%20b'), 'a b');
check('解 + 号不当空格（标准解码）', api.decSafe('a+b'), 'a+b');
check('form 解码把 + 当空格', api.decForm('a+b'), 'a b');
check('无转义原样返回', api.decSafe('abc123'), 'abc123');
check('空串', api.decSafe(''), '');

console.log('== 5. 残缺 / 非法编码必须拦下（不能崩）==');
check('半个字 %E5', api.decSafe('%E5'), null);
check('单字符 %', api.decSafe('%'), null);
check('%zz 非法', api.decSafe('%zz'), null);
check('%E5%BC 不完整', api.decSafe('%E5%BC'), null);
check('孤立高位字节 %80', api.decSafe('%80'), null);
check('合法部分能解', api.decSafe('a%E5%BC%A0b'), 'a张b');

console.log('== 6. 编码→解码 往返 ==');
const samples = ['', 'abc', 'a b', 'a/b?c=1&d=2', '张三', '张三 138-0013-8000',
  '搜索词=张三&城市=北京', 'https://example.com/搜?q=中文#锚', '100%纯棉', 'a+b=c d'];
samples.forEach(function (s, i) {
  check('往返 #' + i + ' ' + JSON.stringify(s).slice(0, 26),
        api.decSafe(api.encComp(s)), s);
});

console.log('== 7. baseOf / hashOf ==');
check('取 ? 之前', api.baseOf('https://a.com/p?q=1'), 'https://a.com/p');
check('无 ? 原样', api.baseOf('https://a.com/p'), 'https://a.com/p');
check('取 # 之后', api.hashOf('https://a.com/p?q=1#top'), '#top');
check('无 # 返回空', api.hashOf('https://a.com/p'), '');
check('空串', api.baseOf(''), '');

console.log('== 8. toPairs 拆查询串 ==');
check('简单两个参数', api.toPairs('?q=1&page=2'), [['q', '1'], ['page', '2']]);
check('不带 ? 也能拆', api.toPairs('q=1&page=2'), [['q', '1'], ['page', '2']]);
check('中文值被还原', api.toPairs('?q=%E5%BC%A0%E4%B8%89'), [['q', '张三']]);
check('键也还原', api.toPairs('?%E5%9F%8E%E5%B8%82=%E5%8C%97%E4%BA%AC'), [['城市', '北京']]);
check('保留重复键', api.toPairs('?a=1&a=2'), [['a', '1'], ['a', '2']]);
check('无值参数', api.toPairs('?a&b=2'), [['a', ''], ['b', '2']]);
check('忽略 # 锚点', api.toPairs('?a=1#top'), [['a', '1']]);
check('空查询串', api.toPairs('https://a.com'), []);
check('带路径无参数返回空', api.toPairs('https://a.com/p'), []);
check('带端口无参数返回空', api.toPairs('https://a.com:8080/x'), []);
check('裸的名=值仍能拆', api.toPairs('城市=北京'), [['城市', '北京']]);
check('不含 = 的裸串不拆', api.toPairs('flag'), []);
check('跳过空片段', api.toPairs('?a=1&&b=2'), [['a', '1'], ['b', '2']]);
check('残缺编码不崩（原样保留）', api.toPairs('?a=%E5').length, 1);

console.log('== 9. buildQuery 组装 ==');
check('组装并转义', api.buildQuery([['q', '张三'], ['page', '2']], false),
      'q=%E5%BC%A0%E4%B8%89&page=2');
check('plus 模式空格转 +', api.buildQuery([['kw', 'a b']], true), 'kw=a+b');
check('默认空格 %20', api.buildQuery([['kw', 'a b']], false), 'kw=a%20b');
check('空数组返回空串', api.buildQuery([], false), '');
check('保留重复键', api.buildQuery([['a', '1'], ['a', '2']], false), 'a=1&a=2');
check('无值键', api.buildQuery([['a', '']], false), 'a=');
ok('组装后 & 未被二次转义', api.buildQuery([['a', '1'], ['b', '2']], false).indexOf('%26') < 0);

console.log('== 10. 参数文本 ↔ 数组 ==');
check('数组转文本', api.pairsToText([['q', '1'], ['page', '2']]), 'q=1\npage=2');
check('文本转数组', api.textToPairs('q=1\npage=2'), [['q', '1'], ['page', '2']]);
check('跳过空行', api.textToPairs('q=1\n\n\npage=2'), [['q', '1'], ['page', '2']]);
check('无 = 的行当无值键', api.textToPairs('flag'), [['flag', '']]);
check('值里含 = 只切第一个', api.textToPairs('a=b=c'), [['a', 'b=c']]);
check('CRLF 也能处理', api.textToPairs('a=1\r\nb=2'), [['a', '1'], ['b', '2']]);
check('空文本', api.textToPairs(''), []);
check('往返一致', api.textToPairs(api.pairsToText([['城市', '北京'], ['q', 'a b']])),
      [['城市', '北京'], ['q', 'a b']]);

console.log('== 11. esc 防注入 ==');
check('转义 <', api.esc('<script>'), '&lt;script&gt;');
check('转义 &', api.esc('a&b'), 'a&amp;b');
check('普通文本不变', api.esc('张三 北京'), '张三 北京');

console.log('== 12. 页面动作：编码 / 解码 ==');
el('uIn').value = '张三 北京';
el('optKeep').checked = false; el('optPlus').checked = false;
const enc = api.runEnc();
check('编码结果', enc, '%E5%BC%A0%E4%B8%89%20%E5%8C%97%E4%BA%AC');
check('写进 uOut', el('uOut').value, enc);
check('提示为成功态', el('msgEnc').className.indexOf('ok') >= 0, true);
ok('统计里有字符数', el('statEnc').textContent.indexOf('字符') >= 0);

el('uIn').value = enc;
check('解码还原', api.runDec(), '张三 北京');
check('解码写进 uOut', el('uOut').value, '张三 北京');

el('optPlus').checked = true;
el('uIn').value = '张三 北京';
check('plus 模式编码', api.runEnc(), '%E5%BC%A0%E4%B8%89+%E5%8C%97%E4%BA%AC');
el('uIn').value = '%E5%BC%A0%E4%B8%89+%E5%8C%97%E4%BA%AC';
check('plus 模式解码', api.runDec(), '张三 北京');
el('optPlus').checked = false;

el('optKeep').checked = true;
el('uIn').value = 'https://a.com/搜?q=张三';
check('整串模式编码', api.runEnc(), 'https://a.com/%E6%90%9C?q=%E5%BC%A0%E4%B8%89');
el('optKeep').checked = false;

el('uIn').value = '%E5';
check('残缺编码返回 null', api.runDec(), null);
check('残缺时清空输出', el('uOut').value, '');
ok('残缺时给错误提示', el('msgEnc').className.indexOf('err') >= 0);

el('uIn').value = '';
check('空输入编码返回 null', api.runEnc(), null);
check('空输入解码返回 null', api.runDec(), null);

console.log('== 13. swap / clearEnc ==');
el('uIn').value = 'abc'; el('optKeep').checked = false; el('optPlus').checked = false;
const e2 = api.runEnc();
api.swap();
check('swap 把结果填回输入框', el('uIn').value, e2);
api.clearEnc();
check('清空输入', el('uIn').value, '');
check('清空输出', el('uOut').value, '');

console.log('== 14. 页面动作：查询串拆装 ==');
el('qIn').value = 'https://example.com/search?q=%E5%BC%A0%E4%B8%89&page=2&city=%E5%8C%97%E4%BA%AC';
const pairs = api.runSplit();
check('拆出 3 个参数', pairs.length, 3);
check('参数写进文本框', el('qPairs').value, 'q=张三\npage=2\ncity=北京');
ok('信息面板已显示', el('qInfo').style.display === 'grid');
ok('信息面板含转义后的 HTML', typeof el('qInfo').innerHTML === 'string' && el('qInfo').innerHTML.length > 0);

const joined = api.runJoin();
check('拼回完整网址', joined,
      'https://example.com/search?q=%E5%BC%A0%E4%B8%89&page=2&city=%E5%8C%97%E4%BA%AC');
check('结果写进 qOut', el('qOut').value, joined);

// 改一个参数再拼
el('qPairs').value = 'q=李四\npage=9';
check('改完再拼', api.runJoin(), 'https://example.com/search?q=%E6%9D%8E%E5%9B%9B&page=9');

el('qIn').value = 'https://a.com';
check('无参数返回 null', api.runSplit(), null);
el('qIn').value = '';
check('空输入返回 null', api.runSplit(), null);
el('qPairs').value = '';
check('参数框空时拼装返回 null', api.runJoin(), null);
api.clearQ();
check('清空后 qOut 为空', el('qOut').value, '');

console.log('== 15. 批量 ==');
el('bIn').value = '张三\n北京 朝阳\na/b?c=1';
el('optKeep').checked = false; el('optPlus').checked = false;
check('批量编码', api.runBatch(1),
      ['%E5%BC%A0%E4%B8%89', '%E5%8C%97%E4%BA%AC%20%E6%9C%9D%E9%98%B3', 'a%2Fb%3Fc%3D1']);
el('bIn').value = '%E5%BC%A0%E4%B8%89\n%E5%8C%97%E4%BA%AC%20%E6%9C%9D%E9%98%B3';
check('批量解码', api.runBatch(0), ['张三', '北京 朝阳']);
check('批量结果写进 bOut（按行拼接）', el('bOut').value, '张三\n北京 朝阳');
el('bIn').value = 'a\n\nb';
check('空行保持为空行', api.runBatch(1), ['a', '', 'b']);
el('bIn').value = '%E5%BC%A0%E4%B8%89\n%E5\nok';
const badOut = api.runBatch(0);
ok('解不开的行被标出', badOut[1].indexOf('解不开') >= 0);
check('其他行仍正常', badOut[2], 'ok');
ok('统计提示有 1 行解不开', el('statB').textContent.indexOf('1 行解不开') >= 0);

console.log('== 16. 一致性与幂等 ==');
const once = api.encComp('张三&北京');
check('编两次后能解回一次的结果', api.decSafe(api.encComp(once)), once);
check('二次编码会转义 %（文档里提醒过的坑）', api.encComp('%'), '%25');
check('解两次能回到原文', api.decSafe(api.decSafe(api.encComp(api.encComp('张三')))), '张三');

console.log('');
console.log('----------------------------------------');
console.log('URL 编码工具自检：通过 ' + pass + ' 项，失败 ' + fail + ' 项');
console.log('----------------------------------------');
process.exit(fail ? 1 : 0);
