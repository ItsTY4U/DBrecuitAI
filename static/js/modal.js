// Modal handling with event delegation (supports standard loads and HTMX swaps)
document.addEventListener("click", function (e) {
    // Open post job modal (from header or per-department section button)
    const openPostBtn = e.target.closest('#open-post-modal, .open-post-modal-btn, .btn-open-post-modal');
    if (openPostBtn) {
        const modal = document.getElementById('post-job-modal');
        if (modal) {
            const deptAttr = openPostBtn.getAttribute('data-department');
            const deptInput = document.getElementById('new-job-cat');
            if (deptInput) {
                deptInput.value = deptAttr ? deptAttr : '';
            }
            modal.classList.add('active');
        }
        return;
    }

    // Close post job modal
    const closePostBtn = e.target.closest('#close-post-modal, #cancel-modal, .close-post-modal-btn');
    if (closePostBtn) {
        const modal = document.getElementById('post-job-modal');
        if (modal) modal.classList.remove('active');
        return;
    }

    // Open new department modal
    const openDeptBtn = e.target.closest('#open-new-department-modal, .open-new-department-modal-btn');
    if (openDeptBtn) {
        const modal = document.getElementById('new-department-modal');
        if (modal) {
            modal.classList.add('active');
            const input = modal.querySelector('#new-dept-name');
            if (input) setTimeout(() => input.focus(), 100);
        }
        return;
    }

    // Close new department modal
    const closeDeptBtn = e.target.closest('#close-dept-modal, #cancel-dept-modal, .close-dept-modal-btn');
    if (closeDeptBtn) {
        const modal = document.getElementById('new-department-modal');
        if (modal) modal.classList.remove('active');
        return;
    }

    // Close edit job modal
    const closeEditBtn = e.target.closest('#close-edit-modal, #cancel-edit-modal, .close-edit-modal-btn');
    if (closeEditBtn) {
        const editContainer = document.getElementById('edit-job-modal-container');
        if (editContainer) editContainer.innerHTML = '';
        const modal = document.getElementById('edit-job-modal');
        if (modal) modal.classList.remove('active');
        return;
    }

    // Backdrop clicks
    const postModal = document.getElementById('post-job-modal');
    if (postModal && e.target === postModal) {
        postModal.classList.remove('active');
    }

    const deptModal = document.getElementById('new-department-modal');
    if (deptModal && e.target === deptModal) {
        deptModal.classList.remove('active');
    }

    const editModal = document.getElementById('edit-job-modal');
    if (editModal && e.target === editModal) {
        const editContainer = document.getElementById('edit-job-modal-container');
        if (editContainer) editContainer.innerHTML = '';
    }

    // ==========================================
    // KEY QUALIFICATIONS ADD (Event Delegation)
    // ==========================================
    const addQualBtn = e.target.closest('#edit-add-key-qualification, #add-key-qualification, .btn-add-req-chip');
    if (addQualBtn) {
        const form = addQualBtn.closest('form');
        const container = form
            ? form.querySelector('.requirements-container, #key-qualifications-container')
            : document.getElementById('key-qualifications-container');

        if (container) {
            const row = document.createElement('div');
            row.className = 'requirement-row';
            row.style.marginTop = '8px';
            row.innerHTML = `
                <input
                    type="text"
                    name="key_qualifications"
                    class="form-input"
                    placeholder="Enter a key qualification..."
                    required
                >
                <button
                    type="button"
                    class="remove-requirement"
                    title="Remove qualification"
                >
                    <i class="fas fa-trash-can"></i>
                </button>
            `;
            container.appendChild(row);
        }
        return;
    }

    // ==========================================
    // KEY QUALIFICATIONS REMOVE (Event Delegation)
    // ==========================================
    const removeQualBtn = e.target.closest('.remove-requirement, .remove-key-qualification');
    if (removeQualBtn) {
        const row = removeQualBtn.closest('.requirement-row, .key-qualification-row');
        if (row) {
            row.remove();
        }
        return;
    }
});

// Escape key closes modals
document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
        const postModal = document.getElementById('post-job-modal');
        if (postModal && postModal.classList.contains('active')) {
            postModal.classList.remove('active');
        }

        const deptModal = document.getElementById('new-department-modal');
        if (deptModal && deptModal.classList.contains('active')) {
            deptModal.classList.remove('active');
        }

        const editContainer = document.getElementById('edit-job-modal-container');
        if (editContainer && editContainer.innerHTML.trim() !== '') {
            editContainer.innerHTML = '';
        }
    }
});

// Listen for HTMX custom events to auto-close modals
document.addEventListener("closeDeptModal", function () {
    const modal = document.getElementById('new-department-modal');
    if (modal) {
        modal.classList.remove('active');
        const form = modal.querySelector('form');
        if (form) form.reset();
    }
});

document.addEventListener("closeEditModal", function () {
    const editContainer = document.getElementById('edit-job-modal-container');
    if (editContainer) {
        editContainer.innerHTML = '';
    }
});

// Job Status Toggle Switch handler
document.addEventListener("change", function (e) {
    const toggle = e.target.closest("#edit-status-toggle, .status-toggle-input");
    if (toggle) {
        const form = toggle.closest("form");
        const hiddenInput = form ? form.querySelector("input[name='status']") : document.getElementById("edit-status");
        const card = toggle.closest(".status-toggle-card");
        const badge = card ? card.querySelector("#status-display-badge, .status-toggle-label") : null;
        const desc = card ? card.querySelector("#status-display-desc, .status-toggle-desc") : null;

        if (toggle.checked) {
            if (hiddenInput) hiddenInput.value = "Active";
            if (badge) {
                badge.textContent = "Active";
                badge.className = "status-toggle-label status-active";
            }
            if (desc) desc.textContent = "Publicly visible & open for applications";
        } else {
            if (hiddenInput) hiddenInput.value = "Inactive";
            if (badge) {
                badge.textContent = "Inactive";
                badge.className = "status-toggle-label status-inactive";
            }
            if (desc) desc.textContent = "Archived & closed to applications";
        }
    }
});

// Manage job status confirmation
document.addEventListener("submit", function (event) {
    if (event.target && event.target.id === "manage-job-form") {
        const statusSelect = event.target.querySelector("#status, #edit-status, input[name='status']");
        const initialStatus = statusSelect ? statusSelect.getAttribute("data-initial-status") : "";
        if (statusSelect && statusSelect.value === "Inactive" && initialStatus === "Active") {
            const confirmed = confirm(
                "Are you sure you want to close this job?\n\n" +
                "This job will no longer appear in the Active Jobs section " +
                "and applicants will no longer be able to apply."
            );
            if (!confirmed) {
                event.preventDefault();
            }
        }
    }
});

// Interview reschedule fields toggle
function initInterviewStatus() {
    const statusSelect = document.querySelector(".status-select");
    const rescheduleFields = document.getElementById("reschedule-fields");

    if (!statusSelect || !rescheduleFields) {
        return;
    }

    function toggleRescheduleFields() {
        if (statusSelect.value === "Rescheduled") {
            rescheduleFields.style.display = "grid";
        } else {
            rescheduleFields.style.display = "none";
        }
    }

    statusSelect.removeEventListener("change", toggleRescheduleFields);
    statusSelect.addEventListener("change", toggleRescheduleFields);
    toggleRescheduleFields();
}

document.addEventListener("DOMContentLoaded", initInterviewStatus);
document.addEventListener("htmx:afterSwap", initInterviewStatus);