/**
 * Global UX: Button Action Coordinator (Applicants and HR)
 * Prevents duplicate or conflicting submissions by disabling all other buttons
 * whenever an action, form submission, or HTMX request is triggered,
 * and re-enabling them when the action completes.
 */
(function () {
    "use strict";

    let safetyTimer = null;
    const SAFETY_TIMEOUT_MS = 8000; // Auto-restore if navigation or async hangs
    let disabledButtons = new Set();

    function isCloseOrDismissButton(el) {
        if (!el) return false;
        return (
            el.classList.contains("alertify-close") ||
            el.classList.contains("close") ||
            el.classList.contains("btn-close") ||
            el.hasAttribute("data-dismiss") ||
            el.hasAttribute("data-bs-dismiss") ||
            el.hasAttribute("data-no-disable")
        );
    }

    function getAllInteractiveButtons() {
        return Array.from(
            document.querySelectorAll(
                "button, input[type='submit'], input[type='button'], a.btn, a.track-btn, a.nav-btn-link"
            )
        ).filter(btn => !isCloseOrDismissButton(btn));
    }

    function disableOtherButtons(clickedButton) {
        clearSafetyTimer();
        const buttons = getAllInteractiveButtons();

        buttons.forEach(btn => {
            if (btn !== clickedButton && !isCloseOrDismissButton(btn)) {
                // If it was already disabled prior to this action, remember not to falsely touch it
                if (!btn.disabled && !btn.classList.contains("btn-action-disabled")) {
                    btn.classList.add("btn-action-disabled");
                    btn.setAttribute("aria-disabled", "true");
                    btn.dataset.actionDisabled = "true";
                    if ("disabled" in btn) {
                        btn.disabled = true;
                    }
                    disabledButtons.add(btn);
                }
            }
        });

        // Set safety fallback timer so buttons are never permanently stuck
        safetyTimer = setTimeout(function () {
            restoreButtons();
        }, SAFETY_TIMEOUT_MS);
    }

    function restoreButtons() {
        clearSafetyTimer();
        disabledButtons.forEach(btn => {
            if (document.body.contains(btn)) {
                btn.classList.remove("btn-action-disabled");
                btn.removeAttribute("aria-disabled");
                delete btn.dataset.actionDisabled;
                if ("disabled" in btn) {
                    btn.disabled = false;
                }
            }
        });
        disabledButtons.clear();

        // Also restore any orphaned elements with the class
        document.querySelectorAll(".btn-action-disabled").forEach(btn => {
            btn.classList.remove("btn-action-disabled");
            btn.removeAttribute("aria-disabled");
            delete btn.dataset.actionDisabled;
            if ("disabled" in btn) {
                btn.disabled = false;
            }
        });
    }

    function clearSafetyTimer() {
        if (safetyTimer) {
            clearTimeout(safetyTimer);
            safetyTimer = null;
        }
    }

    // 1. Listen for clicks on interactive buttons
    document.addEventListener("click", function (event) {
        const targetBtn = event.target.closest(
            "button, input[type='submit'], input[type='button'], a.btn, a.track-btn"
        );

        if (!targetBtn || isCloseOrDismissButton(targetBtn)) {
            return;
        }

        // If the button is already disabled or marked as disabled, ignore
        if (targetBtn.disabled || targetBtn.getAttribute("aria-disabled") === "true") {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }

        // If inside a form with submit type
        const form = targetBtn.closest("form");
        const isSubmit = targetBtn.type === "submit" || (form && targetBtn.tagName.toLowerCase() === "button" && !targetBtn.type);

        if (form && isSubmit) {
            // Check HTML5 validity before disabling anything
            if (typeof form.checkValidity === "function" && !form.checkValidity()) {
                // Form is invalid: browser will show tooltips; do not lock buttons
                return;
            }
        }

        // Disable all other buttons
        disableOtherButtons(targetBtn);
    }, true);

    // 2. Form submission handler
    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (typeof form.checkValidity === "function" && !form.checkValidity()) {
            restoreButtons();
            return;
        }

        const submitBtns = form.querySelectorAll("button[type='submit'], input[type='submit']");
        submitBtns.forEach(btn => {
            // Slight delay before disabling clicked submit button so form submit payload is sent
            setTimeout(() => {
                if ("disabled" in btn) {
                    btn.disabled = true;
                }
            }, 10);
        });

        // Set fallback timeout in case submit is intercepted or fails
        clearSafetyTimer();
        safetyTimer = setTimeout(restoreButtons, SAFETY_TIMEOUT_MS);
    });

    // 3. HTMX Lifecycle Integration
    document.addEventListener("htmx:beforeRequest", function (evt) {
        const triggeringEl = evt.detail.elt;
        disableOtherButtons(triggeringEl);
    });

    document.addEventListener("htmx:afterRequest", function () {
        restoreButtons();
    });

    document.addEventListener("htmx:responseError", function () {
        restoreButtons();
    });

    document.addEventListener("htmx:sendError", function () {
        restoreButtons();
    });

    document.addEventListener("htmx:timeout", function () {
        restoreButtons();
    });

    // 4. Browser Back/Forward Cache (bfcache) restoration
    window.addEventListener("pageshow", function (event) {
        // Always restore buttons when user navigates back to the page
        restoreButtons();
    });

    // Export globally for manual reset if ever needed by specialized modals
    window.globalUX = {
        disableOtherButtons: disableOtherButtons,
        restoreButtons: restoreButtons,
    };
})();
