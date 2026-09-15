/**
 * DBRecruitAI - Global HR Loader Controller
 * Manages loading states across /hr/ for HTMX requests, page transitions,
 * and form submissions.
 */
(function () {
    'use strict';

    let activeRequests = 0;
    let safetyTimer = null;
    const SAFETY_TIMEOUT_MS = 8000;

    /**
     * Updates visual state on body and loader elements
     */
    function updateDOM() {
        const isLoading = activeRequests > 0;
        if (isLoading) {
            document.body.classList.add('hr-loading');
        } else {
            document.body.classList.remove('hr-loading');
        }

        const loaders = document.querySelectorAll(
            '#hr-loader, .sidebar-logo .loader, .login-logo-container .loader'
        );
        loaders.forEach(function (el) {
            if (isLoading) {
                el.classList.add('active', 'is-active');
            } else {
                el.classList.remove('active', 'is-active');
            }
        });
    }

    /**
     * Shows loader
     */
    function showLoader() {
        activeRequests++;
        updateDOM();

        clearTimeout(safetyTimer);
        safetyTimer = setTimeout(function () {
            resetLoader();
        }, SAFETY_TIMEOUT_MS);
    }

    /**
     * Hides loader
     */
    function hideLoader() {
        activeRequests = Math.max(0, activeRequests - 1);
        updateDOM();
        if (activeRequests === 0) {
            clearTimeout(safetyTimer);
            safetyTimer = null;
        }
    }

    /**
     * Force resets loader state (guaranteed disappearance)
     */
    function resetLoader() {
        activeRequests = 0;
        clearTimeout(safetyTimer);
        safetyTimer = null;
        updateDOM();
    }

    // --- 1. Page Load Lifecycle: Loader MUST disappear after page is loaded ---
    // Make sure loader is hidden as soon as DOM is ready or page finishes rendering
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        resetLoader();
    } else {
        document.addEventListener('DOMContentLoaded', resetLoader, { once: true });
        window.addEventListener('load', resetLoader, { once: true });
    }
    // Hard ceiling to guarantee loader never remains stuck on initial load
    setTimeout(resetLoader, 300);

    // Reset when restored from browser Back/Forward cache (bfcache)
    window.addEventListener('pageshow', function () {
        resetLoader();
    });

    // --- 2. HTMX Lifecycle Integration ---
    document.addEventListener('htmx:beforeRequest', function () {
        showLoader();
    });

    document.addEventListener('htmx:afterRequest', function () {
        hideLoader();
    });

    document.addEventListener('htmx:responseError', function () {
        resetLoader();
    });

    document.addEventListener('htmx:sendError', function () {
        resetLoader();
    });

    document.addEventListener('htmx:abort', function () {
        resetLoader();
    });

    document.addEventListener('htmx:timeout', function () {
        resetLoader();
    });

    // When HTMX content settles, if no pending requests, guarantee loader is hidden
    document.addEventListener('htmx:afterSettle', function () {
        const pending = document.querySelectorAll('.htmx-request');
        if (pending.length === 0) {
            resetLoader();
        }
    });

    document.addEventListener('htmx:historyRestore', function () {
        resetLoader();
    });

    // --- 3. Form Submissions ---
    document.addEventListener('submit', function (e) {
        if (!e.defaultPrevented) {
            showLoader();
        }
    });

    // --- 4. Standard Navigation Links (non-HTMX only) ---
    document.addEventListener('click', function (e) {
        const link = e.target.closest('a');
        if (!link || !link.href) return;

        // Ignore if handled by HTMX (sidebar boost or hx-attributes)
        if (link.closest('[hx-boost="true"]') ||
            link.hasAttribute('hx-get') ||
            link.hasAttribute('hx-post') ||
            link.hasAttribute('hx-delete') ||
            link.hasAttribute('hx-put') ||
            link.hasAttribute('hx-patch')) {
            return; // HTMX events will manage the loader
        }

        // Ignore new tabs, downloads, modified clicks, hash links, js urls
        if (link.target && link.target !== '_self') return;
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        if (link.hasAttribute('download')) return;

        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;

        showLoader();
    });

    // --- 5. Global API & Custom Events ---
    document.addEventListener('hr:loader:show', showLoader);
    document.addEventListener('hr:loader:hide', hideLoader);
    document.addEventListener('hr:loader:reset', resetLoader);

    window.HRLoader = {
        show: showLoader,
        hide: hideLoader,
        reset: resetLoader,
        isActive: function () {
            return activeRequests > 0;
        }
    };
})();
