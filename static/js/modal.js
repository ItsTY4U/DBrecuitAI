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
            updateCriteriaModal(modal);
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
            if (input) input.focus();
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
    const addQualBtn = e.target.closest('#edit-add-key-qualification, #add-key-qualification');
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
    showAlertify("New department created successfully!", "success");
});

document.addEventListener("closePostModal", function () {
    const modal = document.getElementById('post-job-modal');
    if (modal) {
        modal.classList.remove('active');
        const form = modal.querySelector('form');
        if (form) {
            form.reset();
            const container = form.querySelector('#key-qualifications-container');
            if (container) {
                container.innerHTML = `
                    <div class="requirement-row">
                        <input type="text" name="key_qualifications" class="form-input" placeholder="Enter a key qualification" required>
                        <button type="button" class="remove-requirement" title="Remove qualification">
                            <i class="fas fa-trash-can"></i>
                        </button>
                    </div>
                `;
            }
        }
    }
    showAlertify("New job created successfully!", "success");
});

document.addEventListener("closeEditModal", function () {
    const editContainer = document.getElementById('edit-job-modal-container');
    if (editContainer) {
        editContainer.innerHTML = '';
    }
    showAlertify("Changes saved successfully!", "success");
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

// Alertify Notification (placed on top of Logout section)
function showAlertify(message, type = 'success') {
    const container = document.getElementById('sidebar-alert-container');
    if (container) {
        container.innerHTML = '';

        const alertEl = document.createElement('div');
        alertEl.className = `sidebar-alert alertify-banner alertify-${type}`;

        let iconClass = 'fa-circle-check';
        if (type === 'error') iconClass = 'fa-circle-xmark';
        else if (type === 'warning') iconClass = 'fa-triangle-exclamation';

        alertEl.innerHTML = `
            <div class="alertify-content">
                <i class="fas ${iconClass}"></i>
                <span>${message}</span>
            </div>
            <button type="button" class="alertify-close" aria-label="Close">&times;</button>
        `;

        const closeBtn = alertEl.querySelector('.alertify-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function () {
                alertEl.remove();
            });
        }

        container.appendChild(alertEl);

        setTimeout(function () {
            alertEl.classList.add('fade-out');
            setTimeout(function () {
                alertEl.remove();
            }, 400);
        }, 4500);
    }
}
window.showAlertify = showAlertify;

function initSidebarAlerts() {
    const alerts = document.querySelectorAll('#sidebar-alert-container .sidebar-alert');
    alerts.forEach(function (alertEl) {
        const closeBtn = alertEl.querySelector('.alertify-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function () {
                alertEl.remove();
            });
        }
        setTimeout(function () {
            alertEl.classList.add('fade-out');
            setTimeout(function () {
                alertEl.remove();
            }, 400);
        }, 4500);
    });
}

document.addEventListener("DOMContentLoaded", initSidebarAlerts);
document.addEventListener("htmx:afterSwap", initSidebarAlerts);

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

function toggleInterviewComment(button) {

    const card = button.closest(".interview-applicant-card");

    if (!card) {
        return;
    }

    const commentBox = card.querySelector(".interview-comment-box");
    const toggleText = button.querySelector(".comment-toggle-text");

    if (!commentBox) {
        return;
    }

    const isVisible = commentBox.classList.toggle("is-visible");

    if (toggleText) {
        toggleText.textContent = isVisible
            ? "Hide Comment"
            : "Add Comment";
    }

    if (isVisible) {
        const textarea = commentBox.querySelector(
            ".interview-comment-input"
        );

        if (textarea) {
            textarea.focus();
        }
    }
}


function cancelInterviewComment(button) {

    const card = button.closest(".interview-applicant-card");

    if (!card) {
        return;
    }

    const commentBox = card.querySelector(".interview-comment-box");
    const toggleButton = card.querySelector(
        ".interview-comment-toggle"
    );
    const toggleText = toggleButton
        ? toggleButton.querySelector(".comment-toggle-text")
        : null;

    const textarea = card.querySelector(
        ".interview-comment-input"
    );

    if (textarea) {
        textarea.value = "";
    }

    if (commentBox) {
        commentBox.classList.remove("is-visible");
    }

    if (toggleText) {
        toggleText.textContent = "Add Comment";
    }
}


function handleStatusChange(value) {
    const rescheduleContainer = document.getElementById('reschedule-container');
    const reasonContainer = document.querySelector('.interview-status-reason-group');

    // Reschedule date and time
    if (rescheduleContainer) {
        if (value === 'Rescheduled') {
            rescheduleContainer.style.display = 'block';
        } else {
            rescheduleContainer.style.display = 'none';
        }
    }

    // Reschedule / cancellation reason
    if (reasonContainer) {
        if (value === 'Rescheduled' || value === 'Cancelled') {
            reasonContainer.classList.add('is-visible');
        } else {
            reasonContainer.classList.remove('is-visible');
        }
    }
}

// Run when the page loads
document.addEventListener('DOMContentLoaded', function () {
    const statusSelect = document.getElementById('interview-status-select');

    if (statusSelect) {
        handleStatusChange(statusSelect.value);
    }
});


document.addEventListener('DOMContentLoaded', function () {

    const selectAllCheckbox =
        document.getElementById('select-all');

    const applicantCheckboxes =
        document.querySelectorAll('.applicant-check');


    /*
     * Select All
     */

    if (selectAllCheckbox) {

        selectAllCheckbox.addEventListener(
            'change',
            function () {

                applicantCheckboxes.forEach(function (checkbox) {

                    checkbox.checked =
                        selectAllCheckbox.checked;

                    updateApplicantTimeField(checkbox);

                });

            }
        );

    }


    /*
     * Individual Applicant Selection
     */

    applicantCheckboxes.forEach(function (checkbox) {

        checkbox.addEventListener(
            'change',
            function () {

                updateApplicantTimeField(this);
                updateSelectAllState();

            }
        );

    });


    /*
     * Update the time field
     */

    function updateApplicantTimeField(checkbox) {

        const applicantId =
            checkbox.value;

        const timeContainer =
            document.getElementById(
                'time-container-' + applicantId
            );

        const timeInput =
            document.getElementById(
                'time-' + applicantId
            );

        const card =
            checkbox.closest(
                '.candidate-schedule-card'
            );


        if (
            !timeContainer ||
            !timeInput
        ) {
            return;
        }


        if (checkbox.checked) {

            timeContainer.classList.add(
                'is-visible'
            );

            timeInput.disabled = false;

            timeInput.required = true;

            if (card) {
                card.classList.add(
                    'is-selected'
                );
            }

        } else {

            timeContainer.classList.remove(
                'is-visible'
            );

            timeInput.disabled = true;

            timeInput.required = false;

            timeInput.value = '';

            if (card) {
                card.classList.remove(
                    'is-selected'
                );
            }

        }

    }


    /*
     * Keep Select All checkbox updated
     */

    function updateSelectAllState() {

        if (!selectAllCheckbox) {
            return;
        }

        const total =
            applicantCheckboxes.length;

        const checked =
            document.querySelectorAll(
                '.applicant-check:checked'
            ).length;


        selectAllCheckbox.checked =
            total > 0 &&
            checked === total;

        selectAllCheckbox.indeterminate =
            checked > 0 &&
            checked < total;

    }


    /*
     * Initial state
     */

    applicantCheckboxes.forEach(function (checkbox) {

        updateApplicantTimeField(
            checkbox
        );

    });

});


// ==========================================
// CRITERIA WEIGHT CALCULATION
// ==========================================

function updateCriteriaTotal(
    container,
    totalDisplay,
    validation,
    submitButton
) {
    if (
        !container ||
        !totalDisplay ||
        !validation ||
        !submitButton
    ) {
        return;
    }

    const inputs = container.querySelectorAll(
        ".criteria-weight-input"
    );

    let total = 0;

    inputs.forEach(function (input) {

        let value = parseFloat(input.value);

        if (!isNaN(value)) {
            total += value;
        }

    });

    total = Math.round(total * 100) / 100;

    totalDisplay.textContent = `${total}%`;

    if (total === 100) {

        totalDisplay.classList.remove("is-invalid");
        totalDisplay.classList.add("is-valid");

        validation.classList.remove("is-invalid");
        validation.classList.add("is-valid");

        validation.innerHTML = `
            <i class="fas fa-circle-check"></i>
            <span>
                Criteria weights are valid.
            </span>
        `;

    } else {

        totalDisplay.classList.remove("is-valid");
        totalDisplay.classList.add("is-invalid");

        validation.classList.remove("is-valid");
        validation.classList.add("is-invalid");

        validation.innerHTML = `
            <i class="fas fa-circle-info"></i>
            <span>
                Criteria weights must total 100%.
            </span>
        `;
    }
}


// ==========================================
// CRITERIA WEIGHT CALCULATOR
// ==========================================

function updateCriteriaModal(modal) {

    if (!modal) {
        return;
    }

    const container = modal.querySelector(
        ".criteria-container"
    );

    const totalElement = modal.querySelector(
        ".criteria-total"
    );

    const validationElement = modal.querySelector(
        ".criteria-validation"
    );

    const submitButton = modal.querySelector(
        ".btn-modal-submit"
    );

    if (
        !container ||
        !totalElement ||
        !validationElement ||
        !submitButton
    ) {
        return;
    }

    const inputs = container.querySelectorAll(
        ".criteria-weight-input"
    );

    let total = 0;

    inputs.forEach(function (input) {

        const value = parseFloat(input.value);

        if (!isNaN(value)) {
            total += value;
        }

    });

    total = Math.round(total * 100) / 100;

    totalElement.textContent = total + "%";


    if (total === 100) {

        totalElement.classList.remove("is-invalid");
        totalElement.classList.add("is-valid");

        validationElement.classList.remove("is-invalid");
        validationElement.classList.add("is-valid");

        validationElement.innerHTML = `
            <i class="fas fa-circle-check"></i>
            <span>
                Criteria weights are valid.
            </span>
        `;

    } else {

        totalElement.classList.remove("is-valid");
        totalElement.classList.add("is-invalid");

        validationElement.classList.remove("is-valid");
        validationElement.classList.add("is-invalid");

        validationElement.innerHTML = `
            <i class="fas fa-circle-info"></i>
            <span>
                Criteria weights must total 100%.
            </span>
        `;
    }
}


// ==========================================
// HANDLE CRITERIA INPUT
// ==========================================

document.addEventListener("input", function (event) {

    if (
        !event.target.classList.contains(
            "criteria-weight-input"
        )
    ) {
        return;
    }

    const modal = event.target.closest(
        "#post-job-modal, #edit-job-modal"
    );

    if (!modal) {
        return;
    }

    let value = event.target.value;

    if (value !== "") {

        value = parseFloat(value);

        if (isNaN(value)) {

            event.target.value = "";

        } else if (value < 0) {

            event.target.value = 0;

        } else if (value > 100) {

            event.target.value = 100;

        }
    }

    updateCriteriaModal(modal);

});


// ==========================================
// HANDLE CHANGE EVENT
// ==========================================

document.addEventListener("change", function (event) {

    if (
        !event.target.classList.contains(
            "criteria-weight-input"
        )
    ) {
        return;
    }

    const modal = event.target.closest(
        "#post-job-modal, #edit-job-modal"
    );

    if (!modal) {
        return;
    }

    updateCriteriaModal(modal);

});


// ==========================================
// INITIALIZE EXISTING MODALS
// ==========================================

function initializeCriteriaModals() {

    const postModal = document.getElementById(
        "post-job-modal"
    );

    const editModal = document.getElementById(
        "edit-job-modal"
    );

    if (postModal) {
        updateCriteriaModal(postModal);
    }

    if (editModal) {
        updateCriteriaModal(editModal);
    }
}


// ==========================================
// INITIAL PAGE LOAD
// ==========================================

document.addEventListener(
    "DOMContentLoaded",
    function () {

        initializeCriteriaModals();

    }
);


// ==========================================
// HTMX MODAL LOAD
// ==========================================

document.body.addEventListener(
    "htmx:afterSwap",
    function () {

        initializeCriteriaModals();

    }
);


document.body.addEventListener(
    "htmx:afterSettle",
    function () {

        initializeCriteriaModals();

    }
);