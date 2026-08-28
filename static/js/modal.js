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

    const container = document.getElementById("requirements-container");
    const addBtn = document.getElementById("add-requirement");

    if (!container || !addBtn) return;

    addBtn.addEventListener("click", () => {

        const row = document.createElement("div");
        row.className = "requirement-row";
        row.style.marginTop = "10px";

        row.innerHTML = `
            <input
                type="text"
                name="requirements"
                placeholder="Enter a requirement"
                required>

            <button
                type="button"
                class="remove-requirement">
                ×
            </button>
        `;

        container.appendChild(row);
    });

    container.addEventListener("click", function(e){

        if(e.target.classList.contains("remove-requirement")){

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