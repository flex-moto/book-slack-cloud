---
tags: Kindle
status: null
author: ミック
started: null
finished: null
evaluation: null
imageUrl: 'https://m.media-amazon.com/images/I/91MT5VmpjTL._SX1024.jpg'
kindle-bookId: '26016'
kindle-title: 達人に学ぶSQL徹底指南書 第2版 初級者で終わりたくないあなたへ CodeZine BOOKS
kindle-author: ミック
kindle-highlightsCount: 2
kindle-asin: B07GB4CNKP
kindle-lastAnnotatedDate: Invalid date
kindle-bookImageUrl: 'https://m.media-amazon.com/images/I/91MT5VmpjTL._SX1024.jpg'
---
![|300](https://m.media-amazon.com/images/I/91MT5VmpjTL._SX1024.jpg)

<!-- kindle-description:start -->
## 概要

SQLを扱うエンジニア必携のロングセラー、10年ぶりの改訂! ――SQLの正しい書き方・考え方が学べる本 開発者のためのWebマガジン「CodeZine」の人気連載を大幅加筆・修正して2008年に刊行、好評を博した『達人に学ぶSQL徹底指南書』の改訂・第2版です。 第2版では、初版構成を生かしつつ、SQLの強力な機能ウインドウ関数を全面的に採用して多くのコードをリバイスしました。全体的な解説の見直しや最新化も行ない、CASE式、ウィンドウ関数、外部結合、HAVING句、EXISTS述語など、SQLを扱うエンジニアに必要な「正しい書き方・考え方」「ビッグデータ時代に対応したモダンなSQL機能を駆使した書き方」を徹底解説しています。 標準SQL準拠のため、Oracle/SQL Server/DB2/PostgreSQL/MySQL等々の幅広いデータベースに対応しているほか、実際の開発現場でも活かしやすい実践的なコーディング事例も多数紹介しています。 チューニングテクニックやリレーショナルデータベースの歴史なども網羅。 SQLの原理となっている仕組みや、この言語を作った人々が何を考えて現在のような形にしたのか、というバックグラウンドも掘り起こして伝えます。 ・脱初級や、より高みを目指したいDBエンジニア、プログラマ ・「SQLとは何なのか」を知りたいと思っている人 ※本電子書籍は同名出版物を底本として作成しました。記載内容は印刷出版当時のものです。 ※印刷出版再現のため電子書籍としては不要な情報を含んでいる場合があります。 ※印刷出版とは異なる表記・表現の場合があります。予めご了承ください。 ※プレビューにてお手持ちの電子端末での表示状態をご確認の上、商品をお買い求めください。 (翔泳社)
<!-- kindle-description:end -->

## この本を読む目的

## この本を読んで取り入れたいアクションプラン

## Highlights
比較述語を適用できるのは値だけです。したがって、値ではないNULLに比較述語を適用することは、そもそもナンセンスなのです＊4。 それゆえ、「列の値がNULLである」とか「NULL値」「ナル値」といった表現も、まったくの誤りです。値ではないので、そもそもNULLは定義域（domain）に含まれていません＊5。逆に、NULLを値だと思っている人にたずねたいのですが、 もしNULLが値ならば、その型はいったい何でしょう。 リレーショナルデータベースで扱われる値はすべて、文字型や数値型など何らかの型を持ちます。仮にNULLが値なら、やはり何らかの型を持たねばなりません。しいて、NULLに対して積極的な定義を与えるなら、それは「ここには値がない」という 文の短縮形 です。 おそらく、NULLを値と勘違いしやすい理由は2つあります。第一の理由は、C言語などにおいてNULLが1つの定数（多くの処理系では整数0）として定義されているため、それと混同しがちなことです。SQLにおけるNULLと他のプログラミング言語のNULLは、まったくの別物です（参考資料の「 初級C言語 Q&A」を参照）。 第二の理由は、「IS NULL」という述語が2つの単語から構成されているので、「IS」が述語で「NULL」が値のように見えることです。特にSQLは、「IS TRUE」や「ISFALSE」といった述語も持っているので、それと類比的に考えると、こういう印象を抱くのも無理はありません。しかし標準SQLの解説書でも注意が促されているように、「IS NULL」はこれで1つの述語と見なすべきで、したがってむしろ「IS _NULL」と1語で書いたほうがふさわしいぐらいです＊6。 — location: [1463](kindle://book?action=open&asin=B07GB4CNKP&location=1463) ^ref-48397

無限大も、イコールで繋げられない

---
EXISTS述語が絶対に unknown を返さないからです。EXISTSは、 true と false しか返しません。この結果、INとEXISTSは同値変換が可能なのに、NOT INとNOT EXISTSは同値ではないという、まぎらわしい状況が生じています。プログラミングの際に直感に頼ることができないというのは困難な条件ですが、DBエンジニアはこの現象をよく理解しておく必要があります。 — location: [1634](kindle://book?action=open&asin=B07GB4CNKP&location=1634) ^ref-24632

---
