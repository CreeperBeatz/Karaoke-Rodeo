// Furigana over the interface itself - every menu, heading, button and hint gets its reading.
// A curated dictionary of the words the UI actually uses (readings are for THIS interface's contexts), longest match
// first. A key may carry okurigana (歌って → the ruby sits over 歌 only). Song titles use their own stored readings
// (see rubyEl in common.js) and are skipped here via .noruby.
'use strict';

const KANJI = /[一-鿿々〆ヶ]/;
const DIGIT = /[0-9０-９]/;

// Counter readings after a number: 6日 → にち, 3人 → にん, 582音 → おん …
const AFTER_DIGIT = { '音': 'おん', '人': 'にん', '回': 'かい', '位': 'い', '分': 'ふん', '日': 'にち', '点': 'てん', '曲': 'きょく',
                      '桁': 'けた', '秒': 'びょう', '件': 'けん', '番': 'ばん', '月': 'がつ', '時': 'じ', '文字': 'もじ', '枚': 'まい' };

// key → reading of the kanji part of the key
const DICT = {
  // app vocabulary
  '一番乗り': 'いちばんの', '一度': 'いちど', '一人': 'ひとり', '以上': 'いじょう', '期限切れ': 'きげんぎ',
  '管理画面': 'かんりがめん', '管理者': 'かんりしゃ', '管理': 'かんり',
  '練習動画': 'れんしゅうどうが', '練習映像': 'れんしゅうえいぞう', '練習': 'れんしゅう',
  '上書き': 'うわが', '上達': 'じょうたつ', '上げ': 'あ', '上': 'うえ', '下': 'した',
  '今日': 'きょう', '今月': 'こんげつ', '仕上げ': 'しあ', '保存中': 'ほぞんちゅう', '保存': 'ほぞん',
  '入力': 'にゅうりょく', '入ります': 'はい', '入る': 'はい', '入り': 'い', '入れ': 'い', '入': 'い',
  '非公開': 'ひこうかい', '公開中': 'こうかいちゅう', '公開': 'こうかい', '写真': 'しゃしん',
  '再処理': 'さいしょり', '再利用': 'さいりよう', '再生': 'さいせい', '再': 'さい',
  '処理中': 'しょりちゅう', '処理': 'しょり', '判定': 'はんてい', '削除': 'さくじょ', '区間': 'くかん',
  '参加者': 'さんかしゃ', '参加画面': 'さんかがめん', '参加': 'さんか', '採点': 'さいてん',
  '曲名': 'きょくめい', '曲別': 'きょくべつ', '曲数': 'きょくすう', '曲': 'きょく',
  '更新': 'こうしん', '歌詞領域': 'かしりょういき', '歌詞': 'かし', '歌': 'うた',
  '点数': 'てんすう', '満点': 'まんてん', '得点': 'とくてん', '点': 'てん',
  '登録': 'とうろく', '確認': 'かくにん', '途中終了': 'とちゅうしゅうりょう', '途中': 'とちゅう', '終了': 'しゅうりょう', '終わ': 'お',
  '記録': 'きろく', '追加': 'ついか', '遅延補正': 'ちえんほせい', '遅延': 'ちえん', '補正': 'ほせい', '遅れ': 'おく',
  '中止': 'ちゅうし', '何位': 'なんい', '使': 'つか',
  '全画面': 'ぜんがめん', '全回': 'ぜんかい', '全曲': 'ぜんきょく', '全部': 'ぜんぶ', '全': 'ぜん', '内': 'ない',
  '出': 'で', '初': 'はじ', '動画': 'どうが', '動': 'うご', '友': 'とも', '呼': 'よ',
  '回目': 'かいめ', '回数': 'かいすう', '回': 'かい', '増': 'ふ', '変': 'か', '外': 'はず', '始': 'はじ',
  '未完走': 'みかんそう', '完走': 'かんそう', '家': 'いえ', '少し': 'すこ', '少ない': 'すく', '少': 'すこ',
  '広告': 'こうこく', '感': 'かん', '戻': 'もど', '抜': 'ぬ', '方': 'かた', '書': 'か',
  '最高得点': 'さいこうとくてん', '最高音': 'さいこうおん', '最低音': 'さいていおん', '最高': 'さいこう', '最初': 'さいしょ', '最後': 'さいご', '最近': 'さいきん', '最長': 'さいちょう',
  '検索': 'けんさく', '機': 'き', '次': 'つぎ', '正方形': 'せいほうけい', '正確': 'せいかく',
  '残': 'のこ', '殿堂': 'でんどう', '比': 'くら', '決': 'き', '消': 'き', '画面': 'がめん',
  '継': 'つ', '続': 'つづ', '線': 'せん', '色': 'いろ', '見': 'み', '許可': 'きょか', '誰': 'だれ', '走': 'はし', '込': 'こ', '送': 'おく',
  '連続日数': 'れんぞくにっすう', '連続': 'れんぞく', '開': 'ひら',
  '音程': 'おんてい', '音符': 'おんぷ', '音数': 'おんすう', '高音': 'こうおん', '音': 'おと',
  '順番待ち': 'じゅんばんま', '順位': 'じゅんい', '順': 'じゅん',
  '低': 'ひく', '作': 'つく', '単位': 'たんい', '取': 'と', '右上': 'みぎうえ', '右端': 'みぎはし', '名前': 'なまえ',
  '命中率': 'めいちゅうりつ', '命中': 'めいちゅう', '声': 'こえ', '実行中': 'じっこうちゅう', '実行': 'じっこう', '対象外': 'たいしょうがい', '対象': 'たいしょう',
  '小': 'ちい', '届': 'とど', '弱': 'よわ', '当': 'あ', '応答': 'おうとう', '手作業': 'てさぎょう', '手': 'て', '押': 'お',
  '数字': 'すうじ', '文字': 'もじ', '時間前': 'じかんまえ', '時間': 'じかん', '時': 'とき',
  '流': 'なが', '渡': 'わた', '準備中': 'じゅんびちゅう', '準備': 'じゅんび', '無効': 'むこう', '無料': 'むりょう', '現在': 'げんざい',
  '空': 'から', '自分': 'じぶん', '自己': 'じこ', '表示名': 'ひょうじめい', '表示': 'ひょうじ', '設定': 'せってい',
  '読': 'よ', '貼': 'は', '違': 'ちが', '選択': 'せんたく', '選': 'えら', '金色': 'きんいろ', '閉': 'と', '高': 'たか',
  '並': 'なら', '人': 'ひと', '付': 'つ', '光': 'ひか', '共有': 'きょうゆう', '分前': 'ふんまえ', '有効': 'ゆうこう', '分': 'ふん',
  '切': 'き', '割合': 'わりあい', '同': 'おな', '含': 'ふく', '多': 'おお', '夜': 'よる', '失敗': 'しっぱい', '履歴': 'りれき', '平均': 'へいきん',
  '引': 'ひ', '待': 'ま', '抽出': 'ちゅうしゅつ', '推移': 'すいい', '操作': 'そうさ', '日前': 'にちまえ', '日々': 'ひび', '日': 'ひ',
  '映像': 'えいぞう', '暗': 'くら', '桁': 'けた', '棒': 'ぼう', '漢字': 'かんじ', '濃': 'こ', '状態': 'じょうたい', '用': 'よう', '番目': 'ばんめ',
  '直近': 'ちょっきん', '競': 'きそ', '総合': 'そうごう', '隠': 'かく', '超': 'ちょう', '駆': 'か', '件': 'けん', '例': 'れい', '級': 'きゅう',
  '秒': 'びょう', '月': 'つき', '名': 'な', '目': 'め', '本物': 'ほんもの', '毎週': 'まいしゅう', '週': 'しゅう', '新': 'あたら', '古': 'ふる',
  '大': 'おお', '長': 'なが', '短': 'みじか', '早': 'はや', '速': 'はや', '前': 'まえ', '後': 'あと', '間': 'あいだ', '今': 'いま', '先': 'さき',
  '説明': 'せつめい', '注意': 'ちゅうい', '問題': 'もんだい', '準': 'じゅん', '進': 'すす', '止': 'と', '受': 'う', '待機': 'たいき', '接続': 'せつぞく',
  '端末': 'たんまつ', '許': 'ゆる', '不明': 'ふめい', '成功': 'せいこう', '完了': 'かんりょう', '開始': 'かいし', '停止': 'ていし', '調整': 'ちょうせい',
  '画像': 'がぞう', '形式': 'けいしき', '容量': 'ようりょう', '制限': 'せいげん', '通知': 'つうち', '言語': 'げんご', '英語': 'えいご', '日本語': 'にほんご',
};

// index by first character, longest keys first
const INDEX = new Map();
for (const k of Object.keys(DICT)) {
  const a = INDEX.get(k[0]) || [];
  a.push(k); INDEX.set(k[0], a);
}
for (const a of INDEX.values()) a.sort((x, y) => y.length - x.length);

function kanjiPrefix(s) { let i = 0; while (i < s.length && KANJI.test(s[i])) i++; return i; }
const isKata = (c) => /[゠-ヿ]/.test(c);

function annotate(text) {
  if (!KANJI.test(text)) return null;
  const frag = document.createDocumentFragment();
  let plain = '';
  let any = false;
  const flush = () => { if (plain) { frag.append(plain); plain = ''; } };
  const ruby = (base, rt) => {
    flush();
    any = true;
    const r = document.createElement('ruby');
    r.append(base);
    const t = document.createElement('rt'); t.textContent = rt; r.append(t);
    frag.append(r);
  };
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (!KANJI.test(c)) { plain += c; i++; continue; }
    // a counter right after a number (with an optional space)
    const before = text.slice(0, i).replace(/[ 　]+$/, '');
    const prev = before[before.length - 1] || '';
    if (DIGIT.test(prev)) {
      const two = text.slice(i, i + 2);
      if (AFTER_DIGIT[two]) { ruby(two, AFTER_DIGIT[two]); i += 2; continue; }
      if (AFTER_DIGIT[c]) { ruby(c, AFTER_DIGIT[c]); i += 1; continue; }
    }
    // 中: ちゅう after a word (パーティー中, 処理中), なか on its own
    if (c === '中' && (KANJI.test(prev) || isKata(prev))) { ruby('中', 'ちゅう'); i++; continue; }
    let hit = null;
    for (const k of INDEX.get(c) || []) if (text.startsWith(k, i)) { hit = k; break; }
    if (!hit) { plain += c; i++; continue; }
    const n = kanjiPrefix(hit);
    ruby(hit.slice(0, n), DICT[hit]);
    plain += hit.slice(n);
    i += hit.length;
  }
  flush();
  if (!any) return null;
  // Hand back ONE inline element, not a run of <ruby> and text. In a flex row - a button, a pill, the
  // party bar - every child of the container is its own flex item: the run would get the row's gap
  // wedged between a kanji and its okurigana, and centring would sit the taller ruby box (kanji plus
  // reading) lower than the plain kana beside it. Wrapped, the whole label is one item again.
  const box = document.createElement('span');
  box.className = 'rb';
  box.append(frag);
  return box;
}

// measured values (LED digits) and anything that carries its own reading are left alone
const SKIP_SEL = '.noruby, .readout, .value, .score, .final, .code, .pcode, ruby, [contenteditable]';
const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'RUBY', 'RT', 'RP', 'CODE', 'PRE', 'KBD', 'SVG', 'CANVAS', 'TITLE']);

export function applyFurigana(root = document.body) {
  if (!root || root.nodeType !== 1) return;
  if (root.closest && root.closest(SKIP_SEL)) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      const p = n.parentElement;
      if (!p || SKIP.has(p.tagName) || p.closest(SKIP_SEL)) return NodeFilter.FILTER_REJECT;
      return KANJI.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) {
    const frag = annotate(n.nodeValue);
    if (frag) n.replaceWith(frag);
  }
}
