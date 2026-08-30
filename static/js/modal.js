document.addEventListener("DOMContentLoaded", function () {
    const modal = document.getElementById('post-job-modal');
    const openBtn = document.getElementById('open-post-modal');
    const closeBtn = document.getElementById('close-post-modal');
    const cancelBtn = document.getElementById('cancel-modal');

    if (openBtn && modal) {
        openBtn.addEventListener('click', () => {
            modal.classList.add('active');
        });
    }

    function closeModal() {
        if (modal) modal.classList.remove('active');
    }

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

    // Close on backdrop click
    if (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === modal) {
                closeModal();
            }
        });
    }
});

document.addEventListener("DOMContentLoaded", () => {
    const container = document.getElementById("requirements-container");
    const addBtn = document.getElementById("add-requirement");

    if (!container || !addBtn) return;

    addBtn.addEventListener("click", () => {
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
    });

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

const form = document.getElementById("manage-job-form");
const statusSelect = document.getElementById("status");

form.addEventListener("submit", function(event) {

    if (statusSelect.value === "Inactive") {

        const confirmed = confirm(
            "Are you sure you want to close this job?\n\n" +
            "This job will no longer appear in the Active Jobs section " +
            "and applicants will no longer be able to apply."
        );

        if (!confirmed) {
            event.preventDefault();
        }
    }

});


// interview status

document.addEventListener("DOMContentLoaded", function () {

    const statusSelect = document.querySelector(".status-select");
    const rescheduleFields =
        document.getElementById("reschedule-fields");

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

    statusSelect.addEventListener(
        "change",
        toggleRescheduleFields
    );

    toggleRescheduleFields();


});