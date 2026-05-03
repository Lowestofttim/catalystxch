// Sidebar + TOC scroll-spy for docs.html.
(function () {
    const sectionIds = [
        'overview', 'getting-started', 'dashboard', 'offers', 'spreads',
        'inventory', 'coins', 'intel', 'sniper', 'gap-closer',
        'wallet', 'config', 'troubleshooting'
    ];
    const sidebar = document.querySelector('.sidebar');
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const sidebarLinks = document.querySelectorAll('.sidebar-list a');
    const tocLinks = document.querySelectorAll('.toc-list a');

    if (mobileMenuBtn && sidebar) {
        mobileMenuBtn.addEventListener('click', () => {
            sidebar.classList.toggle('is-open');
        });
    }

    function setActive(id) {
        sidebarLinks.forEach((a) => {
            a.classList.toggle('is-active', a.getAttribute('href') === '#' + id);
        });
        tocLinks.forEach((a) => {
            a.classList.toggle('is-active', a.getAttribute('href') === '#' + id);
        });
    }

    const observer = new IntersectionObserver((entries) => {
        const visible = entries
            .filter((e) => e.isIntersecting)
            .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length) {
            setActive(visible[0].target.id);
        }
    }, {
        rootMargin: '-88px 0px -65% 0px',
        threshold: 0
    });

    sectionIds.forEach((id) => {
        const el = document.getElementById(id);
        if (el) observer.observe(el);
    });

    document.querySelectorAll('.sidebar-list a').forEach((a) => {
        a.addEventListener('click', () => {
            if (sidebar) sidebar.classList.remove('is-open');
        });
    });
})();
