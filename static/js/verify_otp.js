document.addEventListener("DOMContentLoaded", function () {

    const otpInputs = document.querySelectorAll(".otp-input");
    const otpValue = document.getElementById("otp-value");
    const otpForm = document.getElementById("otp-form");

    const countdown = document.getElementById("otp-countdown");
    const resendButton = document.getElementById("resend-otp");
    const errorMessage = document.getElementById("otp-error");


    /* =========================================
       OTP INPUT
    ========================================= */

    otpInputs.forEach((input, index) => {

        input.addEventListener("input", function () {

            // Allow numbers only
            this.value = this.value.replace(/\D/g, "");

            if (this.value.length > 0) {
                this.classList.add("filled");

                // Move to next input
                if (index < otpInputs.length - 1) {
                    otpInputs[index + 1].focus();
                }
            } else {
                this.classList.remove("filled");
            }

            updateOTPValue();
            clearOTPError();
        });


        /* =========================================
           BACKSPACE
        ========================================= */

        input.addEventListener("keydown", function (event) {

            if (event.key === "Backspace" && this.value === "") {

                if (index > 0) {
                    otpInputs[index - 1].focus();
                    otpInputs[index - 1].value = "";
                    otpInputs[index - 1].classList.remove("filled");

                    updateOTPValue();
                }

            }


            // Allow arrow navigation
            if (event.key === "ArrowLeft" && index > 0) {
                event.preventDefault();
                otpInputs[index - 1].focus();
            }


            if (
                event.key === "ArrowRight" &&
                index < otpInputs.length - 1
            ) {
                event.preventDefault();
                otpInputs[index + 1].focus();
            }

        });


        /* =========================================
           PASTE OTP
        ========================================= */

        input.addEventListener("paste", function (event) {

            event.preventDefault();

            const pastedText =
                (event.clipboardData || window.clipboardData)
                .getData("text")
                .replace(/\D/g, "")
                .slice(0, 6);

            if (!pastedText) {
                return;
            }


            pastedText.split("").forEach((digit, i) => {

                if (otpInputs[i]) {
                    otpInputs[i].value = digit;
                    otpInputs[i].classList.add("filled");
                }

            });


            updateOTPValue();

            const nextEmpty =
                Array.from(otpInputs).findIndex(
                    input => input.value === ""
                );

            if (nextEmpty !== -1) {
                otpInputs[nextEmpty].focus();
            } else {
                otpInputs[otpInputs.length - 1].focus();
            }

            clearOTPError();

        });

    });


    /* =========================================
       UPDATE HIDDEN OTP
    ========================================= */

    function updateOTPValue() {

        let otp = "";

        otpInputs.forEach(input => {
            otp += input.value;
        });

        otpValue.value = otp;
    }


    /* =========================================
       ERROR MESSAGE
    ========================================= */

    function showOTPError(message) {

        errorMessage.textContent = message;
        errorMessage.classList.add("show");
    }


    function clearOTPError() {

        errorMessage.textContent = "";
        errorMessage.classList.remove("show");
    }


    /* =========================================
       COUNTDOWN TIMER
    ========================================= */

    let remainingSeconds = 5 * 60;

    let timerInterval;


    function updateCountdown() {

        const minutes =
            Math.floor(remainingSeconds / 60)
            .toString()
            .padStart(2, "0");

        const seconds =
            (remainingSeconds % 60)
            .toString()
            .padStart(2, "0");


        countdown.textContent =
            `${minutes}:${seconds}`;


        if (remainingSeconds <= 0) {

            clearInterval(timerInterval);

            countdown.textContent = "00:00";

            countdown.closest(".otp-timer")
                .classList.add("expired");

            resendButton.disabled = false;

            return;
        }


        remainingSeconds--;

    }


    updateCountdown();

    timerInterval = setInterval(
        updateCountdown,
        1000
    );


    /* =========================================
       RESEND CODE
    ========================================= */

    resendButton.addEventListener("click", function () {

        if (this.disabled) {
            return;
        }


        clearOTPError();


        // Clear OTP inputs
        otpInputs.forEach(input => {

            input.value = "";

            input.classList.remove("filled");

        });


        updateOTPValue();


        // Restart timer
        remainingSeconds = 5 * 60;

        countdown
            .closest(".otp-timer")
            .classList.remove("expired");


        resendButton.disabled = true;


        clearInterval(timerInterval);

        timerInterval = setInterval(
            updateCountdown,
            1000
        );


        otpInputs[0].focus();


        /*
         * Backend integration will be added later.
         *
         * This is currently only the frontend
         * behavior for the Resend Code button.
         */

    });


    /* =========================================
       FORM VALIDATION
    ========================================= */

    otpForm.addEventListener("submit", function (event) {

        updateOTPValue();

        const otp = otpValue.value;


        if (otp.length !== 6) {

            event.preventDefault();

            showOTPError(
                "Please enter the complete 6-digit verification code."
            );

            const firstEmpty =
                Array.from(otpInputs).find(
                    input => input.value === ""
                );

            if (firstEmpty) {
                firstEmpty.focus();
            }

            return;
        }


        clearOTPError();

        /*
         * The form is allowed to submit here.
         *
         * Django OTP verification will be connected later.
         */

    });


});