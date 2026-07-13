// js/main.js

document.addEventListener('DOMContentLoaded', () => {

    const backToTopButton = document.getElementById('back-to-top');
    const directory = document.querySelector('.floating-directory');
    const mobileTrigger = document.getElementById('mobile-directory-trigger');
    const directoryLinks = document.querySelectorAll('.floating-directory a');

    // --- 全站导航头部（移动端汉堡菜单） ---
    const siteNavToggle = document.querySelector('.site-nav-toggle');
    const siteNav = document.querySelector('.site-nav');
    const siteNavLinks = document.querySelectorAll('.site-nav-list a, .site-nav-local a');

    if (siteNavToggle && siteNav) {
        function closeSiteNav() {
            siteNav.classList.remove('is-open');
            siteNavToggle.setAttribute('aria-expanded', 'false');
            siteNavToggle.setAttribute('aria-label', '打开导航');
        }

        function openSiteNav() {
            siteNav.classList.add('is-open');
            siteNavToggle.setAttribute('aria-expanded', 'true');
            siteNavToggle.setAttribute('aria-label', '关闭导航');
        }

        siteNavToggle.addEventListener('click', () => {
            if (siteNav.classList.contains('is-open')) {
                closeSiteNav();
            } else {
                openSiteNav();
            }
        });

        siteNavLinks.forEach(link => {
            link.addEventListener('click', closeSiteNav);
        });

        document.addEventListener('click', (e) => {
            if (siteNav.classList.contains('is-open') &&
                !siteNav.contains(e.target) &&
                !siteNavToggle.contains(e.target)) {
                closeSiteNav();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && siteNav.classList.contains('is-open')) {
                closeSiteNav();
            }
        });
    }

    // --- TRACE Engine 本地服务状态检测 ---
    const TRACE_ORIGIN = 'http://localhost:3000';
    const traceBadge = document.getElementById('trace-status-badge');
    const traceText = document.getElementById('trace-status-text');
    const traceCheckBtn = document.getElementById('trace-check-btn');
    const traceOpenBtn = document.getElementById('trace-open-btn');

    function setTraceStatus(state, message) {
        if (!traceBadge || !traceText) return;
        traceBadge.className = 'status-badge';
        traceBadge.textContent = state.toUpperCase();
        traceText.textContent = message;
        if (state === 'online') {
            traceBadge.classList.add('status-online');
            if (traceOpenBtn) traceOpenBtn.classList.remove('portal-card-button-secondary');
        } else if (state === 'offline') {
            traceBadge.classList.add('status-offline');
        } else {
            traceBadge.classList.add('status-local');
        }
    }

    async function checkTraceEngineStatus() {
        setTraceStatus('local', '正在检测…');
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 3500);
            const res = await fetch(`${TRACE_ORIGIN}/api/health`, {
                method: 'GET',
                signal: controller.signal,
                mode: 'cors',
            });
            clearTimeout(timeoutId);
            if (res.ok) {
                const data = await res.json().catch(() => ({}));
                const status = data.status === 'healthy' ? 'HEALTHY' : 'DEGRADED';
                setTraceStatus('online', `${status} · ${TRACE_ORIGIN}`);
            } else {
                setTraceStatus('offline', `HTTP ${res.status} · 服务异常`);
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                setTraceStatus('offline', '检测超时 · 服务未响应');
            } else {
                setTraceStatus('offline', '未检测到本地服务');
            }
        }
    }

    if (traceCheckBtn) {
        traceCheckBtn.addEventListener('click', checkTraceEngineStatus);
    }
    // 页面加载后静默检测一次（不阻断，失败也友好）
    if (traceBadge) {
        setTimeout(checkTraceEngineStatus, 800);
    }

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
    
    // --- 移动端：目录菜单打开/关闭逻辑 ---
    if (mobileTrigger && directory) {
        function syncDirectoryLabels() {
            const isMobile = window.innerWidth <= 1024;
            directoryLinks.forEach(link => {
                link.textContent = isMobile ? link.getAttribute('data-title') : '';
            });
        }

        mobileTrigger.addEventListener('click', () => {
            directory.classList.toggle('is-open');
            syncDirectoryLabels();
        });

        directoryLinks.forEach(link => {
            link.addEventListener('click', () => {
                directory.classList.remove('is-open');
            });
        });

        // 点击目录外部关闭
        document.addEventListener('click', (e) => {
            if (directory.classList.contains('is-open') &&
                !directory.contains(e.target) &&
                e.target !== mobileTrigger &&
                !mobileTrigger.contains(e.target)) {
                directory.classList.remove('is-open');
            }
        });

        // ESC 关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && directory.classList.contains('is-open')) {
                directory.classList.remove('is-open');
            }
        });

        window.addEventListener('resize', syncDirectoryLabels);
        syncDirectoryLabels();
    }
});