document.addEventListener("DOMContentLoaded", function () {

    const editButton = document.getElementById("edit-profile-btn");
    const cancelButton = document.getElementById("cancel-profile-btn");
    const profileEdit = document.getElementById("profile-edit");

    console.log("profile.js loaded");
    console.log("Edit button:", editButton);
    console.log("Profile edit:", profileEdit);

    if (editButton && profileEdit) {
        if (window.getComputedStyle(profileEdit).display !== "none") {
            editButton.textContent = "Cancel";
        }

        editButton.addEventListener("click", function () {

            console.log("Edit button clicked");

            const isHidden =
                window.getComputedStyle(profileEdit).display === "none";

            if (isHidden) {

                profileEdit.style.display = "block";
                editButton.textContent = "Cancel";

                profileEdit.scrollIntoView({
                    behavior: "smooth",
                    block: "start"
                });

            } else {

                profileEdit.style.display = "none";
                editButton.textContent = "Edit profile";

            }

        });

    }

    if (cancelButton && profileEdit) {

        cancelButton.addEventListener("click", function () {

            profileEdit.style.display = "none";

            if (editButton) {
                editButton.textContent = "Edit profile";
            }

        });

    }

    // Auto-dismiss profile messages after 5 seconds
    dismissProfileMessages();

    // =========================================
    // CHANGE RESUME MODAL & PROCESSING
    // =========================================
    const openResumeModalBtns = document.querySelectorAll("#open-change-resume-btn");
    const resumeModal = document.getElementById("change-resume-modal");
    const closeResumeModalBtn = document.getElementById("close-resume-modal-btn");
    const cancelResumeModalBtn = document.getElementById("cancel-resume-modal-btn");
    const modalFileInput = document.getElementById("modal-resume-file");
    const modalDropzone = document.getElementById("resume-modal-dropzone");
    const dropzoneIdle = document.getElementById("dropzone-idle");
    const dropzoneSelected = document.getElementById("dropzone-selected");
    const selectedFileName = document.getElementById("selected-file-name");
    const selectedFileSize = document.getElementById("selected-file-size");
    const clearSelectedBtn = document.getElementById("clear-selected-resume-btn");
    const submitResumeModalBtn = document.getElementById("submit-resume-modal-btn");
    const modalError = document.getElementById("modal-resume-error");
    const changeResumeForm = document.getElementById("change-resume-form");

    function openResumeModal() {
        if (resumeModal) {
            resumeModal.style.display = "flex";
            resetResumeModal();
        }
    }

    function closeResumeModal() {
        if (resumeModal) {
            resumeModal.style.display = "none";
            resetResumeModal();
        }
    }

    function resetResumeModal() {
        if (modalFileInput) modalFileInput.value = "";
        if (dropzoneIdle) dropzoneIdle.style.display = "block";
        if (dropzoneSelected) dropzoneSelected.style.display = "none";
        if (submitResumeModalBtn) {
            submitResumeModalBtn.disabled = true;
            submitResumeModalBtn.innerHTML = '<i class="fa-solid fa-arrow-up-from-bracket"></i> Save & Process Resume';
        }
        if (modalError) {
            modalError.textContent = "";
            modalError.style.display = "none";
        }
        if (modalDropzone) modalDropzone.classList.remove("drag-over");
    }

    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
        return (bytes / 1048576).toFixed(1) + " MB";
    }

    function handleFileSelection(file) {
        if (!file) return;

        // Validation
        if (!file.name.toLowerCase().endsWith(".pdf")) {
            if (modalError) {
                modalError.textContent = "Only PDF files are allowed.";
                modalError.style.display = "block";
            }
            if (modalFileInput) modalFileInput.value = "";
            if (submitResumeModalBtn) submitResumeModalBtn.disabled = true;
            return;
        }

        const maxSize = 5 * 1024 * 1024; // 5MB
        if (file.size > maxSize) {
            if (modalError) {
                modalError.textContent = "Resume file must not exceed 5MB.";
                modalError.style.display = "block";
            }
            if (modalFileInput) modalFileInput.value = "";
            if (submitResumeModalBtn) submitResumeModalBtn.disabled = true;
            return;
        }

        if (modalError) {
            modalError.textContent = "";
            modalError.style.display = "none";
        }

        if (selectedFileName) selectedFileName.textContent = file.name;
        if (selectedFileSize) selectedFileSize.textContent = formatFileSize(file.size);
        if (dropzoneIdle) dropzoneIdle.style.display = "none";
        if (dropzoneSelected) dropzoneSelected.style.display = "block";
        if (submitResumeModalBtn) submitResumeModalBtn.disabled = false;
    }

    openResumeModalBtns.forEach(btn => {
        btn.addEventListener("click", openResumeModal);
    });

    if (closeResumeModalBtn) closeResumeModalBtn.addEventListener("click", closeResumeModal);
    if (cancelResumeModalBtn) cancelResumeModalBtn.addEventListener("click", closeResumeModal);

    if (resumeModal) {
        resumeModal.addEventListener("click", function (e) {
            if (e.target === resumeModal) {
                closeResumeModal();
            }
        });
    }

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && resumeModal && resumeModal.style.display === "flex") {
            closeResumeModal();
        }
    });

    if (modalFileInput) {
        modalFileInput.addEventListener("change", function () {
            if (this.files && this.files.length > 0) {
                handleFileSelection(this.files[0]);
            }
        });
    }

    if (clearSelectedBtn) {
        clearSelectedBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            resetResumeModal();
        });
    }

    if (modalDropzone) {
        ["dragenter", "dragover"].forEach(eventName => {
            modalDropzone.addEventListener(eventName, function (e) {
                e.preventDefault();
                e.stopPropagation();
                modalDropzone.classList.add("drag-over");
            }, false);
        });

        ["dragleave", "drop"].forEach(eventName => {
            modalDropzone.addEventListener(eventName, function (e) {
                e.preventDefault();
                e.stopPropagation();
                modalDropzone.classList.remove("drag-over");
            }, false);
        });

        modalDropzone.addEventListener("drop", function (e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files && files.length > 0) {
                if (modalFileInput) {
                    modalFileInput.files = files;
                }
                handleFileSelection(files[0]);
            }
        }, false);
    }

    if (changeResumeForm) {
        changeResumeForm.addEventListener("submit", function () {
            if (resumeModal) {
                resumeModal.style.display = "none";
            }
            if (overlay) {
                overlay.style.display = "flex";
            }
            if (submitResumeModalBtn) {
                submitResumeModalBtn.disabled = true;
                submitResumeModalBtn.textContent = "Processing...";
            }
            if (processingTitle && processingMessage) {
                processingTitle.textContent = "Saving your new resume...";
                processingMessage.textContent = "Please wait while we update your profile.";

                setTimeout(function () {
                    processingTitle.textContent = "Analyzing your resume...";
                    processingMessage.textContent = "Extracting your skills, experience, and qualifications.";
                }, 800);

                setTimeout(function () {
                    processingTitle.textContent = "Updating job recommendations...";
                    processingMessage.textContent = "We're finding jobs that match your profile.";
                }, 2500);
            }
        });
    }

    // Profile form submission and resume processing overlay
    const profileForm = document.getElementById("profile-form");
    const resumeInput = document.getElementById("id_default_resume");
    const overlay = document.getElementById("resume-processing-overlay");
    const processingTitle = document.getElementById("processing-title");
    const processingMessage = document.getElementById("processing-message");
    const saveButton = document.getElementById("save-profile-btn");

    if (profileForm) {
        profileForm.addEventListener("submit", function () {
            const resumeChanged =
                resumeInput &&
                resumeInput.files &&
                resumeInput.files.length > 0;

            if (!resumeChanged) {
                if (saveButton) {
                    saveButton.disabled = true;
                    saveButton.textContent = "Saving...";
                }
                return;
            }

            if (overlay) {
                overlay.style.display = "flex";
            }

            if (saveButton) {
                saveButton.disabled = true;
                saveButton.textContent = "Processing...";
            }

            if (processingTitle && processingMessage) {
                processingTitle.textContent = "Saving your new resume...";
                processingMessage.textContent = "Please wait while we update your profile.";

                setTimeout(function () {
                    processingTitle.textContent = "Analyzing your resume...";
                    processingMessage.textContent = "Extracting your skills, experience, and qualifications.";
                }, 800);

                setTimeout(function () {
                    processingTitle.textContent = "Updating job recommendations...";
                    processingMessage.textContent = "We're finding jobs that match your profile.";
                }, 2500);
            }
        });
    }

});

// Auto-dismiss profile messages after 5 seconds
function dismissProfileMessages() {
    const messages = document.querySelectorAll(".profile-message");
    const messagesContainer = document.querySelector(".profile-messages");

    if (!messages || messages.length === 0) return;

    messages.forEach(function (message) {
        setTimeout(function () {
            message.classList.add("fade-out");
            message.style.opacity = "0";
            message.style.transform = "translateY(-8px)";

            setTimeout(function () {
                message.remove();
                if (messagesContainer && messagesContainer.querySelectorAll(".profile-message").length === 0) {
                    messagesContainer.remove();
                }
            }, 300);
        }, 5000);
    });
}

document.addEventListener("htmx:afterSwap", dismissProfileMessages);