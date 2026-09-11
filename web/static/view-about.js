// について - what this is, how signing in works.
export default {
  title: 'このサイトについて',

  render(main) {
    main.innerHTML = `
  <div class="box stack" style="gap:16px">
    <section class="panel">
      <h2>カラオケ.ロデオについて <span class="sub">about</span></h2>
      <p>カラオケ@DIVA の練習動画をブラウザで再生して、マイクの音程を音符バーと比べます。カラオケ機みたいに点数が出て、記録が残る。
        ひとりの練習にも、スマホで参加するパーティーにも。</p>
      <div class="tags">
        <span class="pill">ふりがな付き映像</span><span class="pill">リアルタイム採点</span><span class="pill">1〜8人</span><span class="pill">無料</span>
      </div>
    </section>
    <section class="panel">
      <h2>ログインについて <span class="sub">signing in</span></h2>
      <p>メールだけでログイン、1分。パスワードなし、アプリなし。届いたリンクを開くか、6桁のコードを入れるだけです。</p>
    </section>
    <section class="panel mission">
      <h2>ミッション <span class="sub">our mission</span></h2>
      <p>I started studying for N3 and hit the wall every learner hits: to actually hold a conversation, you have to read fast
        enough and speak fast enough. The best solution I read about is shadowing - following the words out loud, at full speed.
        And the most enjoyable way to shadow, in my opinion, is karaoke.</p>
      <p>But no karaoke app had <b>scoring</b>, <b>Japanese songs</b>, and <b>furigana</b> at the same time. There was
        always one element missing. So I built &#12459;&#12521;&#12458;&#12465;.&#12525;&#12487;&#12458;.</p>
      <p>This is also why the site itself is in Japanese. Furigana is there to help you through, and hovering over a label shows
        you the English, but there is no English option by itself. The point is for your eyes to start recognising
        the characters, not to switch back to English and forget Japanese was ever an option.</p>
      <p>It is built on openly available karaoke videos, it is free, and it stays free. I want to bring the joy of karaoke to
        everyone, and give Japanese learners somewhere to practise - on your own, in a classroom, or at a party.</p>
    </section>
  </div>`;
  },
};
