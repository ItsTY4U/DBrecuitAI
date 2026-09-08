document.addEventListener("DOMContentLoaded", function () {

/*
=========================================
PASSWORD
=========================================
*/

const password =
    document.getElementById("id_password1");

const confirmPassword =
    document.getElementById("id_password2");

const passwordStatus =
    document.getElementById("password-status");

const submitButton =
    document.getElementById("signup-button");


/*
=========================================
PASSWORD MATCHING
=========================================
*/

function checkPasswords() {

    // Make sure the signup page elements exist
    if (!password || !confirmPassword) {
        return;
    }

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


    /*
    Nothing entered in confirmation field
    */

    if (confirmValue === "") {

        if (passwordStatus) {

            passwordStatus.className =
                "password-status neutral";

            passwordStatus.innerHTML =
                "Enter your password again";

        }

        if (submitButton) {
            submitButton.disabled = false;
        }

        return;
    }


    /*
    Passwords match
    */

    if (passwordValue === confirmValue) {

        if (passwordStatus) {

            passwordStatus.className =
                "password-status match";

            passwordStatus.innerHTML =
                "✓ Passwords match";

        }

        password.classList.add(
            "password-match"
        );

        confirmPassword.classList.add(
            "password-match"
        );


        if (submitButton) {
            submitButton.disabled = false;
        }

    }


    /*
    Passwords do not match
    */

    else {

        if (passwordStatus) {

            passwordStatus.className =
                "password-status no-match";

            passwordStatus.innerHTML =
                "✕ Passwords do not match";

        }

        confirmPassword.classList.add(
            "password-no-match"
        );


        if (submitButton) {
            submitButton.disabled = true;
        }

    }

}


if (password && confirmPassword) {

    password.addEventListener(
        "input",
        checkPasswords
    );

    confirmPassword.addEventListener(
        "input",
        checkPasswords
    );

    checkPasswords();

}


/*
=========================================
PASSWORD STRENGTH
=========================================
*/

const strengthBar =
    document.getElementById("strength-bar");

const ruleLength =
    document.getElementById("rule-length");

const ruleUpper =
    document.getElementById("rule-upper");

const ruleNumber =
    document.getElementById("rule-number");

const ruleSpecial =
    document.getElementById("rule-special");


/*
Allowed special characters
*/

const specialPattern =
    /[!@#$%&*_\-]/;


function checkStrength() {

    if (!password || !strengthBar) {
        return;
    }

    const value = password.value;


    const hasLength =
        value.length >= 8;

    const hasUpper =
        /[A-Z]/.test(value);

    const hasNumber =
        /[0-9]/.test(value);

    const hasSpecial =
        specialPattern.test(value);


    /*
    Update checklist
    */

    if (ruleLength) {

        ruleLength.classList.toggle(
            "valid",
            hasLength
        );

    }

    if (ruleUpper) {

        ruleUpper.classList.toggle(
            "valid",
            hasUpper
        );

    }

    if (ruleNumber) {

        ruleNumber.classList.toggle(
            "valid",
            hasNumber
        );

    }

    if (ruleSpecial) {

        ruleSpecial.classList.toggle(
            "valid",
            hasSpecial
        );

    }


    /*
    Count requirements
    */

    const passedCount = [
        hasLength,
        hasUpper,
        hasNumber,
        hasSpecial
    ].filter(Boolean).length;


    /*
    Remove old strength classes
    */

    strengthBar.classList.remove(
        "weak",
        "fair",
        "good",
        "strong"
    );


    /*
    Empty password
    */

    if (value === "") {

        strengthBar.style.width = "0%";

        return;
    }


    /*
    Weak
    */

    if (passedCount === 1) {

        strengthBar.classList.add(
            "weak"
        );

    }


    /*
    Fair
    */

    else if (passedCount === 2) {

        strengthBar.classList.add(
            "fair"
        );

    }


    /*
    Good
    */

    else if (passedCount === 3) {

        strengthBar.classList.add(
            "good"
        );

    }


    /*
    Strong
    */

    else if (passedCount === 4) {

        strengthBar.classList.add(
            "strong"
        );

    }

}


if (password && strengthBar) {

    password.addEventListener(
        "input",
        checkStrength
    );

    checkStrength();

}


/*
=========================================
RESUME PROCESSING
=========================================
*/

const processButton =
    document.getElementById(
        "process-resume-btn"
    );

const resumeInput =
    document.getElementById(
        "id_default_resume"
    );

const resumeStatus =
    document.getElementById(
        "resume-status"
    );


/*
Only run resume processing if
the signup page has the elements.
*/

if (
    processButton &&
    resumeInput
) {

    const processUrl =
        processButton.dataset.processUrl;


    /*
    Get CSRF cookie
    */

    function getCookie(name) {

        let cookieValue = null;


        if (
            document.cookie &&
            document.cookie !== ""
        ) {

            const cookies =
                document.cookie.split(";");


            for (
                let i = 0;
                i < cookies.length;
                i++
            ) {

                const cookie =
                    cookies[i].trim();


                if (
                    cookie.substring(
                        0,
                        name.length + 1
                    ) === name + "="
                ) {

                    cookieValue =
                        decodeURIComponent(
                            cookie.substring(
                                name.length + 1
                            )
                        );

                    break;

                }

            }

        }

        return cookieValue;

    }


    /*
    Process resume
    */

    processButton.addEventListener(
        "click",
        async function () {

            const resume =
                resumeInput.files[0];


            /*
            No resume selected
            */

            if (!resume) {

                if (resumeStatus) {

                    resumeStatus.textContent =
                        "Please select a resume first.";

                }

                return;

            }


            /*
            Create form data
            */

            const formData =
                new FormData();

            formData.append(
                "resume",
                resume
            );


            /*
            CSRF token
            */

            const csrfInput =
                document.querySelector(
                    "[name=csrfmiddlewaretoken]"
                );


            if (!csrfInput) {

                console.error(
                    "CSRF token not found."
                );

                if (resumeStatus) {

                    resumeStatus.textContent =
                        "Security token not found. Please refresh the page.";

                }

                return;

            }


            const csrfToken =
                csrfInput.value;


            /*
            Disable button
            */

            processButton.disabled =
                true;

            processButton.textContent =
                "Processing Resume...";


            if (resumeStatus) {

                resumeStatus.textContent =
                    "Please wait while we analyze your resume.";

            }


            try {

                console.log(
                    "Processing URL:",
                    processUrl
                );


                const response =
                    await fetch(
                        processUrl,
                        {
                            method: "POST",

                            headers: {
                                "X-CSRFToken":
                                    csrfToken
                            },

                            body: formData,

                            credentials:
                                "same-origin"
                        }
                    );


                /*
                Read response
                */

                const result =
                    await response.json();


                /*
                Server error
                */

                if (!response.ok) {

                    if (resumeStatus) {

                        resumeStatus.textContent =
                            result.error ||
                            "Unable to process the resume.";

                    }

                    return;

                }


                /*
                Successful processing
                */

                if (result.success) {

                    const personal =
                        result.data?.personal || {};


                    /*
                    First name
                    */

                    const firstName =
                        document.getElementById(
                            "id_first_name"
                        );

                    if (firstName) {

                        firstName.value =
                            personal.first_name ||
                            "";

                    }


                    /*
                    Middle name
                    */

                    const middleName =
                        document.getElementById(
                            "id_middle_name"
                        );

                    if (middleName) {

                        middleName.value =
                            personal.middle_name ||
                            "";

                    }


                    /*
                    Last name
                    */

                    const lastName =
                        document.getElementById(
                            "id_last_name"
                        );

                    if (lastName) {

                        lastName.value =
                            personal.last_name ||
                            "";

                    }


                    /*
                    Email
                    */

                    const email =
                        document.getElementById(
                            "id_email"
                        );

                    if (email) {

                        email.value =
                            personal.email ||
                            "";

                    }


                    /*
                    Success message
                    */

                    if (resumeStatus) {

                        resumeStatus.textContent =
                            "✓ Resume processed successfully.";

                    }

                }

                else {

                    if (resumeStatus) {

                        resumeStatus.textContent =
                            result.error ||
                            "Unable to process the resume.";

                    }

                }

            }


            catch (error) {

                console.error(
                    "Resume processing error:",
                    error
                );


                if (resumeStatus) {

                    resumeStatus.textContent =
                        "An error occurred while processing the resume.";

                }

            }


            finally {

                processButton.disabled =
                    false;

                processButton.textContent =
                    "Process Resume";

            }

        }
    );

}

});
