document.addEventListener("DOMContentLoaded", function () {

    const editButton = document.getElementById("edit-profile-btn");
    const cancelButton = document.getElementById("cancel-profile-btn");
    const profileEdit = document.getElementById("profile-edit");

    console.log("profile.js loaded");
    console.log("Edit button:", editButton);
    console.log("Profile edit:", profileEdit);

    if (editButton && profileEdit) {

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