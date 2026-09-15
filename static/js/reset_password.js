document.addEventListener("DOMContentLoaded", function () {

    const newPassword =
        document.getElementById("new-password");

    const confirmPassword =
        document.getElementById("confirm-password");

    const strengthBar =
        document.getElementById("reset-strength-bar");

    const strengthText =
        document.getElementById("reset-strength-text");

    const matchMessage =
        document.getElementById("reset-password-match");

    const errorMessage =
        document.getElementById("reset-password-error");

    const form =
        document.getElementById("reset-password-form");


    /* =========================================
       SHOW / HIDE PASSWORD
    ========================================= */

    const toggleButtons =
        document.querySelectorAll(".reset-password-toggle");


    toggleButtons.forEach(function (button) {

        button.addEventListener("click", function () {

            const targetId =
                this.getAttribute("data-target");

            const target =
                document.getElementById(targetId);

            const icon =
                this.querySelector("i");


            if (target.type === "password") {

                target.type = "text";

                icon.classList.remove("fa-eye");
                icon.classList.add("fa-eye-slash");

                this.setAttribute(
                    "aria-label",
                    "Hide password"
                );

            } else {

                target.type = "password";

                icon.classList.remove("fa-eye-slash");
                icon.classList.add("fa-eye");

                this.setAttribute(
                    "aria-label",
                    "Show password"
                );

            }

        });

    });


    /* =========================================
       PASSWORD REQUIREMENTS
    ========================================= */

    const requirements = {

        length:
            document.getElementById("reset-length"),

        uppercase:
            document.getElementById("reset-uppercase"),

        number:
            document.getElementById("reset-number"),

        special:
            document.getElementById("reset-special")

    };


    function checkPassword(password) {

        return {

            length:
                password.length >= 8,

            uppercase:
                /[A-Z]/.test(password),

            number:
                /[0-9]/.test(password),

            special:
                /[!@#$%&*_\-]/.test(password)

        };

    }


    function updateRequirements(password) {

        const checks =
            checkPassword(password);


        Object.keys(checks).forEach(function (key) {

            const requirement =
                requirements[key];

            const icon =
                requirement.querySelector("i");


            if (checks[key]) {

                requirement.classList.add("valid");

                icon.classList.remove(
                    "fa-circle"
                );

                icon.classList.add(
                    "fa-check"
                );

            } else {

                requirement.classList.remove("valid");

                icon.classList.remove(
                    "fa-check"
                );

                icon.classList.add(
                    "fa-circle"
                );

            }

        });


        return checks;

    }


    /* =========================================
       PASSWORD STRENGTH
    ========================================= */

    function updateStrength(password) {

        if (!password) {

            strengthBar.style.width = "0%";

            strengthText.textContent =
                "Enter a password";

            return;

        }


        const checks =
            updateRequirements(password);


        let score = 0;


        if (checks.length) {
            score++;
        }

        if (checks.uppercase) {
            score++;
        }

        if (checks.number) {
            score++;
        }

        if (checks.special) {
            score++;
        }


        if (password.length >= 12) {
            score++;
        }


        if (score <= 1) {

            strengthBar.style.width = "25%";

            strengthText.textContent =
                "Weak";

        } else if (score <= 3) {

            strengthBar.style.width = "60%";

            strengthText.textContent =
                "Medium";

        } else {

            strengthBar.style.width = "100%";

            strengthText.textContent =
                "Strong";

        }

    }


    /* =========================================
       PASSWORD MATCH
    ========================================= */

    function updatePasswordMatch() {

        const password =
            newPassword.value;

        const confirm =
            confirmPassword.value;


        matchMessage.textContent = "";

        matchMessage.className =
            "reset-password-match";


        if (!confirm) {
            return;
        }


        if (password === confirm) {

            matchMessage.textContent =
                "Passwords match.";

            matchMessage.classList.add(
                "match"
            );

        } else {

            matchMessage.textContent =
                "Passwords do not match.";

            matchMessage.classList.add(
                "no-match"
            );

        }

    }


    /* =========================================
       PASSWORD INPUT EVENTS
    ========================================= */

    newPassword.addEventListener(
        "input",
        function () {

            updateStrength(
                this.value
            );

            updatePasswordMatch();

            clearError();

        }
    );


    confirmPassword.addEventListener(
        "input",
        function () {

            updatePasswordMatch();

            clearError();

        }
    );


    /* =========================================
       ERROR
    ========================================= */

    function showError(message) {

        errorMessage.textContent =
            message;

        errorMessage.classList.add(
            "show"
        );

    }


    function clearError() {

        errorMessage.textContent =
            "";

        errorMessage.classList.remove(
            "show"
        );

    }


    /* =========================================
       FORM VALIDATION
    ========================================= */

    form.addEventListener(
        "submit",
        function (event) {

            const password =
                newPassword.value;

            const confirm =
                confirmPassword.value;

            const checks =
                checkPassword(password);


            if (
                !checks.length ||
                !checks.uppercase ||
                !checks.number ||
                !checks.special
            ) {

                event.preventDefault();

                showError(
                    "Please make sure your password meets all the requirements."
                );

                return;

            }


            if (password !== confirm) {

                event.preventDefault();

                showError(
                    "Passwords do not match."
                );

                confirmPassword.focus();

                return;

            }


            clearError();

        }
    );

});