/**
 * BASE 导航隧道模式自适应
 * ========================
 * P1-2 (§20.12): 替代 9 处硬编码 127.0.0.1:PORT，
 * 根据当前 hostname 自动适配本地/隧道模式。
 *
 * OPT-7 (2026-07-30 审计): 从 index.html 内联 <script> 抽取为外部文件，
 * 以便移除 CSP 的 unsafe-inline，改用 nonce-free 的纯外部脚本策略。
 */
(function () {
  var nav = document.getElementById('baseNav');
  if (!nav) return;
  var selfPort = document.body.getAttribute('data-self-port') || '';
  var host = window.location.hostname;
  var isTunnel = /trycloudflare\.com$|\.cfargotunnel\.com$/.test(host);
  var links = nav.querySelectorAll('a[data-port]');
  links.forEach(function (a) {
    var port = a.getAttribute('data-port');
    if (port === selfPort) {
      // 当前项目: 用相对路径, 隧道/本地均可
      a.href = '/';
    } else if (isTunnel) {
      // 隧道模式跨项目: 从 localStorage 读取已配置的隧道 URL
      var saved = localStorage.getItem('tunnel_url_' + port);
      if (saved) {
        a.href = saved;
        a.target = '_blank';
        a.rel = 'noopener';
      } else {
        a.href = '#';
        a.classList.add('tunnel-unconfigured');
        a.title = '隧道模式下未配置此项目的 URL, 点击配置';
        a.addEventListener('click', function (e) {
          e.preventDefault();
          var label = a.textContent.trim();
          var input = prompt('请输入 ' + label + ' (端口 ' + port + ') 的隧道 URL (如 https://xxx.trycloudflare.com):');
          if (input) {
            try { new URL(input); } catch (err) { alert('URL 格式无效'); return; }
            localStorage.setItem('tunnel_url_' + port, input);
            a.href = input;
            a.target = '_blank';
            a.rel = 'noopener';
            a.classList.remove('tunnel-unconfigured');
          }
        });
      }
    } else {
      // 本地模式: 保持 127.0.0.1:PORT
      a.href = 'http://127.0.0.1:' + port;
      // P1 fix (Round 22 §4): 跨项目跳转在新标签页打开, 避免中断当前页 SSE 实时汇报.
      a.target = '_blank';
      a.rel = 'noopener';
    }
  });
})();
