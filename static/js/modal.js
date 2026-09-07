// Modal handling with event delegation (supports standard loads and HTMX swaps)
document.addEventListener("click", function (e) {
    // Open post job modal
    const openBtn = e.target.closest('#open-post-modal, .open-post-modal-btn, .btn-open-post-modal');
    if (openBtn) {
        const modal = document.getElementById('post-job-modal');
        if (modal) modal.classList.add('active');
        return;
    }

    // Close post job modal
    const closeBtn = e.target.closest('#close-post-modal') || e.target.closest('#cancel-modal') || e.target.closest('.close-post-modal-btn');
    if (closeBtn) {
        const modal = document.getElementById('post-job-modal');
        if (modal) modal.classList.remove('active');
        return;
    }

    // Backdrop click
    const modal = document.getElementById('post-job-modal');
    if (modal && e.target === modal) {
        modal.classList.remove('active');
    }
});

// Escape key closes modal
document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
        const modal = document.getElementById('post-job-modal');
        if (modal && modal.classList.contains('active')) {
            modal.classList.remove('active');
        }
    }
});

// Dynamic job requirements with event delegation
document.addEventListener("click", function (e) {
    const addBtn = e.target.closest("#add-requirement");
    if (addBtn) {
        const container = document.getElementById("requirements-container");
        if (!container) return;

        const row = document.createElement("div");
        row.className = "requirement-row";
        row.style.marginTop = "8px";
        row.innerHTML = `
            <input
                type="text"
                name="requirements"
                class="form-input"
                placeholder="Enter a requirement"
                required>
            <button
                type="button"
                class="remove-requirement"
                title="Remove requirement">
                <i class="fas fa-trash-can"></i>
            </button>
        `;
        container.appendChild(row);
        return;
    }

    const removeBtn = e.target.closest(".remove-requirement");
    if (removeBtn) {
        const row = removeBtn.closest(".requirement-row");
        if (row) row.remove();
    }
});

// Manage job status confirmation
document.addEventListener("submit", function (event) {
    if (event.target && event.target.id === "manage-job-form") {
        const statusSelect = document.getElementById("status");
        if (statusSelect && statusSelect.value === "Inactive") {
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