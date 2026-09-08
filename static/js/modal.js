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

document.addEventListener("DOMContentLoaded", () => {

    const container = document.getElementById("key-qualifications-container");
    const addBtn = document.getElementById("edit-add-key-qualification");

    if (!container || !addBtn) return;


    // ==============================
    // ADD QUALIFICATION
    // ==============================

    addBtn.addEventListener("click", () => {

        const row = document.createElement("div");

        row.className = "requirement-row";
        row.style.marginTop = "8px";
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
        return;
    })


    // ==============================
    // REMOVE QUALIFICATION
    // ==============================

    container.addEventListener("click", function (e) {
        const removeBtn = e.target.closest(".remove-requirement");
        if (removeBtn) {
            const row = removeBtn.closest(".requirement-row");
            if (row) {
                row.remove();
            }
        }
    });
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



document.addEventListener("DOMContentLoaded", () => {

    const container = document.getElementById("key-qualifications-container");
    const addBtn = document.getElementById("add-key-qualification");

    if (!container || !addBtn) return;


    // Add qualification
    addBtn.addEventListener("click", () => {

        const row = document.createElement("div");

        row.className = "key-qualification-row";

        row.style.display = "flex";
        row.style.gap = "10px";
        row.style.marginBottom = "10px";

        row.innerHTML = `
            <input
                type="text"
                name="key_qualifications"
                placeholder="Enter a key qualification..."
                style="width: 100%; padding: 15px; border-radius: 8px; border: 1px solid #ddd; font-family: 'Montserrat', sans-serif;"
            >

            <button
                type="button"
                class="remove-key-qualification"
                style="padding: 0 15px; border: none; border-radius: 8px; cursor: pointer;"
            >
                <i class="fas fa-trash-can"></i>
            </button>
        `;

        container.appendChild(row);
    });


    // Remove qualification
    container.addEventListener("click", (event) => {

        if (event.target.classList.contains("remove-key-qualification")) {

            const rows = container.querySelectorAll(".key-qualification-row");

            // Keep at least one field
            if (rows.length > 1) {
                event.target.closest(".key-qualification-row").remove();
            }

        }

    });

});