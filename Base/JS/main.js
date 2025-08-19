// js/main.js

document.addEventListener('DOMContentLoaded', () => {

    const backToTopButton = document.getElementById('back-to-top');
    const directory = document.querySelector('.floating-directory');

    // --- 滚动事件统一处理 ---
    const handleScroll = () => {
        const scrollY = window.scrollY;

        // 控制“返回顶部”按钮的显示/隐藏
        if (backToTopButton) {
            backToTopButton.style.display = (scrollY > 200) ? 'block' : 'none';
        }

        // 控制“悬浮目录”的浮现/消失
        if (directory) {
            directory.classList.toggle('visible', scrollY > 300);
        }
    };
    
    window.addEventListener('scroll', handleScroll);

    // --- 悬浮目录滚动监听 (Scrollspy) ---
    const directoryLinks = document.querySelectorAll('.floating-directory a');
    
    if (directoryLinks.length > 0) {
        const sections = Array.from(directoryLinks).map(link => {
            const sectionId = link.getAttribute('href').substring(1);
            return document.getElementById(sectionId);
        }).filter(section => section !== null);

        const highlightDirectoryLink = () => {
            const scrollPosition = window.scrollY;
            let currentSectionId = '';

            for (const section of sections) {
                const sectionTop = section.offsetTop - 150;
                if (scrollPosition >= sectionTop) {
                    currentSectionId = section.getAttribute('id');
                }
            }

            directoryLinks.forEach(link => {
                const isActive = link.getAttribute('href') === `#${currentSectionId}`;
                link.classList.toggle('active', isActive);
            });
        };

        window.addEventListener('scroll', highlightDirectoryLink);
        highlightDirectoryLink(); // Initial check
    }
});