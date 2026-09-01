document.addEventListener("DOMContentLoaded", function () {

    const modal = document.getElementById('post-job-modal');
    const openBtn = document.getElementById('open-post-modal');
    const closeBtn = document.getElementById('close-post-modal');
    const cancelBtn = document.getElementById('cancel-modal');

    openBtn.addEventListener('click', () => {
        modal.classList.add('active');
    });

    function closeModal() {
        modal.classList.remove('active');
    }

    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);

});

document.addEventListener("DOMContentLoaded", () => {

    const container = document.getElementById("key-qualifications-container");
    const addBtn = document.getElementById("add-key-qualification");

    if (!container || !addBtn) return;

    addBtn.addEventListener("click", () => {

        const row = document.createElement("div");

        row.className = "requirement-row";
        row.style.marginTop = "10px";

        row.innerHTML = `
            <input
                type="text"
                name="key_qualifications"
                placeholder="Enter a key qualification"
                required>

            <button
                type="button"
                class="remove-requirement">
                ×
            </button>
        `;

        container.appendChild(row);
    });


    container.addEventListener("click", function(e) {

        if (e.target.classList.contains("remove-requirement")) {

            e.target.parentElement.remove();

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
                ×
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