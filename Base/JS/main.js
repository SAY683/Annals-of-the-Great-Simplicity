/**
 * main.js
 * 存放网站通用交互脚本
 */

// 功能：控制“返回顶部”按钮的显示与隐藏
window.addEventListener('scroll', function() {
    var backToTopButton = document.getElementById('back-to-top');
    if (window.scrollY > 200) { // 当页面向下滚动超过 200px 时
        backToTopButton.style.display = 'block';
    } else {
        backToTopButton.style.display = 'none';
    }
});