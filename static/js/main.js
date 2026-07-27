const dropZone = document.getElementById("drop-zone");
const resumeInput = document.getElementById("resume-upload");
const resumeForm = document.getElementById("resume-form");

dropZone.addEventListener("click", function () {
    resumeInput.click();
});

resumeInput.addEventListener("change", function () {

    if (resumeInput.files.length > 0) {

        const file = resumeInput.files[0];

        console.log("Selected file:", file.name);

        // Show loading UI
        document.querySelector(".upload-idle")
            .classList.add("hidden");

        document.querySelector(".upload-loading")
            .classList.remove("hidden");

        // Submit form through HTMX
        htmx.trigger(
            resumeForm,
            "submit"
        );
    }

});