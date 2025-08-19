// js/main.js

document.addEventListener('DOMContentLoaded', () => {

    const backToTopButton = document.getElementById('back-to-top');
    const directory = document.querySelector('.floating-directory');
    const mobileTrigger = document.getElementById('mobile-directory-trigger');
    const directoryLinks = document.querySelectorAll('.floating-directory a');

    // --- 统一的滚动事件处理 ---
    const handleScroll = () => {
        const scrollY = window.scrollY;
        if (backToTopButton) {
            backToTopButton.style.display = (scrollY > 200) ? 'block' : 'none';
        }
        if (directory && window.innerWidth > 1024) { // 只在桌面端处理浮现
            directory.classList.toggle('visible', scrollY > 300);
        }
    };
    window.addEventListener('scroll', handleScroll);

    // --- 桌面端：滚动监听 (Scrollspy) ---
    if (directoryLinks.length > 0 && window.innerWidth > 1024) {
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
        highlightDirectoryLink();
    }
    
    // --- 【新增】移动端：菜单打开/关闭逻辑 ---
    if (mobileTrigger && directory) {
        // 打开菜单
        mobileTrigger.addEventListener('click', () => {
            directory.classList.toggle('is-open');
        });

        // 点击菜单项后自动关闭菜单
        directoryLinks.forEach(link => {
            // 在移动端，用 data-title 填充链接文本
            if (window.innerWidth <= 1024) {
                link.textContent = link.getAttribute('data-title');
            }
            link.addEventListener('click', () => {
                directory.classList.remove('is-open');
            });
        });
    }
});