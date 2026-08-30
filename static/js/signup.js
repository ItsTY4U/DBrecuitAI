
document.addEventListener("DOMContentLoaded", function () {

    const password = document.getElementById("id_password1");
    const confirmPassword = document.getElementById("id_password2");
    const status = document.getElementById("password-status");
    const submitButton = document.getElementById("signup-button");

    function checkPasswords() {

        const passwordValue = password.value;
        const confirmValue = confirmPassword.value;

        password.classList.remove(
            "password-match",
            "password-no-match"
        );

        confirmPassword.classList.remove(
            "password-match",
            "password-no-match"
        );

        if (confirmValue === "") {
            status.className = "password-status neutral";
            status.innerHTML = "Enter your password again";
            submitButton.disabled = false;
            return;
        }

        if (passwordValue === confirmValue) {

            status.className = "password-status match";
            status.innerHTML = "✓ Passwords match";

            password.classList.add("password-match");
            confirmPassword.classList.add("password-match");

            submitButton.disabled = false;

        } else {

            status.className = "password-status no-match";
            status.innerHTML = "✕ Passwords do not match";

            confirmPassword.classList.add("password-no-match");

            submitButton.disabled = true;
        }
    }

    password.addEventListener("input", checkPasswords);
    confirmPassword.addEventListener("input", checkPasswords);

    checkStrength();
    checkPasswords();
});

function togglePassword(id, button) {
    const input = document.getElementById(id);

    if (input.type === "password") {
        input.type = "text";
        button.textContent = "🙈";
    } else {
        input.type = "password";
        button.textContent = "👁";
    }
}



document.addEventListener("DOMContentLoaded", function () {

    const password = document.getElementById("id_password1");
    const strengthBar = document.getElementById("strength-bar");

    const ruleLength = document.getElementById("rule-length");
    const ruleUpper = document.getElementById("rule-upper");
    const ruleNumber = document.getElementById("rule-number");
    const ruleSpecial = document.getElementById("rule-special");

    // Limited allowed special characters
    const specialPattern = /[!@#$%&*_\-]/;

    function checkStrength() {
        const value = password.value;

        const hasLength = value.length >= 8;
        const hasUpper = /[A-Z]/.test(value);
        const hasNumber = /[0-9]/.test(value);
        const hasSpecial = specialPattern.test(value);

        ruleLength.classList.toggle("valid", hasLength);
        ruleUpper.classList.toggle("valid", hasUpper);
        ruleNumber.classList.toggle("valid", hasNumber);
        ruleSpecial.classList.toggle("valid", hasSpecial);

        const passedCount = [hasLength, hasNumber, hasSpecial, hasUpper]
            .filter(Boolean).length;

        strengthBar.classList.remove(
            "weak",
            "fair",
            "good",
            "strong"
        );

        if (value === "") {
            strengthBar.style.width = "0%";
            return;
        } 
        if (passedCount === 1) {
            strengthBar.classList.add("weak");
        } else if (passedCount === 2) {
            strengthBar.classList.add("fair");
        } else if (passedCount === 3) {
            strengthBar.classList.add("good");
        } else if (passedCount === 4) {
            strengthBar.classList.add("strong");
        }
    }

    password.addEventListener("input", checkStrength);
});


document.addEventListener("DOMContentLoaded", function () {

    const editButton = document.getElementById("edit-profile-btn");
    const cancelButton = document.getElementById("cancel-profile-btn");

    const profileView = document.getElementById("profile-view");
    const profileEdit = document.getElementById("profile-edit");


    editButton.addEventListener("click", function () {

        profileView.style.display = "none";
        profileEdit.style.display = "block";

        editButton.textContent = "Cancel";

    });


    cancelButton.addEventListener("click", function () {

        profileEdit.style.display = "none";
        profileView.style.display = "block";

        editButton.textContent = "Edit Profile";

    });



});


document.addEventListener("DOMContentLoaded", function () {

    const processButton =
        document.getElementById("process-resume-btn");

    const resumeInput =
        document.getElementById("id_default_resume");

    const status =
        document.getElementById("resume-status");

    // Get the Django-generated URL
    const processUrl =
        processButton.dataset.processUrl;


    function getCookie(name) {
        let cookieValue = null;

        if (document.cookie && document.cookie !== "") {

            const cookies = document.cookie.split(";");

            for (let i = 0; i < cookies.length; i++) {

                const cookie = cookies[i].trim();

                if (
                    cookie.substring(
                        0,
                        name.length + 1
                    ) === name + "="
                ) {

                    cookieValue = decodeURIComponent(
                        cookie.substring(name.length + 1)
                    );

                    break;
                }
            }
        }

        return cookieValue;
    }


    processButton.addEventListener(
        "click",
        async function () {

            const resume = resumeInput.files[0];

            if (!resume) {
                status.textContent =
                    "Please select a resume first.";
                return;
            }

            const formData = new FormData();

            formData.append(
                "resume",
                resume
            );

            const csrfToken =
                document.querySelector(
                    "[name=csrfmiddlewaretoken]"
                ).value;

            processButton.disabled = true;

            processButton.textContent =
                "Processing Resume...";

            status.textContent =
                "Please wait while we analyze your resume.";

            try {

                console.log(
                    "Processing URL:",
                    processUrl
                );

                const response = await fetch(
                    processUrl,
                    {
                        method: "POST",
                        headers: {
                            "X-CSRFToken": getCookie("csrftoken")
                        },
                        body: formData,
                        credentials: "same-origin"
                    }
                );

                const result = await response.json();
                if (!response.ok) {

                    status.textContent =
                        result.error ||
                        "Unable to process the resume.";

                    return;
                }

                if (result.success) {

                    const personal =
                        result.data.personal || {};

                    document.getElementById(
                        "id_first_name"
                    ).value =
                        personal.first_name || "";

                    document.getElementById(
                        "id_middle_name"
                    ).value =
                        personal.middle_name || "";

                    document.getElementById(
                        "id_last_name"
                    ).value =
                        personal.last_name || "";

                    document.getElementById(
                        "id_email"
                    ).value =
                        personal.email || "";

                    status.textContent =
                        "✓ Resume processed successfully.";
                }

            } catch (error) {

                console.error(
                    "Resume processing error:",
                    error
                );

                status.textContent =
                    "An error occurred while processing the resume.";

            } finally {

                processButton.disabled = false;

                processButton.textContent =
                    "Process Resume";
            }

        }
    );

    

});

document.addEventListener("DOMContentLoaded", function () {

    const profileForm = document.getElementById("profile-form");
    const resumeInput = document.getElementById("id_default_resume");
    const overlay = document.getElementById("resume-processing-overlay");
    const processingTitle = document.getElementById("processing-title");
    const processingMessage = document.getElementById("processing-message");
    const saveButton =document.getElementById("save-profile-btn");
    const messages = document.querySelectorAll(".profile-message");
    const completeProfileBtn = document.getElementById("complete-profile-btn");


    if (!profileForm) {
        return;
    }

    profileForm.addEventListener(
        "submit",
        function () {

            /*
             * Check if the applicant selected
             * a new resume.
             */

            const resumeChanged =
                resumeInput &&
                resumeInput.files.length > 0;

            /*
             * If no resume was changed,
             * submit normally.
             */

            if (!resumeChanged) {

                if (saveButton) {

                    saveButton.disabled = true;

                    saveButton.textContent =
                        "Saving...";
                }

                return;
            }


            /*
             * Resume was changed.
             * Show processing overlay.
             */

            if (overlay) {

                overlay.style.display = "flex";

            }


            /*
             * Disable the save button.
             */

            if (saveButton) {

                saveButton.disabled = true;

                saveButton.textContent =
                    "Processing...";
            }


            /*
             * Step 1
             */

            processingTitle.textContent =
                "Saving your new resume...";

            processingMessage.textContent =
                "Please wait while we update your profile.";


            /*
             * Step 2
             *
             * This is only visual feedback while
             * Django processes the resume.
             */

            setTimeout(function () {

                processingTitle.textContent =
                    "Analyzing your resume...";

                processingMessage.textContent =
                    "Extracting your skills, experience, and qualifications.";

            }, 800);


            /*
             * Step 3
             */

            setTimeout(function () {

                processingTitle.textContent =
                    "Updating job recommendations...";

                processingMessage.textContent =
                    "We're finding jobs that match your profile.";

            }, 2500);

        }
    );

    messages.forEach(function (message) {
        setTimeout(function () {
            message.style.opacity = "0";
            message.style.transform = "translateY(-10px)";

            setTimeout(function (){
                message.remove();
            }, 300);
        }, 5000);
    });

    if (completeProfileBtn) {
        completeProfileBtn.addEventListener("click", function () {

            const profileView = document.getElementById("profile-view");
            const profileEdit = document.getElementById("profile-edit");

            if (profileView && profileEdit) {
                profileView.style.display = "none";
                profileEdit.style.display = "block";

                profileEdit.scrollIntoView({
                    behavior: "smooth",
                    block: "start"
                });
            }
        });
    }

});